"""Idempotently seed one declared synthetic bundle into PostgreSQL and Blob."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from io import BytesIO
from pathlib import PurePosixPath
from uuid import UUID, UUID as UUIDType, uuid5

from src.db.unit_of_work import PostgresUnitOfWork
from src.forecast.contracts import ForecastRequest, ProductCandidate
from src.repositories.datasets import DatasetRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.services.analysis_service import AnalysisService
from src.services.demo_action_authority import DemoActionAuthority
from src.services.forecast_service import ForecastService
from src.services.public_release_service import (
    PUBLIC_ANALYSIS_KINDS,
    PublicReleaseService,
)
from src.services.profit_bridge_service import ProfitBridgeService
from src.storage.keys import dataset_object_key
from src.storage.protocol import AvailableObject, StagedObject, WorkflowStorage
from src.synthetic.contracts import SyntheticBundle, SyntheticFile
from src.synthetic.release_profile import PUBLIC_RELEASE_PROFILE

WORKSPACE_ID = "synthetic-demo"
SERIES_NAME = "synthetic-main"
SEED_NAMESPACE = UUIDType("cb794ce7-d3cf-516a-850b-643ab0c2ec91")
MANIFEST_MEDIA_TYPE = "application/json"
SEED_IDEMPOTENCY_PEPPER = "synthetic-seed-internal-idempotency-v1"


@dataclass(frozen=True, slots=True)
class SeedResult:
    series_id: UUID
    dataset_version_id: UUID
    public_release_id: UUID
    manifest_sha256: str
    created: bool


@dataclass(frozen=True, slots=True)
class PromotedSeedObject:
    file: SyntheticFile
    object_id: UUID
    artifact_id: UUID
    artifact_kind: str
    staged: StagedObject
    available: AvailableObject


def seed_demo(
    bundle: SyntheticBundle,
    uow: PostgresUnitOfWork,
    storage: WorkflowStorage,
    *,
    now: datetime | None = None,
) -> SeedResult:
    """Own the supplied UOW lifecycle and never contact an unpassed provider."""

    _validate_bundle(bundle)
    manifest_sha256 = bundle.manifest_sha256
    timestamp = now or datetime.now(UTC)
    existing = _existing_state(uow, manifest_sha256)
    if existing is not None:
        version, historical_release = existing
        if historical_release is not None:
            _ensure_release_assets(
                uow.engine,
                storage,
                version.id,
                timestamp,
            )
            return SeedResult(
                series_id=version.series_id,
                dataset_version_id=version.id,
                public_release_id=historical_release.id,
                manifest_sha256=manifest_sha256,
                created=False,
            )
        recovered_release = _publish_version(
            uow.engine,
            storage,
            version.id,
            manifest_sha256,
            timestamp,
        )
        return SeedResult(
            series_id=version.series_id,
            dataset_version_id=version.id,
            public_release_id=recovered_release.release_id,
            manifest_sha256=manifest_sha256,
            created=False,
        )

    series_id = uuid5(SEED_NAMESPACE, f"{WORKSPACE_ID}:{SERIES_NAME}")
    version_id = uuid5(SEED_NAMESPACE, f"version:{manifest_sha256}")
    seed_files = (
        SyntheticFile(
            "manifest.json",
            bundle.manifest_bytes,
            MANIFEST_MEDIA_TYPE,
            1,
        ),
        *bundle.files,
    )
    promoted: list[PromotedSeedObject] = []
    staged_objects: list[StagedObject] = []
    try:
        for file in seed_files:
            staged = storage.put_staging(
                BytesIO(file.content),
                max_bytes=len(file.content),
                media_type=file.media_type,
            )
            staged_objects.append(staged)
            final_key = dataset_object_key(
                WORKSPACE_ID,
                str(version_id),
                file.sha256,
            )
            available = storage.promote(staged.key, final_key, file.sha256)
            artifact_kind = (
                "manifest"
                if file.relative_path == "manifest.json"
                else PurePosixPath(file.relative_path).stem
            )
            promoted.append(
                PromotedSeedObject(
                    file=file,
                    object_id=uuid5(
                        SEED_NAMESPACE,
                        f"object:{manifest_sha256}:{file.relative_path}",
                    ),
                    artifact_id=uuid5(
                        SEED_NAMESPACE,
                        f"artifact:{manifest_sha256}:{file.relative_path}",
                    ),
                    artifact_kind=artifact_kind,
                    staged=staged,
                    available=available,
                )
            )

        with uow as transaction:
            datasets = DatasetRepository(transaction.connection)
            series = datasets.get_series_by_name(WORKSPACE_ID, SERIES_NAME)
            if series is None:
                series = datasets.create_series(
                    workspace_id=WORKSPACE_ID,
                    name=SERIES_NAME,
                    now=timestamp,
                    series_id=series_id,
                )
            version = datasets.create_version(
                series_id=series.id,
                workspace_id=WORKSPACE_ID,
                source_workflow_id=None,
                version_number=datasets.next_version_number(series.id),
                schema_version=bundle.manifest.schema_version,
                content_sha256=manifest_sha256,
                now=timestamp,
                version_id=version_id,
            )
            storage_repository = StorageObjectRepository(transaction.connection)
            for item in promoted:
                storage_record = storage_repository.create_available(
                    object_id=item.object_id,
                    workspace_id=WORKSPACE_ID,
                    available=item.available,
                    purpose="normalized_dataset",
                    media_type=item.file.media_type,
                    now=timestamp,
                )
                datasets.create_artifact(
                    dataset_version_id=version.id,
                    storage_object_id=storage_record.id,
                    artifact_kind=item.artifact_kind,
                    sha256=item.file.sha256,
                    now=timestamp,
                    artifact_id=item.artifact_id,
                )
            datasets.point_series_at(series.id, version.id)
    except BaseException:
        _compensate(storage, promoted, staged_objects)
        raise

    for staged in staged_objects:
        storage.delete(staged.key, expected_etag=staged.etag)
    release = _publish_version(
        uow.engine,
        storage,
        version.id,
        manifest_sha256,
        timestamp,
    )
    return SeedResult(
        series_id=series.id,
        dataset_version_id=version.id,
        public_release_id=release.release_id,
        manifest_sha256=manifest_sha256,
        created=True,
    )


def _existing_state(
    uow: PostgresUnitOfWork,
    manifest_sha256: str,
):
    with uow as transaction:
        repository = DatasetRepository(transaction.connection)
        version = repository.find_version_by_content(WORKSPACE_ID, manifest_sha256)
        if version is None:
            return None
        release = repository.find_release_for_version(WORKSPACE_ID, version.id)
        return version, release


def _publish_version(
    engine,
    storage,
    dataset_version_id,
    manifest_sha256,
    timestamp,
):
    analyses, bridges, forecasts, actions = _ensure_release_assets(
        engine,
        storage,
        dataset_version_id,
        timestamp,
    )
    releases = PublicReleaseService(
        engine,
        WORKSPACE_ID,
        idempotency_pepper=SEED_IDEMPOTENCY_PEPPER,
        clock=lambda: timestamp,
        analysis_service=analyses,
        profit_bridge_service=bridges,
        action_authority=actions,
        forecast_service=forecasts,
    )
    current = releases.current()
    expected_id = current.dataset_version_id if current is not None else None
    return releases.publish(
        dataset_version_id,
        expected_current_id=expected_id,
        idempotency_key=f"seed-{manifest_sha256}",
    )


def _ensure_analyses(engine, storage, dataset_version_id, timestamp):
    analyses = AnalysisService(
        engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: timestamp,
    )
    monthly_kinds = ("sales_ads", "operating_profit")
    requests = []
    current_scopes = analyses.preparation_scopes(dataset_version_id)
    for current_scope in current_scopes:
        identity_scope = {
            key: value
            for key, value in current_scope.items()
            if key in {"currency", "store_id"}
        }
        for period in PUBLIC_RELEASE_PROFILE.monthly_periods():
            scope = {
                **identity_scope,
                "period_start": period[0].isoformat(),
                "period_end": period[1].isoformat(),
            }
            requests.extend((kind, scope) for kind in monthly_kinds)
        requests.extend(
            (kind, current_scope)
            for kind in PUBLIC_ANALYSIS_KINDS
            if kind not in monthly_kinds
        )
    for kind, scope in requests:
        plan = analyses.plan(kind, dataset_version_id, scope)
        analyses.run(
            plan,
            idempotency_key=(
                f"seed-analysis-{kind}-{scope.get('store_id', 'all')}-"
                f"{scope['period_start']}-{scope['period_end']}"
            ),
        )
        analyses.get_exact_completed(
            kind,
            dataset_version_id,
            scope,
        )
    return analyses


def _ensure_release_assets(engine, storage, dataset_version_id, timestamp):
    analyses = _ensure_analyses(engine, storage, dataset_version_id, timestamp)
    bridges = ProfitBridgeService(
        engine,
        storage,
        WORKSPACE_ID,
        analysis_service=analyses,
        clock=lambda: timestamp,
    )
    forecasts = ForecastService(
        engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: timestamp,
    )
    actions = DemoActionAuthority(
        engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: timestamp,
        profit_bridge_service=bridges,
    )
    for analysis_scope in analyses.preparation_scopes(dataset_version_id):
        identity_scope = {
            key: value
            for key, value in analysis_scope.items()
            if key in {"currency", "store_id"}
        }
        bridges.run(
            dataset_version_id,
            current_period=PUBLIC_RELEASE_PROFILE.current_period,
            comparison_period=PUBLIC_RELEASE_PROFILE.comparison_period,
            scope=identity_scope,
        )
        _ensure_forecast(forecasts, dataset_version_id, identity_scope)
        actions.ensure(dataset_version_id, identity_scope)
    return analyses, bridges, forecasts, actions


def _ensure_forecast(
    forecasts: ForecastService,
    dataset_version_id: UUID,
    scope: dict[str, object],
):
    request = ForecastRequest(
        candidate=ProductCandidate(
            product_name="Synthetic Portable Organizer",
            category="travel_bag",
            attributes=("portable", "zippered", "compact"),
            planned_launch_date=date(2026, 8, 20),
            planned_price_brl=Decimal("119.90"),
            expected_discount_brl=Decimal("5.00"),
            unit_cost_brl=Decimal("42.00"),
            opening_inventory_units=80,
            moq_units=24,
            lead_time_days=18,
            planned_daily_ad_brl=Decimal("12.00"),
        ),
        safety_stock_units=20,
        assumptions=("synthetic_launch_ramp",),
        missing_fields=(),
    )
    forecast = forecasts.create(
        dataset_version_id,
        request,
        scope=scope,
        idempotency_key=(
            f"seed-forecast-{dataset_version_id}-{scope.get('store_id', 'all')}"
        ),
    )
    if forecast.status == "draft":
        forecast = forecasts.confirm_analogs(
            forecast.id,
            tuple(item.sku_id for item in forecast.analogs[:2]),
        )
    if forecast.status == "analogs_confirmed":
        forecast = forecasts.run(forecast.id)
    if forecast.status != "completed":
        raise ValueError("synthetic_forecast_authority_unavailable")
    return forecast


def ensure_demo_action(
    engine,
    storage,
    dataset_version_id,
    *,
    now: datetime | None = None,
):
    """Idempotently prepare the hosted Demo's evidence-backed action card."""

    timestamp = now or datetime.now(UTC)
    return DemoActionAuthority(
        engine,
        storage,
        WORKSPACE_ID,
        clock=lambda: timestamp,
    ).ensure(dataset_version_id)


