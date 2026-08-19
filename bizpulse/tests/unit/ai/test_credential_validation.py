from __future__ import annotations

import importlib

import httpx
import pytest
from openai import APIConnectionError, APITimeoutError, AuthenticationError

from src.config import (
    APPROVED_OPENAI_BASE_URL,
    APPROVED_OPENAI_MODEL,
    APPROVED_REASONING_EFFORT,
)


CANDIDATE = "candidate-not-a-real-openai-key"
OUTPUT_SENTINEL = "provider-output-must-not-be-retained"


def _module():
    return importlib.import_module("src.ai.credential_validation")


class FakeResponse:
    def __init__(
        self,
        *,
        status: str = "completed",
        request_id: str | None = "req_test_123",
        output_text: str = OUTPUT_SENTINEL,
    ) -> None:
        self.status = status
        self._request_id = request_id
        self.output_text = output_text


class PoisonedResponse:
    @property
    def status(self) -> str:
        raise RuntimeError(f"malformed {CANDIDATE} {OUTPUT_SENTINEL}")


class FakeResponses:
    def __init__(self, outcome: object) -> None:
        self._outcome = outcome
        self.request: dict[str, object] | None = None

    def create(self, **kwargs):
        self.request = kwargs
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


class FakeOpenAIClient:
    def __init__(self, outcome: object) -> None:
        self.responses = FakeResponses(outcome)
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class FakeOpenAIFactory:
    def __init__(self, outcome: object | None = None) -> None:
        self.outcome = outcome or FakeResponse()
        self.options: dict[str, object] | None = None
        self.client: FakeOpenAIClient | None = None

    @property
    def request(self) -> dict[str, object]:
        assert self.client is not None
        assert self.client.responses.request is not None
        return self.client.responses.request

    def __call__(self, **kwargs) -> FakeOpenAIClient:
        self.options = kwargs
        self.client = FakeOpenAIClient(self.outcome)
        return self.client


def _authentication_error() -> AuthenticationError:
    request = httpx.Request("POST", APPROVED_OPENAI_BASE_URL)
    response = httpx.Response(401, request=request)
    return AuthenticationError(
        f"rejected {CANDIDATE}",
        response=response,
        body={"error": OUTPUT_SENTINEL},
    )


def test_validator_uses_fixed_model_store_false_and_zero_retries() -> None:
    module = _module()
    validator_type = getattr(module, "OpenAICredentialValidator")
    fake_openai_factory = FakeOpenAIFactory()

    result = validator_type(client_factory=fake_openai_factory).validate(CANDIDATE)

    assert result.status == "verified"
    assert result.request_id == "req_test_123"
    assert fake_openai_factory.options == {
        "api_key": CANDIDATE,
        "base_url": APPROVED_OPENAI_BASE_URL,
        "max_retries": 0,
        "timeout": 30.0,
    }
    assert fake_openai_factory.request == {
        "model": APPROVED_OPENAI_MODEL,
        "reasoning": {"effort": APPROVED_REASONING_EFFORT},
        "input": "Return exactly: ready",
        "max_output_tokens": 32,
        "store": False,
    }
    assert fake_openai_factory.client is not None
    assert fake_openai_factory.client.close_calls == 1


def test_validator_rejects_authentication_failure_without_secret_details() -> None:
    module = _module()
    validator_type = getattr(module, "OpenAICredentialValidator")
    factory = FakeOpenAIFactory(_authentication_error())

    result = validator_type(client_factory=factory).validate(CANDIDATE)

    assert result.status == "rejected"
    assert result.request_id is None
    assert CANDIDATE not in repr(result)
    assert OUTPUT_SENTINEL not in repr(result)
    assert factory.client is not None
    assert factory.client.close_calls == 1


@pytest.mark.parametrize(
    "error",
    [
        APIConnectionError(
            message=f"connection {CANDIDATE}",
            request=httpx.Request("POST", APPROVED_OPENAI_BASE_URL),
        ),
        APITimeoutError(httpx.Request("POST", APPROVED_OPENAI_BASE_URL)),
    ],
)
def test_validator_returns_unknown_for_non_retryable_transport_failure(
    error: Exception,
) -> None:
    module = _module()
    validator_type = getattr(module, "OpenAICredentialValidator")
    factory = FakeOpenAIFactory(error)

    result = validator_type(client_factory=factory).validate(CANDIDATE)

    assert result.status == "unknown"
    assert result.request_id is None
    assert CANDIDATE not in repr(result)
    assert factory.client is not None
    assert factory.client.close_calls == 1


def test_validator_rejects_incomplete_response_without_retaining_output() -> None:
    module = _module()
    validator_type = getattr(module, "OpenAICredentialValidator")
    factory = FakeOpenAIFactory(FakeResponse(status="incomplete"))

    result = validator_type(client_factory=factory).validate(CANDIDATE)

    assert result.status == "rejected"
    assert result.request_id is None
    assert CANDIDATE not in repr(result)
    assert OUTPUT_SENTINEL not in repr(result)


def test_validator_returns_unknown_when_response_metadata_is_malformed() -> None:
    module = _module()
    validator_type = getattr(module, "OpenAICredentialValidator")
    factory = FakeOpenAIFactory(PoisonedResponse())

    result = validator_type(client_factory=factory).validate(CANDIDATE)

    assert result.status == "unknown"
    assert result.request_id is None
    assert CANDIDATE not in repr(result)
    assert OUTPUT_SENTINEL not in repr(result)


def test_validator_rejects_blank_candidate_without_constructing_client() -> None:
    module = _module()
    validator_type = getattr(module, "OpenAICredentialValidator")
    factory = FakeOpenAIFactory()

    result = validator_type(client_factory=factory).validate("   ")

    assert result.status == "rejected"
    assert result.request_id is None
    assert factory.options is None
