"""Fail-closed merge of model language with authoritative server facts."""

from __future__ import annotations

import re
from uuid import UUID

from src.ai.contracts import ChatAnswer, ModelExplanation, ToolResult
from src.synthetic.boundary import (
    SyntheticSourceBoundaryError,
    validate_synthetic_records,
)


class AnswerMergeRejected(ValueError):
    pass


NUMBER = re.compile(r"(?<![A-Za-z])[-+]?\d+(?:[.,]\d+)*(?![A-Za-z])")
FACT_REF = re.compile(r"\bfact-\d{3}\b")


def merge_answer(
    turn_id: UUID,
    result: ToolResult,
    explanation: ModelExplanation,
) -> ChatAnswer:
    available = tuple(item.fact_ref for item in result.facts)
    supplied = explanation.fact_refs
    if len(supplied) != len(set(supplied)):
        raise AnswerMergeRejected("duplicate_fact_ref")
    if not set(supplied) <= set(available):
        raise AnswerMergeRejected("unknown_fact_ref")
    if result.facts and set(supplied) != set(available):
        raise AnswerMergeRejected("omitted_fact_ref")
    try:
        validate_synthetic_records(
            (
                {
                    "answer": explanation.answer,
                    "suggested_questions": ";".join(
                        explanation.suggested_questions
                    ),
                },
            )
        )
    except SyntheticSourceBoundaryError as error:
        raise AnswerMergeRejected("unsafe_model_text") from error
    model_text = (explanation.answer,) + explanation.suggested_questions
    if any(NUMBER.search(FACT_REF.sub("", item)) for item in model_text):
        raise AnswerMergeRejected("model_numeric_text_forbidden")
    return ChatAnswer(
        turn_id=turn_id,
        status="answered",
        answer=explanation.answer,
        scope=result.scope,
        facts=result.facts,
        limitations=result.limitations,
        suggested_questions=explanation.suggested_questions,
        action_card_draft_eligible=result.action_card_draft is not None,
    )
