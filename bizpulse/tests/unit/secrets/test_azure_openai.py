from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import importlib
import importlib.util
from threading import Event

import pytest
from azure.keyvault.secrets import KeyVaultSecret, SecretProperties


VAULT_URL = "https://bizpulse-ai-test.vault.azure.net"
SECRET_NAME = "openai-api-key"
CLIENT_ID = "00000000-0000-4000-8000-000000000001"
SENTINEL = "sentinel-not-a-real-openai-key"
SECOND_SENTINEL = "sentinel-second-not-real-key"
THIRD_SENTINEL = "sentinel-third-not-real-key"
VERSION_A = "00000000000000000000000000000001"
VERSION_B = "00000000000000000000000000000002"
VERSION_C = "00000000000000000000000000000003"


def _module():
    return importlib.import_module("src.secrets.azure_openai")


def _traceback_locals(error: BaseException, function_name: str) -> dict[str, object]:
    traceback = error.__traceback__
    while traceback is not None:
        if traceback.tb_frame.f_code.co_name == function_name:
            return dict(traceback.tb_frame.f_locals)
        traceback = traceback.tb_next
    raise AssertionError("expected traceback frame was absent")


def _exception_chain_retains_sentinel(error: BaseException) -> bool:
    pending = [error]
    seen: set[int] = set()
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        traceback = current.__traceback__
        while traceback is not None:
            for local_value in traceback.tb_frame.f_locals.values():
                if isinstance(local_value, str) and local_value == SENTINEL:
                    return True
                if isinstance(local_value, PoisonedSecret):
                    return True
            traceback = traceback.tb_next
        for linked in (current.__cause__, current.__context__):
            if linked is not None:
                pending.append(linked)
    return False


def _secret(
    value: str | None,
    version: str = VERSION_A,
) -> KeyVaultSecret:
    return KeyVaultSecret(
        SecretProperties(vault_id=f"{VAULT_URL}/secrets/{SECRET_NAME}/{version}"),
        value,
    )


class RecordingSecretClient:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.get_calls: list[tuple[str, str | None]] = []
        self.set_calls: list[tuple[str, str]] = []
        self.close_calls = 0

    def get_secret(self, name: str, version: str | None = None) -> KeyVaultSecret:
        self.get_calls.append((name, version))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, KeyVaultSecret)
        return response

    def set_secret(self, name: str, value: str) -> KeyVaultSecret:
        self.set_calls.append((name, value))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        assert isinstance(response, KeyVaultSecret)
        return response

    def close(self) -> None:
        self.close_calls += 1


class RecordingCredential:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class RecordingOpenAIClient:
    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class PoisonedSecret:
    value = SENTINEL

    @property
    def properties(self):
        raise RuntimeError("malformed secret metadata")


def test_secret_provider_module_exists() -> None:
    assert importlib.util.find_spec("src.secrets.azure_openai") is not None


def test_fixed_provider_yields_the_injected_client_without_closing_it() -> None:
    module = _module()
    fixed_provider = getattr(module, "FixedOpenAIClientProvider")
    client = RecordingOpenAIClient()
    provider = fixed_provider(client)

    with provider.acquire() as acquired:
        assert acquired is client

    provider.close()
    assert client.close_calls == 0


def test_secret_manager_reads_only_the_requested_exact_version() -> None:
    module = _module()
    manager_type = getattr(module, "OpenAISecretManager")
    secret_client = RecordingSecretClient([_secret(SENTINEL, VERSION_A)])
    manager = manager_type(secret_name=SECRET_NAME, secret_client=secret_client)

    result = manager.read(VERSION_A)

    assert result.value == SENTINEL
    assert result.version == VERSION_A
    assert secret_client.get_calls == [(SECRET_NAME, VERSION_A)]
    assert SENTINEL not in repr(result)


def test_secret_manager_rejects_a_mismatched_returned_version_without_value_leak() -> (
    None
):
    module = _module()
    manager_type = getattr(module, "OpenAISecretManager")
    unavailable_type = getattr(module, "OpenAISecretUnavailable")
    secret_client = RecordingSecretClient([_secret(SENTINEL, VERSION_B)])
    manager = manager_type(secret_name=SECRET_NAME, secret_client=secret_client)

    with pytest.raises(unavailable_type) as captured:
        manager.read(VERSION_A)

    assert str(captured.value) == "openai_secret_unavailable"
    assert captured.value.__cause__ is None
    assert SENTINEL not in repr(captured.value)


