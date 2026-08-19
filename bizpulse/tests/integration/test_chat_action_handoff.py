from __future__ import annotations

from sqlalchemy import Engine

from src.ai.query_catalog import QueryCatalog
from src.ai.query_executor import QueryExecutor
from src.services.action_service import ActionService
from src.services.ai_chat_service import AIBudgetLimits, AIChatService
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID
from tests.services.test_ai_chat_service import (
    DraftBackend,
    FakeAIControl,
    FakeGateway,
    NOW,
    _principal,
    _preset,
)


def test_chat_answer_requires_explicit_second_request_for_action_draft(
    migrated_engine: Engine,
) -> None:
    principal, _dataset_version_id = _principal(migrated_engine)
    backend = DraftBackend()
    actions = ActionService(
        migrated_engine,
        MemoryWorkflowStorage(),
        WORKSPACE_ID,
        clock=lambda: NOW,
    )
    chat = AIChatService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        catalog=QueryCatalog(),
        executor=QueryExecutor(backend=backend),
        gateway=FakeGateway(),
        ai_control=FakeAIControl(),
        budget_limits=AIBudgetLimits(100, 100_000, 10),
        action_service=actions,
        clock=lambda: NOW,
    )

    answer = chat.submit(
        principal,
        **_preset("inventory_risks"),
        idempotency_key="handoff-answer-one",
    )
    assert answer.answer is not None
    assert answer.answer.action_card_draft_eligible is True
    assert answer.action_draft_id is None

    drafted = chat.create_action_draft(
        principal,
        answer.id,
        idempotency_key="handoff-explicit-two",
    )
    replay = chat.create_action_draft(
        principal,
        answer.id,
        idempotency_key="handoff-explicit-two",
    )
    assert drafted == replay
    assert drafted.action_draft_id is not None
    card = actions.get(drafted.action_draft_id)
    assert card.source_type == "chat_box_draft"
    assert card.revisions[0].chat_turn_id == answer.id
    assert backend.calls == 2
