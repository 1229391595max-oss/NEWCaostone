from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import Engine

from api.main import create_app
from api.v1.schemas.ai_chat import ChatTurnRequest
from src.ai.query_catalog import QueryCatalog
from src.ai.query_executor import QueryExecutor
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.ai_chat_service import AIBudgetLimits, AIChatService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import (
    LOGIN_NAME,
    PASSWORD,
    activate_demo_data,
    build_container,
    fast_password_hasher,
    initial_clock,
    seed_operator,
)
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID
from tests.services.test_ai_chat_service import (
    FakeAIControl,
    FakeGateway,
    StaticBackend,
)

ORIGIN = "http://testserver"


def preset_payload(preset_id: str, locale: str = "en") -> dict[str, object]:
    preset = QueryCatalog().prompt_catalog.get(preset_id)
    return {
        "question": preset.templates[locale],
        "store_ids": ["SYNTH-STORE-01"],
        "recommended_question_id": preset.id,
        "prompt_locale": locale,
        "prompt_template_version": preset.template_version,
        "prompt_template_sha256": preset.template_sha256(locale),
    }


def test_chat_request_requires_actual_text_and_complete_preset_audit() -> None:
    preset = QueryCatalog().prompt_catalog.get("inventory_risks")
    valid = ChatTurnRequest.model_validate(
        {
            "question": preset.templates["en"],
            "store_ids": ["SYNTH-STORE-02"],
            "recommended_question_id": preset.id,
            "prompt_locale": "en",
            "prompt_template_version": preset.template_version,
            "prompt_template_sha256": preset.template_sha256("en"),
        }
    )

    assert valid.question == preset.templates["en"]
    assert valid.store_ids == ("SYNTH-STORE-02",)
    payload = valid.model_dump(mode="json")
    payload.pop("question")
    with pytest.raises(ValueError):
        ChatTurnRequest.model_validate(payload)
    for missing in (
        "prompt_locale",
        "prompt_template_version",
        "prompt_template_sha256",
    ):
        payload = valid.model_dump(mode="json")
        payload.pop(missing)
        with pytest.raises(ValueError, match="prompt_preset_contract_invalid"):
            ChatTurnRequest.model_validate(payload)


def test_free_text_request_has_no_preset_audit_metadata() -> None:
    request = ChatTurnRequest.model_validate(
        {
            "question": "What changed in current synthetic net sales?",
            "store_ids": [],
        }
    )

    assert request.recommended_question_id is None
    assert request.prompt_locale is None
    assert request.store_ids == ()

    with pytest.raises(ValueError):
        ChatTurnRequest.model_validate(
            {
                "question": "Compare unsupported arbitrary store combinations",
                "store_ids": ["SYNTH-STORE-01", "SYNTH-STORE-02"],
            }
        )


