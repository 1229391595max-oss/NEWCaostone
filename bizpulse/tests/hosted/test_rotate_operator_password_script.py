from __future__ import annotations

import inspect

import pytest

from scripts.rotate_operator_password import (
    OperatorRotationJobConfigurationError,
    read_rotation_job_settings,
    run_rotation,
)
from src.config import BizPulseSettings
from src.services.operator_password_rotation_service import RotationResult


VALID_OPERATOR_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "dspPsWevmFQvVX8T5BXmFA$"
    "ayB1yKL+3347+SAAe59WoJsD4u1eZvHySBBiSx1jfIk"
)


class FakeRotationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def rotate(
        self,
        *,
        expected_hash_fingerprint: str,
        replacement_password_hash: str,
    ) -> RotationResult:
        self.calls.append((expected_hash_fingerprint, replacement_password_hash))
        return RotationResult(
            status="rotated",
            revoked_session_count=2,
            deleted_ephemeral_chat_count=1,
        )


def _settings() -> BizPulseSettings:
    return BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://db.example/bizpulse",
        blob_endpoint="https://synthetic.blob.core.windows.net",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.example",
        cookie_secure=True,
        operator_password_hash=VALID_OPERATOR_HASH,
        session_pepper="x" * 32,
    )


def _environment() -> dict[str, str]:
    return {
        "BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256": "a" * 64,
        "BIZPULSE_OPERATOR_ROTATION_ID": "b" * 64,
    }


def test_job_reads_only_valid_scoped_environment_inputs() -> None:
    values = read_rotation_job_settings(_settings(), environ=_environment())

    assert values.expected_hash_fingerprint == "a" * 64
    assert values.rotation_id == "b" * 64
    assert values.replacement_password_hash == VALID_OPERATOR_HASH


@pytest.mark.parametrize(
    "name,value,error",
    [
        (
            "BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256",
            "not-a-fingerprint",
            "expected_hash_fingerprint_invalid",
        ),
        (
            "BIZPULSE_OPERATOR_ROTATION_ID",
            "not-a-rotation-id",
            "rotation_id_invalid",
        ),
    ],
)
def test_job_rejects_malformed_authority_inputs(
    name: str,
    value: str,
    error: str,
) -> None:
    environment = _environment()
    environment[name] = value

    with pytest.raises(OperatorRotationJobConfigurationError, match=error):
        read_rotation_job_settings(_settings(), environ=environment)


def test_job_output_is_redacted_and_passes_only_hash_values_to_service() -> None:
    service = FakeRotationService()
    values = read_rotation_job_settings(_settings(), environ=_environment())

    result = run_rotation(service, values)

    assert service.calls == [("a" * 64, VALID_OPERATOR_HASH)]
    assert result == {
        "rotation_id": "b" * 64,
        "status": "rotated",
        "revoked_session_count": 2,
        "deleted_ephemeral_chat_count": 1,
    }
    assert VALID_OPERATOR_HASH not in repr(result)


def test_job_module_has_no_macos_keychain_dependency() -> None:
    import scripts.rotate_operator_password as module

    assert "operator_rotation_keychain" not in inspect.getsource(module)
