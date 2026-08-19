from __future__ import annotations

import pytest

from src.config import (
    APPROVED_AI_DAILY_ATTEMPT_LIMIT,
    APPROVED_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE,
    APPROVED_AI_MAX_CONCURRENT_TURNS,
    APPROVED_AI_MONTHLY_TOKEN_LIMIT,
    APPROVED_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE,
    APPROVED_CHAT_OUTPUT_TOKEN_LIMIT,
    APPROVED_OPENAI_MODEL,
    APPROVED_REASONING_EFFORT,
    BizPulseSettings,
    ConfigError,
    validate_operator_password_hash,
)

VALID_OPERATOR_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "dspPsWevmFQvVX8T5BXmFA$"
    "ayB1yKL+3347+SAAe59WoJsD4u1eZvHySBBiSx1jfIk"
)


def set_valid_local_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "local")
    monkeypatch.setenv(
        "BIZPULSE_DATABASE_URL",
        "postgresql+psycopg://localhost/bizpulse_test",
    )
    monkeypatch.setenv(
        "BIZPULSE_BLOB_ENDPOINT", "http://127.0.0.1:10000/devstoreaccount1"
    )
    monkeypatch.setenv("BIZPULSE_BLOB_CONTAINER", "synthetic-demo")
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "http://127.0.0.1:8000")
    monkeypatch.setenv("BIZPULSE_OPERATOR_PASSWORD_HASH", "$argon2id$demo-hash")


def set_valid_cloud_ai_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_DATABASE_URL", "postgresql+psycopg://db/bizpulse")
    monkeypatch.setenv(
        "BIZPULSE_BLOB_ENDPOINT",
        "https://synthetic.blob.core.windows.net",
    )
    monkeypatch.setenv(
        "BIZPULSE_BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=synthetic;"
        "AccountKey=not-real;EndpointSuffix=core.windows.net",
    )
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)
    monkeypatch.setenv("BIZPULSE_OPERATOR_PASSWORD_HASH", VALID_OPERATOR_HASH)
    monkeypatch.setenv("BIZPULSE_AI_CHAT_ENABLED", "true")
    monkeypatch.setenv("BIZPULSE_AI_DAILY_ATTEMPT_LIMIT", "120")
    monkeypatch.setenv("BIZPULSE_AI_MONTHLY_TOKEN_LIMIT", "150000")
    monkeypatch.setenv("BIZPULSE_AI_MAX_CONCURRENT_TURNS", "15")
    monkeypatch.setenv("BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE", "3")
    monkeypatch.setenv("BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE", "20")
    monkeypatch.setenv(
        "BIZPULSE_OPENAI_KEY_VAULT_URL",
        "https://bizpulse-ai-test.vault.azure.net",
    )
    monkeypatch.setenv(
        "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
        "openai-api-key",
    )
    monkeypatch.setenv(
        "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
        "00000000-0000-4000-8000-000000000001",
    )


def test_model_and_reasoning_are_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_local_environment(monkeypatch)

    settings = BizPulseSettings.from_env()

    assert settings.openai_model == APPROVED_OPENAI_MODEL
    assert settings.openai_reasoning_effort == APPROVED_REASONING_EFFORT


def test_model_cannot_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_OPENAI_MODEL", "forbidden-override")

    with pytest.raises(
        ConfigError,
        match="openai_model_must_equal_approved_snapshot",
    ):
        BizPulseSettings.from_env()


def test_reasoning_effort_cannot_be_overridden(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_OPENAI_REASONING_EFFORT", "medium")

    with pytest.raises(
        ConfigError,
        match="openai_reasoning_effort_must_equal_low",
    ):
        BizPulseSettings.from_env()


def test_ai_provider_endpoint_is_absent_or_the_exact_official_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_cloud_ai_environment(monkeypatch)

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    assert BizPulseSettings.from_env().ai_chat_enabled is True

    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    assert BizPulseSettings.from_env().ai_chat_enabled is True


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "https://proxy.example.test/v1",
        "https://127.0.0.1:1",
        "https://bizpulse.openai.azure.com/openai/deployments/nano",
        "not-a-url",
        "https://api.openai.com/v1/",
    ],
)
def test_ai_provider_endpoint_drift_fails_before_client_construction(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: str,
) -> None:
    set_valid_cloud_ai_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)

    with pytest.raises(ConfigError, match="openai_base_url_must_be_official"):
        BizPulseSettings.from_env()


