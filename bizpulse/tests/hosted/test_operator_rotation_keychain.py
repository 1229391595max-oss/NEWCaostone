from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher

from scripts.operator_rotation_keychain import (
    CURRENT_HASH,
    CURRENT_PASSWORD,
    PENDING_HASH,
    PENDING_PASSWORD,
    KeychainPromotionError,
    OperatorRotationKeychain,
    PendingCredentialError,
)


NOW = datetime(2026, 8, 17, 16, 0, tzinfo=UTC)


class InMemoryKeychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}
        self.created_at: dict[tuple[str, str], datetime] = {}
        self.modified_at: dict[tuple[str, str], datetime] = {}
        self.read_calls = 0
        self.fail_next_upsert_for: tuple[str, str] | None = None

    def read_secret(self, service: str, account: str) -> bytes | None:
        self.read_calls += 1
        return self.values.get((service, account))

    def upsert_secret(self, service: str, account: str, value: bytes) -> None:
        if self.fail_next_upsert_for == (service, account):
            self.fail_next_upsert_for = None
            raise RuntimeError("injected_keychain_write_failure")
        key = (service, account)
        self.values[key] = bytes(value)
        self.created_at.setdefault(key, NOW)
        self.modified_at[key] = NOW

    def delete_secret(self, service: str, account: str) -> None:
        key = (service, account)
        self.values.pop(key, None)
        self.created_at.pop(key, None)
        self.modified_at.pop(key, None)

    def metadata(self, service: str, account: str):
        from scripts.operator_rotation_keychain import KeychainItemMetadata

        key = (service, account)
        if key not in self.values:
            return None
        return KeychainItemMetadata(
            created_at=self.created_at[key],
            modified_at=self.modified_at[key],
        )


def _controller(backend: InMemoryKeychain) -> OperatorRotationKeychain:
    return OperatorRotationKeychain(
        backend=backend,
        password_hasher=PasswordHasher(time_cost=1, memory_cost=1_024, parallelism=1),
    )


def _seed_current(backend: InMemoryKeychain) -> tuple[str, str]:
    password = "current-operator-password"
    password_hash = PasswordHasher(
        time_cost=1,
        memory_cost=1_024,
        parallelism=1,
    ).hash(password)
    backend.upsert_secret(*CURRENT_PASSWORD, password.encode())
    backend.upsert_secret(*CURRENT_HASH, password_hash.encode())
    return password, password_hash


def test_prepare_pending_keeps_current_pair_and_stores_matching_argon2id_pair() -> None:
    backend = InMemoryKeychain()
    current_password, current_hash = _seed_current(backend)
    controller = _controller(backend)

    controller.prepare_pending("replacement-operator-password")

    assert backend.values[CURRENT_PASSWORD] == current_password.encode()
    assert backend.values[CURRENT_HASH] == current_hash.encode()
    pending_password = backend.values[PENDING_PASSWORD].decode()
    pending_hash = backend.values[PENDING_HASH].decode()
    assert pending_password == "replacement-operator-password"
    assert PasswordHasher(
        time_cost=1,
        memory_cost=1_024,
        parallelism=1,
    ).verify(pending_hash, pending_password)


def test_status_reads_only_metadata_and_never_fetches_secret_values() -> None:
    backend = InMemoryKeychain()
    _seed_current(backend)
    controller = _controller(backend)

    status = controller.status()

    assert backend.read_calls == 0
    assert status.current_pair_present is True
    assert status.pending_pair_present is False
    assert "current-operator-password" not in repr(status)


def test_promote_pending_copies_verified_pair_and_clears_pending_entries() -> None:
    backend = InMemoryKeychain()
    _seed_current(backend)
    controller = _controller(backend)
    controller.prepare_pending("replacement-operator-password")

    controller.promote_pending(verified_rotation_id="a" * 64)

    assert backend.values[CURRENT_PASSWORD] == b"replacement-operator-password"
    assert PENDING_PASSWORD not in backend.values
    assert PENDING_HASH not in backend.values
    assert controller.status().current_pair_present is True
    assert controller.status().pending_pair_present is False


def test_promote_pending_restores_current_pair_when_current_hash_write_fails() -> None:
    backend = InMemoryKeychain()
    current_password, current_hash = _seed_current(backend)
    controller = _controller(backend)
    controller.prepare_pending("replacement-operator-password")
    backend.fail_next_upsert_for = CURRENT_HASH

    with pytest.raises(KeychainPromotionError, match="current_pair_not_promoted"):
        controller.promote_pending(verified_rotation_id="a" * 64)

    assert backend.values[CURRENT_PASSWORD] == current_password.encode()
    assert backend.values[CURRENT_HASH] == current_hash.encode()
    assert PENDING_PASSWORD in backend.values
    assert PENDING_HASH in backend.values


def test_prepare_pending_rejects_blank_password() -> None:
    controller = _controller(InMemoryKeychain())

    with pytest.raises(PendingCredentialError, match="pending_password_blank"):
        controller.prepare_pending("  \t\n")


def test_discard_pending_leaves_current_pair_unchanged() -> None:
    backend = InMemoryKeychain()
    current_password, current_hash = _seed_current(backend)
    controller = _controller(backend)
    controller.prepare_pending("replacement-operator-password")

    controller.discard_pending()

    assert backend.values[CURRENT_PASSWORD] == current_password.encode()
    assert backend.values[CURRENT_HASH] == current_hash.encode()
    assert PENDING_PASSWORD not in backend.values
    assert PENDING_HASH not in backend.values


def test_public_status_serialization_never_contains_stored_secret_values() -> None:
    backend = InMemoryKeychain()
    _seed_current(backend)
    controller = _controller(backend)
    controller.prepare_pending("replacement-operator-password")

    public_status = controller.status().as_public_dict()

    assert "current-operator-password" not in repr(public_status)
    assert "replacement-operator-password" not in repr(public_status)
    assert public_status["current_pair"] == "present"
    assert public_status["pending_pair"] == "present"


def test_loaded_pending_pair_verifies_in_memory_and_redacts_repr() -> None:
    backend = InMemoryKeychain()
    controller = _controller(backend)
    controller.prepare_pending("replacement-operator-password")

    pair = controller.pending_pair()

    assert pair.password == "replacement-operator-password"
    assert PasswordHasher(
        time_cost=1,
        memory_cost=1_024,
        parallelism=1,
    ).verify(pair.password_hash, pair.password)
    assert "replacement-operator-password" not in repr(pair)
    assert pair.password_hash not in repr(pair)
