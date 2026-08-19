"""Bounded workbook export for one normalized dataset version."""

from __future__ import annotations

from io import BytesIO
import json
import re

import xlsxwriter

MAX_EXPORT_BYTES = 8 * 1024 * 1024
MAX_TABLES = 24
MAX_ROWS_PER_TABLE = 5_000


def safe_cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def build_dataset_workbook(version_number: int, tables) -> bytes:
    output = BytesIO()
    workbook = xlsxwriter.Workbook(
        output,
        {
            "in_memory": True,
            "strings_to_formulas": False,
            "strings_to_urls": False,
        },
    )
    heading = workbook.add_format({"bold": True, "bg_color": "#EEEAF8"})
    manifest = workbook.add_worksheet("Manifest")
    manifest.write_row(0, 0, ["BizPulse dataset export", f"Version {version_number}"], heading)
    manifest.write_row(2, 0, ["Table", "Rows", "Exported rows"], heading)
    used_names = {"Manifest"}
    for index, (role, rows) in enumerate(sorted(tables.items())[:MAX_TABLES], start=3):
        exported = rows[:MAX_ROWS_PER_TABLE]
        manifest.write_row(index, 0, [role, len(rows), len(exported)])
        name = _sheet_name(role, used_names)
        sheet = workbook.add_worksheet(name)
        columns = sorted({str(key) for row in exported for key in row})[:80]
        sheet.write_row(0, 0, columns, heading)
        for row_index, row in enumerate(exported, start=1):
            sheet.write_row(row_index, 0, [safe_cell(row.get(key)) for key in columns])
        sheet.freeze_panes(1, 0)
        sheet.autofilter(0, 0, max(len(exported), 1), max(len(columns) - 1, 0))
        sheet.set_column(0, max(len(columns) - 1, 0), 18)
    workbook.close()
    content = output.getvalue()
    if not content or len(content) > MAX_EXPORT_BYTES:
        raise ValueError("DATASET_EXPORT_SIZE_INVALID")
    return content


def _sheet_name(role: str, used: set[str]) -> str:
    base = re.sub(r"[\\/*?:\[\]]", "_", role)[:31] or "Table"
    name = base
    counter = 2
    while name in used:
        suffix = f" {counter}"
        name = base[: 31 - len(suffix)] + suffix
        counter += 1
    used.add(name)
    return name
