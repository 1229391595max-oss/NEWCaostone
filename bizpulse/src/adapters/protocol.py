"""Contracts for bounded recognition and canonical standardization."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class AdapterError(ValueError):
    code = "ADAPTER_ERROR"


class UnsupportedSource(AdapterError):
    code = "UNSUPPORTED_SOURCE"


class SourceShapeInvalid(AdapterError):
    code = "SOURCE_SHAPE_INVALID"


class MappingInvalid(AdapterError):
    code = "MAPPING_INVALID"


class ParserBusy(AdapterError):
    code = "PARSER_BUSY"


@dataclass(frozen=True, slots=True)
class AdapterLimits:
    max_rows: int
    max_columns: int
    max_cell_chars: int
    max_parse_seconds: float
    max_expanded_bytes: int | None = None
    max_sheets: int | None = None


@dataclass(frozen=True, slots=True)
class RecognitionResult:
    adapter_id: str
    adapter_version: str
    source_role: str
    record_count: int
    source_fields: tuple[str, ...]
    suggested_mapping: dict[str, str]
    details: dict[str, object]

    def projection(self) -> dict[str, object]:
        return {
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "source_role": self.source_role,
            "record_count": self.record_count,
            "source_fields": list(self.source_fields),
            "suggested_mapping": dict(self.suggested_mapping),
            "details": self.details,
        }


@dataclass(frozen=True, slots=True)
class StandardizedArtifact:
    content: bytes
    record_count: int
    preview_records: tuple[dict[str, object], ...]
    quality_report: dict[str, object]


class SourceAdapter(Protocol):
    adapter_id: str
    adapter_version: str
    canonical_schema: str
    limits: AdapterLimits

    def recognizes(
        self,
        filename: str,
        media_type: str,
        content: bytes,
        source_kind: str = "legacy_synthetic",
    ) -> bool: ...

    def recognize(
        self,
        content: bytes,
        source_kind: str = "legacy_synthetic",
    ) -> RecognitionResult: ...

    def standardize(
        self,
        content: bytes,
        mapping: dict[str, str],
        source_kind: str = "legacy_synthetic",
        *,
        source_name: str = "source",
    ) -> StandardizedArtifact: ...
