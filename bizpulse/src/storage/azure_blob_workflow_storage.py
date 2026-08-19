"""Bounded, conditional Azure Blob implementation of workflow storage."""

from __future__ import annotations

import re
from contextlib import closing
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from typing import Any, BinaryIO

from azure.core import MatchConditions
from azure.core.exceptions import (
    AzureError,
    ResourceExistsError,
    ResourceModifiedError,
    ResourceNotFoundError,
)
from azure.storage.blob import ContentSettings

from src.config import BizPulseSettings
from src.storage.keys import normalize_storage_key, staging_upload_key
from src.storage.protocol import (
    AvailableObject,
    InventoryObject,
    StagedObject,
    StorageConcurrency,
    StorageIntegrityError,
    StorageTooLarge,
    StorageUnavailable,
)

LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
CHUNK_BYTES = 64 * 1024
SPOOL_MEMORY_BYTES = 1024 * 1024
OPERATION_TIMEOUT_SECONDS = 30
READINESS_TIMEOUT_SECONDS = 1


def build_storage(
    settings: BizPulseSettings,
    container_client: Any,
    *,
    entry_locks: Any,
) -> AzureBlobWorkflowStorage:
    """Build a Blob adapter and fail closed instead of selecting disk storage."""

    storage = AzureBlobWorkflowStorage(
        container_client=container_client,
        workspace_id="synthetic-demo",
        staging_scope="runtime",
        entry_locks=entry_locks,
    )
    try:
        storage.check_readiness()
    except Exception as error:
        if isinstance(error, StorageUnavailable):
            raise
        raise StorageUnavailable from error
    return storage


