from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from src.repositories.admin_ai import AdminAuditProjection, AIControlProjection
from src.repositories.admin_ai import AIControlBusy
from src.repositories.ai_chat import CredentialBindingAuditProjection
from src.services.ai_control_service import (
    AIControlAvailabilityFailed,
    AIReauthenticationFailed,
    AIStateConflict,
)
from src.services.openai_key_rotation_service import AIKeyRotationFailed
from src.services.operator_auth_service import AuthenticationRateLimited
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)

ORIGIN = "http://testserver"
NOW = datetime(2026, 8, 18, 12, 0, tzinfo=UTC)
CANDIDATE = "candidate-key-sentinel"


def projection(*, revision: int = 4) -> AIControlProjection:
    return AIControlProjection(
        workspace_id="synthetic-demo",
        operator_enabled=True,
        demo_enabled=False,
        key_name="openai-api-key",
        key_version="key-version-must-not-project",
        key_reference="openai-api-key/key-version-must-not-project",
        key_fingerprint="7fa2c91e" + "a" * 56,
        verified_at=NOW,
        key_validation_state="verified",
        revision=revision,
        updated_by_operator_id=None,
        updated_at=NOW,
    )


class SummaryService:
    def get(self):
        from src.services.admin_summary_service import (
            AdminSummaryProjection,
            AdminSystemProjection,
            unavailable_ai_projection,
        )

        return AdminSummaryProjection(
            system=AdminSystemProjection(
                database="ready",
                blob="ready",
                configuration="valid",
                migration="0017_ai_turn_credential_binding",
            ),
            published_dataset=None,
            latest_import=None,
            actionable_failure_count=0,
            recent_activity=(),
            ai=unavailable_ai_projection(),
        )


class ControlService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def get(self) -> AIControlProjection:
        return projection()

    def set_channels(self, **values) -> AIControlProjection:
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        return replace(
            projection(),
            operator_enabled=bool(values["operator_enabled"]),
            demo_enabled=bool(values["demo_enabled"]),
            revision=5,
        )

    def mutation_audit(self, request_ids):
        return tuple(
            AdminAuditProjection(
                id=UUID(int=index + 1),
                workspace_id="synthetic-demo",
                operator_id=UUID(int=99),
                action="key.rotate" if index == 0 else "channels.update",
                result="succeeded",
                safe_error_code=None,
                prior_revision=index + 4,
                resulting_revision=index + 5,
                requested_operator_enabled=(True if index else None),
                requested_demo_enabled=(False if index else None),
                request_id=request_id,
                created_at=NOW,
            )
            for index, request_id in enumerate(request_ids)
        )


class RotationService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def rotate(self, **values) -> AIControlProjection:
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        return projection(revision=5)


class ChatAuditService:
    def credential_binding_audit(self, turn_ids):
        return tuple(
            CredentialBindingAuditProjection(
                turn_id=turn_id,
                actor_kind="operator" if index == 0 else "demo",
                request_id=f"request-binding-{index + 1}",
                credential_binding_id="d" * 64,
                credential_control_revision=index + 2,
                status="answered",
            )
            for index, turn_id in enumerate(turn_ids)
        )


def admin_client(
    migrated_engine,
    *,
    control=None,
    rotation=None,
    chat_audit=None,
) -> TestClient:
    container = replace(
        build_container(migrated_engine, initial_clock()),
        admin_summary_service=SummaryService(),
        ai_control_service=control or ControlService(),
        openai_key_rotation_service=rotation or RotationService(),
        ai_chat_service=chat_audit,
    )
    return TestClient(create_app(container=container))


