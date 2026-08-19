from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest
from pydantic import SecretStr
from sqlalchemy import select

from src.ai.credential_validation import CredentialValidationResult
from src.db.unit_of_work import PostgresUnitOfWork
from src.db.schema import idempotency_receipts
from src.repositories.admin_ai import AIControlRepository
from src.secrets.azure_openai import OpenAISecretUnavailable, SecretVersion
from src.services.ai_control_service import (
    AIControlAvailabilityFailed,
    AIControlService,
    AIStateConflict,
)
from src.services.openai_key_rotation_service import (
    AIKeyRotationFailed,
    OpenAIKeyRotationService,
)
from src.services.operator_auth_service import OperatorAuthService, RequestMeta
from tests.auth_support import (
    PASSWORD,
    SESSION_PEPPER,
    WORKSPACE_ID,
    fast_password_hasher,
    seed_operator,
)

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
OLD_KEY = "old-admin-idempotency-key"
NEW_KEY = "new-admin-idempotency-key"
OTHER_KEY = "other-admin-idempotency-key"


class FakeSecretManager:
    def __init__(self) -> None:
        self.values = {"old-version": OLD_KEY}
        self.reads: list[str] = []
        self.writes: list[str] = []

    def read(self, version: str) -> SecretVersion:
        self.reads.append(version)
        try:
            value = self.values[version]
        except KeyError:
            raise OpenAISecretUnavailable("openai_secret_unavailable") from None
        return SecretVersion(value=value, version=version)

    def write(self, value: str) -> SecretVersion:
        self.writes.append(value)
        version = f"written-{len(self.writes)}"
        self.values[version] = value
        return SecretVersion(value=value, version=version)


class FakeValidator:
    def __init__(self, *statuses: str) -> None:
        self.statuses = list(statuses)
        self.calls = 0

    def validate(self, candidate: str) -> CredentialValidationResult:
        assert candidate in {OLD_KEY, NEW_KEY, OTHER_KEY}
        self.calls += 1
        status = self.statuses.pop(0) if self.statuses else "verified"
        return CredentialValidationResult(status, None)


def authority(migrated_engine):
    seed_operator(migrated_engine, fast_password_hasher())
    auth = OperatorAuthService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        session_pepper=SESSION_PEPPER,
        password_hasher=fast_password_hasher(),
        clock=lambda: NOW,
    )
    meta = RequestMeta(
        source_address_hash=auth.source_address_fingerprint("127.0.0.1"),
        now=NOW,
    )
    principal = auth.login("operator", SecretStr(PASSWORD), meta).principal
    with PostgresUnitOfWork(migrated_engine) as uow:
        repository = AIControlRepository(uow.connection)
        initial = repository.get_or_create(WORKSPACE_ID, now=NOW)
        configured = repository.activate_key(
            workspace_id=WORKSPACE_ID,
            expected_revision=initial.revision,
            key_name="openai-api-key",
            key_version="old-version",
            key_reference="openai-api-key/old-version",
            key_fingerprint="a" * 64,
            verified_at=NOW,
            updated_by_operator_id=principal.operator_id,
            now=NOW,
        )
    assert configured is not None
    return auth, meta, principal, configured


def test_channel_same_key_replays_success_and_changed_payload_conflicts(
    migrated_engine,
) -> None:
    auth, meta, principal, configured = authority(migrated_engine)
    secrets = FakeSecretManager()
    validator = FakeValidator("verified")
    service = AIControlService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        operator_auth_service=auth,
        secret_manager=secrets,
        credential_validator=validator,
        session_pepper=SESSION_PEPPER.encode(),
        clock=lambda: NOW,
    )
    arguments = {
        "principal": principal,
        "current_password": SecretStr(PASSWORD),
        "request_meta": meta,
        "expected_revision": configured.revision,
        "operator_enabled": True,
        "demo_enabled": False,
        "request_id": "channel-request-1",
        "idempotency_key": "channel-idempotency-1",
    }

    first = service.set_channels(**arguments)
    replay = service.set_channels(
        **{**arguments, "current_password": SecretStr(PASSWORD)}
    )

    assert replay.revision == first.revision
    assert replay.operator_enabled is True
    assert replay.demo_enabled is False
    assert validator.calls == 1
    assert secrets.reads == ["old-version"]
    with pytest.raises(AIStateConflict, match="ADMIN_AI_STATE_CONFLICT"):
        service.set_channels(
            **{
                **arguments,
                "current_password": SecretStr(PASSWORD),
                "demo_enabled": True,
            }
        )


