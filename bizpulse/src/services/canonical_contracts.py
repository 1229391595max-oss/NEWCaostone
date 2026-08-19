"""Immutable contracts shared by canonical assembly and store-scoped features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import PurePath
from typing import Literal


@dataclass(frozen=True, slots=True)
class RowOrigin:
    source_kind: Literal["base", "upload"]
    source_name: str
    sheet_name: str | None
    row_number: int | None

    def __post_init__(self) -> None:
        if (
            not self.source_name
            or PurePath(self.source_name).name != self.source_name
            or any(ord(character) < 0x20 for character in self.source_name)
        ):
            raise ValueError("row_origin_source_name_invalid")
        if self.sheet_name is not None and (
            not self.sheet_name
            or any(ord(character) < 0x20 for character in self.sheet_name)
        ):
            raise ValueError("row_origin_sheet_name_invalid")
        if self.row_number is not None and (
            type(self.row_number) is not int or self.row_number < 1
        ):
            raise ValueError("row_origin_row_number_invalid")

    def safe_projection(self) -> dict[str, object]:
        """Exclude internal ingestion authority from serialized provenance."""

        return {
            "source_name": self.source_name,
            "sheet_name": self.sheet_name,
            "row_number": self.row_number,
        }


@dataclass(frozen=True, slots=True)
class DedupeConflict:
    role: str
    business_key: tuple[tuple[str, str], ...]
    fields: tuple[str, ...]
    existing: RowOrigin
    incoming: RowOrigin


@dataclass(frozen=True, slots=True)
class DedupeSummary:
    rows_read: int
    rows_retained: int
    duplicates_removed: int
    conflicts: int
    per_role: dict[str, dict[str, int]]


@dataclass(frozen=True, slots=True)
class StoreDescriptor:
    store_id: str
    display_name_en: str
    display_name_zh: str
    currency: str
    opened_on: date | None
    lifecycle: Literal["established", "new"]
    has_data: bool


@dataclass(frozen=True, slots=True)
class StoreScope:
    kind: Literal["all", "single"]
    store_ids: tuple[str, ...]
