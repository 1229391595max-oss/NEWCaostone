"""Safe zero-real-data checks for operator-provided Demo uploads."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

EMAIL = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b", re.IGNORECASE)
PHONE = re.compile(r"(?:\+\d{8,15}|\b\d{10,15}\b)")
CREDENTIAL = re.compile(
    r"(?:sk-(?:proj-)?[A-Za-z0-9_-]{12,}|AccountKey=|postgres(?:ql)?://|"
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)",
    re.IGNORECASE,
)
URL = re.compile(r"https?://", re.IGNORECASE)
ADDRESS = re.compile(
    r"(?:\b\d{1,6}\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{1,80}\s+"
    r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|lane|ln|drive|dr)\b|"
    r"\b(?:rua|avenida|av\.?|travessa|alameda|rodovia)\s+"
    r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{1,80}(?:,?\s*\d{1,6})?\b)",
    re.IGNORECASE,
)
FORBIDDEN_SOURCE = re.compile(
    r"\b(?:google_trends|mercado_live|real|private)\b",
    re.IGNORECASE,
)
SENSITIVE_FIELD = re.compile(
    r"(?:^|_)(?:e?mail|phone|mobile|address|password|passwd|secret|token|"
    r"credential|api_?key|access_?key|private_?key)(?:$|_)",
    re.IGNORECASE,
)


class SyntheticSourceBoundaryError(ValueError):
    code = "SYNTHETIC_SOURCE_BOUNDARY_FAILED"

    def __init__(self, *, field: str, rule: str) -> None:
        self.field = field
        self.rule = rule
        super().__init__(f"{self.code}:{field}:{rule}")


def validate_synthetic_records(records: Iterable[Mapping[str, object]]) -> None:
    _validate_records(records, synthetic_only=True)


def validate_safe_import_records(records: Iterable[Mapping[str, object]]) -> None:
    """Reject secrets, personal data, formulas, and external links.

    Operator data may retain ordinary business identifiers and does not need a
    synthetic-data label. This is intentionally separate from the stricter
    prepared-Demo boundary.
    """

    _validate_records(records, synthetic_only=False)


def _validate_records(
    records: Iterable[Mapping[str, object]],
    *,
    synthetic_only: bool,
) -> None:
    for row_index, record in enumerate(records, start=1):
        for field, raw_value in record.items():
            value = "" if raw_value is None else str(raw_value)
            rule = _violating_rule(field, value, synthetic_only=synthetic_only)
            if rule is not None:
                raise SyntheticSourceBoundaryError(
                    field=f"row{row_index}.{field}",
                    rule=rule,
                )


def _violating_rule(
    field: str,
    value: str,
    *,
    synthetic_only: bool = True,
) -> str | None:
    normalized_field = field.strip().lower()
    field_name = normalized_field.rsplit(".", 1)[-1]
    if SENSITIVE_FIELD.search(field_name):
        return "sensitive_field"
    for pattern, rule in (
        (EMAIL, "email_pattern"),
        (PHONE, "phone_pattern"),
        (CREDENTIAL, "credential_pattern"),
        (URL, "external_url"),
        (ADDRESS, "address_pattern"),
    ):
        if pattern.search(value):
            return rule
    if synthetic_only:
        if FORBIDDEN_SOURCE.search(value):
            return "forbidden_source_label"
        if field_name == "source_classification" and value != "pure_synthetic":
            return "source_classification_invalid"
        if field_name.endswith("_id") and value:
            if field_name == "scenario_id":
                if not re.fullmatch(r"[a-z][a-z0-9_]{1,63}", value):
                    return "unapproved_identifier"
            elif not value.startswith("SYNTH-"):
                return "unapproved_identifier"
    if value.startswith(("=", "+", "@")):
        return "formula_pattern"
    if value.startswith("-") and not re.fullmatch(r"-\d+(?:\.\d+)?", value):
        return "formula_pattern"
    return None