def test_channel_failure_replays_without_repeating_exact_binding_qualification(
    migrated_engine,
) -> None:
    auth, meta, principal, configured = authority(migrated_engine)
    secrets = FakeSecretManager()
    validator = FakeValidator("unknown")
    service = AIControlService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        operator_auth_service=auth,
        secret_manager=secrets,
        credential_validator=validator,
        session_pepper=SESSION_PEPPER.encode(),
        clock=lambda: NOW,
    )
    arguments = {
        "principal": principal,
        "current_password": SecretStr(PASSWORD),
        "request_meta": meta,
        "expected_revision": configured.revision,
        "operator_enabled": True,
        "demo_enabled": False,
        "request_id": "channel-failure-request-1",
        "idempotency_key": "channel-failure-idempotency-1",
    }

    for _ in range(2):
        with pytest.raises(
            AIControlAvailabilityFailed,
            match="ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN",
        ):
            service.set_channels(
                **{**arguments, "current_password": SecretStr(PASSWORD)}
            )

    assert validator.calls == 1
    assert secrets.reads == ["old-version"]


def test_rotation_same_key_replays_without_provider_or_secret_side_effects(
    migrated_engine,
) -> None:
    auth, meta, principal, configured = authority(migrated_engine)
    secrets = FakeSecretManager()
    validator = FakeValidator("verified", "verified")
    service = OpenAIKeyRotationService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        key_name="openai-api-key",
        operator_auth_service=auth,
        secret_manager=secrets,
        credential_validator=validator,
        session_pepper=SESSION_PEPPER.encode(),
        clock=lambda: NOW,
    )
    arguments = {
        "principal": principal,
        "current_password": SecretStr(PASSWORD),
        "request_meta": meta,
        "candidate": SecretStr(NEW_KEY),
        "expected_revision": configured.revision,
        "request_id": "rotation-request-1",
        "idempotency_key": "rotation-idempotency-1",
    }

    first = service.rotate(**arguments)
    replay = service.rotate(
        **{
            **arguments,
            "current_password": SecretStr(PASSWORD),
            "candidate": SecretStr(NEW_KEY),
        }
    )

    assert replay.revision == first.revision
    assert replay.key_fingerprint == first.key_fingerprint
    assert validator.calls == 2
    assert secrets.writes == [NEW_KEY]
    with migrated_engine.connect() as connection:
        stored = connection.execute(
            select(idempotency_receipts.c.response_projection)
        ).scalar_one()
    serialized_receipt = json.dumps(stored, sort_keys=True)
    assert NEW_KEY not in serialized_receipt
    assert PASSWORD not in serialized_receipt
    assert "old-version" not in serialized_receipt
    assert "written-1" not in serialized_receipt
    assert "openai-api-key" not in serialized_receipt
    with pytest.raises(AIStateConflict, match="ADMIN_AI_STATE_CONFLICT"):
        service.rotate(
            **{
                **arguments,
                "current_password": SecretStr(PASSWORD),
                "candidate": SecretStr(OTHER_KEY),
            }
        )
    assert validator.calls == 2
    assert secrets.writes == [NEW_KEY]


def test_rotation_replays_compensated_failure_without_repeating_side_effects(
    migrated_engine,
) -> None:
    auth, meta, principal, configured = authority(migrated_engine)
    secrets = FakeSecretManager()
    validator = FakeValidator("verified", "rejected")
    service = OpenAIKeyRotationService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        key_name="openai-api-key",
        operator_auth_service=auth,
        secret_manager=secrets,
        credential_validator=validator,
        session_pepper=SESSION_PEPPER.encode(),
        clock=lambda: NOW,
    )
    arguments = {
        "principal": principal,
        "current_password": SecretStr(PASSWORD),
        "request_meta": meta,
        "candidate": SecretStr(NEW_KEY),
        "expected_revision": configured.revision,
        "request_id": "rotation-failure-request-1",
        "idempotency_key": "rotation-failure-idempotency-1",
    }

    with pytest.raises(AIKeyRotationFailed, match="ADMIN_AI_KEY_REJECTED"):
        service.rotate(**arguments)
    with pytest.raises(AIKeyRotationFailed, match="ADMIN_AI_KEY_REJECTED"):
        service.rotate(
            **{
                **arguments,
                "current_password": SecretStr(PASSWORD),
                "candidate": SecretStr(NEW_KEY),
            }
        )

    assert validator.calls == 2
    assert secrets.writes == [NEW_KEY, OLD_KEY]