def test_operator_and_demo_chat_routes_are_server_scoped_and_session_isolated(
    migrated_engine: Engine,
    monkeypatch,
) -> None:
    ai_events: list[dict[str, object]] = []
    monkeypatch.setattr(
        "api.v1.routers.ai_chat.log_ai_turn",
        lambda fields: ai_events.append(dict(fields)),
    )
    monkeypatch.setattr(
        "api.main.log_ai_turn",
        lambda fields: ai_events.append(dict(fields)),
    )
    clock = initial_clock()
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    seeded = seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=clock(),
    )
    gateway = FakeGateway()
    backend = StaticBackend()
    service = AIChatService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        catalog=QueryCatalog(),
        executor=QueryExecutor(backend=backend),
        gateway=gateway,
        ai_control=FakeAIControl(),
        budget_limits=AIBudgetLimits(100, 100_000, 10),
        clock=clock,
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
        ai_chat_service=service,
    )
    app = create_app(container=container)

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/ai-chat/turns").status_code == 401

    with TestClient(app) as operator:
        login = operator.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": login.json()["csrf_token"],
            "Idempotency-Key": "api-operator-one",
        }
        created = operator.post(
            "/api/v1/ai-chat/turns",
            headers=headers,
            json={
                **preset_payload("profit_changes"),
                "context": {
                    "kind": "profit_bridge",
                    "reference": "profit_bridge:pinned",
                },
            },
        )
        replayed = operator.post(
            "/api/v1/ai-chat/turns",
            headers=headers,
            json={
                **preset_payload("profit_changes"),
                "context": {
                    "kind": "profit_bridge",
                    "reference": "profit_bridge:pinned",
                },
            },
        )
        listed = operator.get("/api/v1/ai-chat/turns")
        saved = operator.post(
            f"/api/v1/ai-chat/turns/{created.json()['id']}/save",
            headers=headers,
        )
        fetched = operator.get(f"/api/v1/ai-chat/turns/{created.json()['id']}")
        conflict = operator.post(
            "/api/v1/ai-chat/turns",
            headers=headers,
            json=preset_payload("inventory_risks"),
        )
        rejected = operator.post(
            "/api/v1/ai-chat/turns",
            headers={**headers, "Idempotency-Key": "api-operator-sensitive"},
            json={"question": "What happened to person@example.test?"},
        )
        invalid_context = operator.post(
            "/api/v1/ai-chat/turns",
            headers={**headers, "Idempotency-Key": "api-context-invalid"},
            json={
                **preset_payload("profit_changes"),
                "context": {
                    "kind": "profit_bridge",
                    "reference": "profit_bridge:client-uuid",
                },
            },
        )

    assert created.status_code == 201, created.text
    assert replayed.status_code == 201
    assert replayed.json()["id"] == created.json()["id"]
    assert created.json()["status"] == "answered"
    assert created.json()["question"] == preset_payload("profit_changes")["question"]
    assert created.json()["recommended_question_id"] == "profit_changes"
    assert created.json()["prompt_audit_state"] == "recorded"
    assert created.json()["prompt_locale"] == "en"
    assert created.json()["provider_audit"] == {
        "attempt_count": 1,
        "ledger_attempt_count": 1,
        "reserved_tokens": 80000,
        "ledger_reserved_tokens": 80000,
        "attempts": [
            {
                "stage": "answering",
                "status": "succeeded",
                "reserved_tokens": 80000,
                "error_code": None,
            }
        ],
    }
    assert created.json()["answer"]["scope"] == {
        "dataset_version_id": str(seeded.dataset_version_id),
        "store_ids": ["SYNTH-STORE-01"],
        "period_start": "2026-07-01",
        "period_end": "2026-07-31",
        "currency": "BRL",
    }
    assert "workspace_id" not in created.text
    assert "session_id" not in created.text
    assert listed.status_code == fetched.status_code == 200
    assert saved.status_code == 200
    assert saved.json()["saved"] is True
    assert listed.headers["cache-control"] == "private, no-store"
    assert fetched.headers["vary"] == "Cookie"
    assert len(listed.json()["items"]) == 1
    assert listed.json()["saved_items"] == []
    assert listed.json()["availability"] == "available"
    assert listed.json()["unavailable_code"] is None
    assert [item["id"] for item in listed.json()["recommended_questions"]] == list(
        QueryCatalog().recommended_ids()
    )
    assert any(
        item["context_kind"] == "profit_bridge"
        for item in listed.json()["recommended_questions"]
    )
    assert conflict.status_code == 409
    assert rejected.status_code == 422
    assert invalid_context.status_code == 422
    assert gateway.plan_calls == 0
    assert len(ai_events) == 5
    answered_events = [event for event in ai_events if event["status"] == "answered"]
    rejected_events = [event for event in ai_events if event["status"] == "rejected"]
    assert [event["replayed"] for event in answered_events] == [False, True]
    assert all(
        event["tool_name"] == "profit_bridge_explain"
        and event["input_tokens"] == 30
        and event["output_tokens"] == 10
        for event in answered_events
    )
    assert {event["error_code"] for event in rejected_events} == {
        "AI_CHAT_INPUT_REJECTED",
        "AI_CHAT_INVALID",
        "IDEMPOTENCY_CONFLICT",
    }
    assert all(
        event["input_tokens"] == event["output_tokens"] == 0
        and event["replayed"] is False
        for event in rejected_events
    )
    assert [
        event["dataset_version_hash_prefix"] is None for event in rejected_events
    ].count(True) == 1
    assert all(
        event["dataset_version_hash_prefix"] is None
        or len(event["dataset_version_hash_prefix"]) == 12
        for event in ai_events
    )
    assert {
        event["dataset_version_hash_prefix"]
        for event in ai_events
        if event["dataset_version_hash_prefix"] is not None
    } == {seeded.manifest_sha256[:12]}
    assert all("question" not in event for event in ai_events)
    assert gateway.explain_calls == 1

    with TestClient(app) as second_operator:
        second_operator.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        cross_session = second_operator.get(
            f"/api/v1/ai-chat/turns/{created.json()['id']}"
        )
        saved_after_relogin = second_operator.get("/api/v1/ai-chat/turns")
    assert cross_session.status_code == 404
    assert saved_after_relogin.json()["items"] == []
    assert [item["id"] for item in saved_after_relogin.json()["saved_items"]] == [
        created.json()["id"]
    ]

    with TestClient(app) as viewer:
        session = viewer.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        activate_demo_data(viewer, session)
        demo_headers = {
            "Origin": ORIGIN,
            "X-CSRF-Token": session.json()["csrf_token"],
            "Idempotency-Key": "api-demo-one",
        }
        demo_created = viewer.post(
            "/api/v1/ai-chat/turns",
            headers=demo_headers,
            json={
                **preset_payload("advertising_performance"),
                "store_ids": ["SYNTH-STORE-02"],
            },
        )
        demo_list = viewer.get("/api/v1/ai-chat/turns")
        demo_save = viewer.post(
            f"/api/v1/ai-chat/turns/{demo_created.json()['id']}/save",
            headers=demo_headers,
        )
        deleted = viewer.delete(
            "/api/v1/ai-chat/session",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": session.json()["csrf_token"],
            },
        )

    assert demo_created.status_code == 201, demo_created.text
    assert demo_created.json()["answer"]["scope"]["store_ids"] == ["SYNTH-STORE-02"]
    assert demo_list.status_code == 200
    assert len(demo_list.json()["items"]) == 1
    assert demo_list.json()["saved_items"] == []
    assert demo_save.status_code == 422
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted_turns": 1}
    assert gateway.plan_calls == 0
    assert gateway.explain_calls == 2