def test_malformed_read_drops_secret_value_and_wrapper_from_traceback() -> None:
    module = _module()
    manager_type = getattr(module, "OpenAISecretManager")
    unavailable_type = getattr(module, "OpenAISecretUnavailable")

    class MalformedReadClient:
        def get_secret(self, name: str, version: str) -> PoisonedSecret:
            del name, version
            return PoisonedSecret()

    manager = manager_type(
        secret_name=SECRET_NAME,
        secret_client=MalformedReadClient(),
    )

    with pytest.raises(unavailable_type) as captured:
        manager.read(VERSION_A)

    frame_locals = _traceback_locals(captured.value, "read")
    value_cleared = frame_locals.get("value") == ""
    wrapper_dropped = frame_locals.get("secret") is None
    chain_cleared = not _exception_chain_retains_sentinel(captured.value)
    assert value_cleared
    assert wrapper_dropped
    assert chain_cleared


def test_secret_manager_writes_only_the_canonical_secret_and_returns_its_version() -> (
    None
):
    module = _module()
    manager_type = getattr(module, "OpenAISecretManager")
    secret_client = RecordingSecretClient([_secret(SENTINEL, VERSION_B)])
    manager = manager_type(secret_name=SECRET_NAME, secret_client=secret_client)

    result = manager.write(SENTINEL)

    assert result.value == SENTINEL
    assert result.version == VERSION_B
    assert secret_client.set_calls == [(SECRET_NAME, SENTINEL)]
    assert SENTINEL not in repr(result)


@pytest.mark.parametrize(
    "response",
    [
        RuntimeError(f"write failed {SENTINEL}"),
        _secret(SENTINEL, ""),
    ],
)
def test_secret_manager_write_failures_are_value_free(response: object) -> None:
    module = _module()
    manager_type = getattr(module, "OpenAISecretManager")
    unavailable_type = getattr(module, "OpenAISecretUnavailable")
    secret_client = RecordingSecretClient([response])
    manager = manager_type(secret_name=SECRET_NAME, secret_client=secret_client)

    with pytest.raises(unavailable_type) as captured:
        manager.write(SENTINEL)

    assert str(captured.value) == "openai_secret_unavailable"
    assert captured.value.__cause__ is None
    assert SENTINEL not in repr(captured.value)
    assert secret_client.set_calls == [(SECRET_NAME, SENTINEL)]


def test_failed_write_drops_secret_value_and_wrapper_from_traceback() -> None:
    module = _module()
    manager_type = getattr(module, "OpenAISecretManager")
    unavailable_type = getattr(module, "OpenAISecretUnavailable")

    class FailedWriteClient:
        def set_secret(self, name: str, value: str) -> None:
            del name
            raise RuntimeError("key vault write failed")

    manager = manager_type(
        secret_name=SECRET_NAME,
        secret_client=FailedWriteClient(),
    )

    with pytest.raises(unavailable_type) as captured:
        manager.write(SENTINEL)

    frame_locals = _traceback_locals(captured.value, "write")
    value_cleared = frame_locals.get("value") == ""
    wrapper_dropped = frame_locals.get("secret") is None
    chain_cleared = not _exception_chain_retains_sentinel(captured.value)
    assert value_cleared
    assert wrapper_dropped
    assert chain_cleared


