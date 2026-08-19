"""Bounded synthetic Shopee-style advertising CSV adapter."""

from __future__ import annotations

import csv
import json
from io import StringIO
from time import monotonic

from src.adapters.protocol import (
    AdapterLimits,
    RecognitionResult,
    SourceShapeInvalid,
    StandardizedArtifact,
)
from src.adapters.validation import canonicalize_role_records, validate_mapping
from src.services.canonical_contracts import RowOrigin
from src.synthetic.boundary import (
    validate_safe_import_records,
    validate_synthetic_records,
)

MAX_ROWS = 20_000
MAX_COLUMNS = 64
MAX_CELL_CHARS = 4_096
MAX_PARSE_SECONDS = 5.0
CORE_REQUIRED_FIELDS = {
    "date",
    "sku_id",
    "spend_brl",
    "impressions",
    "clicks",
    "attributed_orders",
}
REQUIRED_FIELDS = CORE_REQUIRED_FIELDS | {"source_classification"}
ALLOWED_FIELDS = REQUIRED_FIELDS | {"store_id", "scenario_id"}


class ShopeeAdvertisingCsvAdapter:
    adapter_id = "shopee_advertising_csv"
    adapter_version = "1.0.0"
    canonical_schema = "canonical.import.v1"
    limits = AdapterLimits(
        max_rows=MAX_ROWS,
        max_columns=MAX_COLUMNS,
        max_cell_chars=MAX_CELL_CHARS,
        max_parse_seconds=MAX_PARSE_SECONDS,
    )

    def recognizes(
        self,
        filename: str,
        media_type: str,
        content: bytes,
        source_kind: str = "legacy_synthetic",
    ) -> bool:
        if not filename.lower().endswith(".csv") or media_type != "text/csv":
            return False
        try:
            headers, _records = _parse(content, source_kind)
        except SourceShapeInvalid:
            return False
        required = (
            REQUIRED_FIELDS
            if source_kind == "legacy_synthetic"
            else CORE_REQUIRED_FIELDS
        )
        return required <= set(headers)

    def recognize(
        self,
        content: bytes,
        source_kind: str = "legacy_synthetic",
    ) -> RecognitionResult:
        headers, records = _parse(content, source_kind)
        required = (
            REQUIRED_FIELDS
            if source_kind == "legacy_synthetic"
            else CORE_REQUIRED_FIELDS
        )
        if not required <= set(headers):
            raise SourceShapeInvalid("advertising_required_fields_missing")
        return RecognitionResult(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            source_role="shopee_advertising",
            record_count=len(records),
            source_fields=headers,
            suggested_mapping={field: field for field in headers},
            details={"delimiter": ",", "canonical_schema": self.canonical_schema},
        )

    def standardize(
        self,
        content: bytes,
        mapping: dict[str, str],
        source_kind: str = "legacy_synthetic",
        *,
        source_name: str = "source",
    ) -> StandardizedArtifact:
        headers, records = _parse(content, source_kind)
        validate_mapping(
            set(headers),
            mapping,
            allowed_fields=ALLOWED_FIELDS,
            roles=("shopee_advertising",),
        )
        canonical = [
            {mapping[field]: value for field, value in record.items()}
            for record in records
        ]
        canonical = canonicalize_role_records("shopee_advertising", canonical)
        payload = {
            "schema_version": "canonical.import.v1",
            "source_classification": (
                "pure_synthetic"
                if source_kind == "legacy_synthetic"
                else "operator_upload"
            ),
            "tables": {"shopee_advertising": canonical},
            "row_provenance": {
                "shopee_advertising": [
                    RowOrigin(
                        source_kind="upload",
                        source_name=source_name,
                        sheet_name=None,
                        row_number=row_number,
                    ).safe_projection()
                    for row_number in range(2, len(canonical) + 2)
                ]
            },
        }
        serialized = (
            json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        return StandardizedArtifact(
            content=serialized,
            record_count=len(canonical),
            preview_records=tuple(canonical[:25]),
            quality_report={
                "status": "passed",
                "record_count": len(canonical),
                "missing_required_fields": [],
            },
        )


def _parse(
    content: bytes,
    source_kind: str = "legacy_synthetic",
) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    started = monotonic()
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise SourceShapeInvalid("csv_must_be_utf8") from error
    reader = csv.DictReader(StringIO(text, newline=""))
    headers = tuple(reader.fieldnames or ())
    if not headers or len(headers) > MAX_COLUMNS or len(set(headers)) != len(headers):
        raise SourceShapeInvalid("csv_headers_invalid")
    if not set(headers) <= ALLOWED_FIELDS:
        raise SourceShapeInvalid("csv_field_not_allowed")
    records = []
    for record in reader:
        if len(records) >= MAX_ROWS:
            raise SourceShapeInvalid("csv_row_limit_exceeded")
        if monotonic() - started > MAX_PARSE_SECONDS:
            raise SourceShapeInvalid("csv_parse_budget_exceeded")
        if None in record or any(record.get(field) is None for field in headers):
            raise SourceShapeInvalid("csv_column_count_mismatch")
        normalized = {field: record.get(field, "") for field in headers}
        if any(len(value or "") > MAX_CELL_CHARS for value in normalized.values()):
            raise SourceShapeInvalid("csv_cell_limit_exceeded")
        records.append(normalized)
    if not records:
        raise SourceShapeInvalid("csv_has_no_records")
    validator = (
        validate_synthetic_records
        if source_kind == "legacy_synthetic"
        else validate_safe_import_records
    )
    validator(records)
    return headers, records
