"""Deterministically merge normalized canonical sources by explicit business key."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Literal, Mapping, Sequence

from src.services.business_keys import BusinessKey, business_key
from src.services.canonical_contracts import (
    DedupeConflict,
    DedupeSummary,
    RowOrigin,
    StoreDescriptor,
)

_INGESTION_FIELDS = frozenset(
    {
        "blob_key",
        "object_key",
        "parsed_at",
        "sha256",
        "sheet_name",
        "source_classification",
        "source_filename",
        "source_row_number",
        "staging_key",
        "upload_id",
        "uploaded_at",
    }
)


class CanonicalSourceInvalid(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CanonicalSource:
    source_kind: Literal["base", "upload"]
    source_name: str
    tables: Mapping[str, Sequence[Mapping[str, object]]]
    row_provenance: Mapping[str, Sequence[Mapping[str, object]]]
    store_catalog: tuple[StoreDescriptor, ...] = ()
    created_at: datetime | None = None

    def __post_init__(self) -> None:
        RowOrigin(
            source_kind=self.source_kind,
            source_name=self.source_name,
            sheet_name=None,
            row_number=None,
        )
        if self.source_kind == "base" and self.created_at is not None:
            raise CanonicalSourceInvalid("base_created_at_not_allowed")


@dataclass(frozen=True, slots=True)
class AssemblyResult:
    content: bytes
    sha256: str
    summary: DedupeSummary
    conflicts: tuple[DedupeConflict, ...]


@dataclass(frozen=True, slots=True)
class _RetainedRow:
    row: dict[str, object]
    comparison: object
    origin: RowOrigin


class CanonicalDatasetAssembler:
    def assemble(
        self,
        *,
        base: CanonicalSource | None,
        uploads: tuple[CanonicalSource, ...],
    ) -> AssemblyResult:
        if base is not None and base.source_kind != "base":
            raise CanonicalSourceInvalid("base_source_kind_invalid")
        if any(source.source_kind != "upload" for source in uploads):
            raise CanonicalSourceInvalid("upload_source_kind_invalid")

        ordered_sources = (
            *((base,) if base is not None else ()),
            *sorted(uploads, key=_source_order),
        )
        retained: dict[str, dict[BusinessKey, _RetainedRow]] = {}
        role_order: set[str] = set()
        counters: dict[str, dict[str, int]] = {}
        conflicts: list[DedupeConflict] = []

        for source in ordered_sources:
            _validate_parallel_provenance(source)
            for role in sorted(source.tables):
                role_order.add(role)
                role_rows = retained.setdefault(role, {})
                counts = counters.setdefault(
                    role,
                    {
                        "rows_read": 0,
                        "rows_retained": 0,
                        "duplicates_removed": 0,
                        "conflicts": 0,
                    },
                )
                indexed_rows = [
                    (
                        _origin(source, role, index),
                        dict(row),
                        index,
                    )
                    for index, row in enumerate(source.tables[role])
                ]
                indexed_rows.sort(key=lambda item: (*_origin_order(item[0]), item[2]))
                for origin, row, _index in indexed_rows:
                    counts["rows_read"] += 1
                    key = business_key(role, row)
                    comparison = _comparison_value(_business_values(row))
                    existing = role_rows.get(key)
                    if existing is None:
                        role_rows[key] = _RetainedRow(
                            row=_json_row(row),
                            comparison=comparison,
                            origin=origin,
                        )
                        counts["rows_retained"] += 1
                        continue
                    if existing.comparison == comparison:
                        counts["duplicates_removed"] += 1
                        continue
                    changed = _changed_fields(existing.row, row)
                    conflicts.append(
                        DedupeConflict(
                            role=role,
                            business_key=key,
                            fields=changed,
                            existing=existing.origin,
                            incoming=origin,
                        )
                    )
                    counts["conflicts"] += 1

        summary = DedupeSummary(
            rows_read=sum(item["rows_read"] for item in counters.values()),
            rows_retained=sum(item["rows_retained"] for item in counters.values()),
            duplicates_removed=sum(
                item["duplicates_removed"] for item in counters.values()
            ),
            conflicts=sum(item["conflicts"] for item in counters.values()),
            per_role={role: dict(counters[role]) for role in sorted(counters)},
        )
        if conflicts:
            return AssemblyResult(b"", "", summary, tuple(conflicts))

        tables: dict[str, list[dict[str, object]]] = {}
        provenance: dict[str, list[dict[str, object]]] = {}
        for role in sorted(role_order):
            rows = tuple(retained[role].values())
            tables[role] = [item.row for item in rows]
            provenance[role] = [_persisted_origin(item.origin) for item in rows]
        payload = {
            "row_provenance": provenance,
            "schema_version": "canonical.import.v1",
            "store_catalog": _store_catalog(ordered_sources, tables),
            "tables": tables,
        }
        content = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        return AssemblyResult(
            content=content,
            sha256=hashlib.sha256(content).hexdigest(),
            summary=summary,
            conflicts=(),
        )


def _validate_parallel_provenance(source: CanonicalSource) -> None:
    if set(source.tables) != set(source.row_provenance):
        raise CanonicalSourceInvalid("row_provenance_roles_mismatch")
    for role, rows in source.tables.items():
        if len(rows) != len(source.row_provenance[role]):
            raise CanonicalSourceInvalid(f"row_provenance_count_mismatch:{role}")


def _origin(source: CanonicalSource, role: str, index: int) -> RowOrigin:
    projection = source.row_provenance[role][index]
    if not isinstance(projection, Mapping):
        raise CanonicalSourceInvalid("row_provenance_invalid")
    allowed = {"row_number", "sheet_name", "source_kind", "source_name"}
    if not set(projection) <= allowed:
        raise CanonicalSourceInvalid("row_provenance_metadata_not_allowed")
    source_name = projection.get("source_name", source.source_name)
    sheet_name = projection.get("sheet_name")
    row_number = projection.get("row_number")
    if not isinstance(source_name, str):
        raise CanonicalSourceInvalid("row_provenance_source_name_invalid")
    if sheet_name is not None and not isinstance(sheet_name, str):
        raise CanonicalSourceInvalid("row_provenance_sheet_name_invalid")
    if row_number is not None and type(row_number) is not int:
        raise CanonicalSourceInvalid("row_provenance_row_number_invalid")
    return RowOrigin(
        source_kind=source.source_kind,
        source_name=source_name,
        sheet_name=sheet_name,
        row_number=row_number,
    )


def _source_order(source: CanonicalSource) -> tuple[str, str]:
    timestamp = source.created_at
    if timestamp is None:
        rendered = ""
    else:
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=UTC)
        rendered = timestamp.astimezone(UTC).isoformat()
    return rendered, source.source_name


def _origin_order(origin: RowOrigin) -> tuple[str, str, int]:
    return (
        origin.source_name,
        origin.sheet_name or "",
        origin.row_number or 0,
    )


def _business_values(row: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in row.items()
        if key not in _INGESTION_FIELDS and not key.startswith("_ingestion_")
    }


def _comparison_value(value: object) -> object:
    if isinstance(value, Mapping):
        return tuple(
            (str(key), _comparison_value(item))
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        )
    if isinstance(value, (list, tuple)):
        return tuple(_comparison_value(item) for item in value)
    if isinstance(value, datetime):
        return ("datetime", value.isoformat())
    if isinstance(value, date):
        return ("date", value.isoformat())
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        try:
            parsed = Decimal(str(value))
        except InvalidOperation:
            return ("value", str(value))
        if parsed.is_finite():
            return ("number", format(parsed.normalize(), "f"))
    if isinstance(value, str):
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation:
            pass
        else:
            if parsed.is_finite():
                return ("number", format(parsed.normalize(), "f"))
    return ("value", str(value))


def _changed_fields(
    existing: Mapping[str, object],
    incoming: Mapping[str, object],
) -> tuple[str, ...]:
    existing_business = _business_values(existing)
    incoming_business = _business_values(incoming)
    return tuple(
        field
        for field in sorted(set(existing_business) | set(incoming_business))
        if _comparison_value(existing_business.get(field))
        != _comparison_value(incoming_business.get(field))
    )


def _json_row(row: Mapping[str, object]) -> dict[str, object]:
    return {str(key): _json_value(value) for key, value in row.items()}


def _json_value(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    return value


def _persisted_origin(origin: RowOrigin) -> dict[str, object]:
    return {"source_kind": origin.source_kind, **origin.safe_projection()}


def _store_catalog(
    sources: Sequence[CanonicalSource],
    tables: Mapping[str, Sequence[Mapping[str, object]]],
) -> list[dict[str, object]]:
    descriptors: dict[str, StoreDescriptor] = {}
    for source in sources:
        for descriptor in source.store_catalog:
            existing = descriptors.get(descriptor.store_id)
            if existing is not None and existing != descriptor:
                raise CanonicalSourceInvalid(
                    f"store_catalog_conflict:{descriptor.store_id}"
                )
            descriptors.setdefault(descriptor.store_id, descriptor)
    rows_by_store: dict[str, list[Mapping[str, object]]] = {}
    exact_store_rows: dict[str, Mapping[str, object]] = {}
    for role, rows in tables.items():
        for row in rows:
            store_id = row.get("store_id")
            if store_id in (None, ""):
                continue
            if (
                not isinstance(store_id, str)
                or store_id != store_id.strip()
                or not store_id
            ):
                raise CanonicalSourceInvalid("store_catalog_store_id_invalid")
            rows_by_store.setdefault(store_id, []).append(row)
            if role == "stores":
                previous = exact_store_rows.get(store_id)
                if previous is not None and _comparison_value(previous) != _comparison_value(row):
                    raise CanonicalSourceInvalid(
                        f"store_catalog_conflict:{store_id}"
                    )
                exact_store_rows[store_id] = row
    for store_id in sorted(rows_by_store):
        if store_id in descriptors:
            continue
        descriptors[store_id] = _inferred_store_descriptor(
            store_id,
            rows_by_store[store_id],
            exact_store_rows.get(store_id),
        )
    if len(descriptors) > 32:
        raise CanonicalSourceInvalid("store_catalog_too_large")
    return [
        {
            "currency": descriptor.currency,
            "display_name_en": descriptor.display_name_en,
            "display_name_zh": descriptor.display_name_zh,
            "has_data": descriptor.has_data,
            "lifecycle": descriptor.lifecycle,
            "opened_on": (
                descriptor.opened_on.isoformat()
                if descriptor.opened_on is not None
                else None
            ),
            "store_id": descriptor.store_id,
        }
        for descriptor in descriptors.values()
    ]


def _inferred_store_descriptor(
    store_id: str,
    rows: Sequence[Mapping[str, object]],
    exact: Mapping[str, object] | None,
) -> StoreDescriptor:
    currencies = {
        str(row["currency"])
        for row in rows
        if isinstance(row.get("currency"), str) and row["currency"]
    }
    if len(currencies) > 1:
        raise CanonicalSourceInvalid(f"store_catalog_currency_conflict:{store_id}")
    currency = next(iter(currencies), "BRL")
    display_name_en = store_id
    display_name_zh = store_id
    opened_on = None
    lifecycle = "established"
    has_data = True
    if exact is not None:
        display_name_en = _catalog_text(exact.get("display_name_en"), store_id)
        display_name_zh = _catalog_text(exact.get("display_name_zh"), store_id)
        currency = _catalog_text(exact.get("currency"), currency)
        raw_opened_on = exact.get("opened_on")
        try:
            opened_on = (
                date.fromisoformat(raw_opened_on)
                if isinstance(raw_opened_on, str) and raw_opened_on
                else raw_opened_on
                if isinstance(raw_opened_on, date)
                else None
            )
        except ValueError as error:
            raise CanonicalSourceInvalid("store_catalog_opened_on_invalid") from error
        raw_lifecycle = exact.get("lifecycle", lifecycle)
        if raw_lifecycle not in {"established", "new"}:
            raise CanonicalSourceInvalid("store_catalog_lifecycle_invalid")
        lifecycle = raw_lifecycle
        raw_has_data = exact.get("has_data", True)
        if not isinstance(raw_has_data, bool):
            raise CanonicalSourceInvalid("store_catalog_has_data_invalid")
        has_data = raw_has_data
    return StoreDescriptor(
        store_id=store_id,
        display_name_en=display_name_en,
        display_name_zh=display_name_zh,
        currency=currency,
        opened_on=opened_on,
        lifecycle=lifecycle,
        has_data=has_data,
    )


def _catalog_text(value: object, fallback: str) -> str:
    if value in (None, ""):
        return fallback
    if not isinstance(value, str) or value != value.strip():
        raise CanonicalSourceInvalid("store_catalog_text_invalid")
    return value