def _validate_bundle(bundle: SyntheticBundle) -> None:
    if bundle.manifest.source_classification != "pure_synthetic":
        raise ValueError("synthetic_source_classification_required")
    try:
        payload = json.loads(bundle.manifest_bytes)
        declarations = {
            str(item["path"]): (
                str(item["sha256"]),
                str(item["media_type"]),
                int(item["row_count"]),
            )
            for item in payload["files"]
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise ValueError("synthetic_manifest_invalid") from error
    actual = {
        file.relative_path: (file.sha256, file.media_type, file.row_count)
        for file in bundle.files
    }
    expected_catalog = [
        {
            "store_id": item.store_id,
            "display_name_en": item.display_name_en,
            "display_name_zh": item.display_name_zh,
            "currency": item.currency,
            "opened_on": (
                item.opened_on.isoformat()
                if item.opened_on is not None
                else None
            ),
            "lifecycle": item.lifecycle,
            "has_data": item.has_data,
        }
        for item in bundle.manifest.store_catalog
    ]
    analysis_files = tuple(
        file for file in bundle.files
        if file.relative_path == "analysis_bundle.json"
    )
    try:
        analysis_catalog = json.loads(analysis_files[0].content)["store_catalog"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("synthetic_manifest_content_mismatch") from error
    if (
        payload.get("source_classification") != "pure_synthetic"
        or payload.get("schema_version") != bundle.manifest.schema_version
        or payload.get("store_catalog") != expected_catalog
        or analysis_catalog != expected_catalog
        or len(analysis_files) != 1
        or declarations != actual
        or tuple(bundle.files) != tuple(bundle.manifest.files)
    ):
        raise ValueError("synthetic_manifest_content_mismatch")


def _compensate(
    storage: WorkflowStorage,
    promoted: list[PromotedSeedObject],
    staged_objects: list[StagedObject],
) -> None:
    for item in reversed(promoted):
        if item.available.created:
            try:
                storage.delete(
                    item.available.key,
                    expected_etag=item.available.etag,
                )
            except Exception:
                pass
    for staged in reversed(staged_objects):
        try:
            storage.delete(staged.key, expected_etag=staged.etag)
        except Exception:
            pass
