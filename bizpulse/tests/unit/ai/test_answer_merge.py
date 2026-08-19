from __future__ import annotations

from datetime import date
from uuid import UUID

import pytest

from src.ai.answer_merge import AnswerMergeRejected, merge_answer
from src.ai.contracts import (
    AuthoritativeFact,
    ModelExplanation,
    QueryScope,
    ToolResult,
)


def tool_result() -> ToolResult:
    return ToolResult(
        tool="metric_lookup",
        scope=QueryScope(
            workspace_id="synthetic-demo",
            dataset_version_id=UUID("00000000-0000-0000-0000-000000000001"),
            store_ids=("SYNTH-STORE-01",),
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 30),
            currency="BRL",
        ),
        facts=(
            AuthoritativeFact(
                fact_ref="fact-001",
                label="Net sales",
                value="100.00 BRL",
                evidence_state="measured",
                evidence_refs=("analysis:sales_ads:net_sales",),
            ),
        ),
        limitations=("sample_data_only",),
        result_hash="a" * 64,
        action_card_draft=None,
    )


def test_invented_fact_ref_fails_closed() -> None:
    explanation = ModelExplanation(
        answer="Revenue improved.",
        fact_refs=("fact-999",),
        suggested_questions=(),
    )

    with pytest.raises(AnswerMergeRejected, match="unknown_fact_ref"):
        merge_answer(UUID(int=1), tool_result(), explanation)


def test_merge_keeps_server_facts_scope_and_limitations_authoritative() -> None:
    explanation = ModelExplanation(
        answer="Net sales are shown in fact-001.",
        fact_refs=("fact-001",),
        suggested_questions=("Compare the prior period",),
    )

    answer = merge_answer(UUID(int=1), tool_result(), explanation)

    assert answer.facts == tool_result().facts
    assert answer.scope == tool_result().scope
    assert answer.limitations == tool_result().limitations
    assert answer.answer == explanation.answer


@pytest.mark.parametrize(
    ("answer", "error"),
    (
        ("Net sales were 999.00 BRL.", "model_numeric_text_forbidden"),
        ("Email person@example.test for details.", "unsafe_model_text"),
        ("Use sk-proj-abcdefghijklmnop.", "unsafe_model_text"),
    ),
)
def test_model_text_cannot_invent_numbers_or_sensitive_content(
    answer: str,
    error: str,
) -> None:
    explanation = ModelExplanation(
        answer=answer,
        fact_refs=("fact-001",),
        suggested_questions=(),
    )

    with pytest.raises(AnswerMergeRejected, match=error):
        merge_answer(UUID(int=1), tool_result(), explanation)


def test_model_text_cannot_swap_authoritative_numbers_between_facts() -> None:
    result = tool_result().model_copy(
        update={
            "facts": (
                AuthoritativeFact(
                    fact_ref="fact-001",
                    label="Revenue",
                    value="100.00 BRL",
                    evidence_state="measured",
                    evidence_refs=("analysis:sales_ads:net_sales",),
                ),
                AuthoritativeFact(
                    fact_ref="fact-002",
                    label="Units",
                    value="5 units",
                    evidence_state="measured",
                    evidence_refs=("analysis:sales_ads:units",),
                ),
            )
        }
    )
    explanation = ModelExplanation(
        answer="Revenue is 5 BRL and units are 100.",
        fact_refs=("fact-001", "fact-002"),
        suggested_questions=(),
    )

    with pytest.raises(AnswerMergeRejected, match="model_numeric_text_forbidden"):
        merge_answer(UUID(int=1), result, explanation)
