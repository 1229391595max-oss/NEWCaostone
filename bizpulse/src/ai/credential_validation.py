"""Bounded, non-retried validation for candidate OpenAI credentials."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
)

from src.config import (
    APPROVED_OPENAI_BASE_URL,
    APPROVED_OPENAI_MODEL,
    APPROVED_REASONING_EFFORT,
)

VALIDATION_TIMEOUT_SECONDS = 30.0
VALIDATION_MAX_OUTPUT_TOKENS = 32
VALIDATION_PROMPT = "Return exactly: ready"


@dataclass(frozen=True, slots=True)
class CredentialValidationResult:
    """Secret-free validation state suitable for service-layer decisions."""

    status: Literal["verified", "rejected", "unknown"]
    request_id: str | None


class OpenAICredentialValidator:
    """Validate one candidate with the pinned model and no SDK retry."""

    def __init__(self, *, client_factory: Callable[..., object] = OpenAI) -> None:
        self._client_factory = client_factory

    def validate(self, candidate: str) -> CredentialValidationResult:
        if not isinstance(candidate, str) or not candidate.strip():
            return CredentialValidationResult("rejected", None)

        client = None
        response = None
        try:
            client = self._client_factory(
                api_key=candidate,
                base_url=APPROVED_OPENAI_BASE_URL,
                max_retries=0,
                timeout=VALIDATION_TIMEOUT_SECONDS,
            )
            response = client.responses.create(
                model=APPROVED_OPENAI_MODEL,
                reasoning={"effort": APPROVED_REASONING_EFFORT},
                input=VALIDATION_PROMPT,
                max_output_tokens=VALIDATION_MAX_OUTPUT_TOKENS,
                store=False,
            )
        except AuthenticationError:
            return CredentialValidationResult("rejected", None)
        except (APIConnectionError, APITimeoutError):
            return CredentialValidationResult("unknown", None)
        except Exception:
            return CredentialValidationResult("unknown", None)
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            candidate = ""

        try:
            status = getattr(response, "status", None)
            request_id = getattr(response, "_request_id", None)
        except Exception:
            return CredentialValidationResult("unknown", None)
        if status != "completed":
            return CredentialValidationResult("rejected", None)
        if not isinstance(request_id, str):
            request_id = None
        return CredentialValidationResult("verified", request_id)
