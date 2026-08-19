"""Storage contracts with safe, stable failure classes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol


class StorageError(RuntimeError):
    """Base class for safe workflow-storage failures."""


class StorageUnavailable(StorageError):
    def __init__(self) -> None:
        super().__init__("blob_unavailable")


class StorageConcurrency(StorageError):
    def __init__(self) -> None:
        super().__init__("blob_state_changed")


class StorageIntegrityError(StorageError):
    def __init__(self) -> None:
        super().__init__("blob_integrity_failed")


class StorageTooLarge(StorageError):
    def __init__(self) -> None:
        super().__init__("blob_size_limit_exceeded")


@dataclass(frozen=True, slots=True)
class StagedObject:
    key: str
    size_bytes: int
    sha256: str
    etag: str
    media_type: str


@dataclass(frozen=True, slots=True)
class AvailableObject:
    key: str
    size_bytes: int
    sha256: str
    etag: str
    created: bool


@dataclass(frozen=True, slots=True)
class InventoryObject:
    key: str
    size_bytes: int
    etag: str


class WorkflowStorage(Protocol):
    def put_staging(
        self,
        stream: BinaryIO,
        *,
        max_bytes: int,
        media_type: str,
    ) -> StagedObject: ...

    def promote(
        self,
        staged_key: str,
        final_key: str,
        expected_sha256: str,
    ) -> AvailableObject: ...

    def open_verified(
        self,
        key: str,
        expected_sha256: str,
        max_bytes: int,
    ) -> BinaryIO: ...

    def delete(self, key: str, *, expected_etag: str | None = None) -> None: ...

    def inventory(self, prefix: str) -> tuple[InventoryObject, ...]: ...
