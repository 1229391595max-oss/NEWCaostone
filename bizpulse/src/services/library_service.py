"""Read-only BP Library projections over immutable dataset authority."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from typing import Mapping
from uuid import UUID

from sqlalchemy import Engine

from src.repositories.library import LibraryRepository
from src.repositories.dataset_exports import DatasetExportRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.services.canonical_contracts import StoreDescriptor, StoreScope
from src.services.store_scope import StoreScopeResolver
from src.synthetic.release_profile import PUBLIC_SOURCE_ROLES

MAX_LIBRARY_VERSIONS = 12
MAX_LIBRARY_TABLES = 32
MAX_LIBRARY_PREVIEW = 10
ALLOWED_LIBRARY_PAGE_SIZES = (25, 50, 100)
MAX_LIBRARY_PROVENANCE = 20
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_SUMMARY_BYTES_PER_VERSION = 4 * 1024 * 1024
MAX_DETAIL_BYTES = 24 * 1024 * 1024
FACT_PERIOD_ROLES = ("daily_sales", "shopee_advertising")


class LibraryNotFound(RuntimeError):
    code = "LIBRARY_VERSION_NOT_FOUND"


class LibraryUnavailable(RuntimeError):
    code = "LIBRARY_UNAVAILABLE"


class LibraryTableNotFound(RuntimeError):
    code = "LIBRARY_TABLE_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class QualitySummary:
    status: str
    missing_roles: tuple[str, ...]
    issue_count: int


@dataclass(frozen=True, slots=True)
class PreparationSummary:
    status: str
    domains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LibraryVersion:
    dataset_version_id: UUID
    version_number: int
    lifecycle: str
    created_at: datetime
    period_start: date | None
    period_end: date | None
    stores: int
    skus: int
    source_roles: tuple[str, ...]
    row_count: int
    quality: QualitySummary
    preparation: PreparationSummary
    preview_available: bool
    export_available: bool


@dataclass(frozen=True, slots=True)
class LibraryTable:
    role: str
    scope_kind: str
    row_count: int
    columns: tuple[str, ...]
    preview: tuple[dict[str, object], ...]


@dataclass(frozen=True, slots=True)
class LibraryTablePage:
    role: str
    scope_kind: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    page: int
    page_size: int
    total_rows: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class LibraryProvenance:
    source_name: str
    source_role: str
    status: str
    adapter: str | None
    row_count: int | None


@dataclass(frozen=True, slots=True)
class LibraryVersionDetail(LibraryVersion):
    store_catalog: tuple[StoreDescriptor, ...]
    resolved_scope: StoreScope
    tables: tuple[LibraryTable, ...]
    provenance: tuple[LibraryProvenance, ...]
    analyses: tuple[str, ...]
    exports: tuple[object, ...]


class LibraryService:
    def __init__(
        self,
        engine: Engine,
        storage,
        workspace_id: str,
        *,
        preparation_service=None,
        store_scope_resolver=None,
    ) -> None:
        self._engine = engine
        self._storage = storage
        self._workspace_id = workspace_id
        self._preparations = preparation_service
        self._store_scopes = store_scope_resolver or StoreScopeResolver(
            engine,
            storage,
            workspace_id,
        )

    def list_versions(self) -> tuple[LibraryVersion, ...]:
        with self._engine.connect() as connection:
            repository = LibraryRepository(connection, self._workspace_id)
            versions = repository.list_versions(limit=MAX_LIBRARY_VERSIONS)
            current = repository.current_release_version_id()
            released = repository.released_version_ids()
        return tuple(
            self._summarize(row, current=current, released=released)
            for row in versions
        )

    def get_version(
        self,
        version_id: UUID,
        *,
        preview_limit: int = 5,
        store_ids: tuple[str, ...] | None = None,
    ) -> LibraryVersionDetail:
        if type(preview_limit) is not int or not 1 <= preview_limit <= MAX_LIBRARY_PREVIEW:
            raise ValueError("LIBRARY_PREVIEW_LIMIT_INVALID")
        with self._engine.connect() as connection:
            repository = LibraryRepository(connection, self._workspace_id)
            version = repository.get_version(version_id)
            if version is None:
                raise LibraryNotFound
            current = repository.current_release_version_id()
            released = repository.released_version_ids()
            analyses = repository.completed_analysis_kinds(version_id)
            uploads = repository.uploads(
                version["source_workflow_id"],
                limit=MAX_LIBRARY_PROVENANCE,
            )
        all_tables = self._load_tables(version_id)
        catalog = self._store_scopes.catalog(version_id)
        resolved_scope = self._store_scopes.resolve(version_id, store_ids)
        tables = _scope_tables(all_tables, resolved_scope)
        summary = self._summary_from_tables(
            version,
            tables,
            current=current,
            released=released,
        )
        table_items = tuple(
            LibraryTable(
                role=role,
                scope_kind=_scope_kind(all_tables[role]),
                row_count=len(rows),
                columns=_safe_columns(rows)[:40],
                preview=tuple(_safe_row(row) for row in rows[:preview_limit]),
            )
            for role, rows in sorted(tables.items())[:MAX_LIBRARY_TABLES]
        )
        provenance = self._provenance(uploads, tables)
        with self._engine.connect() as connection:
            exports = DatasetExportRepository(connection).list(
                self._workspace_id,
                version_id,
            )
        return LibraryVersionDetail(
            **{field: getattr(summary, field) for field in LibraryVersion.__dataclass_fields__},
            store_catalog=catalog,
            resolved_scope=resolved_scope,
            tables=table_items,
            provenance=provenance,
            analyses=analyses,
            exports=exports,
        )

    def tables_for_export(self, version_id: UUID):
        """Return verified normalized tables only to the bounded export service."""

        return self._load_tables(version_id, total_byte_limit=MAX_DETAIL_BYTES)

    def get_table_page(
        self,
        version_id: UUID,
        role: str,
        *,
        page: int = 1,
        page_size: int = 50,
        store_ids: tuple[str, ...] | None = None,
    ) -> LibraryTablePage:
        if type(page) is not int or page < 1:
            raise ValueError("LIBRARY_PAGE_INVALID")
        if type(page_size) is not int or page_size not in ALLOWED_LIBRARY_PAGE_SIZES:
            raise ValueError("LIBRARY_PAGE_SIZE_INVALID")
        all_rows = self._load_table(version_id, role)
        scope = self._store_scopes.resolve(version_id, store_ids)
        rows = _scope_rows(all_rows, scope)
        total_rows = len(rows)
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        if page > total_pages:
            raise ValueError("LIBRARY_PAGE_INVALID")
        start = (page - 1) * page_size
        safe_rows = tuple(_safe_row(row) for row in rows[start : start + page_size])
        return LibraryTablePage(
            role=role,
            scope_kind=_scope_kind(all_rows),
            columns=_safe_columns(rows),
            rows=safe_rows,
            page=page,
            page_size=page_size,
            total_rows=total_rows,
            total_pages=total_pages,
        )

    def _load_table(
        self,
        version_id: UUID,
        role: str,
    ) -> tuple[dict[str, object], ...]:
        """Load only until the requested normalized table is found.

        The current immutable artifact is JSON, so its containing artifact must still
        be parsed. Stopping at the first matching table avoids opening unrelated
        later artifacts, while page sanitization is limited to the returned slice.
        """

        if self._storage is None:
            raise LibraryTableNotFound
        with self._engine.connect() as connection:
            repository = LibraryRepository(connection, self._workspace_id)
            version = repository.get_version(version_id)
            if version is None:
                raise LibraryNotFound
            artifacts = repository.artifacts(version_id, limit=MAX_LIBRARY_TABLES)
            storage_repository = StorageObjectRepository(connection)
            storage_records = tuple(
                storage_repository.get(artifact["storage_object_id"])
                for artifact in artifacts
            )
        opened_bytes = 0
        for artifact, storage in zip(artifacts, storage_records, strict=True):
            if (
                storage is None
                or storage.workspace_id != self._workspace_id
                or storage.state != "available"
                or storage.purpose != "normalized_dataset"
                or storage.sha256 != artifact["sha256"]
            ):
                raise LibraryUnavailable
            if version["schema_version"] == "synthetic.v1" and artifact[
                "artifact_kind"
            ] != "analysis_bundle":
                continue
            opened_bytes += storage.size_bytes
            if storage.size_bytes > MAX_ARTIFACT_BYTES or opened_bytes > MAX_DETAIL_BYTES:
                raise LibraryUnavailable
            with self._storage.open_verified(
                storage.object_key,
                artifact["sha256"],
                storage.size_bytes,
            ) as opened:
                payload = json.load(opened)
            raw_tables = payload.get("tables") if isinstance(payload, dict) else None
            if not isinstance(raw_tables, dict) or role not in raw_tables:
                continue
            rows = raw_tables[role]
            if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
                raise LibraryUnavailable
            return tuple(rows)
        raise LibraryTableNotFound

    def _summarize(self, version, *, current, released) -> LibraryVersion:
        try:
            tables = self._load_tables(
                version["id"],
                total_byte_limit=MAX_SUMMARY_BYTES_PER_VERSION,
            )
            authority_available = True
        except LibraryUnavailable:
            tables = {}
            authority_available = False
        return self._summary_from_tables(
            version,
            tables,
            current=current,
            released=released,
            authority_available=authority_available,
        )

    def _summary_from_tables(
        self,
        version,
        tables,
        *,
        current,
        released,
        authority_available: bool = True,
    ):
        roles = tuple(sorted(tables))
        period_start, period_end = _period(tables)
        stores = _unique_count(tables, "store_id")
        skus = _unique_count(tables, "sku_id")
        missing = tuple(role for role in PUBLIC_SOURCE_ROLES if role not in tables)
        quality = QualitySummary(
            status=(
                "unavailable"
                if not authority_available
                else "complete" if not missing else "needs_inputs"
            ),
            missing_roles=missing if authority_available else (),
            issue_count=len(missing) if authority_available else 0,
        )
        if version["id"] == current:
            lifecycle = "current"
        elif version["id"] in released:
            lifecycle = "published"
        else:
            lifecycle = "unpublished"
        preparation = self._preparation(version["id"])
        return LibraryVersion(
            dataset_version_id=version["id"],
            version_number=version["version_number"],
            lifecycle=lifecycle,
            created_at=version["created_at"],
            period_start=period_start,
            period_end=period_end,
            stores=stores,
            skus=skus,
            source_roles=roles,
            row_count=sum(len(rows) for rows in tables.values()),
            quality=quality,
            preparation=preparation,
            preview_available=bool(tables),
            export_available=self._has_export(version["id"]),
        )

    def _has_export(self, version_id: UUID) -> bool:
        with self._engine.connect() as connection:
            return bool(
                DatasetExportRepository(connection).list(
                    self._workspace_id,
                    version_id,
                    limit=1,
                )
            )

    def _preparation(self, version_id: UUID) -> PreparationSummary:
        if self._preparations is None:
            with self._engine.connect() as connection:
                kinds = LibraryRepository(
                    connection,
                    self._workspace_id,
                ).completed_analysis_kinds(version_id)
            status = "ready" if len(kinds) >= 5 else "not_started"
            return PreparationSummary(status, kinds)
        result = self._preparations.readiness(version_id)
        domains = tuple(
            item.name for item in result.domains if item.status == "ready"
        )
        return PreparationSummary(result.status, domains)

    def _load_tables(
        self,
        version_id: UUID,
        *,
        total_byte_limit: int = MAX_DETAIL_BYTES,
    ) -> dict[str, tuple[dict[str, object], ...]]:
        if self._storage is None:
            return {}
        with self._engine.connect() as connection:
            repository = LibraryRepository(connection, self._workspace_id)
            version = repository.get_version(version_id)
            if version is None:
                raise LibraryNotFound
            artifacts = repository.artifacts(version_id, limit=MAX_LIBRARY_TABLES)
            storage_repository = StorageObjectRepository(connection)
            storage_records = tuple(
                storage_repository.get(artifact["storage_object_id"])
                for artifact in artifacts
            )
        tables: dict[str, tuple[dict[str, object], ...]] = {}
        opened_bytes = 0
        for artifact, storage in zip(artifacts, storage_records, strict=True):
            if (
                storage is None
                or storage.workspace_id != self._workspace_id
                or storage.state != "available"
                or storage.purpose != "normalized_dataset"
                or storage.sha256 != artifact["sha256"]
            ):
                raise LibraryUnavailable
            if version["schema_version"] == "synthetic.v1" and artifact[
                "artifact_kind"
            ] != "analysis_bundle":
                continue
            opened_bytes += storage.size_bytes
            if (
                storage.size_bytes > MAX_ARTIFACT_BYTES
                or opened_bytes > total_byte_limit
            ):
                raise LibraryUnavailable
            with self._storage.open_verified(
                storage.object_key,
                artifact["sha256"],
                storage.size_bytes,
            ) as opened:
                payload = json.load(opened)
            raw_tables = payload.get("tables") if isinstance(payload, dict) else None
            if not isinstance(raw_tables, dict):
                continue
            for role, rows in raw_tables.items():
                if (
                    role in tables
                    or not isinstance(role, str)
                    or not isinstance(rows, list)
                    or not all(isinstance(row, dict) for row in rows)
                ):
                    raise LibraryUnavailable
                tables[role] = tuple(dict(row) for row in rows)
        return tables

    @staticmethod
    def _provenance(uploads, tables) -> tuple[LibraryProvenance, ...]:
        if uploads:
            return tuple(
                LibraryProvenance(
                    source_name=str(row["source_filename"]),
                    source_role=str(row["source_role"] or "unclassified"),
                    status=str(row["status"]),
                    adapter=(str(row["adapter_id"]) if row["adapter_id"] else None),
                    row_count=_quality_count(row["quality_report"]),
                )
                for row in uploads[:MAX_LIBRARY_PROVENANCE]
            )
        return tuple(
            LibraryProvenance(
                source_name="BizPulse prepared data",
                source_role=role,
                status="available",
                adapter=None,
                row_count=len(rows),
            )
            for role, rows in sorted(tables.items())[:MAX_LIBRARY_PROVENANCE]
        )


def _quality_count(value) -> int | None:
    if not isinstance(value, Mapping):
        return None
    count = value.get("record_count")
    return count if type(count) is int and count >= 0 else None


def _safe_key(key: object) -> bool:
    blocked = (
        "object_key",
        "sha256",
        "digest",
        "storage_object",
        "source_classification",
    )
    return not any(token in str(key).lower() for token in blocked)


def _safe_value(value):
    if isinstance(value, Mapping):
        return {
            str(key): _safe_value(item)
            for key, item in value.items()
            if _safe_key(key)
        }
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    return value


def _safe_columns(rows) -> tuple[str, ...]:
    return tuple(
        sorted(
            {
                str(key)
                for row in rows
                for key in row
                if _safe_key(key)
            }
        )
    )


def _safe_row(row: Mapping[str, object]) -> dict[str, object]:
    return {
        str(key): _safe_value(value)
        for key, value in row.items()
        if _safe_key(key)
    }


def _period(tables) -> tuple[date | None, date | None]:
    values: list[date] = []
    for role in FACT_PERIOD_ROLES:
        for row in tables.get(role, ()):
            value = row.get("date")
            if isinstance(value, str):
                try:
                    values.append(date.fromisoformat(value))
                except ValueError:
                    pass
    return (min(values), max(values)) if values else (None, None)


def _unique_count(tables, field: str) -> int:
    return len(
        {
            str(row[field])
            for rows in tables.values()
            for row in rows
            if row.get(field) not in (None, "")
        }
    )


def _scope_tables(
    tables: Mapping[str, tuple[dict[str, object], ...]],
    scope: StoreScope,
) -> dict[str, tuple[dict[str, object], ...]]:
    return {
        role: _scope_rows(rows, scope)
        for role, rows in tables.items()
    }


def _scope_rows(
    rows: tuple[dict[str, object], ...],
    scope: StoreScope,
) -> tuple[dict[str, object], ...]:
    if scope.kind == "all" or _scope_kind(rows) == "shared":
        return rows
    accepted = []
    for row in rows:
        store_id = row.get("store_id")
        if isinstance(store_id, str) and store_id in scope.store_ids:
            accepted.append(row)
        elif store_id in (None, "") and row.get("scope") == "shared":
            accepted.append(row)
    return tuple(accepted)


def _scope_kind(rows: tuple[dict[str, object], ...]) -> str:
    return "store" if any("store_id" in row for row in rows) else "shared"
