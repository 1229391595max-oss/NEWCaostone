from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from src.adapters.validation import canonicalize_role_records
from src.services.business_keys import BusinessKeyIncomplete
from src.services.canonical_contracts import StoreDescriptor
from src.services.canonical_dataset_assembler import (
    CanonicalDatasetAssembler,
    CanonicalSource,
)


def _sale(
    order_id: str,
    *,
    units: object = 1,
    gross: object = "10",
    classification: str = "operator_upload",
) -> dict[str, object]:
    return {
        "date": "2026-07-01",
        "order_id": order_id,
        "store_id": "S1",
        "sku_id": "K1",
        "units": units,
        "gross_sales_brl": gross,
        "source_classification": classification,
    }


def _source(
    source_kind: str,
    source_name: str,
    rows: list[dict[str, object]],
    *,
    sheets: tuple[str | None, ...] | None = None,
    created_at: datetime | None = None,
    store_catalog: tuple[StoreDescriptor, ...] = (),
) -> CanonicalSource:
    sheet_names = sheets or tuple("Daily Sales" for _row in rows)
    return CanonicalSource(
        source_kind=source_kind,
        source_name=source_name,
        created_at=created_at,
        tables={"daily_sales": rows},
        row_provenance={
            "daily_sales": [
                {
                    "source_name": source_name,
                    "sheet_name": sheet_name,
                    "row_number": index + 2,
                }
                for index, sheet_name in enumerate(sheet_names)
            ]
        },
        store_catalog=store_catalog,
    )


def _payload(result) -> dict[str, object]:
    return json.loads(result.content)


def test_same_file_and_cross_sheet_exact_duplicates_keep_earliest_origin() -> None:
    source = _source(
        "upload",
        "sales.xlsx",
        [_sale("O1"), _sale("O1"), _sale("O1")],
        sheets=("Daily Sales", "Daily Sales", "Sales Archive"),
        created_at=datetime(2026, 8, 16, 10, tzinfo=UTC),
    )

    result = CanonicalDatasetAssembler().assemble(base=None, uploads=(source,))

    payload = _payload(result)
    assert result.summary.rows_read == 3
    assert result.summary.rows_retained == 1
    assert result.summary.duplicates_removed == 2
    assert result.summary.conflicts == 0
    assert payload["tables"]["daily_sales"] == [_sale("O1")]
    assert payload["row_provenance"]["daily_sales"] == [
        {
            "source_kind": "upload",
            "source_name": "sales.xlsx",
            "sheet_name": "Daily Sales",
            "row_number": 2,
        }
    ]


def test_base_precedes_cross_file_upload_and_internal_metadata_is_ignored() -> None:
    base = _source(
        "base",
        "version-1",
        [_sale("O1", classification="pure_synthetic")],
    )
    upload = _source(
        "upload",
        "sales.csv",
        [_sale("O1", classification="operator_upload")],
        created_at=datetime(2026, 8, 16, 11, tzinfo=UTC),
    )

    result = CanonicalDatasetAssembler().assemble(base=base, uploads=(upload,))

    assert result.summary.duplicates_removed == 1
    assert _payload(result)["row_provenance"]["daily_sales"][0]["source_kind"] == "base"


def test_same_key_with_different_business_value_blocks_committable_content() -> None:
    base = _source("base", "version-1", [_sale("O1", units=1)])
    upload = _source(
        "upload",
        "sales.csv",
        [_sale("O1", units=2)],
        created_at=datetime(2026, 8, 16, 11, tzinfo=UTC),
    )

    result = CanonicalDatasetAssembler().assemble(base=base, uploads=(upload,))

    assert result.content == b""
    assert result.sha256 == ""
    assert result.summary.conflicts == 1
    assert result.conflicts[0].role == "daily_sales"
    assert result.conflicts[0].business_key == (
        ("store_id", "S1"),
        ("order_id", "O1"),
        ("sku_id", "K1"),
    )
    assert result.conflicts[0].fields == ("units",)
    assert result.conflicts[0].existing.source_kind == "base"
    assert result.conflicts[0].incoming.source_name == "sales.csv"


def test_output_order_and_sha_are_stable_across_unsorted_upload_arguments() -> None:
    later = _source(
        "upload",
        "b.csv",
        [_sale("O2")],
        created_at=datetime(2026, 8, 16, 12, tzinfo=UTC),
    )
    earlier = _source(
        "upload",
        "a.csv",
        [_sale("O1")],
        created_at=datetime(2026, 8, 16, 11, tzinfo=UTC),
    )
    assembler = CanonicalDatasetAssembler()

    first = assembler.assemble(base=None, uploads=(later, earlier))
    second = assembler.assemble(base=None, uploads=(earlier, later))

    assert first.content == second.content
    assert first.sha256 == second.sha256
    assert [row["order_id"] for row in _payload(first)["tables"]["daily_sales"]] == [
        "O1",
        "O2",
    ]