def test_azure_provider_is_lazy_and_constructs_bounded_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    credential = RecordingCredential()
    secret_client = RecordingSecretClient([_secret(SENTINEL)])
    transport = object()
    calls: dict[str, list[object]] = {
        "credential": [],
        "transport": [],
        "secret_client": [],
        "openai": [],
    }
    created_clients: list[RecordingOpenAIClient] = []

    def credential_factory(**kwargs):
        calls["credential"].append(kwargs)
        return credential

    def transport_factory(**kwargs):
        calls["transport"].append(kwargs)
        return transport

    def secret_client_factory(vault_url, supplied_credential, **kwargs):
        calls["secret_client"].append((vault_url, supplied_credential, kwargs))
        return secret_client

    def openai_factory(**kwargs):
        calls["openai"].append(kwargs)
        client = RecordingOpenAIClient()
        created_clients.append(client)
        return client

    monkeypatch.setattr(module, "ManagedIdentityCredential", credential_factory)
    monkeypatch.setattr(module, "RequestsTransport", transport_factory)
    monkeypatch.setattr(module, "SecretClient", secret_client_factory)
    monkeypatch.setattr(module, "OpenAI", openai_factory)

    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
    )

    assert secret_client.get_calls == []
    assert calls["credential"] == [{"client_id": CLIENT_ID, "logging_enable": False}]
    assert calls["transport"] == [
        {
            "connection_timeout": 5.0,
            "read_timeout": 5.0,
            "use_env_settings": False,
        }
    ]
    assert calls["secret_client"] == [
        (
            VAULT_URL,
            credential,
            {
                "logging_enable": False,
                "retry_total": 0,
                "retry_connect": 0,
                "retry_read": 0,
                "retry_status": 0,
                "transport": transport,
            },
        )
    ]

    with provider.acquire(VERSION_A) as acquired:
        assert acquired is created_clients[0]

    assert secret_client.get_calls == [(SECRET_NAME, VERSION_A)]
    assert calls["openai"] == [
        {
            "api_key": SENTINEL,
            "base_url": "https://api.openai.com/v1",
            "max_retries": 0,
            "timeout": 30.0,
        }
    ]
    assert created_clients[0].close_calls == 1
    rendered = repr(provider)
    assert rendered == "AzureOpenAIClientProvider(closed=False)"
    assert SENTINEL not in rendered
    assert "bizpulse-ai-test" not in rendered
    assert CLIENT_ID not in rendered


def test_secret_is_cached_for_less_than_sixty_seconds_and_refreshed_at_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    now = [10.0]
    secret_client = RecordingSecretClient(
        [_secret(SENTINEL, VERSION_A), _secret(SECOND_SENTINEL, VERSION_A)]
    )
    observed_keys: list[str] = []

    def openai_factory(**kwargs):
        observed_keys.append(kwargs["api_key"])
        return RecordingOpenAIClient()

    monkeypatch.setattr(module, "OpenAI", openai_factory)
    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        credential=RecordingCredential(),
        secret_client=secret_client,
        clock=lambda: now[0],
    )

    with provider.acquire(VERSION_A):
        pass
    now[0] = 69.999
    with provider.acquire(VERSION_A):
        pass
    now[0] = 70.0
    with provider.acquire(VERSION_A):
        pass

    assert secret_client.get_calls == [
        (SECRET_NAME, VERSION_A),
        (SECRET_NAME, VERSION_A),
    ]
    assert observed_keys == [
        SENTINEL,
        SENTINEL,
        SECOND_SENTINEL,
    ]


def test_provider_caches_by_exact_secret_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    secret_client = RecordingSecretClient(
        [_secret(SENTINEL, VERSION_A), _secret(SECOND_SENTINEL, VERSION_B)]
    )
    monkeypatch.setattr(
        module,
        "OpenAI",
        lambda **kwargs: RecordingOpenAIClient(),
    )
    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        credential=RecordingCredential(),
        secret_client=secret_client,
    )

    with provider.acquire(VERSION_A):
        pass
    with provider.acquire(VERSION_B):
        pass
    with provider.acquire(VERSION_A):
        pass

    assert secret_client.get_calls == [
        (SECRET_NAME, VERSION_A),
        (SECRET_NAME, VERSION_B),
    ]


def test_provider_cache_retains_active_and_immediately_prior_fetched_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    secret_client = RecordingSecretClient(
        [
            _secret(SENTINEL, VERSION_A),
            _secret(SECOND_SENTINEL, VERSION_B),
            _secret(THIRD_SENTINEL, VERSION_C),
            _secret(SECOND_SENTINEL, VERSION_B),
        ]
    )
    monkeypatch.setattr(
        module,
        "OpenAI",
        lambda **kwargs: RecordingOpenAIClient(),
    )
    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        credential=RecordingCredential(),
        secret_client=secret_client,
    )

    for version in (VERSION_A, VERSION_B, VERSION_A, VERSION_C, VERSION_B):
        with provider.acquire(version):
            pass

    assert secret_client.get_calls == [
        (SECRET_NAME, VERSION_A),
        (SECRET_NAME, VERSION_B),
        (SECRET_NAME, VERSION_C),
    ]


