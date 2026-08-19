"""Managed-identity OpenAI secret provider with a bounded in-memory cache."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from threading import RLock
from time import monotonic
from typing import Protocol

from azure.core.credentials import TokenCredential
from azure.core.pipeline.transport import RequestsTransport
from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient
from openai import OpenAI

from src.config import APPROVED_OPENAI_BASE_URL

KEY_VAULT_TIMEOUT_SECONDS = 5.0
OPENAI_PROVIDER_TIMEOUT_SECONDS = 30.0


class OpenAIClientProtocol(Protocol):
    def with_options(self, **kwargs): ...


class OpenAIClientProvider(Protocol):
    @contextmanager
    def acquire(self, version: str) -> Iterator[OpenAIClientProtocol]: ...

    def close(self) -> None: ...


class OpenAISecretUnavailable(RuntimeError):
    """A value-free signal for every Key Vault/provider construction failure."""


@dataclass(frozen=True, slots=True, repr=False)
class SecretVersion:
    """One exact Key Vault value/version pair held only in server memory."""

    value: str
    version: str


class OpenAISecretManager:
    """Read or write only the configured canonical OpenAI secret."""

    def __init__(self, *, secret_name: str, secret_client: SecretClient) -> None:
        self._secret_name = secret_name
        self._secret_client = secret_client

    def __repr__(self) -> str:
        return "OpenAISecretManager()"

    def read(self, version: str) -> SecretVersion:
        if not isinstance(version, str) or not version.strip():
            raise OpenAISecretUnavailable("openai_secret_unavailable")
        secret = None
        value = ""
        read_failed = False
        try:
            secret = self._secret_client.get_secret(
                self._secret_name,
                version=version,
            )
            value = secret.value
            returned_version = secret.properties.version
        except Exception:
            value = ""
            secret = None
            read_failed = True
        if read_failed:
            raise OpenAISecretUnavailable("openai_secret_unavailable") from None
        if (
            not isinstance(value, str)
            or not value.strip()
            or not isinstance(returned_version, str)
            or returned_version != version
        ):
            value = ""
            secret = None
            raise OpenAISecretUnavailable("openai_secret_unavailable")
        return SecretVersion(value=value, version=returned_version)

    def write(self, value: str) -> SecretVersion:
        if not isinstance(value, str) or not value.strip():
            raise OpenAISecretUnavailable("openai_secret_unavailable")
        secret = None
        try:
            secret = self._secret_client.set_secret(self._secret_name, value)
            returned_version = secret.properties.version
            if not isinstance(returned_version, str) or not returned_version:
                value = ""
                secret = None
            else:
                return SecretVersion(value=value, version=returned_version)
        except Exception:
            value = ""
            secret = None
        finally:
            value = ""
        raise OpenAISecretUnavailable("openai_secret_unavailable") from None


class FixedOpenAIClientProvider:
    """Adapt an externally owned fake or fixed client for tests."""

    def __init__(self, client: OpenAIClientProtocol) -> None:
        self._client = client

    @contextmanager
    def acquire(
        self,
        version: str | None = None,
    ) -> Iterator[OpenAIClientProtocol]:
        del version
        yield self._client

    def close(self) -> None:
        return None


class AzureOpenAIClientProvider:
    """Resolve one task-owned Key Vault secret immediately before provider use."""

    def __init__(
        self,
        *,
        vault_url: str,
        secret_name: str,
        managed_identity_client_id: str,
        cache_ttl_seconds: float = 60.0,
        credential: TokenCredential | None = None,
        secret_client: SecretClient | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._secret_name = secret_name
        self._cache_ttl_seconds = cache_ttl_seconds
        self._clock = clock
        self._lock = RLock()
        self._closed = False
        self._cached_values: dict[str, tuple[str, float]] = {}
        self._credential = credential or ManagedIdentityCredential(
            client_id=managed_identity_client_id,
            logging_enable=False,
        )
        if secret_client is None:
            transport = RequestsTransport(
                connection_timeout=KEY_VAULT_TIMEOUT_SECONDS,
                read_timeout=KEY_VAULT_TIMEOUT_SECONDS,
                use_env_settings=False,
            )
            secret_client = SecretClient(
                vault_url,
                self._credential,
                logging_enable=False,
                retry_total=0,
                retry_connect=0,
                retry_read=0,
                retry_status=0,
                transport=transport,
            )
        self._secret_client = secret_client
        self._secret_manager = OpenAISecretManager(
            secret_name=secret_name,
            secret_client=secret_client,
        )

    def __repr__(self) -> str:
        return f"AzureOpenAIClientProvider(closed={self._closed})"

    @property
    def secret_manager(self) -> OpenAISecretManager:
        """Return the exact manager shared by runtime reads and key rotation."""

        return self._secret_manager

    @contextmanager
    def acquire(self, version: str) -> Iterator[OpenAIClientProtocol]:
        api_key = self._secret_value(version)
        client = None
        try:
            try:
                client = OpenAI(
                    api_key=api_key,
                    base_url=APPROVED_OPENAI_BASE_URL,
                    max_retries=0,
                    timeout=OPENAI_PROVIDER_TIMEOUT_SECONDS,
                )
            except Exception:
                raise OpenAISecretUnavailable("openai_secret_unavailable") from None
            yield client
        finally:
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
            api_key = ""

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            while self._cached_values:
                _, cached = self._cached_values.popitem()
                cached_value, _ = cached
                del cached_value
        for resource in (self._secret_client, self._credential):
            close = getattr(resource, "close", None)
            if close is None:
                continue
            try:
                close()
            except Exception:
                pass

    def _secret_value(self, version: str) -> str:
        with self._lock:
            if self._closed:
                raise OpenAISecretUnavailable("openai_secret_unavailable")
            now = self._clock()
            expired_versions = [
                cached_version
                for cached_version, (_, expires_at) in self._cached_values.items()
                if now >= expires_at
            ]
            for expired_version in expired_versions:
                expired_value, _ = self._cached_values.pop(expired_version)
                del expired_value
            cached = self._cached_values.get(version)
            if cached is not None:
                return cached[0]
            secret = self._secret_manager.read(version)
            self._cached_values[version] = (
                secret.value,
                now + self._cache_ttl_seconds,
            )
            while len(self._cached_values) > 2:
                oldest_version = next(iter(self._cached_values))
                evicted, _ = self._cached_values.pop(oldest_version)
                del evicted
            return secret.value