def test_enabled_ai_requires_exact_key_vault_bindings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_cloud_ai_environment(monkeypatch)

    settings = BizPulseSettings.from_env()

    assert settings.openai_key_vault_url == "https://bizpulse-ai-test.vault.azure.net"
    assert settings.openai_key_vault_secret_name == "openai-api-key"
    assert (
        settings.openai_managed_identity_client_id
        == "00000000-0000-4000-8000-000000000001"
    )
    assert "bizpulse-ai-test" not in repr(settings)
    assert "00000000-0000-4000-8000-000000000001" not in repr(settings)


@pytest.mark.parametrize(
    "missing_name",
    [
        "BIZPULSE_OPENAI_KEY_VAULT_URL",
        "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
        "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
    ],
)
def test_enabled_ai_rejects_missing_key_vault_binding(
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
) -> None:
    set_valid_cloud_ai_environment(monkeypatch)
    monkeypatch.delenv(missing_name)

    with pytest.raises(ConfigError, match="ai_chat_requires_key_vault_bindings"):
        BizPulseSettings.from_env()


@pytest.mark.parametrize(
    "vault_url",
    [
        "",
        "http://bizpulse-ai-test.vault.azure.net",
        "https://bizpulse-ai-test.vault.azure.net/secret",
        "https://bizpulse-ai-test.vault.azure.net?version=1",
        "https://bizpulse-ai-test.vault.azure.net#fragment",
        "https://user@bizpulse-ai-test.vault.azure.net",
        "https://bizpulse-ai-test.vault.azure.net:443",
        "https://bizpulse-ai-test.vault.azure.net.evil.test",
        "https://vault.azure.net",
        "not-a-url",
    ],
)
def test_enabled_ai_rejects_unapproved_key_vault_url(
    monkeypatch: pytest.MonkeyPatch,
    vault_url: str,
) -> None:
    set_valid_cloud_ai_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_OPENAI_KEY_VAULT_URL", vault_url)

    with pytest.raises(ConfigError, match="openai_key_vault_url_invalid"):
        BizPulseSettings.from_env()


def test_enabled_ai_rejects_wrong_key_vault_secret_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_cloud_ai_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME", "another-secret")

    with pytest.raises(ConfigError, match="openai_key_vault_secret_name_invalid"):
        BizPulseSettings.from_env()


@pytest.mark.parametrize(
    "client_id",
    [
        "",
        "not-a-uuid",
        "00000000-0000-0000-0000-000000000001",
        "00000000-0000-4000-8000-000000000001 ",
        "00000000-0000-4000-8000-000000000001/extra",
    ],
)
def test_enabled_ai_rejects_invalid_managed_identity_client_id(
    monkeypatch: pytest.MonkeyPatch,
    client_id: str,
) -> None:
    set_valid_cloud_ai_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID", client_id)

    with pytest.raises(
        ConfigError,
        match="openai_managed_identity_client_id_invalid",
    ):
        BizPulseSettings.from_env()


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (
            "BIZPULSE_OPENAI_KEY_VAULT_URL",
            "https://bizpulse-ai-test.vault.azure.net",
        ),
        ("BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME", "openai-api-key"),
        (
            "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
            "00000000-0000-4000-8000-000000000001",
        ),
    ],
)
def test_disabled_ai_rejects_stale_key_vault_bindings(
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(
        ConfigError,
        match="ai_key_vault_bindings_require_enabled_ai",
    ):
        BizPulseSettings.from_env()


def test_direct_openai_process_key_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sentinel-not-a-real-key")

    with pytest.raises(ConfigError, match="direct_openai_api_key_forbidden"):
        BizPulseSettings.from_env()


@pytest.mark.parametrize(
    "duplicate_channel_authority",
    (
        "BIZPULSE_OPERATOR_AI_ENABLED",
        "BIZPULSE_DEMO_AI_ENABLED",
        "BIZPULSE_AI_OPERATOR_ENABLED",
        "BIZPULSE_AI_DEMO_ENABLED",
    ),
)
def test_environment_cannot_duplicate_database_ai_channel_authority(
    monkeypatch: pytest.MonkeyPatch,
    duplicate_channel_authority: str,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv(duplicate_channel_authority, "true")

    with pytest.raises(ConfigError, match="ai_channels_are_database_authoritative"):
        BizPulseSettings.from_env()


def test_session_and_chat_limits_are_fixed(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_local_environment(monkeypatch)

    settings = BizPulseSettings.from_env()

    assert settings.session_idle_seconds == 1_800
    assert settings.session_absolute_seconds == 7_200
    assert settings.chat_input_char_limit == 2_000
    assert settings.chat_output_token_limit == APPROVED_CHAT_OUTPUT_TOKEN_LIMIT == 2_800


def test_operator_password_hash_stays_server_owned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)

    settings = BizPulseSettings.from_env()

    assert settings.operator_password_hash == "$argon2id$demo-hash"


def test_public_operator_hash_validator_enforces_cloud_argon2id_policy() -> None:
    assert (
        validate_operator_password_hash(
            VALID_OPERATOR_HASH,
            source="rotation_target",
        )
        == VALID_OPERATOR_HASH
    )
    with pytest.raises(ConfigError, match="cloud_operator_password_hash_invalid"):
        validate_operator_password_hash("plaintext-is-not-a-hash", source="test")


def test_cloud_runtime_requires_https_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")

    with pytest.raises(ConfigError, match="cloud_allowed_origin_must_use_https"):
        BizPulseSettings.from_env()


def test_cloud_runtime_requires_https_blob_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)

    with pytest.raises(ConfigError, match="cloud_blob_endpoint_must_use_https"):
        BizPulseSettings.from_env()


def test_cloud_runtime_requires_server_owned_blob_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv(
        "BIZPULSE_BLOB_ENDPOINT",
        "https://synthetic.blob.core.windows.net",
    )
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)
    monkeypatch.setenv("BIZPULSE_OPERATOR_PASSWORD_HASH", VALID_OPERATOR_HASH)

    with pytest.raises(ConfigError, match="cloud_blob_credential_required"):
        BizPulseSettings.from_env()

    monkeypatch.setenv(
        "BIZPULSE_BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=synthetic;"
        "AccountKey=not-real;EndpointSuffix=core.windows.net",
    )
    settings = BizPulseSettings.from_env()
    assert settings.blob_connection_string is not None
    assert "blob_connection_string" not in repr(settings)