def test_provider_sweeps_all_expired_versions_before_a_cache_hit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    now = [0.0]
    secret_client = RecordingSecretClient(
        [_secret(SENTINEL, VERSION_A), _secret(SECOND_SENTINEL, VERSION_B)]
    )
    monkeypatch.setattr(
        module,
        "OpenAI",
        lambda **kwargs: RecordingOpenAIClient(),
    )
    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        credential=RecordingCredential(),
        secret_client=secret_client,
        clock=lambda: now[0],
    )

    with provider.acquire(VERSION_A):
        pass
    now[0] = 1.0
    with provider.acquire(VERSION_B):
        pass
    now[0] = 60.5
    with provider.acquire(VERSION_B):
        pass

    assert tuple(provider._cached_values) == (VERSION_B,)
    assert secret_client.get_calls == [
        (SECRET_NAME, VERSION_A),
        (SECRET_NAME, VERSION_B),
    ]


def test_expired_refresh_failure_has_no_stale_secret_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    unavailable_type = getattr(module, "OpenAISecretUnavailable")
    now = [1.0]
    secret_client = RecordingSecretClient(
        [
            _secret(SENTINEL, VERSION_A),
            RuntimeError(f"do-not-echo {SENTINEL}"),
        ]
    )
    observed_keys: list[str] = []

    def openai_factory(**kwargs):
        observed_keys.append(kwargs["api_key"])
        return RecordingOpenAIClient()

    monkeypatch.setattr(module, "OpenAI", openai_factory)
    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        credential=RecordingCredential(),
        secret_client=secret_client,
        clock=lambda: now[0],
    )
    with provider.acquire(VERSION_A):
        pass

    now[0] = 61.0
    with pytest.raises(unavailable_type) as captured:
        with provider.acquire(VERSION_A):
            pass

    assert str(captured.value) == "openai_secret_unavailable"
    assert captured.value.__cause__ is None
    assert SENTINEL not in repr(captured.value)
    assert observed_keys == [SENTINEL]


@pytest.mark.parametrize("value", [None, "", "   "])
def test_missing_or_blank_secret_fails_closed_without_openai_client(
    monkeypatch: pytest.MonkeyPatch,
    value: str | None,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    unavailable_type = getattr(module, "OpenAISecretUnavailable")
    openai_calls = 0

    def openai_factory(**kwargs):
        del kwargs
        nonlocal openai_calls
        openai_calls += 1
        return RecordingOpenAIClient()

    monkeypatch.setattr(module, "OpenAI", openai_factory)
    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        credential=RecordingCredential(),
        secret_client=RecordingSecretClient([_secret(value, VERSION_A)]),
    )

    with pytest.raises(unavailable_type, match="^openai_secret_unavailable$"):
        with provider.acquire(VERSION_A):
            pass

    assert openai_calls == 0


def test_close_is_idempotent_clears_cache_and_closes_azure_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    unavailable_type = getattr(module, "OpenAISecretUnavailable")
    credential = RecordingCredential()
    secret_client = RecordingSecretClient([_secret(SENTINEL, VERSION_A)])
    monkeypatch.setattr(
        module,
        "OpenAI",
        lambda **kwargs: RecordingOpenAIClient(),
    )
    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        credential=credential,
        secret_client=secret_client,
    )
    with provider.acquire(VERSION_A):
        pass

    provider.close()
    provider.close()

    assert credential.close_calls == 1
    assert secret_client.close_calls == 1
    assert provider._cached_values == {}
    assert repr(provider) == "AzureOpenAIClientProvider(closed=True)"
    with pytest.raises(unavailable_type, match="^openai_secret_unavailable$"):
        with provider.acquire(VERSION_A):
            pass


def test_concurrent_acquisition_fetches_one_secret_per_cache_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module()
    provider_type = getattr(module, "AzureOpenAIClientProvider")
    entered = Event()
    release = Event()

    class BlockingSecretClient(RecordingSecretClient):
        def get_secret(self, name, version=None):
            entered.set()
            assert release.wait(timeout=2)
            return super().get_secret(name, version)

    secret_client = BlockingSecretClient([_secret(SENTINEL, VERSION_A)])
    monkeypatch.setattr(
        module,
        "OpenAI",
        lambda **kwargs: RecordingOpenAIClient(),
    )
    provider = provider_type(
        vault_url=VAULT_URL,
        secret_name=SECRET_NAME,
        managed_identity_client_id=CLIENT_ID,
        credential=RecordingCredential(),
        secret_client=secret_client,
    )

    def acquire_once() -> None:
        with provider.acquire(VERSION_A):
            pass

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(acquire_once)
        assert entered.wait(timeout=2)
        second = pool.submit(acquire_once)
        release.set()
        first.result(timeout=2)
        second.result(timeout=2)

    assert secret_client.get_calls == [(SECRET_NAME, VERSION_A)]
