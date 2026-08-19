#!/usr/bin/env python3
"""Explicit, synthetic-only qualification for the approved OpenAI snapshot."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.config import (
    APPROVED_CHAT_OUTPUT_TOKEN_LIMIT,
    APPROVED_OPENAI_MODEL,
    APPROVED_REASONING_EFFORT,
)

APPROVED_MODEL = APPROVED_OPENAI_MODEL
MAX_OUTPUT_TOKENS = APPROVED_CHAT_OUTPUT_TOKEN_LIMIT
PROVIDER_TIMEOUT_SECONDS = 30.0
_CJK = re.compile(r"[\u3400-\u9fff]")
_ENGLISH = re.compile(r"[A-Za-z]{3,}")


class NumericalCitation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: Literal["net_sales", "at_risk_skus"]
    value: str = Field(min_length=1, max_length=50)


class QualificationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    language: Literal["en", "zh"]
    store_scope: Literal["all", "main", "launch"]
    intent: Literal["monthly-sales-report", "inventory-risk"]
    answer: str = Field(min_length=1, max_length=8_000)
    numerical_citations: tuple[NumericalCitation, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class QualificationCase:
    case_id: str
    locale: Literal["en", "zh"]
    store_scope: Literal["all", "main", "launch"]
    intent: Literal["monthly-sales-report", "inventory-risk"]
    authority: tuple[tuple[str, str], ...] = (
        ("net_sales", "1250.00"),
        ("at_risk_skus", "6"),
    )
    evidence_refs: tuple[str, ...] = (
        "analysis:qualification:net_sales",
        "analysis:qualification:inventory_risk",
    )

    def prompt_payload(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "language": self.locale,
            "store_scope": self.store_scope,
            "intent": self.intent,
            "synthetic_authority": dict(self.authority),
            "allowed_evidence_refs": list(self.evidence_refs),
            "instruction": (
                "Return only the requested structured answer. Cite at least one "
                "supplied number and one supplied evidence reference."
            ),
        }


@dataclass(frozen=True, slots=True)
class ProviderCaseResult:
    output: object
    input_tokens: int
    output_tokens: int


def build_cases() -> tuple[QualificationCase, ...]:
    return tuple(
        QualificationCase(
            case_id=f"{locale}-{scope}-{intent}",
            locale=locale,
            store_scope=scope,
            intent=intent,
        )
        for locale in ("en", "zh")
        for scope in ("all", "main", "launch")
        for intent in ("monthly-sales-report", "inventory-risk")
    )


class OpenAIQualificationProvider:
    """One-call adapter with the same no-retry/no-fallback provider boundary."""

    def __init__(self, client) -> None:
        self._client = client

    def run_case(
        self,
        case: QualificationCase,
        *,
        model: str,
        reasoning_effort: str,
        max_output_tokens: int,
    ) -> ProviderCaseResult:
        client = self._client.with_options(
            max_retries=0,
            timeout=PROVIDER_TIMEOUT_SECONDS,
        )
        response = client.responses.parse(
            model=model,
            reasoning={"effort": reasoning_effort},
            max_output_tokens=max_output_tokens,
            tools=[],
            input=[
                {
                    "role": "system",
                    "content": (
                        "You are qualifying a fixed BizPulse model using only "
                        "synthetic authority. Never add facts or evidence."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        case.prompt_payload(),
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                },
            ],
            text_format=QualificationOutput,
        )
        if getattr(response, "status", None) != "completed":
            return ProviderCaseResult(
                output=None,
                input_tokens=0,
                output_tokens=0,
            )
        usage = getattr(response, "usage", None)
        return ProviderCaseResult(
            output=getattr(response, "output_parsed", None),
            input_tokens=getattr(usage, "input_tokens"),
            output_tokens=getattr(usage, "output_tokens"),
        )


def run_qualification(provider) -> dict[str, object]:
    case_receipts = []
    for case in build_cases():
        prompt_sha256 = _sha256(case.prompt_payload())
        checks = {
            "schema": False,
            "scope": False,
            "numerical_citations": False,
            "evidence_refs": False,
            "language": False,
            "token_limit": False,
        }
        input_tokens = 0
        output_tokens = 0
        response_sha256 = _sha256({"invalid": "provider_not_called"})
        try:
            result = provider.run_case(
                case,
                model=APPROVED_MODEL,
                reasoning_effort=APPROVED_REASONING_EFFORT,
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
            input_tokens = _token_count(result.input_tokens)
            output_tokens = _token_count(result.output_tokens)
            response_sha256 = _sha256(result.output)
            output = QualificationOutput.model_validate(result.output)
            checks["schema"] = True
            checks["scope"] = (
                output.store_scope == case.store_scope
                and output.intent == case.intent
            )
            allowed_citations = set(case.authority)
            checks["numerical_citations"] = bool(output.numerical_citations) and all(
                (citation.label, citation.value) in allowed_citations
                for citation in output.numerical_citations
            )
            checks["evidence_refs"] = bool(output.evidence_refs) and set(
                output.evidence_refs
            ).issubset(case.evidence_refs)
            checks["language"] = (
                output.language == case.locale
                and _answer_matches_language(output.answer, case.locale)
            )
            checks["token_limit"] = (
                input_tokens >= 0 and 0 <= output_tokens <= MAX_OUTPUT_TOKENS
            )
        except (AttributeError, TypeError, ValueError, ValidationError):
            pass
        case_receipts.append(
            {
                "case_id": case.case_id,
                "passed": all(checks.values()),
                "checks": checks,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "prompt_sha256": prompt_sha256,
                "response_sha256": response_sha256,
            }
        )
    return {
        "schema_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "model_snapshot": {
            "model": APPROVED_MODEL,
            "reasoning_effort": APPROVED_REASONING_EFFORT,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
        },
        "case_ids": [case.case_id for case in build_cases()],
        "cases": case_receipts,
        "passed": all(item["passed"] for item in case_receipts),
    }


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client_factory=None,
) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute-paid-qualification", action="store_true")
    parser.add_argument("--receipt", type=Path, required=True)
    options = parser.parse_args(argv)
    environment = os.environ if environ is None else environ
    api_key = environment.get("BIZPULSE_DEPLOY_OPENAI_API_KEY")
    if not options.execute_paid_qualification or not api_key:
        print(
            "qualification_inert: explicit paid flag and provider key are required",
            file=sys.stderr,
        )
        return 2
    factory = client_factory or _default_client_factory
    provider = factory(api_key)
    receipt = run_qualification(provider)
    options.receipt.write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"qualification_complete: passed={str(receipt['passed']).lower()} "
        f"cases={len(receipt['cases'])}"
    )
    return 0 if receipt["passed"] else 1


def _default_client_factory(api_key: str) -> OpenAIQualificationProvider:
    from openai import OpenAI

    return OpenAIQualificationProvider(OpenAI(api_key=api_key))


def _answer_matches_language(answer: str, locale: str) -> bool:
    if locale == "zh":
        return _CJK.search(answer) is not None
    return _CJK.search(answer) is None and _ENGLISH.search(answer) is not None


def _token_count(value: object) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("qualification_token_count_invalid")
    return value


def _sha256(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=lambda item: {"type": type(item).__name__},
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
