from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import permutations

from src.services.canonical_dataset_assembler import (
    CanonicalDatasetAssembler,
    CanonicalSource,
)


def _source(index: int) -> CanonicalSource:
    name = f"sales-{index}.csv"
    return CanonicalSource(
        source_kind="upload",
        source_name=name,
        created_at=datetime(2026, 8, 16, 10, tzinfo=UTC) + timedelta(minutes=index),
        tables={
            "daily_sales": [
                {
                    "date": "2026-07-01",
                    "order_id": f"O{index}",
                    "store_id": "S1",
                    "sku_id": "K1",
                    "units": index,
                    "gross_sales_brl": str(index * 10),
                }
            ]
        },
        row_provenance={
            "daily_sales": [
                {
                    "source_name": name,
                    "sheet_name": None,
                    "row_number": 2,
                }
            ]
        },
    )


def test_all_upload_permutations_produce_identical_bytes_and_sha() -> None:
    sources = tuple(_source(index) for index in range(1, 5))
    assembler = CanonicalDatasetAssembler()

    results = {
        (
            assembler.assemble(base=None, uploads=ordering).content,
            assembler.assemble(base=None, uploads=ordering).sha256,
        )
        for ordering in permutations(sources)
    }

    assert len(results) == 1


def test_repeating_the_same_upload_rows_only_changes_dedupe_counts() -> None:
    source = _source(1)
    repeated = CanonicalSource(
        source_kind="upload",
        source_name=source.source_name,
        created_at=source.created_at,
        tables={"daily_sales": source.tables["daily_sales"] * 20},
        row_provenance={
            "daily_sales": [
                {
                    "source_name": source.source_name,
                    "sheet_name": None,
                    "row_number": row_number,
                }
                for row_number in range(2, 22)
            ]
        },
    )

    result = CanonicalDatasetAssembler().assemble(base=None, uploads=(repeated,))

    assert result.summary.rows_read == 20
    assert result.summary.rows_retained == 1
    assert result.summary.duplicates_removed == 19