def test_assembly_is_idempotent_and_prefers_base_origin() -> None:
    catalog = (
        StoreDescriptor(
            store_id="S1",
            display_name_en="Main Store",
            display_name_zh="主店",
            currency="BRL",
            opened_on=date(2025, 1, 1),
            lifecycle="established",
            has_data=True,
        ),
    )
    base = _source("base", "version-1", [_sale("O1")], store_catalog=catalog)
    duplicate = _source(
        "upload",
        "sales.csv",
        [_sale("O1")],
        created_at=datetime(2026, 8, 16, 11, tzinfo=UTC),
    )
    assembler = CanonicalDatasetAssembler()

    first = assembler.assemble(base=base, uploads=(duplicate,))
    payload = _payload(first)
    rebased = CanonicalSource(
        source_kind="base",
        source_name="version-2",
        tables=payload["tables"],
        row_provenance=payload["row_provenance"],
        store_catalog=catalog,
    )
    second = assembler.assemble(base=rebased, uploads=())

    assert first.content == second.content
    assert first.sha256 == second.sha256
    assert first.summary.duplicates_removed == 1
    assert payload["row_provenance"]["daily_sales"][0]["source_kind"] == "base"
    assert payload["store_catalog"][0]["opened_on"] == "2025-01-01"


def test_assembly_materializes_missing_store_catalog_from_exact_rows() -> None:
    explicit = StoreDescriptor(
        store_id="S1",
        display_name_en="Main Store",
        display_name_zh="主店",
        currency="BRL",
        opened_on=date(2025, 1, 1),
        lifecycle="established",
        has_data=True,
    )
    rows = [
        _sale("O1"),
        {**_sale("O2"), "store_id": "S2", "currency": "BRL"},
    ]

    result = CanonicalDatasetAssembler().assemble(
        base=None,
        uploads=(
            _source(
                "upload",
                "sales.csv",
                rows,
                store_catalog=(explicit,),
            ),
        ),
    )

    assert _payload(result)["store_catalog"] == [
        {
            "currency": "BRL",
            "display_name_en": "Main Store",
            "display_name_zh": "主店",
            "has_data": True,
            "lifecycle": "established",
            "opened_on": "2025-01-01",
            "store_id": "S1",
        },
        {
            "currency": "BRL",
            "display_name_en": "S2",
            "display_name_zh": "S2",
            "has_data": True,
            "lifecycle": "established",
            "opened_on": None,
            "store_id": "S2",
        },
    ]


def test_business_key_incomplete_never_falls_back_to_whole_row_hash() -> None:
    source = _source("upload", "sales.csv", [_sale("O1")])
    del source.tables["daily_sales"][0]["sku_id"]

    with pytest.raises(BusinessKeyIncomplete, match="business_key_incomplete"):
        CanonicalDatasetAssembler().assemble(base=None, uploads=(source,))


def test_adapter_normalized_numeric_spellings_are_exact_duplicates() -> None:
    normalized = [
        canonicalize_role_records(
            "daily_sales",
            [
                {
                    "date": "2026-07-01",
                    "order_id": "O1",
                    "store_id": "S1",
                    "sku_id": "K1",
                    "units": units,
                    "gross_sales_brl": gross,
                }
            ],
        )[0]
        for units, gross in (
            (5, 5),
            (5.0, 5.0),
            (Decimal("5.00"), Decimal("5.00")),
        )
    ]
    source = _source("upload", "sales.csv", normalized)

    result = CanonicalDatasetAssembler().assemble(base=None, uploads=(source,))

    assert result.summary.duplicates_removed == 2
    assert result.summary.rows_retained == 1


def test_legacy_numeric_strings_compare_as_normalized_numbers() -> None:
    base_row = _sale("O1")
    base_row["gross_sales_brl"] = "5.00"
    upload_row = _sale("O1")
    upload_row["gross_sales_brl"] = "5"

    result = CanonicalDatasetAssembler().assemble(
        base=_source("base", "base.json", [base_row]),
        uploads=(_source("upload", "sales.csv", [upload_row]),),
    )

    assert result.conflicts == ()
    assert result.summary.duplicates_removed == 1
