"""Closed, single-concurrency adapter registry."""

from __future__ import annotations

from threading import BoundedSemaphore

from src.adapters.protocol import (
    ParserBusy,
    RecognitionResult,
    SourceAdapter,
    StandardizedArtifact,
    UnsupportedSource,
)
from src.adapters.shopee_advertising_csv import ShopeeAdvertisingCsvAdapter
from src.adapters.upseller_excel import UpsellerCsvAdapter, UpsellerExcelAdapter


class AdapterRegistry:
    def __init__(self, adapters: tuple[SourceAdapter, ...] | None = None) -> None:
        self._adapters = adapters or (
            UpsellerExcelAdapter(),
            ShopeeAdvertisingCsvAdapter(),
            UpsellerCsvAdapter(),
        )
        self._parser_slot = BoundedSemaphore(1)

    def inspect(
        self,
        filename: str,
        media_type: str,
        content: bytes,
        source_kind: str = "legacy_synthetic",
    ) -> RecognitionResult:
        return self._bounded(
            lambda: self._inspect(filename, media_type, content, source_kind)
        )

    def _inspect(
        self,
        filename: str,
        media_type: str,
        content: bytes,
        source_kind: str,
    ) -> RecognitionResult:
        adapter = self._select(filename, media_type, content, source_kind)
        return adapter.recognize(content, source_kind)

    def standardize(
        self,
        adapter_id: str,
        content: bytes,
        mapping: dict[str, str],
        source_kind: str = "legacy_synthetic",
        *,
        source_name: str = "source",
    ) -> StandardizedArtifact:
        adapter = next(
            (candidate for candidate in self._adapters if candidate.adapter_id == adapter_id),
            None,
        )
        if adapter is None:
            raise UnsupportedSource("adapter_not_registered")
        return self._bounded(
            lambda: adapter.standardize(
                content,
                mapping,
                source_kind,
                source_name=source_name,
            )
        )

    def _select(
        self,
        filename: str,
        media_type: str,
        content: bytes,
        source_kind: str,
    ) -> SourceAdapter:
        matches = [
            adapter
            for adapter in self._adapters
            if adapter.recognizes(filename, media_type, content, source_kind)
        ]
        if len(matches) != 1:
            raise UnsupportedSource("source_not_supported")
        return matches[0]

    def _bounded(self, operation):
        if not self._parser_slot.acquire(blocking=False):
            raise ParserBusy("parser_busy")
        try:
            return operation()
        finally:
            self._parser_slot.release()