def test_disabled_chat_list_is_authenticated_availability_projection(
    migrated_engine: Engine,
) -> None:
    clock = initial_clock()
    storage = MemoryWorkflowStorage()
    seed_operator(migrated_engine, fast_password_hasher())
    seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=clock(),
    )
    container = replace(
        build_container(migrated_engine, clock),
        workflow_storage=storage,
    )
    app = create_app(container=container)

    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/ai-chat/turns").status_code == 401

    with TestClient(app) as operator:
        login = operator.post(
            "/api/operator/login",
            headers={"Origin": ORIGIN},
            json={"login_name": LOGIN_NAME, "password": PASSWORD},
        )
        listed = operator.get("/api/v1/ai-chat/turns")
        rejected = operator.post(
            "/api/v1/ai-chat/turns",
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": login.json()["csrf_token"],
                "Idempotency-Key": "no-ai-submit",
            },
            json=preset_payload("advertising_performance"),
        )

    assert listed.status_code == 200
    assert listed.headers["cache-control"] == "private, no-store"
    assert listed.headers["vary"] == "Cookie"
    payload = listed.json()
    assert payload["items"] == []
    assert payload["saved_items"] == []
    assert payload["availability"] == "unavailable"
    assert payload["unavailable_code"] == "AI_CHAT_UNAVAILABLE"
    assert [item["id"] for item in payload["recommended_questions"]] == list(
        QueryCatalog().recommended_ids()
    )
    assert [
        (item["labels"]["en"], item["labels"]["zh"])
        for item in payload["recommended_questions"]
    ] == [
        ("Generate this month's sales report", "生成本月销售报告"),
        ("Explain profit changes", "分析利润变化原因"),
        ("Find inventory risks", "查找库存风险"),
        ("Summarize advertising performance", "总结广告表现"),
        ("Summarize the 30-day forecast", "总结未来 30 天预测"),
        ("Prioritize next actions", "给出下一步行动建议"),
    ]
    assert rejected.status_code == 503
    assert rejected.json() == {"code": "AI_CHAT_UNAVAILABLE"}

    with TestClient(app) as viewer:
        session = viewer.post("/api/demo/sessions", headers={"Origin": ORIGIN})
        activate_demo_data(viewer, session)
        viewer_listed = viewer.get("/api/v1/ai-chat/turns")

    assert session.status_code == 201
    assert viewer_listed.status_code == 200
    assert viewer_listed.json() == payload
