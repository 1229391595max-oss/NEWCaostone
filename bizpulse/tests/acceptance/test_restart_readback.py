from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import Engine, func, select, update

from src.ai.prompt_catalog import PromptCatalog
from src.db.schema import ai_chat_turns, demo_action_overlays, demo_sessions
from src.services.demo_session_service import DemoSessionService
from tests.acceptance.support import (
    acceptance_server,
    azure_storage,
    azurite_container,
    seed_fixed_release,
)
from tests.auth_support import SESSION_PEPPER
from tests.import_support import WORKSPACE_ID


def _prompt_payload() -> dict[str, str]:
    preset = PromptCatalog.default().get("advertising_performance")
    return {
        "question": preset.templates["en"],
        "recommended_question_id": preset.id,
        "prompt_locale": "en",
        "prompt_template_version": preset.template_version,
        "prompt_template_sha256": preset.template_sha256("en"),
    }

def test_replacement_application_reads_unexpired_session_chat_and_blob(
    migrated_engine: Engine,
) -> None:
    with azurite_container() as container:
        first_storage = azure_storage(migrated_engine, container)
        version_id = seed_fixed_release(migrated_engine, first_storage)
        with (
            httpx.Client(timeout=10) as client,
            httpx.Client(timeout=10) as expired_client,
        ):
            with acceptance_server(migrated_engine, container) as base_url:
                first = client
                admitted_response = first.post(
                    f"{base_url}/api/demo/sessions",
                    headers={"Origin": base_url},
                )
                assert admitted_response.status_code == 201
                admitted = admitted_response.json()
                activated = first.post(
                    f"{base_url}/api/demo/sessions/current/import-demo-data",
                    headers={
                        "Origin": base_url,
                        "X-CSRF-Token": admitted["csrf_token"],
                    },
                )
                assert activated.status_code == 200
                created = first.post(
                    f"{base_url}/api/v1/ai-chat/turns",
                    headers={
                        "Origin": base_url,
                        "X-CSRF-Token": admitted["csrf_token"],
                        "Idempotency-Key": "restart-turn-one",
                    },
                    json=_prompt_payload(),
                )
                assert created.status_code == 201
                expired_admission = expired_client.post(
                    f"{base_url}/api/demo/sessions",
                    headers={"Origin": base_url},
                )
                assert expired_admission.status_code == 201
                expired_session = expired_admission.json()
                expired_activation = expired_client.post(
                    f"{base_url}/api/demo/sessions/current/import-demo-data",
                    headers={
                        "Origin": base_url,
                        "X-CSRF-Token": expired_session["csrf_token"],
                    },
                )
                assert expired_activation.status_code == 200
                expired_turn = expired_client.post(
                    f"{base_url}/api/v1/ai-chat/turns",
                    headers={
                        "Origin": base_url,
                        "X-CSRF-Token": expired_session["csrf_token"],
                        "Idempotency-Key": "restart-expired-turn",
                    },
                    json=_prompt_payload(),
                )
                actions = expired_client.get(
                    f"{base_url}/api/demo/release/actions"
                )
                action = actions.json()["items"][0]
                expired_overlay = expired_client.post(
                    f"{base_url}/api/demo/actions/{action['id']}/commands",
                    headers={
                        "Origin": base_url,
                        "X-CSRF-Token": expired_session["csrf_token"],
                        "Idempotency-Key": "restart-expired-overlay",
                    },
                    json={
                        "base_revision": action["current_revision"],
                        "command": "review",
                        "reason": "Restart expiry acceptance",
                        "adjustment": {},
                    },
                )
                assert expired_turn.status_code == 201
                assert expired_overlay.status_code == 200

            expired_at = datetime.now(UTC)
            expired_session_id = expired_session["session"]["session_id"]
            with migrated_engine.begin() as connection:
                connection.execute(
                    update(demo_sessions)
                    .where(demo_sessions.c.id == expired_session_id)
                    .values(idle_expires_at=expired_at - timedelta(seconds=1))
                )
            maintenance = DemoSessionService(
                engine=migrated_engine,
                workspace_id=WORKSPACE_ID,
                session_pepper=SESSION_PEPPER,
                clock=lambda: expired_at,
            )
            assert maintenance.expire_sessions(expired_at) == 1

            with acceptance_server(migrated_engine, container) as base_url:
                current = client.get(f"{base_url}/api/demo/sessions/current")
                release = client.get(f"{base_url}/api/demo/release/current")
                analysis = client.get(
                    f"{base_url}/api/demo/release/analyses/sales_ads"
                )
                turns = client.get(f"{base_url}/api/v1/ai-chat/turns")
                expired_current = expired_client.get(
                    f"{base_url}/api/demo/sessions/current"
                )
                expired_turns = expired_client.get(
                    f"{base_url}/api/v1/ai-chat/turns"
                )
                expired_overlays = expired_client.get(
                    f"{base_url}/api/demo/actions/{action['id']}/overlays"
                )

        assert current.status_code == release.status_code == analysis.status_code == 200
        assert current.json()["session"]["session_id"] == admitted["session"][
            "session_id"
        ]
        assert release.json()["dataset_version_id"] == str(version_id)
        assert analysis.json()["run"]["dataset_version_id"] == str(version_id)
        assert [item["id"] for item in turns.json()["items"]] == [
            created.json()["id"]
        ]
        assert expired_current.status_code == 401
        assert expired_turns.status_code == 401
        assert expired_overlays.status_code == 401
        with migrated_engine.connect() as connection:
            assert connection.scalar(
                select(func.count()).select_from(ai_chat_turns)
            ) == 1
            assert connection.scalar(
                select(func.count()).select_from(demo_action_overlays)
            ) == 0
