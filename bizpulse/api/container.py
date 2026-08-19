"""Application dependency container."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import Engine
from azure.storage.blob import ContainerClient

from src.ai.credential_validation import OpenAICredentialValidator
from src.ai.openai_gateway import OpenAIGateway
from src.ai.query_catalog import QueryCatalog
from src.ai.query_executor import PostgresQueryBackend, QueryExecutor
from src.config import (
    APPROVED_OPENAI_KEY_VAULT_SECRET_NAME,
    BizPulseSettings,
    ConfigError,
)
from src.db.engine import create_postgres_engine
from src.services.analysis_service import AnalysisService
from src.services.admin_summary_service import AdminSummaryService
from src.services.ai_chat_service import AIBudgetLimits, AIChatService
from src.services.ai_control_service import AIControlService
from src.services.action_service import ActionService
from src.services.dataset_service import DatasetService
from src.services.dataset_preparation_service import DatasetPreparationService
from src.services.dataset_export_service import DatasetExportService
from src.services.demo_action_authority import DemoActionAuthority
from src.services.demo_session_service import DemoSessionService
from src.services.forecast_service import ForecastService
from src.services.import_service import ImportService
from src.services.library_service import LibraryService
from src.services.operator_auth_service import OperatorAuthService
from src.services.openai_key_rotation_service import OpenAIKeyRotationService
from src.services.profit_bridge_service import ProfitBridgeService
from src.services.preferences_service import PreferencesService
from src.services.public_release_service import PublicReleaseService
from src.secrets.azure_openai import (
    AzureOpenAIClientProvider,
    FixedOpenAIClientProvider,
    OpenAIClientProvider,
)
from src.storage.azure_blob_workflow_storage import build_storage
from src.storage.lifecycle import StorageLifecycle
from src.storage.postgres_entry_locks import PostgresEntryLockManager
from src.storage.protocol import WorkflowStorage

WORKSPACE_ID = "synthetic-demo"


@dataclass(frozen=True, slots=True)
class ApiContainer:
    """Dependencies shared by API routes."""

    settings: BizPulseSettings
    query_catalog: QueryCatalog = field(default_factory=QueryCatalog)
    engine: Engine | None = None
    operator_auth_service: OperatorAuthService | None = None
    demo_session_service: DemoSessionService | None = None
    workflow_storage: WorkflowStorage | None = None
    storage_lifecycle: StorageLifecycle | None = None
    import_service: ImportService | None = None
    library_service: LibraryService | None = None
    dataset_service: DatasetService | None = None
    dataset_preparation_service: DatasetPreparationService | None = None
    dataset_export_service: DatasetExportService | None = None
    analysis_service: AnalysisService | None = None
    public_release_service: PublicReleaseService | None = None
    forecast_service: ForecastService | None = None
    profit_bridge_service: ProfitBridgeService | None = None
    action_service: ActionService | None = None
    ai_chat_service: AIChatService | None = None
    ai_control_service: AIControlService | None = None
    openai_key_rotation_service: OpenAIKeyRotationService | None = None
    ai_client_provider: OpenAIClientProvider | None = None
    preferences_service: PreferencesService | None = None
    admin_summary_service: AdminSummaryService | None = None

    def close(self) -> None:
        if self.ai_client_provider is not None:
            self.ai_client_provider.close()

    @classmethod
    def build(
        cls,
        settings: BizPulseSettings,
        *,
        openai_client=None,
        openai_secret_manager=None,
        openai_credential_validator=None,
    ) -> ApiContainer:
        engine = create_postgres_engine(settings.database_url)
        operator_auth_service = None
        demo_session_service = None
        public_release_service = None
        if settings.session_pepper is not None:
            operator_auth_service = OperatorAuthService(
                engine=engine,
                workspace_id=WORKSPACE_ID,
                session_pepper=settings.session_pepper,
            )

        workflow_storage = None
        storage_lifecycle = None
        import_service = None
        analysis_service = None
        forecast_service = None
        profit_bridge_service = None
        action_service = None
        demo_action_authority = None
        dataset_preparation_service = None
        if settings.runtime_environment == "cloud":
            if settings.blob_connection_string is not None:
                container_client = ContainerClient.from_connection_string(
                    settings.blob_connection_string,
                    container_name=settings.blob_container,
                )
            else:
                container_client = ContainerClient(
                    account_url=settings.blob_endpoint,
                    container_name=settings.blob_container,
                )
            entry_locks = PostgresEntryLockManager(engine)
            workflow_storage = build_storage(
                settings,
                container_client,
                entry_locks=entry_locks,
            )
            storage_lifecycle = StorageLifecycle(
                engine,
                workflow_storage,
                WORKSPACE_ID,
            )
            if settings.session_pepper is not None:
                import_service = ImportService(
                    engine=engine,
                    storage=workflow_storage,
                    workspace_id=WORKSPACE_ID,
                    idempotency_pepper=settings.session_pepper,
                )
            analysis_service = AnalysisService(
                engine=engine,
                storage=workflow_storage,
                workspace_id=WORKSPACE_ID,
            )
            forecast_service = ForecastService(
                engine=engine,
                storage=workflow_storage,
                workspace_id=WORKSPACE_ID,
            )
            profit_bridge_service = ProfitBridgeService(
                engine=engine,
                storage=workflow_storage,
                workspace_id=WORKSPACE_ID,
                analysis_service=analysis_service,
            )
            action_service = ActionService(
                engine=engine,
                storage=workflow_storage,
                workspace_id=WORKSPACE_ID,
            )
            demo_action_authority = DemoActionAuthority(
                engine,
                workflow_storage,
                WORKSPACE_ID,
                profit_bridge_service=profit_bridge_service,
            )
            dataset_preparation_service = DatasetPreparationService(
                engine,
                WORKSPACE_ID,
                analysis_service=analysis_service,
                profit_bridge_service=profit_bridge_service,
                forecast_service=forecast_service,
                action_authority=demo_action_authority,
            )

        if settings.session_pepper is not None:
            public_release_service = PublicReleaseService(
                engine,
                WORKSPACE_ID,
                idempotency_pepper=settings.session_pepper,
                analysis_service=analysis_service,
                profit_bridge_service=profit_bridge_service,
                action_authority=demo_action_authority,
                forecast_service=forecast_service,
                preparation_service=dataset_preparation_service,
            )
            demo_session_service = DemoSessionService(
                engine=engine,
                workspace_id=WORKSPACE_ID,
                session_pepper=settings.session_pepper,
                release_validator=(
                    public_release_service.release_ready
                    if analysis_service is not None
                    else None
                ),
                forecast_resolver=(
                    forecast_service.completed_id_for_session
                    if forecast_service is not None
                    else None
                ),
                profit_bridge_resolver=(
                    profit_bridge_service.completed_id_for_session
                    if profit_bridge_service is not None
                    else None
                ),
                source_session_limit_per_hour=(
                    settings.demo_session_rate_limit_per_hour
                ),
            )

        query_catalog = QueryCatalog()
        ai_chat_service = None
        ai_control_service = None
        openai_key_rotation_service = None
        ai_client_provider = None
        if settings.ai_chat_enabled:
            if not all(
                (
                    analysis_service,
                    forecast_service,
                    profit_bridge_service,
                    action_service,
                )
            ):
                raise ConfigError("ai_chat_authority_services_unavailable")
            limits = (
                settings.ai_daily_attempt_limit,
                settings.ai_monthly_token_limit,
                settings.ai_max_concurrent_turns,
                settings.ai_session_attempt_limit_per_minute,
                settings.ai_global_attempt_limit_per_minute,
            )
            if any(value is None for value in limits):
                raise ConfigError("ai_chat_requires_all_budget_limits")
            if openai_client is None:
                key_vault_bindings = (
                    settings.openai_key_vault_url,
                    settings.openai_key_vault_secret_name,
                    settings.openai_managed_identity_client_id,
                )
                if any(value is None for value in key_vault_bindings):
                    raise ConfigError("ai_chat_requires_key_vault_bindings")
                ai_client_provider = AzureOpenAIClientProvider(
                    vault_url=settings.openai_key_vault_url,
                    secret_name=settings.openai_key_vault_secret_name,
                    managed_identity_client_id=(
                        settings.openai_managed_identity_client_id
                    ),
                )
                openai_secret_manager = ai_client_provider.secret_manager
            else:
                ai_client_provider = FixedOpenAIClientProvider(openai_client)
                if openai_secret_manager is None:
                    raise ConfigError("ai_chat_test_secret_manager_required")
            if operator_auth_service is None or settings.session_pepper is None:
                raise ConfigError("ai_chat_requires_operator_authority")
            credential_validator = (
                openai_credential_validator or OpenAICredentialValidator()
            )
            ai_control_service = AIControlService(
                engine=engine,
                workspace_id=WORKSPACE_ID,
                operator_auth_service=operator_auth_service,
                secret_manager=openai_secret_manager,
                credential_validator=credential_validator,
                session_pepper=settings.session_pepper.encode("utf-8"),
            )
            openai_key_rotation_service = OpenAIKeyRotationService(
                engine=engine,
                workspace_id=WORKSPACE_ID,
                key_name=APPROVED_OPENAI_KEY_VAULT_SECRET_NAME,
                operator_auth_service=operator_auth_service,
                secret_manager=openai_secret_manager,
                credential_validator=credential_validator,
                session_pepper=settings.session_pepper.encode("utf-8"),
            )
            backend = PostgresQueryBackend(
                engine=engine,
                analysis_service=analysis_service,
                forecast_service=forecast_service,
                profit_bridge_service=profit_bridge_service,
                action_service=action_service,
            )
            ai_chat_service = AIChatService(
                engine=engine,
                workspace_id=WORKSPACE_ID,
                catalog=query_catalog,
                executor=QueryExecutor(backend=backend),
                gateway=OpenAIGateway(ai_client_provider),
                ai_control=ai_control_service,
                budget_limits=AIBudgetLimits(
                    *limits,
                    failure_rehearsal=settings.ai_budget_failure_rehearsal,
                ),
                action_service=action_service,
            )

        library_service = LibraryService(
            engine,
            workflow_storage,
            WORKSPACE_ID,
        )
        dataset_export_service = (
            DatasetExportService(
                engine,
                workflow_storage,
                WORKSPACE_ID,
                library_service,
            )
            if workflow_storage is not None
            else None
        )
        preferences_service = PreferencesService(engine, WORKSPACE_ID)
        admin_summary_service = AdminSummaryService(
            engine=engine,
            workspace_id=WORKSPACE_ID,
            dataset_service=DatasetService(engine, WORKSPACE_ID),
            public_release_service=public_release_service,
            ai_control_service=ai_control_service,
            workflow_storage=workflow_storage,
        )
        return cls(
            settings=settings,
            query_catalog=query_catalog,
            engine=engine,
            operator_auth_service=operator_auth_service,
            demo_session_service=demo_session_service,
            workflow_storage=workflow_storage,
            storage_lifecycle=storage_lifecycle,
            import_service=import_service,
            library_service=library_service,
            dataset_service=DatasetService(engine, WORKSPACE_ID),
            dataset_preparation_service=dataset_preparation_service,
            dataset_export_service=dataset_export_service,
            analysis_service=analysis_service,
            public_release_service=public_release_service,
            forecast_service=forecast_service,
            profit_bridge_service=profit_bridge_service,
            action_service=action_service,
            ai_chat_service=ai_chat_service,
            ai_control_service=ai_control_service,
            openai_key_rotation_service=openai_key_rotation_service,
            ai_client_provider=ai_client_provider,
            preferences_service=preferences_service,
            admin_summary_service=admin_summary_service,
        )
