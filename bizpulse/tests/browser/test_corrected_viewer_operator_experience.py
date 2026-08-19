from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GATE = PROJECT_ROOT / "scripts" / "browser_release_gate.mjs"


def test_real_browser_gate_keeps_corrected_experience_assertions_active() -> None:
    source = GATE.read_text()

    assert 'assertCorrectedBusinessExperience(viewer, "viewer")' in source
    assert 'assertCorrectedBusinessExperience(operator, "operator")' in source
    assert "evidence_not_collapsed_to_four" in source
    assert "inventory_risk_chart_not_removed" in source
    assert "inventory_row_dividers_misaligned" in source
    assert "settings_permission_boundary_invalid" in source
    assert "browser_api_key_field_present" in source
    assert "technical_label_visible" in source
    assert "compact_navigation_full_name_missing" in source
    assert "assertLibraryWorkbook(page, mode)" in source
    assert "library_card_wall_present" in source
    assert "library_detailed_table_count_invalid" in source
    assert "library_tab_switch_failed" in source
    assert "library_row_drawer_missing" in source
    assert "library_row_drawer_escape_failed" in source
    assert "library_horizontal_overflow" in source
    assert "library_decimal_format_invalid" in source
    assert "library_page_size_change_failed" in source
    assert "library_tab_keyboard_failed" in source
    assert "library_chinese_column_missing" in source
    assert "library_modal_focus_escape" in source
    assert "library_workbook_overflow" in source