def test_cloud_blob_credential_cannot_override_https_with_http_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv("BIZPULSE_BLOB_ENDPOINT", "https://blob.test")
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)
    monkeypatch.setenv(
        "BIZPULSE_BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=synthetic;"
        "AccountKey=not-real;BlobEndpoint=http://attacker.invalid/blob",
    )

    with pytest.raises(ConfigError, match="cloud_blob_credential_must_use_https"):
        BizPulseSettings.from_env()


def test_cloud_blob_credential_cannot_override_declared_account_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv(
        "BIZPULSE_BLOB_ENDPOINT", "https://synthetic.blob.core.windows.net"
    )
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)
    monkeypatch.setenv("BIZPULSE_OPERATOR_PASSWORD_HASH", VALID_OPERATOR_HASH)
    monkeypatch.setenv(
        "BIZPULSE_BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=synthetic;"
        "AccountKey=not-real;BlobEndpoint=https://attacker.invalid/blob",
    )

    with pytest.raises(ConfigError, match="cloud_blob_credential_endpoint_override"):
        BizPulseSettings.from_env()


def test_cloud_blob_credential_suffix_must_match_declared_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv(
        "BIZPULSE_BLOB_ENDPOINT", "https://synthetic.blob.core.windows.net"
    )
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)
    monkeypatch.setenv("BIZPULSE_OPERATOR_PASSWORD_HASH", VALID_OPERATOR_HASH)
    monkeypatch.setenv(
        "BIZPULSE_BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=synthetic;"
        "AccountKey=not-real;EndpointSuffix=attacker.invalid",
    )

    with pytest.raises(ConfigError, match="cloud_blob_credential_authority_mismatch"):
        BizPulseSettings.from_env()


def test_ai_chat_requires_cloud_and_all_explicit_budget_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_AI_CHAT_ENABLED", "true")

    with pytest.raises(ConfigError, match="ai_chat_requires_cloud_runtime"):
        BizPulseSettings.from_env()

    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_DATABASE_URL", "postgresql+psycopg://db/bizpulse")
    monkeypatch.setenv(
        "BIZPULSE_BLOB_ENDPOINT",
        "https://synthetic.blob.core.windows.net",
    )
    monkeypatch.setenv(
        "BIZPULSE_BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=synthetic;"
        "AccountKey=not-real;EndpointSuffix=core.windows.net",
    )
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)
    monkeypatch.setenv("BIZPULSE_OPERATOR_PASSWORD_HASH", VALID_OPERATOR_HASH)
    with pytest.raises(ConfigError, match="ai_chat_requires_all_budget_limits"):
        BizPulseSettings.from_env()

    limits = {
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT": str(APPROVED_AI_DAILY_ATTEMPT_LIMIT),
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT": str(APPROVED_AI_MONTHLY_TOKEN_LIMIT),
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS": str(APPROVED_AI_MAX_CONCURRENT_TURNS),
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE": str(
            APPROVED_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE
        ),
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE": str(
            APPROVED_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE
        ),
    }
    for name, value in limits.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv(
        "BIZPULSE_OPENAI_KEY_VAULT_URL",
        "https://bizpulse-ai-test.vault.azure.net",
    )
    monkeypatch.setenv(
        "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME",
        "openai-api-key",
    )
    monkeypatch.setenv(
        "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID",
        "00000000-0000-4000-8000-000000000001",
    )

    settings = BizPulseSettings.from_env()
    assert settings.ai_chat_enabled is True
    assert settings.ai_daily_attempt_limit == 120
    assert settings.ai_monthly_token_limit == 150_000
    assert settings.ai_session_attempt_limit_per_minute == 3
    assert settings.ai_global_attempt_limit_per_minute == 20
    assert settings.ai_max_concurrent_turns == 15


