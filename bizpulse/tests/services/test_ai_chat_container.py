from __future__ import annotations

from sqlalchemy import Engine

import api.container as container_module
from api.container import ApiContainer
from src.config import BizPulseSettings
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.ai_chat_service import AIChatService
from src.services.ai_control_service import AIControlService
from src.services.demo_action_authority import DemoActionAuthority
from src.services.openai_key_rotation_service import OpenAIKeyRotationService
from tests.import_support import MemoryWorkflowStorage


class FakeSecretManager:
    def read(self, version):
        raise AssertionError(f"construction_must_not_read_secret:{version}")

    def write(self, value):
        raise AssertionError(f"construction_must_not_write_secret:{bool(value)}")


def test_cloud_container_uses_server_owned_blob_connection_string(
    monkeypatch,
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    observed: dict[str, str] = {}

    class ContainerClient:
        @classmethod
        def from_connection_string(
            cls,
            connection_string,
            *,
            container_name,
        ):
            observed["connection_string"] = connection_string
            observed["container_name"] = container_name
            return cls()

    monkeypatch.setattr(
        container_module,
        "create_postgres_engine",
        lambda url: migrated_engine,
    )
    monkeypatch.setattr(container_module, "ContainerClient", ContainerClient)
    monkeypatch.setattr(
        container_module,
        "build_storage",
        lambda settings, client, entry_locks: storage,
    )
    settings = BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://db/bizpulse",
        blob_endpoint="https://blob.test",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        blob_connection_string="server-owned-credential",
    )

    ApiContainer.build(settings)

    assert observed == {
        "connection_string": "server-owned-credential",
        "container_name": "synthetic-demo",
    }


def test_enabled_chat_is_assembled_with_explicit_limits_and_injected_client(
    monkeypatch,
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()

    class ContainerClient:
        def __init__(self, *, account_url, container_name):
            del account_url, container_name

    monkeypatch.setattr(
        container_module,
        "create_postgres_engine",
        lambda url: migrated_engine,
    )
    monkeypatch.setattr(container_module, "ContainerClient", ContainerClient)
    monkeypatch.setattr(
        container_module,
        "build_storage",
        lambda settings, client, entry_locks: storage,
    )
    settings = BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://db/bizpulse",
        blob_endpoint="https://blob.test",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        session_pepper="x" * 32,
        ai_chat_enabled=True,
        ai_daily_attempt_limit=120,
        ai_monthly_token_limit=150_000,
        ai_max_concurrent_turns=15,
        ai_session_attempt_limit_per_minute=3,
        ai_global_attempt_limit_per_minute=20,
    )

    container = ApiContainer.build(
        settings,
        openai_client=object(),
        openai_secret_manager=FakeSecretManager(),
        openai_credential_validator=object(),
    )
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(
            container_module.WORKSPACE_ID
        )

    assert isinstance(container.ai_chat_service, AIChatService)
    assert isinstance(container.ai_control_service, AIControlService)
    assert isinstance(
        container.openai_key_rotation_service,
        OpenAIKeyRotationService,
    )
    assert container.ai_chat_service._ai_control is container.ai_control_service
    control = container.ai_control_service.get()
    assert control.operator_enabled is False
    assert control.demo_enabled is False
    assert control.key_version is None
    assert container.ai_chat_service._gateway._client_provider is not None
    assert container.ai_client_provider is not None
    assert container.ai_chat_service._budget == container_module.AIBudgetLimits(
        120,
        150_000,
        15,
        3,
        20,
    )
    assert isinstance(
        container.public_release_service._action_authority,
        DemoActionAuthority,
    )


def test_enabled_chat_constructs_only_the_key_vault_client_provider(
    monkeypatch,
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()
    observed: list[dict[str, str]] = []

    class ContainerClient:
        def __init__(self, *, account_url, container_name):
            del account_url, container_name

    class Provider:
        secret_manager = FakeSecretManager()

        def acquire(self, version):
            del version
            raise AssertionError("construction_must_not_fetch_secret")

        def close(self):
            return None

    provider = Provider()

    def provider_factory(**kwargs):
        observed.append(kwargs)
        return provider

    monkeypatch.setattr(
        container_module,
        "create_postgres_engine",
        lambda url: migrated_engine,
    )
    monkeypatch.setattr(container_module, "ContainerClient", ContainerClient)
    monkeypatch.setattr(
        container_module,
        "build_storage",
        lambda settings, client, entry_locks: storage,
    )
    monkeypatch.setattr(
        container_module,
        "AzureOpenAIClientProvider",
        provider_factory,
        raising=False,
    )
    settings = BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://db/bizpulse",
        blob_endpoint="https://blob.test",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        session_pepper="x" * 32,
        ai_chat_enabled=True,
        ai_daily_attempt_limit=120,
        ai_monthly_token_limit=150_000,
        ai_max_concurrent_turns=15,
        ai_session_attempt_limit_per_minute=3,
        ai_global_attempt_limit_per_minute=20,
        openai_key_vault_url="https://bizpulse-ai-test.vault.azure.net",
        openai_key_vault_secret_name="openai-api-key",
        openai_managed_identity_client_id=("00000000-0000-4000-8000-000000000001"),
    )

    container = ApiContainer.build(settings)

    assert observed == [
        {
            "vault_url": "https://bizpulse-ai-test.vault.azure.net",
            "secret_name": "openai-api-key",
            "managed_identity_client_id": ("00000000-0000-4000-8000-000000000001"),
        }
    ]
    assert container.ai_client_provider is provider
    assert container.ai_chat_service is not None
    assert container.ai_control_service is not None
    assert container.openai_key_rotation_service is not None


def test_disabled_chat_keeps_only_the_server_catalog_and_constructs_no_gateway(
    monkeypatch,
    migrated_engine: Engine,
) -> None:
    storage = MemoryWorkflowStorage()

    class ContainerClient:
        def __init__(self, *, account_url, container_name):
            del account_url, container_name

    class ExplodingClient:
        @property
        def responses(self):
            raise AssertionError("disabled_chat_must_not_construct_or_use_gateway")

    provider_constructions = 0

    def exploding_provider(**kwargs):
        del kwargs
        nonlocal provider_constructions
        provider_constructions += 1
        raise AssertionError("disabled_chat_must_not_construct_key_vault_provider")

    monkeypatch.setattr(
        container_module,
        "create_postgres_engine",
        lambda url: migrated_engine,
    )
    monkeypatch.setattr(container_module, "ContainerClient", ContainerClient)
    monkeypatch.setattr(
        container_module,
        "build_storage",
        lambda settings, client, entry_locks: storage,
    )
    monkeypatch.setattr(
        container_module,
        "AzureOpenAIClientProvider",
        exploding_provider,
        raising=False,
    )
    settings = BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://db/bizpulse",
        blob_endpoint="https://blob.test",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        session_pepper="x" * 32,
        ai_chat_enabled=False,
    )

    container = ApiContainer.build(settings, openai_client=ExplodingClient())

    assert container.ai_chat_service is None
    assert container.ai_control_service is None
    assert container.openai_key_rotation_service is None
    assert container.ai_client_provider is None
    assert provider_constructions == 0
    assert container.query_catalog.recommended_ids() == (
        "monthly_sales_report",
        "profit_changes",
        "inventory_risks",
        "advertising_performance",
        "forecast_30_days",
        "next_actions",
    )
