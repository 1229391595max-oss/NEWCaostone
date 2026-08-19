"""Version-bound store catalogs and fail-closed scope resolution."""

from __future__ import annotations

import csv
from datetime import date
from functools import lru_cache
from io import StringIO
import json
from typing import Mapping, Sequence
from uuid import UUID

from sqlalchemy import Engine

from src.repositories.datasets import DatasetRepository
from src.repositories.storage_objects import StorageObjectRepository
from src.services.canonical_contracts import StoreDescriptor, StoreScope

MAX_STORE_CATALOG = 32
MAX_CATALOG_ARTIFACT_BYTES = 16 * 1024 * 1024
MAX_CATALOG_SCAN_BYTES = 32 * 1024 * 1024


class StoreScopeError(RuntimeError):
    code = "STORE_SCOPE_ERROR"


class StoreScopeInvalid(StoreScopeError):
    code = "STORE_SCOPE_INVALID"


class StoreCatalogUnavailable(StoreScopeError):
    code = "STORE_CATALOG_UNAVAILABLE"


class StoreScopeResolver:
    """Resolve client store IDs only against one immutable dataset version."""

    def __init__(self, engine: Engine, storage, workspace_id: str) -> None:
        self._engine = engine
        self._storage = storage
        self._workspace_id = workspace_id

    @lru_cache(maxsize=64)
    def catalog(self, dataset_version_id: UUID) -> tuple[StoreDescriptor, ...]:
        if not isinstance(dataset_version_id, UUID) or self._storage is None:
            raise StoreCatalogUnavailable
        with self._engine.connect() as connection:
            datasets = DatasetRepository(connection)
            version = datasets.get_version(dataset_version_id)
            artifacts = datasets.list_artifacts(dataset_version_id)
            storage_repository = StorageObjectRepository(connection)
            storage_records = tuple(
                storage_repository.get(artifact.storage_object_id)
                for artifact in artifacts
            )
        if (
            version is None
            or version.workspace_id != self._workspace_id
            or version.status != "complete"
            or not artifacts
        ):
            raise StoreCatalogUnavailable

        fallback: list[StoreDescriptor] = []
        opened_bytes = 0
        candidates = sorted(
            zip(artifacts, storage_records, strict=True),
            key=lambda item: (
                {"analysis_bundle": 0, "manifest": 1, "stores": 2}.get(
                    item[0].artifact_kind,
                    3,
                ),
                item[0].artifact_kind,
            ),
        )
        for artifact, storage in candidates:
            if (
                storage is None
                or storage.workspace_id != self._workspace_id
                or storage.state != "available"
                or storage.purpose != "normalized_dataset"
                or storage.sha256 != artifact.sha256
            ):
                raise StoreCatalogUnavailable
            if storage.media_type == "text/csv" and artifact.artifact_kind != "stores":
                continue
            if storage.media_type not in {"application/json", "text/csv"}:
                continue
            opened_bytes += storage.size_bytes
            if (
                storage.size_bytes > MAX_CATALOG_ARTIFACT_BYTES
                or opened_bytes > MAX_CATALOG_SCAN_BYTES
            ):
                raise StoreCatalogUnavailable
            with self._storage.open_verified(
                storage.object_key,
                artifact.sha256,
                storage.size_bytes,
            ) as opened:
                content = opened.read()
            if storage.media_type == "application/json":
                document = _json_document(content)
                if "store_catalog" in document:
                    explicit = _unique_catalog(
                        _descriptors(document["store_catalog"])
                    )
                    if explicit:
                        return explicit
                raw_tables = document.get("tables")
                if isinstance(raw_tables, Mapping) and "stores" in raw_tables:
                    fallback.extend(_descriptors(raw_tables["stores"]))
            elif artifact.artifact_kind == "stores":
                fallback.extend(_csv_descriptors(content))

        resolved = _unique_catalog(fallback)
        if not resolved:
            raise StoreCatalogUnavailable
        return resolved

    def resolve(
        self,
        dataset_version_id: UUID,
        requested_store_ids: Sequence[str] | None,
    ) -> StoreScope:
        catalog = self.catalog(dataset_version_id)
        catalog_ids = tuple(item.store_id for item in catalog)
        if requested_store_ids is None:
            return StoreScope("all", catalog_ids)
        if (
            isinstance(requested_store_ids, (str, bytes))
            or not isinstance(requested_store_ids, Sequence)
        ):
            raise StoreScopeInvalid
        if len(requested_store_ids) == 0:
            return StoreScope("all", catalog_ids)
        if len(requested_store_ids) != 1:
            raise StoreScopeInvalid
        store_id = requested_store_ids[0]
        if (
            not isinstance(store_id, str)
            or not store_id
            or store_id != store_id.strip()
            or store_id not in catalog_ids
        ):
            raise StoreScopeInvalid
        return StoreScope("single", (store_id,))


def _json_document(content: bytes) -> dict[str, object]:
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StoreCatalogUnavailable from error
    if not isinstance(value, dict):
        raise StoreCatalogUnavailable
    return value


def _csv_descriptors(content: bytes) -> tuple[StoreDescriptor, ...]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise StoreCatalogUnavailable from error
    reader = csv.DictReader(StringIO(text, newline=""))
    if not reader.fieldnames:
        raise StoreCatalogUnavailable
    return _descriptors(list(reader))


def _descriptors(value: object) -> tuple[StoreDescriptor, ...]:
    if not isinstance(value, list) or len(value) > MAX_STORE_CATALOG:
        raise StoreCatalogUnavailable
    descriptors = []
    for item in value:
        if not isinstance(item, Mapping):
            raise StoreCatalogUnavailable
        try:
            store_id = _text(item.get("store_id"))
            opened_on = _opened_on(item.get("opened_on"))
            lifecycle = _text(item.get("lifecycle"))
            if lifecycle not in {"established", "new"}:
                raise StoreCatalogUnavailable
            descriptors.append(
                StoreDescriptor(
                    store_id=store_id,
                    display_name_en=_optional_text(
                        item.get("display_name_en"),
                        store_id,
                    ),
                    display_name_zh=_optional_text(
                        item.get("display_name_zh"),
                        store_id,
                    ),
                    currency=_text(item.get("currency")),
                    opened_on=opened_on,
                    lifecycle=lifecycle,
                    has_data=_boolean(item.get("has_data")),
                )
            )
        except (TypeError, ValueError) as error:
            raise StoreCatalogUnavailable from error
    return tuple(descriptors)


def _unique_catalog(
    descriptors: Sequence[StoreDescriptor],
) -> tuple[StoreDescriptor, ...]:
    unique: dict[str, StoreDescriptor] = {}
    for descriptor in descriptors:
        existing = unique.get(descriptor.store_id)
        if existing is not None and existing != descriptor:
            raise StoreCatalogUnavailable
        unique.setdefault(descriptor.store_id, descriptor)
    if len(unique) > MAX_STORE_CATALOG:
        raise StoreCatalogUnavailable
    return tuple(unique.values())


def _text(value: object) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError("store_catalog_text_invalid")
    if len(value) > 128 or any(ord(character) < 0x20 for character in value):
        raise ValueError("store_catalog_text_invalid")
    return value


def _optional_text(value: object, fallback: str) -> str:
    if value in (None, ""):
        return fallback
    return _text(value)


def _opened_on(value: object) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError("store_catalog_opened_on_invalid")
    return date.fromisoformat(value)


def _boolean(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    raise ValueError("store_catalog_has_data_invalid")
