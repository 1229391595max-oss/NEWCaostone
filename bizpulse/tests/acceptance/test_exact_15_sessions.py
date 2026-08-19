from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import httpx
from sqlalchemy import Engine, func, select

from src.ai.prompt_catalog import PromptCatalog
from src.db.schema import (
    analysis_runs,
    dataset_artifacts,
    dataset_series,
    dataset_versions,
    public_releases,
)
from tests.acceptance.support import (
    acceptance_server,
    azure_storage,
    azurite_container,
    seed_fixed_release,
)


def _prompt_payload() -> dict[str, str]:
    preset = PromptCatalog.default().get("advertising_performance")
    return {
        "question": preset.templates["en"],
        "recommended_question_id": preset.id,
        "prompt_locale": "en",
        "prompt_template_version": preset.template_version,
        "prompt_template_sha256": preset.template_sha256("en"),
    }


def _durable_release_counts(engine: Engine) -> dict[str, int]:
    tables = {
        "dataset_series": dataset_series,
        "dataset_versions": dataset_versions,
        "dataset_artifacts": dataset_artifacts,
        "analysis_runs": analysis_runs,
        "public_releases": public_releases,
    }
    with engine.connect() as connection:
        return {
            name: int(connection.scalar(select(func.count()).select_from(table)) or 0)
            for name, table in tables.items()
        }


def test_exact_15_same_source_sessions_read_and_chat_without_cross_leak(
    migrated_engine: Engine,
) -> None:
    started = monotonic()
    with azurite_container() as container:
        storage = azure_storage(migrated_engine, container)
        version_id = seed_fixed_release(migrated_engine, storage)
        counts_before = _durable_release_counts(migrated_engine)
        blobs_before = len(tuple(container.list_blobs()))
        admissions_started = monotonic()
        admission_times: list[float] = []

        with acceptance_server(migrated_engine, container) as base_url:

            def viewer(index: int) -> tuple[str, str, str, str, str]:
                with httpx.Client(timeout=30) as client:
                    admitted = client.post(
                        f"{base_url}/api/demo/sessions",
                        headers={"Origin": base_url},
                    )
                    assert admitted.status_code == 201, admitted.text
                    admission_times.append(monotonic())
                    session = admitted.json()
                    activated = client.post(
                        f"{base_url}/api/demo/sessions/current/import-demo-data",
                        headers={
                            "Origin": base_url,
                            "X-CSRF-Token": session["csrf_token"],
                        },
                    )
                    assert activated.status_code == 200, activated.text
                    release = client.get(f"{base_url}/api/demo/release/current")
                    analysis = client.get(
                        f"{base_url}/api/demo/release/analyses/sales_ads"
                    )
                    actions = client.get(f"{base_url}/api/demo/release/actions")
                    assert actions.status_code == 200, actions.text
                    action = actions.json()["items"][0]
                    overlay = client.post(
                        f"{base_url}/api/demo/actions/{action['id']}/commands",
                        headers={
                            "Origin": base_url,
                            "X-CSRF-Token": session["csrf_token"],
                            "Idempotency-Key": f"capacity-action-{index}",
                        },
                        json={
                            "base_revision": action["current_revision"],
                            "command": "review",
                            "reason": "Bounded capacity simulation",
                            "adjustment": {},
                        },
                    )
                    turn = client.post(
                        f"{base_url}/api/v1/ai-chat/turns",
                        headers={
                            "Origin": base_url,
                            "X-CSRF-Token": session["csrf_token"],
                            "Idempotency-Key": f"capacity-viewer-{index}",
                        },
                        json=_prompt_payload(),
                    )
                    listed = client.get(f"{base_url}/api/v1/ai-chat/turns")
                    assert release.status_code == analysis.status_code == 200
                    assert overlay.status_code == 200, overlay.text
                    assert turn.status_code == 201, turn.text
                    assert [item["id"] for item in listed.json()["items"]] == [
                        turn.json()["id"]
                    ]
                    return (
                        session["session"]["session_id"],
                        release.json()["release_id"],
                        release.json()["dataset_version_id"],
                        turn.json()["id"],
                        overlay.json()["status"],
                    )

            with ThreadPoolExecutor(max_workers=15) as executor:
                results = tuple(executor.map(viewer, range(15)))

        counts_after = _durable_release_counts(migrated_engine)
        blobs_after = len(tuple(container.list_blobs()))
        elapsed = monotonic() - started
        assert max(admission_times) - admissions_started < 60
        assert len({item[0] for item in results}) == 15
        assert len({item[1] for item in results}) == 1
        assert {item[2] for item in results} == {str(version_id)}
        assert len({item[3] for item in results}) == 15
        assert {item[4] for item in results} == {"reviewed"}
        assert counts_after == counts_before
        assert blobs_after == blobs_before
        assert elapsed < 300
