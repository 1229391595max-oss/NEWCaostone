from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from azure.core.credentials import AzureNamedKeyCredential
from azure.storage.blob import ContainerClient
from azure.storage.blob._shared.parser import (
    DEVSTORE_ACCOUNT_KEY,
    DEVSTORE_ACCOUNT_NAME,
)
from sqlalchemy import Engine

from api.main import create_app
from src.ai.query_catalog import QueryCatalog
from src.ai.contracts import PlanningDecision, ProviderResult, QueryPlan
from src.ai.query_executor import PostgresQueryBackend, QueryExecutor
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.analysis_service import AnalysisService
from src.services.ai_chat_service import AIBudgetLimits, AIChatService
from src.services.action_service import ActionService
from src.services.demo_action_authority import DemoActionAuthority
from src.services.demo_session_service import DemoSessionService
from src.services.dataset_service import DatasetService
from src.services.dataset_preparation_service import DatasetPreparationService
from src.services.dataset_export_service import DatasetExportService
from src.services.forecast_service import ForecastService
from src.services.import_service import ImportService
from src.services.library_service import LibraryService
from src.services.profit_bridge_service import ProfitBridgeService
from src.services.public_release_service import PublicReleaseService
from scripts.seed_demo import SEED_NAMESPACE, seed_verified_hosted_bundle
from src.storage.azure_blob_workflow_storage import AzureBlobWorkflowStorage
from src.storage.postgres_entry_locks import PostgresEntryLockManager
from src.synthetic.generator import generate_demo
from src.synthetic.seed import ensure_demo_action, seed_demo
from tests.auth_support import (
    SESSION_PEPPER,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import WORKSPACE_ID
from tests.services.test_ai_chat_service import FakeAIControl, FakeGateway

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class BoundedLatencyGateway(FakeGateway):
    """Deterministic fake whose latency keeps real concurrent turns in flight."""

    def __init__(self, delay_seconds: float = 0.05) -> None:
        super().__init__()
        self._delay_seconds = delay_seconds

    def plan(
        self,
        question,
        capability_catalog,
        history=(),
        *,
        credential_version: str,
    ):
        time.sleep(self._delay_seconds)
        if question == "Prepare one synthetic stockout action":
            del capability_catalog
            self.plan_calls += 1
            self.plan_histories.append(tuple(history))
            return ProviderResult(
                PlanningDecision(
                    status="planned",
                    plan=QueryPlan.model_validate(
                        {
                            "tool": "inventory_risk_lookup",
                            "arguments": {"risk": "stockout", "limit": 1},
                        }
                    ),
                ),
                input_tokens=20,
                output_tokens=5,
            )
        return super().plan(
            question,
            capability_catalog,
            history,
            credential_version=credential_version,
        )

    def explain(self, *args, **kwargs):
        time.sleep(self._delay_seconds)
        return super().explain(*args, **kwargs)


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@contextmanager
def acceptance_server(
    engine: Engine,
    container: ContainerClient,
    *,
    gateway_mode: str = "normal",
):
    """Run one disposable application process against retained DB/Blob state."""

    port = available_port()
    environment = os.environ.copy()
    environment.update(
        {
            "BIZPULSE_TEST_DATABASE_URL": str(engine.url),
            "BIZPULSE_TEST_BLOB_ACCOUNT_URL": container.url.rsplit("/", 1)[0],
            "BIZPULSE_TEST_BLOB_CONTAINER": container.container_name,
            "BIZPULSE_TEST_GATEWAY_MODE": gateway_mode,
        }
    )
    environment["BIZPULSE_TEST_ALLOWED_ORIGIN"] = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "tests.acceptance.restart_server:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "critical",
        ],
        cwd=PROJECT_ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while True:
            if process.poll() is not None:
                raise RuntimeError("acceptance_server_start_failed")
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                    break
            except OSError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("acceptance_server_start_timeout")
                time.sleep(0.05)
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@contextmanager
def azurite_container():
    """Own one bounded local Azurite Blob process and remove its temp root."""

    port = available_port()
    executable = _azurite_blob_executable()
    with tempfile.TemporaryDirectory(prefix="newcaostone-azurite-") as temporary:
        process = subprocess.Popen(
            [
                str(executable),
                "--blobHost",
                "127.0.0.1",
                "--blobPort",
                str(port),
                "--location",
                temporary,
                "--silent",
                "--disableTelemetry",
                "--skipApiVersionCheck",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 10
            while True:
                if process.poll() is not None:
                    raise RuntimeError("azurite_blob_start_failed")
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                        break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("azurite_blob_start_timeout")
                    time.sleep(0.05)
            container = ContainerClient(
                account_url=(f"http://127.0.0.1:{port}/{DEVSTORE_ACCOUNT_NAME}"),
                container_name=f"newcaostone-{uuid4().hex}",
                credential=AzureNamedKeyCredential(
                    DEVSTORE_ACCOUNT_NAME,
                    DEVSTORE_ACCOUNT_KEY,
                ),
            )
            container.create_container()
            try:
                yield container
            finally:
                container.delete_container()
                container.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def _azurite_blob_executable() -> Path:
    configured = os.getenv("BIZPULSE_TEST_AZURITE_BLOB_EXECUTABLE")
    executable = (
        Path(configured)
        if configured is not None
        else PROJECT_ROOT / "node_modules" / ".bin" / "azurite-blob"
    ).resolve()
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError("azurite_blob_executable_missing")
    return executable


def azure_storage(
    engine: Engine,
    container: ContainerClient,
) -> AzureBlobWorkflowStorage:
    return AzureBlobWorkflowStorage(
        container_client=container,
        workspace_id=WORKSPACE_ID,
        staging_scope="acceptance",
        entry_locks=PostgresEntryLockManager(engine),
    )


def seed_fixed_release(engine: Engine, storage) -> UUID:
    clock = initial_clock()
    seed_operator(engine, fast_password_hasher())
    bundle = generate_demo()
    version_id = uuid5(SEED_NAMESPACE, f"version:{bundle.manifest_sha256}")
    seeded = seed_verified_hosted_bundle(
        bundle,
        PostgresUnitOfWork(engine),
        storage,
        expected_manifest_sha256=bundle.manifest_sha256,
        expected_dataset_version_id=version_id,
        seed=lambda item, uow, target_storage: seed_demo(
            item,
            uow,
            target_storage,
            now=clock(),
        ),
        ensure_action=lambda target_engine, target_storage, dataset_version_id: (
            ensure_demo_action(
                target_engine,
                target_storage,
                dataset_version_id,
                now=clock(),
            )
        ),
    )
    return seeded.dataset_version_id


def build_acceptance_app(
    engine: Engine,
    storage,
    *,
    gateway=None,
    allowed_origin: str | None = None,
    clock=None,
    budget_limits: AIBudgetLimits | None = None,
    ai_enabled: bool = True,
):
    clock = clock or initial_clock()
    analyses = AnalysisService(engine, storage, WORKSPACE_ID, clock=clock)
    profit_bridge = ProfitBridgeService(
        engine,
        storage,
        WORKSPACE_ID,
        analysis_service=analyses,
        clock=clock,
    )
    forecasts = ForecastService(
        engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
    )
    action_authority = DemoActionAuthority(
        engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
        profit_bridge_service=profit_bridge,
    )
    preparation = DatasetPreparationService(
        engine,
        WORKSPACE_ID,
        analysis_service=analyses,
        profit_bridge_service=profit_bridge,
        forecast_service=forecasts,
        action_authority=action_authority,
    )
    public_release = PublicReleaseService(
        engine,
        WORKSPACE_ID,
        idempotency_pepper=SESSION_PEPPER,
        clock=clock,
        analysis_service=analyses,
        profit_bridge_service=profit_bridge,
        action_authority=action_authority,
        preparation_service=preparation,
    )
    actions = ActionService(
        engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
    )
    chat = None
    if ai_enabled:
        chat = AIChatService(
            engine=engine,
            workspace_id=WORKSPACE_ID,
            catalog=QueryCatalog(),
            executor=QueryExecutor(
                backend=PostgresQueryBackend(
                    engine=engine,
                    analysis_service=analyses,
                    forecast_service=forecasts,
                    profit_bridge_service=profit_bridge,
                    action_service=actions,
                )
            ),
            gateway=gateway or BoundedLatencyGateway(),
            ai_control=FakeAIControl(),
            budget_limits=budget_limits
            or AIBudgetLimits(
                daily_attempt_limit=500,
                monthly_token_limit=1_000_000,
                max_concurrent_turns=15,
                session_attempt_limit_per_minute=5,
                global_attempt_limit_per_minute=100,
            ),
            action_service=actions,
            clock=clock,
        )
    base = build_container(engine, clock)
    if allowed_origin is not None:
        base = replace(
            base,
            settings=replace(base.settings, allowed_origin=allowed_origin),
        )
    sessions = DemoSessionService(
        engine=engine,
        workspace_id=WORKSPACE_ID,
        session_pepper=SESSION_PEPPER,
        source_session_limit_per_hour=50,
        release_validator=public_release.release_ready,
        forecast_resolver=forecasts.completed_id_for_session,
        profit_bridge_resolver=profit_bridge.completed_id_for_session,
        clock=clock,
    )
    imports = ImportService(
        engine=engine,
        storage=storage,
        workspace_id=WORKSPACE_ID,
        idempotency_pepper=SESSION_PEPPER,
        clock=clock,
    )
    library = LibraryService(engine, storage, WORKSPACE_ID)
    container = replace(
        base,
        workflow_storage=storage,
        import_service=imports,
        library_service=library,
        dataset_export_service=DatasetExportService(
            engine,
            storage,
            WORKSPACE_ID,
            library,
        ),
        analysis_service=analyses,
        public_release_service=public_release,
        dataset_service=DatasetService(engine, WORKSPACE_ID),
        dataset_preparation_service=preparation,
        forecast_service=forecasts,
        profit_bridge_service=profit_bridge,
        action_service=actions,
        ai_chat_service=chat,
        demo_session_service=sessions,
    )
    return create_app(container=container)
