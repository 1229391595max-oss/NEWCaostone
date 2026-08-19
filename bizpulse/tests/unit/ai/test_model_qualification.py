from __future__ import annotations

import json

from scripts.qualify_openai_model import (
    APPROVED_MODEL,
    MAX_OUTPUT_TOKENS,
    NumericalCitation,
    ProviderCaseResult,
    QualificationOutput,
    build_cases,
    main,
    run_qualification,
)


class FakeProvider:
    def __init__(self) -> None:
        self.calls = []

    def run_case(self, case, *, model, reasoning_effort, max_output_tokens):
        self.calls.append((case.case_id, model, reasoning_effort, max_output_tokens))
        answer = (
            "基于给定证据生成的报告。"
            if case.locale == "zh"
            else "Report generated from the supplied evidence."
        )
        return ProviderCaseResult(
            output=QualificationOutput(
                language=case.locale,
                store_scope=case.store_scope,
                intent=case.intent,
                answer=answer,
                numerical_citations=(
                    NumericalCitation(label="net_sales", value="1250.00"),
                ),
                evidence_refs=("analysis:qualification:net_sales",),
            ),
            input_tokens=120,
            output_tokens=240,
        )


def test_qualification_matrix_is_exactly_twelve_cases() -> None:
    cases = build_cases()

    assert [case.case_id for case in cases] == [
        f"{locale}-{scope}-{intent}"
        for locale in ("en", "zh")
        for scope in ("all", "main", "launch")
        for intent in ("monthly-sales-report", "inventory-risk")
    ]


def test_fake_provider_qualification_checks_every_case_without_secret_or_raw_text() -> None:
    provider = FakeProvider()

    receipt = run_qualification(provider)
    serialized = json.dumps(receipt, sort_keys=True, ensure_ascii=False)

    assert receipt["passed"] is True
    assert receipt["model_snapshot"] == {
        "model": "gpt-5.4-nano-2026-03-17",
        "reasoning_effort": "low",
        "max_output_tokens": 2_800,
    }
    assert len(receipt["cases"]) == 12
    assert all(case["passed"] for case in receipt["cases"])
    assert all("prompt_sha256" in case for case in receipt["cases"])
    assert all("response_sha256" in case for case in receipt["cases"])
    assert len(provider.calls) == 12
    assert all(call[1:] == (APPROVED_MODEL, "low", MAX_OUTPUT_TOKENS) for call in provider.calls)
    assert "OPENAI_API_KEY" not in serialized
    assert "sk-proj" not in serialized
    assert "Report generated" not in serialized
    assert "基于给定" not in serialized


def test_qualification_rejects_scope_language_citation_evidence_and_token_drift() -> None:
    class InvalidProvider(FakeProvider):
        def run_case(self, case, **kwargs):
            result = super().run_case(case, **kwargs)
            if case.case_id == "en-all-monthly-sales-report":
                return ProviderCaseResult(
                    output=result.output.model_copy(
                        update={
                            "language": "zh",
                            "store_scope": "main",
                            "numerical_citations": (
                                NumericalCitation(label="net_sales", value="999999.00"),
                            ),
                            "evidence_refs": ("analysis:unknown",),
                        }
                    ),
                    input_tokens=result.input_tokens,
                    output_tokens=MAX_OUTPUT_TOKENS + 1,
                )
            return result

    receipt = run_qualification(InvalidProvider())
    failed = receipt["cases"][0]

    assert receipt["passed"] is False
    assert failed["passed"] is False
    assert failed["checks"] == {
        "schema": True,
        "scope": False,
        "numerical_citations": False,
        "evidence_refs": False,
        "language": False,
        "token_limit": False,
    }


def test_paid_qualification_is_inert_without_flag_and_key(tmp_path) -> None:
    calls = []

    def factory(api_key):
        calls.append(api_key)
        return FakeProvider()

    receipt = tmp_path / "receipt.json"
    assert main(["--receipt", str(receipt)], environ={}, client_factory=factory) == 2
    assert main(
        ["--execute-paid-qualification", "--receipt", str(receipt)],
        environ={},
        client_factory=factory,
    ) == 2
    assert calls == []
    assert not receipt.exists()


def test_explicit_paid_gate_writes_redacted_receipt_with_injected_provider(tmp_path) -> None:
    calls = []

    def factory(api_key):
        calls.append(api_key)
        return FakeProvider()

    receipt_path = tmp_path / "receipt.json"
    key = "sk-" + "proj-test-only-not-real"
    code = main(
        ["--execute-paid-qualification", "--receipt", str(receipt_path)],
        environ={"BIZPULSE_DEPLOY_OPENAI_API_KEY": key},
        client_factory=factory,
    )

    assert code == 0
    assert calls == [key]
    assert key not in receipt_path.read_text()


def test_generic_runtime_key_name_cannot_open_the_paid_deploy_gate(tmp_path) -> None:
    receipt_path = tmp_path / "receipt.json"
    calls = []

    assert main(
        ["--execute-paid-qualification", "--receipt", str(receipt_path)],
        environ={"OPENAI_API_KEY": "test-only-runtime-key"},
        client_factory=lambda key: calls.append(key),
    ) == 2
    assert calls == []
    assert not receipt_path.exists()