def test_operator_only_binding_audit_projects_exact_non_secret_turn_authority(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    operator_turn = UUID("11111111-1111-4111-8111-111111111111")
    demo_turn = UUID("22222222-2222-4222-8222-222222222222")
    with admin_client(migrated_engine, chat_audit=ChatAuditService()) as client:
        unauthenticated = client.get(
            "/api/v1/admin/ai/turn-bindings",
            params=[("turn_id", str(operator_turn)), ("turn_id", str(demo_turn))],
        )
        login(client)
        response = client.get(
            "/api/v1/admin/ai/turn-bindings",
            params=[("turn_id", str(operator_turn)), ("turn_id", str(demo_turn))],
        )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "turn_id": str(operator_turn),
                "actor_kind": "operator",
                "request_id": "request-binding-1",
                "credential_binding_id": "d" * 64,
                "credential_control_revision": 2,
                "status": "answered",
            },
            {
                "turn_id": str(demo_turn),
                "actor_kind": "demo",
                "request_id": "request-binding-2",
                "credential_binding_id": "d" * 64,
                "credential_control_revision": 3,
                "status": "answered",
            },
        ]
    }
    assert "key_version" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def test_operator_only_mutation_audit_projects_exact_non_secret_rows(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    request_ids = ("request-rotation-1", "request-channel-1")
    with admin_client(migrated_engine) as client:
        unauthenticated = client.get(
            "/api/v1/admin/ai/audit-events",
            params=[("request_id", value) for value in request_ids],
        )
        login(client)
        response = client.get(
            "/api/v1/admin/ai/audit-events",
            params=[("request_id", value) for value in request_ids],
        )

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.json() == {
        "items": [
            {
                "request_id": "request-rotation-1",
                "action": "key.rotate",
                "result": "succeeded",
                "safe_error_code": None,
                "prior_revision": 4,
                "resulting_revision": 5,
                "requested_operator_enabled": None,
                "requested_demo_enabled": None,
            },
            {
                "request_id": "request-channel-1",
                "action": "channels.update",
                "result": "succeeded",
                "safe_error_code": None,
                "prior_revision": 5,
                "resulting_revision": 6,
                "requested_operator_enabled": True,
                "requested_demo_enabled": False,
            },
        ]
    }
    assert "operator_id" not in response.text
    assert "workspace_id" not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"


def login(client: TestClient) -> str:
    response = client.post(
        "/api/operator/login",
        headers={"Origin": ORIGIN},
        json={"login_name": LOGIN_NAME, "password": PASSWORD},
    )
    assert response.status_code == 201
    return response.json()["csrf_token"]


def mutation_headers(csrf: str, *, idempotency: bool = True) -> dict[str, str]:
    headers = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
    if idempotency:
        headers["Idempotency-Key"] = "admin-operation-1"
    return headers


def test_admin_reads_require_operator_and_never_project_secret_authority(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    with admin_client(migrated_engine) as client:
        unauthenticated = client.get("/api/v1/admin/ai")
        login(client)
        response = client.get("/api/v1/admin/ai")
        summary = client.get("/api/v1/admin/summary")

    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["cache-control"] == "private, no-store"
    assert unauthenticated.headers["vary"] == "Cookie"
    assert response.status_code == 200
    assert response.json()["credential"]["fingerprint"] == "7fa2c91e"
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
    serialized = response.text.lower()
    assert "key_version" not in serialized
    assert "key-version-must-not-project" not in serialized
    assert "openai-api-key" not in serialized
    assert summary.status_code == 200
    assert summary.json()["ai"] == {
        "status": "unavailable",
        "revision": None,
        "operator_enabled": False,
        "demo_enabled": False,
        "credential": {
            "configured": False,
            "fingerprint": None,
            "verified_at": None,
        },
    }
    assert summary.headers["cache-control"] == "private, no-store"
    assert summary.headers["vary"] == "Cookie"


def test_channel_update_requires_csrf_password_and_idempotency(
    migrated_engine,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    control = ControlService()
    with admin_client(migrated_engine, control=control) as client:
        csrf = login(client)
        payload = {
            "expected_revision": 4,
            "operator_enabled": False,
            "demo_enabled": True,
            "current_password": PASSWORD,
        }
        missing_csrf = client.patch("/api/v1/admin/ai/channels", json=payload)
        missing_idempotency = client.patch(
            "/api/v1/admin/ai/channels",
            headers=mutation_headers(csrf, idempotency=False),
            json=payload,
        )
        allowed = client.patch(
            "/api/v1/admin/ai/channels",
            headers=mutation_headers(csrf),
            json=payload,
        )

    assert missing_csrf.status_code == 403
    assert missing_csrf.headers["cache-control"] == "private, no-store"
    assert missing_csrf.headers["vary"] == "Cookie"
    assert missing_idempotency.status_code == 422
    assert allowed.status_code == 200
    assert allowed.json()["operator_enabled"] is False
    assert allowed.json()["demo_enabled"] is True
    assert len(control.calls) == 1
    assert control.calls[0]["current_password"].get_secret_value() == PASSWORD
    assert control.calls[0]["idempotency_key"] == "admin-operation-1"


def test_rotation_requires_csrf_password_and_idempotency_without_secret_echo(
    migrated_engine,
    caplog,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    rotation = RotationService()
    with admin_client(migrated_engine, rotation=rotation) as client:
        csrf = login(client)
        payload = {
            "candidate_key": CANDIDATE,
            "current_password": PASSWORD,
            "expected_revision": 4,
        }
        missing_csrf = client.post(
            "/api/v1/admin/ai/key-rotations",
            json=payload,
        )
        missing_idempotency = client.post(
            "/api/v1/admin/ai/key-rotations",
            headers=mutation_headers(csrf, idempotency=False),
            json=payload,
        )
        allowed = client.post(
            "/api/v1/admin/ai/key-rotations",
            headers=mutation_headers(csrf),
            json=payload,
        )

    assert missing_csrf.status_code == 403
    assert missing_idempotency.status_code == 422
    assert allowed.status_code == 200
    assert allowed.json() == {
        "revision": 5,
        "credential": {
            "configured": True,
            "fingerprint": "7fa2c91e",
            "verified_at": "2026-08-18T12:00:00Z",
        },
        "result_code": "ADMIN_AI_KEY_ROTATED",
    }
    captured = allowed.text + missing_csrf.text + missing_idempotency.text + caplog.text
    assert CANDIDATE not in captured
    assert PASSWORD not in captured
    assert rotation.calls[0]["idempotency_key"] == "admin-operation-1"


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (AIStateConflict(), 409, "ADMIN_AI_STATE_CONFLICT"),
        (AIControlBusy("database-lock-detail"), 409, "ADMIN_AI_OPERATION_BUSY"),
        (
            AIControlAvailabilityFailed("ADMIN_AI_OPERATION_BUSY"),
            409,
            "ADMIN_AI_OPERATION_BUSY",
        ),
        (
            AIKeyRotationFailed("ADMIN_AI_KEY_REJECTED"),
            422,
            "ADMIN_AI_KEY_REJECTED",
        ),
        (
            AIKeyRotationFailed("ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN"),
            503,
            "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN",
        ),
        (
            AIKeyRotationFailed("ADMIN_AI_SECRET_UNAVAILABLE"),
            503,
            "ADMIN_AI_SECRET_UNAVAILABLE",
        ),
        (AIReauthenticationFailed(), 401, "ADMIN_REAUTHENTICATION_FAILED"),
        (AuthenticationRateLimited(), 429, "RATE_LIMITED"),
    ],
)
def test_admin_mutations_map_only_stable_safe_errors(
    migrated_engine,
    error: Exception,
    status: int,
    code: str,
) -> None:
    seed_operator(migrated_engine, fast_password_hasher())
    rotation = RotationService(error)
    with admin_client(migrated_engine, rotation=rotation) as client:
        csrf = login(client)
        response = client.post(
            "/api/v1/admin/ai/key-rotations",
            headers=mutation_headers(csrf),
            json={
                "candidate_key": CANDIDATE,
                "current_password": PASSWORD,
                "expected_revision": 4,
            },
        )

    assert response.status_code == status
    assert response.json()["code"] == code
    if code == "ADMIN_AI_STATE_CONFLICT":
        assert response.json()["current"]["revision"] == 4
        assert response.json()["current"]["credential"]["fingerprint"] == "7fa2c91e"
        assert "key_version" not in response.text.lower()
    assert CANDIDATE not in response.text
    assert PASSWORD not in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Cookie"
