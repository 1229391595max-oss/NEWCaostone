"""Small immutable evidence contracts shared by deterministic calculators."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN
from hashlib import sha256
import json
from typing import Literal

EvidenceState = Literal["measured", "derived", "assumed", "unknown"]


@dataclass(frozen=True, slots=True)
class Metric:
    value: Decimal | None
    evidence_state: EvidenceState
    evidence_refs: tuple[str, ...]
    known_subtotal: Decimal | None = None


@dataclass(frozen=True, slots=True)
class Evidence:
    alias: str
    evidence_state: EvidenceState
    formula: str
    source_roles: tuple[str, ...]


def decimal_value(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"{field}_invalid")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError(f"{field}_invalid") from error
    if not result.is_finite():
        raise ValueError(f"{field}_invalid")
    return result


def nonnegative_decimal(value: object, field: str) -> Decimal:
    result = decimal_value(value, field)
    if result < 0:
        raise ValueError(f"{field}_negative")
    return result


def integer_value(value: object, field: str) -> int:
    result = decimal_value(value, field)
    integral = result.to_integral_value()
    if result != integral:
        raise ValueError(f"{field}_not_integer")
    return int(integral)


def money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def ratio(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN)


def stable_hash(value: object) -> str:
    return sha256(
        canonical_json_bytes(value)
    ).hexdigest()


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        canonical_value(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode()


def canonical_value(value: object) -> object:
    if is_dataclass(value):
        return canonical_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): canonical_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [canonical_value(item) for item in value]
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
