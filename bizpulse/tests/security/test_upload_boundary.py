from __future__ import annotations

import pytest
from sqlalchemy import Engine

from api.main import create_app
from src.adapters.protocol import AdapterError
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.import_service import ImportService
from src.synthetic.boundary import SyntheticSourceBoundaryError
from tests.import_support import WORKSPACE_ID, MemoryWorkflowStorage
from tests.auth_support import build_container, initial_clock


def test_viewer_api_surface_has_no_import_or_publish_route(
    migrated_engine: Engine,
) -> None:
    app = create_app(container=build_container(migrated_engine, initial_clock()))
    viewer_paths = {
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith("/api/demo")
    }

    for forbidden in ("upload", "import", "mapping", "commit", "publish"):
        assert all(forbidden not in path for path in viewer_paths)


def test_upload_with_pii_pattern_is_rejected_without_echo(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = ImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )
    workflow = service.create_workflow(True, "boundary-workflow").workflow
    value = "person@example.test"
    payload = (
        "date,sku_id,spend_brl,impressions,clicks,attributed_orders,"
        "source_classification\n"
        f"2026-07-01,SYNTH-SKU-001,10,100,10,2,{value}\n"
    ).encode()

    with pytest.raises(SyntheticSourceBoundaryError) as captured:
        service.upload(
            workflow.id,
            filename="advertising.csv",
            media_type="text/csv",
            content=payload,
            idempotency_key="boundary-upload",
        )

    assert captured.value.code == "SYNTHETIC_SOURCE_BOUNDARY_FAILED"
    assert value not in str(captured.value)
    assert storage.objects == {}


@pytest.mark.parametrize(
    "unsafe_value",
    [
        "=HYPERLINK(\"https://invalid.test\")",
        "sk-" + "proj-" + "secretvalue12345",
    ],
)
def test_upload_formula_or_credential_is_rejected_before_storage(
    migrated_engine: Engine,
    unsafe_value: str,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = ImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )
    workflow = service.create_workflow(True, "unsafe-boundary-workflow").workflow
    payload = (
        "date,sku_id,spend_brl,impressions,clicks,attributed_orders,"
        "source_classification\n"
        f"2026-07-01,SYNTH-SKU-001,10,100,10,2,{unsafe_value}\n"
    ).encode()

    with pytest.raises(SyntheticSourceBoundaryError) as captured:
        service.upload(
            workflow.id,
            filename="advertising.csv",
            media_type="text/csv",
            content=payload,
            idempotency_key="unsafe-boundary-upload",
        )

    assert unsafe_value not in str(captured.value)
    assert storage.objects == {}


def test_upload_rejects_sensitive_value_in_undeclared_trailing_column(
    migrated_engine: Engine,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = ImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )
    workflow = service.create_workflow(True, "extra-column-workflow").workflow
    sensitive_value = "person@example.test"
    payload = (
        "date,sku_id,spend_brl,impressions,clicks,attributed_orders,"
        "source_classification\n"
        "2026-07-01,SYNTH-SKU-001,10,100,10,2,pure_synthetic,"
        f"{sensitive_value}\n"
    ).encode()

    with pytest.raises(AdapterError) as captured:
        service.upload(
            workflow.id,
            filename="advertising.csv",
            media_type="text/csv",
            content=payload,
            idempotency_key="extra-column-upload",
        )

    assert sensitive_value not in str(captured.value)
    assert storage.objects == {}


@pytest.mark.parametrize(
    ("filename", "scenario_id"),
    [
        ("person@example.test.csv", "safe_scenario"),
        ("advertising.csv", "Rua das Flores, 123"),
    ],
)
def test_upload_rejects_sensitive_filename_or_address_before_storage(
    migrated_engine: Engine,
    filename: str,
    scenario_id: str,
) -> None:
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    storage = MemoryWorkflowStorage()
    service = ImportService(
        engine=migrated_engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper="test-import-idempotency-pepper",
    )
    workflow = service.create_workflow(True, "metadata-boundary-workflow").workflow
    payload = (
        "date,sku_id,spend_brl,impressions,clicks,attributed_orders,"
        "scenario_id,source_classification\n"
        f'2026-07-01,SYNTH-SKU-001,10,100,10,2,"{scenario_id}",pure_synthetic\n'
    ).encode()

    with pytest.raises(SyntheticSourceBoundaryError):
        service.upload(
            workflow.id,
            filename=filename,
            media_type="text/csv",
            content=payload,
            idempotency_key="metadata-boundary-upload",
        )

    assert storage.objects == {}
