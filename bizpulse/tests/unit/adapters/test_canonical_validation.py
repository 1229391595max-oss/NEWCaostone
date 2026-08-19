from __future__ import annotations

import json
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
import xlsxwriter

from src.adapters.protocol import MappingInvalid, SourceShapeInvalid
from src.adapters.shopee_advertising_csv import ShopeeAdvertisingCsvAdapter
from src.adapters.upseller_excel import UpsellerCsvAdapter, UpsellerExcelAdapter
from src.synthetic.boundary import SyntheticSourceBoundaryError
from tests.import_support import fixture_bytes


def test_mapping_rejects_duplicate_canonical_targets() -> None:
    adapter = ShopeeAdvertisingCsvAdapter()
    content = fixture_bytes("advertising.csv")
    mapping = adapter.recognize(content).suggested_mapping
    mapping["sku_id"] = "date"

    with pytest.raises(MappingInvalid, match="mapping_targets_must_be_unique"):
        adapter.standardize(content, mapping)


def test_advertising_rejects_negative_numeric_value() -> None:
    adapter = ShopeeAdvertisingCsvAdapter()
    content = (
        "date,sku_id,spend_brl,impressions,clicks,attributed_orders,"
        "source_classification\n"
        "2026-07-01,SYNTH-SKU-001,-1,100,10,2,pure_synthetic\n"
    ).encode()
    mapping = adapter.recognize(content).suggested_mapping

    with pytest.raises(SourceShapeInvalid, match="canonical_decimal_invalid"):
        adapter.standardize(content, mapping)


def test_mapping_rejects_semantic_identifier_swap() -> None:
    adapter = UpsellerCsvAdapter()
    content = fixture_bytes("sales.csv")
    mapping = adapter.recognize(content).suggested_mapping
    mapping["order_id"] = "sku_id"
    mapping["sku_id"] = "order_id"

    with pytest.raises(MappingInvalid, match="mapping_semantic_mismatch"):
        adapter.standardize(content, mapping)


def test_xlsx_sheet_rejects_classification_only_shape() -> None:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("Daily Sales")
    worksheet.write_row(0, 0, ["source_classification"])
    worksheet.write_row(1, 0, ["pure_synthetic"])
    workbook.close()

    with pytest.raises(SourceShapeInvalid, match="xlsx_headers_invalid"):
        UpsellerExcelAdapter().recognize(output.getvalue())


def test_declared_xlsx_allows_standard_openxml_structural_uris() -> None:
    result = UpsellerExcelAdapter().recognize(fixture_bytes("operator_import.xlsx"))
    manifest = json.loads(fixture_bytes("manifest.json"))
    expected = next(
        file["row_count"]
        for file in manifest["files"]
        if file["path"] == "operator_import.xlsx"
    )

    assert result.record_count == expected


@pytest.mark.parametrize("active_content", ["hyperlink", "comment"])
def test_xlsx_rejects_retained_active_parts(active_content: str) -> None:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("Daily Sales")
    headers = [
        "date",
        "order_id",
        "store_id",
        "sku_id",
        "units",
        "gross_sales_brl",
        "source_classification",
    ]
    worksheet.write_row(0, 0, headers)
    worksheet.write_row(
        1,
        0,
        [
            "2026-07-01",
            "SYNTH-ORDER-001",
            "SYNTH-STORE-01",
            "SYNTH-SKU-001",
            1,
            10,
            "pure_synthetic",
        ],
    )
    if active_content == "hyperlink":
        worksheet.write_url(1, 7, "https://invalid.test")
    else:
        worksheet.write_comment(1, 7, "person@example.test")
    workbook.close()

    with pytest.raises(SourceShapeInvalid, match="not_allowed"):
        UpsellerExcelAdapter().recognize(output.getvalue())


def test_xlsx_metadata_is_checked_for_sensitive_values() -> None:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    workbook.set_properties({"author": "person@example.test"})
    worksheet = workbook.add_worksheet("Daily Sales")
    worksheet.write_row(
        0,
        0,
        [
            "date",
            "order_id",
            "store_id",
            "sku_id",
            "units",
            "gross_sales_brl",
            "source_classification",
        ],
    )
    worksheet.write_row(
        1,
        0,
        [
            "2026-07-01",
            "SYNTH-ORDER-001",
            "SYNTH-STORE-01",
            "SYNTH-SKU-001",
            1,
            10,
            "pure_synthetic",
        ],
    )
    workbook.close()

    with pytest.raises(SyntheticSourceBoundaryError) as captured:
        UpsellerExcelAdapter().recognize(output.getvalue())

    assert "person@example.test" not in str(captured.value)


def test_xlsx_rejects_sensitive_unreferenced_shared_string() -> None:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("Daily Sales")
    worksheet.write_row(
        0,
        0,
        [
            "date",
            "order_id",
            "store_id",
            "sku_id",
            "units",
            "gross_sales_brl",
            "source_classification",
        ],
    )
    worksheet.write_row(
        1,
        0,
        [
            "2026-07-01",
            "SYNTH-ORDER-001",
            "SYNTH-STORE-01",
            "SYNTH-SKU-001",
            1,
            10,
            "pure_synthetic",
        ],
    )
    workbook.close()
    modified = BytesIO()
    with ZipFile(BytesIO(output.getvalue())) as source, ZipFile(
        modified,
        "w",
        ZIP_DEFLATED,
    ) as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "xl/sharedStrings.xml":
                content = content.replace(
                    b"</sst>",
                    b"<si><t>person@example.test</t></si></sst>",
                )
            target.writestr(entry, content)

    with pytest.raises(SyntheticSourceBoundaryError) as captured:
        UpsellerExcelAdapter().recognize(modified.getvalue())

    assert "person@example.test" not in str(captured.value)


@pytest.mark.parametrize(
    "hidden_value",
    [
        "person@example.test",
        "sk-proj-secretvalue12345",
        "Rua das Flores, 123",
    ],
)
def test_xlsx_rejects_sensitive_comment_in_retained_styles_part(
    hidden_value: str,
) -> None:
    source_content = fixture_bytes("operator_import.xlsx")
    modified = BytesIO()
    with ZipFile(BytesIO(source_content)) as source, ZipFile(
        modified,
        "w",
        ZIP_DEFLATED,
    ) as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "xl/styles.xml":
                content = content.replace(
                    b"</styleSheet>",
                    f"<!--{hidden_value}--></styleSheet>".encode(),
                )
            target.writestr(entry, content)

    with pytest.raises(SyntheticSourceBoundaryError) as captured:
        UpsellerExcelAdapter().recognize(modified.getvalue())

    assert hidden_value not in str(captured.value)


def test_xlsx_rejects_duplicate_entry_that_could_shadow_sensitive_content() -> None:
    source_content = fixture_bytes("operator_import.xlsx")
    modified = BytesIO()
    with pytest.warns(UserWarning, match="Duplicate name"):
        with ZipFile(BytesIO(source_content)) as source, ZipFile(
            modified,
            "w",
            ZIP_DEFLATED,
        ) as target:
            for entry in source.infolist():
                content = source.read(entry.filename)
                if entry.filename == "xl/styles.xml":
                    target.writestr(
                        entry,
                        content.replace(
                            b"</styleSheet>",
                            b"<!--person@example.test--></styleSheet>",
                        ),
                    )
                target.writestr(entry, content)

    with pytest.raises(SourceShapeInvalid, match="xlsx_zip_entry_name_collision"):
        UpsellerExcelAdapter().recognize(modified.getvalue())