def test_ai_budget_configuration_cannot_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_DATABASE_URL", "postgresql+psycopg://db/bizpulse")
    monkeypatch.setenv(
        "BIZPULSE_BLOB_ENDPOINT",
        "https://synthetic.blob.core.windows.net",
    )
    monkeypatch.setenv(
        "BIZPULSE_BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=synthetic;"
        "AccountKey=not-real;EndpointSuffix=core.windows.net",
    )
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)
    monkeypatch.setenv("BIZPULSE_OPERATOR_PASSWORD_HASH", VALID_OPERATOR_HASH)
    monkeypatch.setenv("BIZPULSE_AI_CHAT_ENABLED", "true")
    approved = {
        "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT": "120",
        "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT": "150000",
        "BIZPULSE_AI_MAX_CONCURRENT_TURNS": "15",
        "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE": "3",
        "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE": "20",
    }
    for name, value in approved.items():
        monkeypatch.setenv(name, value)

    for name in approved:
        monkeypatch.setenv(name, str(int(approved[name]) + 1))
        with pytest.raises(ConfigError, match="ai_budget_must_equal_approved_limits"):
            BizPulseSettings.from_env()
        monkeypatch.setenv(name, approved[name])


def test_budget_failure_rehearsal_requires_enabled_cloud_ai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    set_valid_cloud_ai_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL", "true")

    settings = BizPulseSettings.from_env()

    assert settings.ai_budget_failure_rehearsal is True
    assert settings.ai_monthly_token_limit == APPROVED_AI_MONTHLY_TOKEN_LIMIT

    monkeypatch.setenv("BIZPULSE_AI_CHAT_ENABLED", "false")
    with pytest.raises(
        ConfigError,
        match="ai_budget_failure_rehearsal_requires_enabled_cloud_ai",
    ):
        BizPulseSettings.from_env()

    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL", "true")
    with pytest.raises(
        ConfigError,
        match="ai_budget_failure_rehearsal_requires_enabled_cloud_ai",
    ):
        BizPulseSettings.from_env()


@pytest.mark.parametrize(
    "password_hash",
    [
        None,
        "plaintext-is-not-a-hash",
        "$argon2i$v=19$m=65536,t=3,p=4$dspPsWevmFQvVX8T5BXmFA$"
        "ayB1yKL+3347+SAAe59WoJsD4u1eZvHySBBiSx1jfIk",
        "$argon2id$v=19$m=1024,t=1,p=1$dspPsWevmFQvVX8T5BXmFA$"
        "ayB1yKL+3347+SAAe59WoJsD4u1eZvHySBBiSx1jfIk",
    ],
)
def test_cloud_runtime_requires_strict_argon2id_operator_hash(
    monkeypatch: pytest.MonkeyPatch,
    password_hash: str | None,
) -> None:
    set_valid_local_environment(monkeypatch)
    monkeypatch.setenv("BIZPULSE_RUNTIME_ENVIRONMENT", "cloud")
    monkeypatch.setenv("BIZPULSE_DATABASE_URL", "postgresql+psycopg://db/bizpulse")
    monkeypatch.setenv(
        "BIZPULSE_BLOB_ENDPOINT",
        "https://synthetic.blob.core.windows.net",
    )
    monkeypatch.setenv(
        "BIZPULSE_BLOB_CONNECTION_STRING",
        "DefaultEndpointsProtocol=https;AccountName=synthetic;"
        "AccountKey=not-real;EndpointSuffix=core.windows.net",
    )
    monkeypatch.setenv("BIZPULSE_ALLOWED_ORIGIN", "https://demo.test")
    monkeypatch.setenv("BIZPULSE_SESSION_PEPPER", "x" * 32)
    if password_hash is None:
        monkeypatch.delenv("BIZPULSE_OPERATOR_PASSWORD_HASH", raising=False)
    else:
        monkeypatch.setenv("BIZPULSE_OPERATOR_PASSWORD_HASH", password_hash)

    with pytest.raises(ConfigError, match="cloud_operator_password_hash_invalid"):
        BizPulseSettings.from_env()
