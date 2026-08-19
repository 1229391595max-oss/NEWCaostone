from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.admin_ai import AIControlProjection
from src.repositories.imports import ImportRepository
from src.services.admin_summary_service import AdminSummaryService, project_ai_control
from src.services.dataset_service import DatasetService
from src.services.public_release_service import PublicReleaseService
from tests.auth_support import (
    SESSION_PEPPER,
    WORKSPACE_ID,
    fast_password_hasher,
    seed_operator,
    seed_public_release,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)


class ReadyStorage:
    def check_readiness(self) -> None:
        return None


class ControlService:
    def get(self) -> AIControlProjection:
        return AIControlProjection(
            workspace_id=WORKSPACE_ID,
            operator_enabled=True,
            demo_enabled=False,
            key_name="openai-api-key",
            key_version="secret-version-must-not-project",
            key_reference="openai-api-key/secret-version-must-not-project",
            key_fingerprint="7fa2c91e" + "a" * 56,
            verified_at=NOW,
            key_validation_state="verified",
            revision=4,
            updated_by_operator_id=None,
            updated_at=NOW,
        )


def test_summary_projects_release_import_readiness_and_safe_ai_state(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    released_version_id = seed_public_release(migrated_engine)
    with PostgresUnitOfWork(migrated_engine) as uow:
        imports = ImportRepository(uow.connection)
        workflow = imports.create_workflow(
            workspace_id=WORKSPACE_ID,
            source_confirmed_synthetic=True,
            now=NOW,
        )
        imports.transition_workflow(
            workflow.id,
            expected_revision=0,
            status="rejected",
            failure_code="UPLOAD_INVALID",
            now=NOW,
        )

    summary = AdminSummaryService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        dataset_service=DatasetService(migrated_engine, WORKSPACE_ID),
        public_release_service=PublicReleaseService(
            migrated_engine,
            WORKSPACE_ID,
            idempotency_pepper=SESSION_PEPPER,
        ),
        ai_control_service=ControlService(),
        workflow_storage=ReadyStorage(),
    ).get()

    assert summary.system.database == "ready"
    assert summary.system.blob == "ready"
    assert summary.system.configuration == "valid"
    assert summary.system.migration == "0017_ai_turn_credential_binding"
    assert summary.published_dataset is not None
    assert summary.published_dataset.dataset_version_id == released_version_id
    assert summary.published_dataset.version_number == 1
    assert summary.latest_import is not None
    assert summary.latest_import.workflow_id == workflow.id
    assert summary.latest_import.status == "rejected"
    assert summary.latest_import.failure_code == "UPLOAD_INVALID"
    assert summary.actionable_failure_count == 1
    assert summary.ai.credential.fingerprint == "7fa2c91e"
    serialized = repr(summary).lower()
    assert "secret-version-must-not-project" not in serialized
    assert "openai-api-key" not in serialized


def test_summary_maps_probe_failures_without_serializing_exceptions(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())

    class FailingStorage:
        def check_readiness(self) -> None:
            raise RuntimeError("blob-connection-secret-sentinel")

    class FailingControl:
        def get(self):
            raise RuntimeError("key-vault-secret-sentinel")

    summary = AdminSummaryService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        dataset_service=DatasetService(migrated_engine, WORKSPACE_ID),
        public_release_service=PublicReleaseService(
            migrated_engine,
            WORKSPACE_ID,
            idempotency_pepper=SESSION_PEPPER,
        ),
        ai_control_service=FailingControl(),
        workflow_storage=FailingStorage(),
    ).get()

    assert summary.system.blob == "unavailable"
    assert summary.ai.status == "unavailable"
    serialized = repr(summary).lower()
    assert "blob-connection-secret-sentinel" not in serialized
    assert "key-vault-secret-sentinel" not in serialized


def test_ai_projection_requires_a_complete_exact_version_binding() -> None:
    state = ControlService().get()

    projected = project_ai_control(replace(state, key_version=None, key_reference=None))

    assert projected.credential.configured is False
    assert projected.credential.fingerprint is None
    assert projected.credential.verified_at is None
