"""Bounded Demo-only XLSX action export."""

from __future__ import annotations

from datetime import UTC
from io import BytesIO
import xlsxwriter

from src.actions.contracts import ActionCard

MAX_EXPORT_BYTES = 2 * 1024 * 1024


def safe_cell(value: object) -> object:
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def build_action_xlsx(card: ActionCard) -> bytes:
    revision = card.revisions[-1]
    output = BytesIO()
    workbook = xlsxwriter.Workbook(
        output,
        {
            "in_memory": True,
            "constant_memory": False,
            "strings_to_formulas": False,
            "strings_to_urls": False,
        },
    )
    created_at = card.created_at or revision.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)
    workbook.set_properties(
        {
            "author": "BizPulse",
            "created": created_at.replace(tzinfo=None),
        }
    )
    sheet = workbook.add_worksheet("Demo Action")
    banner = workbook.add_format({"bold": True, "bg_color": "#FFF2CC"})
    sheet.write(0, 0, "SYNTHETIC DEMO ONLY", banner)
    sheet.write(1, 0, "Not sent to an external platform", banner)
    rows = (
        ("Action ID", f"SYNTH-ACTION-{card.id}"),
        ("Dataset version", str(card.dataset_version_id)),
        ("Status", card.status),
        ("Revision", revision.revision),
        ("Suggestion", revision.suggestion),
        ("Target", revision.target),
        ("Period", f"{revision.period_start}/{revision.period_end}"),
        ("Quantity", str(revision.quantity) if revision.quantity is not None else "Unknown"),
        ("Budget BRL", str(revision.budget_brl) if revision.budget_brl is not None else "Unknown"),
        ("Action date", revision.action_date.isoformat() if revision.action_date else "Unknown"),
        ("Threshold", str(revision.threshold) if revision.threshold is not None else "Unknown"),
        ("Expected impact", str(revision.expected_impact)),
        ("Confidence", revision.confidence),
        ("Limitations", "; ".join(revision.limitations)),
        ("Decision", card.decisions[-1].command if card.decisions else "Unknown"),
        ("Decision reason", card.decisions[-1].reason if card.decisions else "Unknown"),
        ("Evidence", "; ".join(f"{fact.alias}:{fact.source_ref}" for fact in revision.facts)),
    )
    for offset, (label, value) in enumerate(rows, start=3):
        sheet.write(offset, 0, label)
        sheet.write(offset, 1, safe_cell(value))
    sheet.set_column(0, 0, 22)
    sheet.set_column(1, 1, 80)
    workbook.close()
    content = output.getvalue()
    if not content or len(content) > MAX_EXPORT_BYTES:
        raise ValueError("action_export_size_invalid")
    return content
