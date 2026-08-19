"""Fixed OpenAI Responses adapter with no tools and structured outputs only."""

from __future__ import annotations

from openai import APIConnectionError, APITimeoutError, AuthenticationError

from src.ai.contracts import (
    ModelExplanation,
    PlanningDecision,
    ProviderResult,
    ToolResult,
)
from src.ai.prompts import EXPLAIN_SYSTEM_PROMPT, PLAN_SYSTEM_PROMPT
from src.config import (
    APPROVED_CHAT_OUTPUT_TOKEN_LIMIT,
    APPROVED_OPENAI_MODEL,
    APPROVED_REASONING_EFFORT,
)
from src.secrets.azure_openai import FixedOpenAIClientProvider, OpenAISecretUnavailable

MAX_OUTPUT_TOKENS = APPROVED_CHAT_OUTPUT_TOKEN_LIMIT
PROVIDER_TIMEOUT_SECONDS = 30.0


class ProviderUnavailable(RuntimeError):
    pass


class ProviderOutcomeUnknown(RuntimeError):
    pass


class OpenAIGateway:
    """Use an injected SDK client; construction alone never reads an API key."""

    model = APPROVED_OPENAI_MODEL
    reasoning_effort = APPROVED_REASONING_EFFORT

    def __init__(self, client_provider) -> None:
        self._client_provider = (
            client_provider
            if hasattr(client_provider, "acquire")
            else FixedOpenAIClientProvider(client_provider)
        )

    def plan(
        self,
        question: str,
        capability_catalog: dict[str, object],
        history: tuple[str, ...] = (),
        *,
        credential_version: str,
    ):
        response = self._parse(
            stage="planning",
            prompt=PLAN_SYSTEM_PROMPT,
            payload={
                "question": question,
                "safe_history": list(history[-4:]),
                "capabilities": capability_catalog,
            },
            schema=PlanningDecision,
            credential_version=credential_version,
        )
        return response

    def explain(
        self,
        question: str,
        result: ToolResult,
        history: tuple[str, ...] = (),
        *,
        credential_version: str,
    ):
        response = self._parse(
            stage="answering",
            prompt=EXPLAIN_SYSTEM_PROMPT,
            payload={
                "question": question,
                "safe_history": list(history[-4:]),
                "tool_result": result.model_dump(mode="json"),
            },
            schema=ModelExplanation,
            credential_version=credential_version,
        )
        return response

    def _parse(
        self,
        *,
        stage: str,
        prompt: str,
        payload: dict[str, object],
        schema,
        credential_version: str,
    ):
        if not isinstance(credential_version, str) or not credential_version.strip():
            raise ProviderUnavailable("credential_version_invalid")
        try:
            with self._client_provider.acquire(credential_version) as acquired_client:
                client = acquired_client.with_options(
                    max_retries=0,
                    timeout=PROVIDER_TIMEOUT_SECONDS,
                )
                response = client.responses.parse(
                    model=self.model,
                    reasoning={"effort": self.reasoning_effort},
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    tools=[],
                    input=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": str(payload)},
                    ],
                    text_format=schema,
                )
        except ProviderOutcomeUnknown:
            raise
        except OpenAISecretUnavailable as error:
            raise ProviderUnavailable("key_vault_secret_unavailable") from error
        except AuthenticationError as error:
            raise ProviderUnavailable("provider_auth_rejected") from error
        except (APIConnectionError, APITimeoutError) as error:
            raise ProviderOutcomeUnknown(f"provider_{stage}_outcome_unknown") from error
        except Exception as error:
            raise ProviderUnavailable(f"provider_{stage}_failed") from error
        if getattr(response, "status", None) != "completed":
            raise ProviderUnavailable(f"provider_{stage}_incomplete")
        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, schema):
            raise ProviderUnavailable(f"provider_{stage}_invalid_output")
        usage = getattr(response, "usage", None)
        try:
            provider_result = ProviderResult(
                parsed,
                getattr(usage, "input_tokens"),
                getattr(usage, "output_tokens"),
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise ProviderUnavailable(f"provider_{stage}_usage_invalid") from error
        return provider_result
