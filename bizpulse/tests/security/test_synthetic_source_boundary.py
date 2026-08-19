from __future__ import annotations

from pathlib import Path

from src.services.canonical_contracts import RowOrigin
from src.synthetic.generator import generate_and_write
from src.synthetic.manifest import verify_bundle_directory
from src.synthetic.boundary import (
    SyntheticSourceBoundaryError,
    validate_safe_import_records,
)


def test_generated_bundle_passes_source_boundary(tmp_path: Path) -> None:
    target = tmp_path / "bundle"
    generate_and_write(target, seed=20260813)

    assert verify_bundle_directory(target) == ()


def test_scanner_reports_rule_and_location_without_echoing_value(
    tmp_path: Path,
) -> None:
    target = tmp_path / "bundle"
    generate_and_write(target, seed=20260813)
    forbidden_value = "person@example.test"
    with (target / "stores.csv").open("a", encoding="utf-8") as stream:
        stream.write(f"SYNTH-STORE-99,Unsafe,{forbidden_value},pure_synthetic\n")

    violations = verify_bundle_directory(target)
    rendered = "\n".join(str(violation) for violation in violations)

    assert any(violation.rule == "email_pattern" for violation in violations)
    assert any(violation.rule == "sha256_mismatch" for violation in violations)
    assert forbidden_value not in rendered


def test_scanner_rejects_undeclared_files_and_forbidden_source_labels(
    tmp_path: Path,
) -> None:
    target = tmp_path / "bundle"
    generate_and_write(target, seed=20260813)
    (target / "undeclared.csv").write_text(
        "source\ngoogle_trends\n",
        encoding="utf-8",
    )

    violations = verify_bundle_directory(target)

    assert any(violation.rule == "undeclared_file" for violation in violations)
    assert any(
        violation.rule == "forbidden_source_label" for violation in violations
    )


def test_safe_operator_boundary_allows_business_ids_but_rejects_sensitive_columns(
) -> None:
    validate_safe_import_records(
        ({"store_id": "BR-STORE-01", "sku_id": "SKU-001"},)
    )

    for field in ("customer_email", "api_key", "delivery_address"):
        try:
            validate_safe_import_records(({field: ""},))
        except SyntheticSourceBoundaryError as error:
            assert error.field == f"row1.{field}"
        else:
            raise AssertionError(f"sensitive column accepted: {field}")


def test_row_provenance_projection_contains_no_internal_ingestion_metadata() -> None:
    projection = RowOrigin(
        source_kind="upload",
        source_name="sales.xlsx",
        sheet_name="Daily Sales",
        row_number=2,
    ).safe_projection()

    assert projection == {
        "source_name": "sales.xlsx",
        "sheet_name": "Daily Sales",
        "row_number": 2,
    }
    rendered = str(projection).lower()
    assert all(
        forbidden not in rendered
        for forbidden in ("blob", "sha256", "staging", "credential", "source_kind")
    )
