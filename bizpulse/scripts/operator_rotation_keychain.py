"""Local, macOS-only credential staging for a guarded operator rotation.

This module intentionally keeps credential values out of command arguments and
stdout.  The command-line interface emits metadata only; callers that need a
credential value must use the backend directly within their own process.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import getpass
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError


CURRENT_PASSWORD = ("NEWCaostone Azure Demo Operator Password", "operator")
CURRENT_HASH = ("NEWCaostone Azure Demo Operator Password Hash", "operator")
PENDING_PASSWORD = ("NEWCaostone Azure Demo Operator Password Pending", "operator")
PENDING_HASH = (
    "NEWCaostone Azure Demo Operator Password Pending Hash",
    "operator",
)

_ERR_SEC_ITEM_NOT_FOUND = -25300
_CF_STRING_ENCODING_UTF8 = 0x08000100
_CF_ABSOLUTE_TIME_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)
_ROTATION_ID = re.compile(r"[0-9a-f]{64}")


class KeychainError(RuntimeError):
    """Raised when the local Keychain cannot safely satisfy an operation."""


class PendingCredentialError(KeychainError):
    """Raised when Pending credentials are absent, invalid, or unsafe to use."""


class KeychainPromotionError(KeychainError):
    """Raised when Current credentials cannot be safely promoted."""


@dataclass(frozen=True, slots=True)
class KeychainItemMetadata:
    created_at: datetime | None
    modified_at: datetime | None


@dataclass(frozen=True, slots=True)
class OperatorCredentialPair:
    """In-memory-only credential material; its repr intentionally hides values."""

    password: str = field(repr=False)
    password_hash: str = field(repr=False)


@dataclass(frozen=True, slots=True)
class KeychainRecordStatus:
    service: str
    account: str
    present: bool
    created_at: datetime | None
    modified_at: datetime | None


@dataclass(frozen=True, slots=True)
class OperatorCredentialStatus:
    current_password: KeychainRecordStatus
    current_hash: KeychainRecordStatus
    pending_password: KeychainRecordStatus
    pending_hash: KeychainRecordStatus

    @property
    def current_pair_present(self) -> bool:
        return self.current_password.present and self.current_hash.present

    @property
    def pending_pair_present(self) -> bool:
        return self.pending_password.present and self.pending_hash.present

    def as_public_dict(self) -> dict[str, object]:
        return {
            "current_pair": _pair_state(
                self.current_password,
                self.current_hash,
            ),
            "pending_pair": _pair_state(
                self.pending_password,
                self.pending_hash,
            ),
            "records": {
                "current_password": _record_to_public_dict(self.current_password),
                "current_hash": _record_to_public_dict(self.current_hash),
                "pending_password": _record_to_public_dict(self.pending_password),
                "pending_hash": _record_to_public_dict(self.pending_hash),
            },
        }


class KeychainBackend(Protocol):
    """Small boundary that keeps native Keychain calls outside business logic."""

    def read_secret(self, service: str, account: str) -> bytes | None: ...

    def upsert_secret(self, service: str, account: str, value: bytes) -> None: ...

    def delete_secret(self, service: str, account: str) -> None: ...

    def metadata(self, service: str, account: str) -> KeychainItemMetadata | None: ...


class _CFDictionaryKeyCallBacks(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_long),
        ("retain", ctypes.c_void_p),
        ("release", ctypes.c_void_p),
        ("copy_description", ctypes.c_void_p),
        ("equal", ctypes.c_void_p),
        ("hash", ctypes.c_void_p),
    ]


class _CFDictionaryValueCallBacks(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_long),
        ("retain", ctypes.c_void_p),
        ("release", ctypes.c_void_p),
        ("copy_description", ctypes.c_void_p),
        ("equal", ctypes.c_void_p),
    ]


class MacOSKeychainBackend:
    """Security.framework generic-password backend with no secret subprocesses."""

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise KeychainError("macos_keychain_required")
        security_path = ctypes.util.find_library("Security")
        core_foundation_path = ctypes.util.find_library("CoreFoundation")
        if security_path is None or core_foundation_path is None:
            raise KeychainError("macos_keychain_framework_unavailable")
        self._security = ctypes.CDLL(security_path)
        self._core_foundation = ctypes.CDLL(core_foundation_path)
        self._configure_functions()
        self._constants = self._load_constants()
        self._key_callbacks = _CFDictionaryKeyCallBacks.in_dll(
            self._core_foundation,
            "kCFTypeDictionaryKeyCallBacks",
        )
        self._value_callbacks = _CFDictionaryValueCallBacks.in_dll(
            self._core_foundation,
            "kCFTypeDictionaryValueCallBacks",
        )

    def read_secret(self, service: str, account: str) -> bytes | None:
        query, owned = self._query(service, account, return_data=True)
        result = ctypes.c_void_p()
        try:
            status = self._security.SecItemCopyMatching(query, ctypes.byref(result))
            if status == _ERR_SEC_ITEM_NOT_FOUND:
                return None
            self._raise_for_status(status)
            return self._copy_cf_data(result.value)
        finally:
            if result.value:
                self._core_foundation.CFRelease(result)
            self._release_owned(query, owned)

    def upsert_secret(self, service: str, account: str, value: bytes) -> None:
        query, query_owned = self._query(service, account)
        attributes, attributes_owned = self._dictionary(
            ((self._constants["kSecValueData"], self._cf_data(value)),)
        )
        try:
            status = self._security.SecItemUpdate(query, attributes)
            if status == _ERR_SEC_ITEM_NOT_FOUND:
                add_attributes, add_owned = self._dictionary(
                    (
                        (self._constants["kSecClass"], self._constants["kSecClassGenericPassword"]),
                        (self._constants["kSecAttrService"], self._cf_string(service)),
                        (self._constants["kSecAttrAccount"], self._cf_string(account)),
                        (self._constants["kSecValueData"], self._cf_data(value)),
                    )
                )
                try:
                    self._raise_for_status(
                        self._security.SecItemAdd(add_attributes, None)
                    )
                finally:
                    self._release_owned(add_attributes, add_owned)
                return
            self._raise_for_status(status)
        finally:
            self._release_owned(attributes, attributes_owned)
            self._release_owned(query, query_owned)

    def delete_secret(self, service: str, account: str) -> None:
        query, owned = self._query(service, account)
        try:
            status = self._security.SecItemDelete(query)
            if status != _ERR_SEC_ITEM_NOT_FOUND:
                self._raise_for_status(status)
        finally:
            self._release_owned(query, owned)

    def metadata(self, service: str, account: str) -> KeychainItemMetadata | None:
        query, owned = self._query(service, account, return_attributes=True)
        result = ctypes.c_void_p()
        try:
            status = self._security.SecItemCopyMatching(query, ctypes.byref(result))
            if status == _ERR_SEC_ITEM_NOT_FOUND:
                return None
            self._raise_for_status(status)
            return KeychainItemMetadata(
                created_at=self._cf_date_at(
                    result.value,
                    self._constants["kSecAttrCreationDate"],
                ),
                modified_at=self._cf_date_at(
                    result.value,
                    self._constants["kSecAttrModificationDate"],
                ),
            )
        finally:
            if result.value:
                self._core_foundation.CFRelease(result)
            self._release_owned(query, owned)

    def _configure_functions(self) -> None:
        self._security.SecItemCopyMatching.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._security.SecItemCopyMatching.restype = ctypes.c_int32
        self._security.SecItemAdd.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._security.SecItemAdd.restype = ctypes.c_int32
        self._security.SecItemUpdate.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._security.SecItemUpdate.restype = ctypes.c_int32
        self._security.SecItemDelete.argtypes = [ctypes.c_void_p]
        self._security.SecItemDelete.restype = ctypes.c_int32
        self._core_foundation.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        self._core_foundation.CFStringCreateWithCString.restype = ctypes.c_void_p
        self._core_foundation.CFDataCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_long,
        ]
        self._core_foundation.CFDataCreate.restype = ctypes.c_void_p
        self._core_foundation.CFDataGetLength.argtypes = [ctypes.c_void_p]
        self._core_foundation.CFDataGetLength.restype = ctypes.c_long
        self._core_foundation.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        self._core_foundation.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_ubyte)
        self._core_foundation.CFDictionaryCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_long,
            ctypes.POINTER(_CFDictionaryKeyCallBacks),
            ctypes.POINTER(_CFDictionaryValueCallBacks),
        ]
        self._core_foundation.CFDictionaryCreate.restype = ctypes.c_void_p
        self._core_foundation.CFDictionaryGetValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._core_foundation.CFDictionaryGetValue.restype = ctypes.c_void_p
        self._core_foundation.CFDateGetAbsoluteTime.argtypes = [ctypes.c_void_p]
        self._core_foundation.CFDateGetAbsoluteTime.restype = ctypes.c_double
        self._core_foundation.CFRelease.argtypes = [ctypes.c_void_p]
        self._core_foundation.CFRelease.restype = None

    def _load_constants(self) -> dict[str, int]:
        names = (
            "kSecClass",
            "kSecClassGenericPassword",
            "kSecAttrService",
            "kSecAttrAccount",
            "kSecAttrCreationDate",
            "kSecAttrModificationDate",
            "kSecValueData",
            "kSecReturnData",
            "kSecReturnAttributes",
        )
        constants = {
            name: ctypes.c_void_p.in_dll(self._security, name).value for name in names
        }
        constants["kCFBooleanTrue"] = ctypes.c_void_p.in_dll(
            self._core_foundation,
            "kCFBooleanTrue",
        ).value
        if any(value is None for value in constants.values()):
            raise KeychainError("macos_keychain_constants_unavailable")
        return {name: int(value) for name, value in constants.items()}

    def _query(
        self,
        service: str,
        account: str,
        *,
        return_data: bool = False,
        return_attributes: bool = False,
    ) -> tuple[int, list[int]]:
        pairs: list[tuple[int, int]] = [
            (self._constants["kSecClass"], self._constants["kSecClassGenericPassword"]),
            (self._constants["kSecAttrService"], self._cf_string(service)),
            (self._constants["kSecAttrAccount"], self._cf_string(account)),
        ]
        if return_data:
            pairs.append(
                (self._constants["kSecReturnData"], self._constants["kCFBooleanTrue"])
            )
        if return_attributes:
            pairs.append(
                (self._constants["kSecReturnAttributes"], self._constants["kCFBooleanTrue"])
            )
        return self._dictionary(tuple(pairs))

    def _dictionary(self, pairs: tuple[tuple[int, int], ...]) -> tuple[int, list[int]]:
        keys = (ctypes.c_void_p * len(pairs))(*(key for key, _ in pairs))
        values = (ctypes.c_void_p * len(pairs))(*(value for _, value in pairs))
        dictionary = self._core_foundation.CFDictionaryCreate(
            None,
            keys,
            values,
            len(pairs),
            ctypes.byref(self._key_callbacks),
            ctypes.byref(self._value_callbacks),
        )
        if not dictionary:
            raise KeychainError("macos_keychain_dictionary_creation_failed")
        owned = [
            value
            for _, value in pairs
            if value not in self._constants.values()
        ]
        return int(dictionary), owned

    def _cf_string(self, value: str) -> int:
        result = self._core_foundation.CFStringCreateWithCString(
            None,
            value.encode("utf-8"),
            _CF_STRING_ENCODING_UTF8,
        )
        if not result:
            raise KeychainError("macos_keychain_string_creation_failed")
        return int(result)

    def _cf_data(self, value: bytes) -> int:
        raw = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        result = self._core_foundation.CFDataCreate(None, raw, len(value))
        if not result:
            raise KeychainError("macos_keychain_data_creation_failed")
        return int(result)

    def _copy_cf_data(self, value: int | None) -> bytes:
        if not value:
            raise KeychainError("macos_keychain_data_missing")
        length = self._core_foundation.CFDataGetLength(value)
        pointer = self._core_foundation.CFDataGetBytePtr(value)
        if length < 0 or (length and not pointer):
            raise KeychainError("macos_keychain_data_invalid")
        return ctypes.string_at(pointer, length)

    def _cf_date_at(self, dictionary: int | None, key: int) -> datetime | None:
        if not dictionary:
            return None
        value = self._core_foundation.CFDictionaryGetValue(dictionary, key)
        if not value:
            return None
        return _CF_ABSOLUTE_TIME_EPOCH + timedelta(
            seconds=self._core_foundation.CFDateGetAbsoluteTime(value)
        )

    def _release_owned(self, dictionary: int, owned: list[int]) -> None:
        self._core_foundation.CFRelease(dictionary)
        for value in owned:
            self._core_foundation.CFRelease(value)

    @staticmethod
    def _raise_for_status(status: int) -> None:
        if status != 0:
            raise KeychainError(f"macos_keychain_status_{status}")


class OperatorRotationKeychain:
    """Stage and promote the single server-owned Demo credential locally."""

    def __init__(
        self,
        *,
        backend: KeychainBackend,
        password_hasher: PasswordHasher | None = None,
    ) -> None:
        self._backend = backend
        self._password_hasher = password_hasher or PasswordHasher(
            time_cost=3,
            memory_cost=65_536,
            parallelism=4,
            hash_len=32,
            salt_len=16,
            type=Type.ID,
        )

    def status(self) -> OperatorCredentialStatus:
        return OperatorCredentialStatus(
            current_password=self._record_status(CURRENT_PASSWORD),
            current_hash=self._record_status(CURRENT_HASH),
            pending_password=self._record_status(PENDING_PASSWORD),
            pending_hash=self._record_status(PENDING_HASH),
        )

    def prepare_pending(self, password: str) -> None:
        if not password or password.isspace():
            raise PendingCredentialError("pending_password_blank")
        password_bytes = bytearray(password.encode("utf-8"))
        try:
            password_hash = self._password_hasher.hash(password)
            self._backend.upsert_secret(*PENDING_PASSWORD, bytes(password_bytes))
            self._backend.upsert_secret(*PENDING_HASH, password_hash.encode("utf-8"))
        except Exception as error:
            if isinstance(error, PendingCredentialError):
                raise
            raise PendingCredentialError("pending_pair_not_staged") from error
        finally:
            _zero(password_bytes)

    def current_pair(self) -> OperatorCredentialPair:
        return self._credential_pair(
            CURRENT_PASSWORD,
            CURRENT_HASH,
            missing_error="current_pair_missing",
            invalid_error="current_pair_invalid",
        )

    def pending_pair(self) -> OperatorCredentialPair:
        return self._credential_pair(
            PENDING_PASSWORD,
            PENDING_HASH,
            missing_error="pending_pair_missing",
            invalid_error="pending_pair_invalid",
        )

    def promote_pending(self, *, verified_rotation_id: str) -> None:
        if _ROTATION_ID.fullmatch(verified_rotation_id) is None:
            raise KeychainPromotionError("verified_rotation_id_invalid")
        current_password, current_hash = self._load_pair(
            CURRENT_PASSWORD,
            CURRENT_HASH,
            missing_error="current_pair_missing",
            invalid_error="current_pair_invalid",
        )
        pending_password, pending_hash = self._load_pair(
            PENDING_PASSWORD,
            PENDING_HASH,
            missing_error="pending_pair_missing",
            invalid_error="pending_pair_invalid",
        )
        try:
            self._backend.upsert_secret(*CURRENT_PASSWORD, pending_password)
            self._backend.upsert_secret(*CURRENT_HASH, pending_hash)
        except Exception as error:
            try:
                self._backend.upsert_secret(*CURRENT_PASSWORD, current_password)
                self._backend.upsert_secret(*CURRENT_HASH, current_hash)
            except Exception as recovery_error:
                raise KeychainPromotionError("current_pair_restore_failed") from recovery_error
            raise KeychainPromotionError("current_pair_not_promoted") from error
        try:
            self._backend.delete_secret(*PENDING_PASSWORD)
            self._backend.delete_secret(*PENDING_HASH)
        except Exception as error:
            raise KeychainPromotionError("pending_pair_not_cleared") from error

    def discard_pending(self) -> None:
        self._backend.delete_secret(*PENDING_PASSWORD)
        self._backend.delete_secret(*PENDING_HASH)

    def _record_status(self, key: tuple[str, str]) -> KeychainRecordStatus:
        service, account = key
        metadata = self._backend.metadata(service, account)
        return KeychainRecordStatus(
            service=service,
            account=account,
            present=metadata is not None,
            created_at=metadata.created_at if metadata else None,
            modified_at=metadata.modified_at if metadata else None,
        )

    def _load_pair(
        self,
        password_key: tuple[str, str],
        hash_key: tuple[str, str],
        *,
        missing_error: str,
        invalid_error: str,
    ) -> tuple[bytes, bytes]:
        password = self._backend.read_secret(*password_key)
        password_hash = self._backend.read_secret(*hash_key)
        if password is None or password_hash is None:
            raise PendingCredentialError(missing_error)
        try:
            password_text = password.decode("utf-8")
            hash_text = password_hash.decode("utf-8")
            verified = self._password_hasher.verify(hash_text, password_text)
        except (InvalidHashError, UnicodeDecodeError, VerificationError) as error:
            raise PendingCredentialError(invalid_error) from error
        if not verified:
            raise PendingCredentialError(invalid_error)
        return password, password_hash

    def _credential_pair(
        self,
        password_key: tuple[str, str],
        hash_key: tuple[str, str],
        *,
        missing_error: str,
        invalid_error: str,
    ) -> OperatorCredentialPair:
        password, password_hash = self._load_pair(
            password_key,
            hash_key,
            missing_error=missing_error,
            invalid_error=invalid_error,
        )
        return OperatorCredentialPair(
            password=password.decode("utf-8"),
            password_hash=password_hash.decode("utf-8"),
        )


def _pair_state(
    password: KeychainRecordStatus,
    password_hash: KeychainRecordStatus,
) -> str:
    if password.present and password_hash.present:
        return "present"
    if not password.present and not password_hash.present:
        return "missing"
    return "incomplete"


def _record_to_public_dict(record: KeychainRecordStatus) -> dict[str, Any]:
    result = asdict(record)
    for key in ("created_at", "modified_at"):
        value = result[key]
        result[key] = value.isoformat() if value is not None else None
    return result


def _zero(value: bytearray) -> None:
    for index in range(len(value)):
        value[index] = 0


def _controller() -> OperatorRotationKeychain:
    return OperatorRotationKeychain(backend=MacOSKeychainBackend())


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("prepare-pending")
    promote = commands.add_parser("promote-pending")
    promote.add_argument("--verified-rotation-id", required=True)
    discard = commands.add_parser("discard-pending")
    discard.add_argument("--confirmed", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        controller = _controller()
        if args.command == "status":
            print(json.dumps(controller.status().as_public_dict(), sort_keys=True))
            return 0
        if args.command == "prepare-pending":
            password = getpass.getpass("New operator password: ")
            confirmation = getpass.getpass("Confirm new operator password: ")
            if password != confirmation:
                raise PendingCredentialError("pending_password_confirmation_mismatch")
            controller.prepare_pending(password)
            print(json.dumps(controller.status().as_public_dict(), sort_keys=True))
            return 0
        if args.command == "promote-pending":
            controller.promote_pending(
                verified_rotation_id=args.verified_rotation_id,
            )
            print(json.dumps(controller.status().as_public_dict(), sort_keys=True))
            return 0
        if args.command == "discard-pending":
            if not args.confirmed:
                raise PendingCredentialError("pending_discard_not_confirmed")
            controller.discard_pending()
            print(json.dumps(controller.status().as_public_dict(), sort_keys=True))
            return 0
    except KeychainError as error:
        print(str(error), file=sys.stderr)
        return 2
    raise AssertionError("unreachable_keychain_command")


if __name__ == "__main__":
    raise SystemExit(main())