class AzureBlobWorkflowStorage:
    def __init__(
        self,
        *,
        container_client: Any,
        workspace_id: str,
        staging_scope: str,
        entry_locks: Any,
        object_id_factory=None,
    ) -> None:
        from uuid import uuid4

        self._container = container_client
        self._workspace_id = workspace_id
        self._staging_scope = staging_scope
        self._entry_locks = entry_locks
        self._object_id_factory = object_id_factory or (lambda: uuid4().hex)

    def check_readiness(self) -> None:
        try:
            self._container.get_container_properties(
                connection_timeout=READINESS_TIMEOUT_SECONDS,
                read_timeout=READINESS_TIMEOUT_SECONDS,
                timeout=READINESS_TIMEOUT_SECONDS,
            )
        except BaseException as error:
            raise self._safe_error(error) from error

    def put_staging(
        self,
        stream: BinaryIO,
        *,
        max_bytes: int,
        media_type: str,
    ) -> StagedObject:
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("max_bytes_invalid")
        if not isinstance(media_type, str) or not 1 <= len(media_type) <= 255:
            raise ValueError("media_type_invalid")
        spool, size_bytes, digest = self._spool(stream, max_bytes)
        key = staging_upload_key(
            self._workspace_id,
            self._staging_scope,
            self._object_id_factory(),
        )
        blob = self._container.get_blob_client(key)
        try:
            with closing(spool):
                blob.upload_blob(
                    spool,
                    overwrite=False,
                    metadata={
                        "sha256": digest,
                        "size_bytes": str(size_bytes),
                        "state": "staging",
                    },
                    content_settings=ContentSettings(content_type=media_type),
                    max_concurrency=1,
                    timeout=OPERATION_TIMEOUT_SECONDS,
                )
            properties = self._properties(key)
            if properties is None:
                raise StorageUnavailable
            return StagedObject(
                key=key,
                size_bytes=size_bytes,
                sha256=digest,
                etag=str(properties.etag),
                media_type=media_type,
            )
        except (StorageTooLarge, StorageUnavailable, StorageConcurrency):
            raise
        except BaseException as error:
            raise self._safe_error(error) from error

    def promote(
        self,
        staged_key: str,
        final_key: str,
        expected_sha256: str,
    ) -> AvailableObject:
        source = normalize_storage_key(staged_key)
        destination = normalize_storage_key(final_key)
        self._validate_digest(expected_sha256)
        if source == destination:
            raise ValueError("promotion_keys_must_differ")
        with self._entry_locks.acquire((source, destination)):
            source_properties = self._properties(source)
            if source_properties is None:
                raise StorageIntegrityError
            spool, size_bytes, digest = self._download(
                source,
                source_properties,
                max_bytes=int(source_properties.size),
            )
            if digest != expected_sha256:
                spool.close()
                raise StorageIntegrityError
            created = False
            try:
                destination_properties = self._properties(destination)
                if destination_properties is None:
                    spool.seek(0)
                    try:
                        self._container.get_blob_client(destination).upload_blob(
                            spool,
                            overwrite=False,
                            metadata={
                                "sha256": digest,
                                "size_bytes": str(size_bytes),
                                "state": "available",
                            },
                            max_concurrency=1,
                            timeout=OPERATION_TIMEOUT_SECONDS,
                        )
                        created = True
                    except ResourceExistsError:
                        destination_properties = self._properties(destination)
                destination_properties = self._properties(destination)
                if destination_properties is None:
                    raise StorageUnavailable
                verified, verified_size, verified_digest = self._download(
                    destination,
                    destination_properties,
                    max_bytes=size_bytes,
                )
                verified.close()
                if verified_size != size_bytes or verified_digest != digest:
                    raise StorageConcurrency
                return AvailableObject(
                    key=destination,
                    size_bytes=size_bytes,
                    sha256=digest,
                    etag=str(destination_properties.etag),
                    created=created,
                )
            finally:
                spool.close()

    def open_verified(
        self,
        key: str,
        expected_sha256: str,
        max_bytes: int,
    ) -> BinaryIO:
        normalized = normalize_storage_key(key)
        self._validate_digest(expected_sha256)
        if type(max_bytes) is not int or max_bytes < 1:
            raise ValueError("max_bytes_invalid")
        properties = self._properties(normalized)
        if properties is None or int(properties.size) > max_bytes:
            raise StorageIntegrityError
        spool, _size, digest = self._download(
            normalized,
            properties,
            max_bytes=max_bytes,
        )
        if digest != expected_sha256:
            spool.close()
            raise StorageIntegrityError
        return spool

    def delete(self, key: str, *, expected_etag: str | None = None) -> None:
        normalized = normalize_storage_key(key)
        with self._entry_locks.acquire((normalized,)):
            properties = self._properties(normalized)
            if properties is None:
                return
            etag = expected_etag or str(properties.etag)
            try:
                self._container.get_blob_client(normalized).delete_blob(
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                    timeout=OPERATION_TIMEOUT_SECONDS,
                )
            except ResourceNotFoundError:
                return
            except ResourceModifiedError as error:
                raise StorageConcurrency from error
            except BaseException as error:
                raise self._safe_error(error) from error

    def inventory(self, prefix: str) -> tuple[InventoryObject, ...]:
        normalized_prefix = normalize_storage_key(prefix.rstrip("/")) + "/"
        try:
            entries = []
            for item in self._container.list_blobs(name_starts_with=normalized_prefix):
                entries.append(
                    InventoryObject(
                        key=normalize_storage_key(str(item.name)),
                        size_bytes=int(item.size),
                        etag=str(item.etag),
                    )
                )
                if len(entries) > 10_000:
                    raise StorageTooLarge
            return tuple(sorted(entries, key=lambda entry: entry.key))
        except StorageTooLarge:
            raise
        except BaseException as error:
            raise self._safe_error(error) from error

    def exists(self, key: str) -> bool:
        return self._properties(normalize_storage_key(key)) is not None

    def _properties(self, key: str):
        try:
            return self._container.get_blob_client(key).get_blob_properties(
                timeout=OPERATION_TIMEOUT_SECONDS
            )
        except ResourceNotFoundError:
            return None
        except BaseException as error:
            raise self._safe_error(error) from error

    def _download(self, key: str, properties, *, max_bytes: int):
        try:
            downloader = self._container.get_blob_client(key).download_blob(
                etag=properties.etag,
                match_condition=MatchConditions.IfNotModified,
                max_concurrency=1,
                timeout=OPERATION_TIMEOUT_SECONDS,
            )
            spool = SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b")
            digest = sha256()
            size_bytes = 0
            try:
                for chunk in downloader.chunks():
                    payload = bytes(chunk)
                    size_bytes += len(payload)
                    if size_bytes > max_bytes:
                        raise StorageIntegrityError
                    spool.write(payload)
                    digest.update(payload)
                if size_bytes != int(properties.size):
                    raise StorageIntegrityError
                spool.seek(0)
                return spool, size_bytes, digest.hexdigest()
            except BaseException:
                spool.close()
                raise
        except ResourceModifiedError as error:
            raise StorageIntegrityError from error
        except StorageIntegrityError:
            raise
        except BaseException as error:
            raise self._safe_error(error) from error

    @staticmethod
    def _spool(stream: BinaryIO, max_bytes: int):
        spool = SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode="w+b")
        digest = sha256()
        size_bytes = 0
        try:
            while True:
                chunk = stream.read(CHUNK_BYTES)
                if not chunk:
                    break
                payload = bytes(chunk)
                size_bytes += len(payload)
                if size_bytes > max_bytes:
                    raise StorageTooLarge
                spool.write(payload)
                digest.update(payload)
            spool.seek(0)
            return spool, size_bytes, digest.hexdigest()
        except BaseException:
            spool.close()
            raise

    @staticmethod
    def _validate_digest(value: str) -> None:
        if not isinstance(value, str) or LOWER_SHA256.fullmatch(value) is None:
            raise ValueError("sha256_invalid")

    @staticmethod
    def _safe_error(error: BaseException) -> Exception:
        if isinstance(error, (StorageUnavailable, StorageConcurrency, StorageIntegrityError)):
            return error
        if isinstance(error, (ResourceExistsError, ResourceModifiedError)):
            return StorageConcurrency()
        if isinstance(error, AzureError) or isinstance(
            error,
            (ConnectionError, TimeoutError, OSError),
        ):
            return StorageUnavailable()
        return StorageUnavailable()
