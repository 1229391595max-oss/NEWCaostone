"""Validated runtime configuration for the BizPulse application."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID

from argon2 import Type, extract_parameters
from argon2.exceptions import InvalidHashError
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from src.ai.release_constants import (
    APPROVED_AI_DAILY_ATTEMPT_LIMIT,
    APPROVED_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE,
    APPROVED_AI_MAX_CONCURRENT_TURNS,
    APPROVED_AI_MONTHLY_TOKEN_LIMIT,
    APPROVED_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE,
    APPROVED_CHAT_OUTPUT_TOKEN_LIMIT,
    APPROVED_OPENAI_MODEL,
)


APPROVED_REASONING_EFFORT = "low"
APPROVED_OPENAI_BASE_URL = "https://api.openai.com/v1"
APPROVED_OPENAI_KEY_VAULT_SECRET_NAME = "openai-api-key"


class ConfigError(ValueError):
    """Raised when runtime configuration violates an approved boundary."""


@dataclass(frozen=True, slots=True)
class BizPulseSettings:
    """Server-owned settings with fixed Demo safety limits."""

    runtime_environment: Literal["local", "cloud"]
    database_url: str = field(repr=False)
    blob_endpoint: str = field(repr=False)
    blob_container: str
    allowed_origin: str
    cookie_secure: bool
    blob_connection_string: str | None = field(default=None, repr=False)
    operator_password_hash: str | None = field(default=None, repr=False)
    session_pepper: str | None = field(default=None, repr=False)
    openai_model: str = APPROVED_OPENAI_MODEL
    openai_reasoning_effort: str = APPROVED_REASONING_EFFORT
    openai_key_vault_url: str | None = field(default=None, repr=False)
    openai_key_vault_secret_name: str | None = field(default=None, repr=False)
    openai_managed_identity_client_id: str | None = field(default=None, repr=False)
    session_idle_seconds: int = 1_800
    session_absolute_seconds: int = 7_200
    request_body_limit_bytes: int = 9 * 1024 * 1024
    demo_session_rate_limit_per_hour: int = 50
    chat_input_char_limit: int = 2_000
    chat_output_token_limit: int = APPROVED_CHAT_OUTPUT_TOKEN_LIMIT
    ai_chat_enabled: bool = False
    ai_daily_attempt_limit: int | None = None
    ai_monthly_token_limit: int | None = None
    ai_max_concurrent_turns: int | None = None
    ai_session_attempt_limit_per_minute: int | None = None
    ai_global_attempt_limit_per_minute: int | None = None
    ai_budget_failure_rehearsal: bool = False

    @classmethod
    def from_env(cls) -> BizPulseSettings:
        """Build settings from environment variables and reject unsafe drift."""

        if any(
            name in os.environ
            for name in (
                "BIZPULSE_OPERATOR_AI_ENABLED",
                "BIZPULSE_DEMO_AI_ENABLED",
                "BIZPULSE_AI_OPERATOR_ENABLED",
                "BIZPULSE_AI_DEMO_ENABLED",
            )
        ):
            raise ConfigError("ai_channels_are_database_authoritative")
        if "OPENAI_API_KEY" in os.environ:
            raise ConfigError("direct_openai_api_key_forbidden")

        runtime = os.getenv("BIZPULSE_RUNTIME_ENVIRONMENT", "local").lower()
        if runtime not in {"local", "cloud"}:
            raise ConfigError("runtime_environment_must_be_local_or_cloud")

        configured_model = os.getenv("BIZPULSE_OPENAI_MODEL", APPROVED_OPENAI_MODEL)
        if configured_model != APPROVED_OPENAI_MODEL:
            raise ConfigError("openai_model_must_equal_approved_snapshot")

        configured_effort = os.getenv(
            "BIZPULSE_OPENAI_REASONING_EFFORT",
            APPROVED_REASONING_EFFORT,
        )
        if configured_effort != APPROVED_REASONING_EFFORT:
            raise ConfigError("openai_reasoning_effort_must_equal_low")

        configured_base_url = os.getenv("OPENAI_BASE_URL")
        if (
            configured_base_url is not None
            and configured_base_url != APPROVED_OPENAI_BASE_URL
        ):
            raise ConfigError("openai_base_url_must_be_official")

        allowed_origin = os.getenv(
            "BIZPULSE_ALLOWED_ORIGIN",
            "http://127.0.0.1:8000",
        )
        if runtime == "cloud" and urlsplit(allowed_origin).scheme != "https":
            raise ConfigError("cloud_allowed_origin_must_use_https")

        blob_endpoint = os.getenv(
            "BIZPULSE_BLOB_ENDPOINT",
            "http://127.0.0.1:10000/devstoreaccount1",
        )
        database_url = os.getenv(
            "BIZPULSE_DATABASE_URL",
            "postgresql+psycopg://localhost/bizpulse",
        )
        if runtime == "cloud":
            try:
                database_backend = make_url(database_url).get_backend_name()
            except ArgumentError as error:
                raise ConfigError("cloud_database_url_must_use_postgresql") from error
            if database_backend != "postgresql":
                raise ConfigError("cloud_database_url_must_use_postgresql")
            parsed_blob_endpoint = urlsplit(blob_endpoint)
            if (
                parsed_blob_endpoint.scheme != "https"
                or not parsed_blob_endpoint.hostname
                or parsed_blob_endpoint.username is not None
                or parsed_blob_endpoint.password is not None
                or parsed_blob_endpoint.path not in {"", "/"}
                or parsed_blob_endpoint.query
                or parsed_blob_endpoint.fragment
            ):
                raise ConfigError("cloud_blob_endpoint_must_use_https")
        blob_connection_string = os.getenv("BIZPULSE_BLOB_CONNECTION_STRING")
        if runtime == "cloud":
            if blob_connection_string is None:
                raise ConfigError("cloud_blob_credential_required")
            _validate_cloud_blob_connection_string(
                blob_connection_string,
                expected_endpoint=blob_endpoint,
            )
        session_pepper = os.getenv("BIZPULSE_SESSION_PEPPER")
        if runtime == "cloud" and (session_pepper is None or len(session_pepper) < 32):
            raise ConfigError("cloud_session_pepper_must_be_at_least_32_characters")
        operator_password_hash = os.getenv("BIZPULSE_OPERATOR_PASSWORD_HASH")
        if runtime == "cloud":
            operator_password_hash = validate_operator_password_hash(
                operator_password_hash,
                source="runtime_environment",
            )

        ai_chat_enabled = _boolean_env("BIZPULSE_AI_CHAT_ENABLED", default=False)
        openai_key_vault_url = os.getenv("BIZPULSE_OPENAI_KEY_VAULT_URL")
        openai_key_vault_secret_name = os.getenv(
            "BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME"
        )
        openai_managed_identity_client_id = os.getenv(
            "BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID"
        )
        key_vault_bindings = (
            openai_key_vault_url,
            openai_key_vault_secret_name,
            openai_managed_identity_client_id,
        )
        ai_budget_failure_rehearsal = _boolean_env(
            "BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL",
            default=False,
        )
        request_body_limit_bytes = _int_env_between(
            "BIZPULSE_REQUEST_BODY_LIMIT_BYTES",
            default=9 * 1024 * 1024,
            minimum=1,
            maximum=9 * 1024 * 1024,
        )
        demo_session_rate_limit_per_hour = _int_env_between(
            "BIZPULSE_DEMO_SESSION_RATE_LIMIT_PER_HOUR",
            default=50,
            minimum=15,
            maximum=50,
        )
        ai_limits = {
            "ai_daily_attempt_limit": _positive_int_env(
                "BIZPULSE_AI_DAILY_ATTEMPT_LIMIT"
            ),
            "ai_monthly_token_limit": _positive_int_env(
                "BIZPULSE_AI_MONTHLY_TOKEN_LIMIT"
            ),
            "ai_max_concurrent_turns": _positive_int_env(
                "BIZPULSE_AI_MAX_CONCURRENT_TURNS"
            ),
            "ai_session_attempt_limit_per_minute": _positive_int_env(
                "BIZPULSE_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE"
            ),
            "ai_global_attempt_limit_per_minute": _positive_int_env(
                "BIZPULSE_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE"
            ),
        }
        if ai_chat_enabled and runtime != "cloud":
            raise ConfigError("ai_chat_requires_cloud_runtime")
        if ai_budget_failure_rehearsal and (
            runtime != "cloud" or not ai_chat_enabled
        ):
            raise ConfigError(
                "ai_budget_failure_rehearsal_requires_enabled_cloud_ai"
            )
        if ai_chat_enabled and any(value is None for value in ai_limits.values()):
            raise ConfigError("ai_chat_requires_all_budget_limits")
        approved_ai_limits = {
            "ai_daily_attempt_limit": APPROVED_AI_DAILY_ATTEMPT_LIMIT,
            "ai_monthly_token_limit": APPROVED_AI_MONTHLY_TOKEN_LIMIT,
            "ai_max_concurrent_turns": APPROVED_AI_MAX_CONCURRENT_TURNS,
            "ai_session_attempt_limit_per_minute": (
                APPROVED_AI_SESSION_ATTEMPT_LIMIT_PER_MINUTE
            ),
            "ai_global_attempt_limit_per_minute": (
                APPROVED_AI_GLOBAL_ATTEMPT_LIMIT_PER_MINUTE
            ),
        }
        if ai_chat_enabled and ai_limits != approved_ai_limits:
            raise ConfigError("ai_budget_must_equal_approved_limits")
        if not ai_chat_enabled and any(
            value is not None for value in key_vault_bindings
        ):
            raise ConfigError("ai_key_vault_bindings_require_enabled_ai")
        if ai_chat_enabled and any(value is None for value in key_vault_bindings):
            raise ConfigError("ai_chat_requires_key_vault_bindings")
        if ai_chat_enabled:
            assert openai_key_vault_url is not None
            assert openai_key_vault_secret_name is not None
            assert openai_managed_identity_client_id is not None
            _validate_openai_key_vault_url(openai_key_vault_url)
            if (
                openai_key_vault_secret_name
                != APPROVED_OPENAI_KEY_VAULT_SECRET_NAME
            ):
                raise ConfigError("openai_key_vault_secret_name_invalid")
            _validate_managed_identity_client_id(
                openai_managed_identity_client_id
            )

        return cls(
            runtime_environment=runtime,
            database_url=database_url,
            blob_endpoint=blob_endpoint,
            blob_container=os.getenv(
                "BIZPULSE_BLOB_CONTAINER",
                "synthetic-demo",
            ),
            allowed_origin=allowed_origin,
            cookie_secure=runtime == "cloud",
            blob_connection_string=blob_connection_string,
            operator_password_hash=operator_password_hash,
            session_pepper=session_pepper,
            openai_model=configured_model,
            openai_reasoning_effort=configured_effort,
            openai_key_vault_url=openai_key_vault_url,
            openai_key_vault_secret_name=openai_key_vault_secret_name,
            openai_managed_identity_client_id=openai_managed_identity_client_id,
            request_body_limit_bytes=request_body_limit_bytes,
            demo_session_rate_limit_per_hour=demo_session_rate_limit_per_hour,
            ai_chat_enabled=ai_chat_enabled,
            ai_budget_failure_rehearsal=ai_budget_failure_rehearsal,
            **ai_limits,
        )


def _validate_openai_key_vault_url(value: str) -> None:
    parsed = urlsplit(value)
    hostname = parsed.hostname
    try:
        port = parsed.port
    except ValueError as error:
        raise ConfigError("openai_key_vault_url_invalid") from error
    if (
        parsed.scheme != "https"
        or hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or value != f"https://{hostname}"
        or re.fullmatch(
            r"[a-z][a-z0-9-]{1,22}[a-z0-9]\.vault\.azure\.net",
            hostname,
        )
        is None
    ):
        raise ConfigError("openai_key_vault_url_invalid")


def _validate_managed_identity_client_id(value: str) -> None:
    try:
        client_id = UUID(value)
    except (ValueError, AttributeError) as error:
        raise ConfigError("openai_managed_identity_client_id_invalid") from error
    if client_id.version != 4 or str(client_id) != value:
        raise ConfigError("openai_managed_identity_client_id_invalid")


def _validate_cloud_blob_connection_string(
    value: str,
    *,
    expected_endpoint: str,
) -> None:
    fields: dict[str, str] = {}
    for segment in value.split(";"):
        if not segment:
            continue
        if "=" not in segment:
            raise ConfigError("cloud_blob_credential_invalid")
        name, raw = segment.split("=", 1)
        normalized = name.strip().lower()
        normalized_value = raw.strip()
        if not normalized or normalized in fields or not normalized_value:
            raise ConfigError("cloud_blob_credential_invalid")
        fields[normalized] = normalized_value
    if fields.get("defaultendpointsprotocol", "").lower() != "https":
        raise ConfigError("cloud_blob_credential_required")
    explicit_endpoints = tuple(
        fields[name]
        for name in ("blobendpoint", "queueendpoint", "tableendpoint", "fileendpoint")
        if name in fields
    )
    for endpoint in explicit_endpoints:
        parsed = urlsplit(endpoint)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ConfigError("cloud_blob_credential_must_use_https")
    if explicit_endpoints:
        raise ConfigError("cloud_blob_credential_endpoint_override")
    if set(fields) != {
        "defaultendpointsprotocol",
        "accountname",
        "accountkey",
        "endpointsuffix",
    }:
        raise ConfigError("cloud_blob_credential_invalid")
    expected_hostname = urlsplit(expected_endpoint).hostname
    credential_hostname = (
        f"{fields['accountname']}.blob.{fields['endpointsuffix']}".lower()
    )
    if expected_hostname is None or expected_hostname.lower() != credential_hostname:
        raise ConfigError("cloud_blob_credential_authority_mismatch")


def validate_operator_password_hash(value: str | None, *, source: str) -> str:
    """Return a cloud-safe Argon2id operator hash without exposing its value.

    ``source`` records the calling boundary for code readability only.  Error
    messages deliberately remain constant so a failed validation cannot reveal
    credential material or its origin.
    """

    del source
    if value is None:
        raise ConfigError("cloud_operator_password_hash_invalid")
    try:
        parameters = extract_parameters(value)
    except (InvalidHashError, TypeError, ValueError) as error:
        raise ConfigError("cloud_operator_password_hash_invalid") from error
    if (
        parameters.type is not Type.ID
        or parameters.version != 19
        or parameters.memory_cost < 65_536
        or parameters.time_cost < 3
        or parameters.parallelism < 1
        or parameters.salt_len < 16
        or parameters.hash_len < 32
    ):
        raise ConfigError("cloud_operator_password_hash_invalid")
    return value


def _validate_cloud_operator_password_hash(value: str | None) -> None:
    """Compatibility wrapper for internal callers retained during migration."""

    validate_operator_password_hash(value, source="legacy_internal")


def _boolean_env(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes"}:
        return True
    if normalized in {"0", "false", "no"}:
        return False
    raise ConfigError(f"{name.lower()}_must_be_boolean")


def _positive_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name.lower()}_must_be_positive_integer") from error
    if value <= 0:
        raise ConfigError(f"{name.lower()}_must_be_positive_integer")
    return value


def _int_env_between(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(
            f"{name.lower()}_must_be_between_{minimum}_and_{maximum}"
        ) from error
    if not minimum <= value <= maximum:
        raise ConfigError(
            f"{name.lower()}_must_be_between_{minimum}_and_{maximum}"
        )
    return value
