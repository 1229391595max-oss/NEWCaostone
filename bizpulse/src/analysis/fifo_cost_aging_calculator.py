"""Deterministic FIFO allocation, cost coverage, and aging."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from src.analysis.evidence import Evidence, Metric, money, nonnegative_decimal, stable_hash

ALGORITHM_VERSION = "fifo_cost_aging.v1"


@dataclass(slots=True)
class _Lot:
    lot_id: str
    sku_id: str
    receipt_date: date
    remaining: int
    unit_cost: Decimal


@dataclass(frozen=True, slots=True)
class FifoAllocation:
    outbound_id: str
    lot_id: str
    sku_id: str
    quantity: int
    unit_cost: Decimal
    extended_cost: Decimal


@dataclass(frozen=True, slots=True)
class FifoCostAgingResult:
    algorithm_version: str
    as_of: date
    cogs: Metric
    ending_inventory_value: Metric
    aging_90_units: int | None
    aging_120_units: int | None
    allocations: tuple[FifoAllocation, ...]
    evidence: tuple[Evidence, ...]
    limitations: tuple[str, ...]
    snapshot_hash: str


def calculate_fifo_cost_aging(
    *,
    receipt_lots: Sequence[Mapping[str, object]],
    outbound_events: Sequence[Mapping[str, object]],
    as_of: date,
    period_start: date | None = None,
) -> FifoCostAgingResult:
    if not isinstance(as_of, date):
        raise ValueError("as_of_invalid")
    if period_start is not None and (
        not isinstance(period_start, date) or period_start > as_of
    ):
        raise ValueError("period_start_invalid")
    lots_present = bool(receipt_lots)
    outbound_present = bool(outbound_events)
    limitations: list[str] = []
    lots_by_sku: dict[str, list[_Lot]] = defaultdict(list)
    seen_lots: set[str] = set()
    for row in receipt_lots:
        lot_id = _text(row.get("lot_id"), "lot_id")
        if lot_id in seen_lots:
            raise ValueError(f"duplicate_lot:{lot_id}")
        seen_lots.add(lot_id)
        sku = _text(row.get("sku_id"), "sku_id")
        received = _whole(nonnegative_decimal(row.get("quantity_received"), "quantity_received"), "quantity_received")
        unit_cost = nonnegative_decimal(row.get("unit_cost_brl"), "unit_cost_brl")
        received_at = _iso_date(row.get("receipt_date"), "receipt_date")
        if received_at > as_of:
            limitations.append(f"future_receipt_excluded:{lot_id}")
            continue
        lots_by_sku[sku].append(_Lot(lot_id, sku, received_at, received, unit_cost))
    for lots in lots_by_sku.values():
        lots.sort(key=lambda lot: (lot.receipt_date, lot.lot_id))

    allocations: list[FifoAllocation] = []
    if not lots_present:
        limitations.append("receipt_lots_missing")
    if not outbound_present:
        limitations.append("outbound_events_missing")
    known_cogs = Decimal(0)
    uncovered = 0
    period_outbound_count = 0
    ordered_outbound: list[tuple[date, str, Mapping[str, object]]] = []
    for row in outbound_events:
        outbound_id = _text(row.get("outbound_id"), "outbound_id")
        outbound_date = _iso_date(row.get("date"), "date")
        if outbound_date > as_of:
            limitations.append(f"future_outbound_excluded:{outbound_id}")
            continue
        ordered_outbound.append((outbound_date, outbound_id, row))
    ordered_outbound.sort(key=lambda item: (item[0], item[1]))
    for outbound_date, outbound_id, row in ordered_outbound:
        in_period = period_start is None or outbound_date >= period_start
        if in_period:
            period_outbound_count += 1
        sku = _text(row.get("sku_id"), "sku_id")
        remaining = _whole(nonnegative_decimal(row.get("quantity"), "quantity"), "quantity")
        for lot in lots_by_sku.get(sku, ()):
            if not remaining:
                break
            if lot.receipt_date > outbound_date:
                continue
            used = min(remaining, lot.remaining)
            if not used:
                continue
            extended = money(Decimal(used) * lot.unit_cost)
            allocations.append(FifoAllocation(outbound_id, lot.lot_id, sku, used, money(lot.unit_cost), extended))
            if in_period:
                known_cogs += extended
            lot.remaining -= used
            remaining -= used
        if remaining:
            uncovered += remaining
            limitations.append(f"uncovered_outbound:{sku}:{remaining}")

    ending_value = money(
        sum((Decimal(lot.remaining) * lot.unit_cost for lots in lots_by_sku.values() for lot in lots), Decimal(0))
    )
    aging_90 = 0
    aging_120 = 0
    for lots in lots_by_sku.values():
        for lot in lots:
            age = (as_of - lot.receipt_date).days
            if age >= 90:
                aging_90 += lot.remaining
            if age >= 120:
                aging_120 += lot.remaining
    refs = ("fifo.allocations",)
    complete_sources = bool(lots_by_sku) and bool(ordered_outbound)
    complete_period_sources = bool(lots_by_sku) and bool(period_outbound_count)
    if period_start is not None and not period_outbound_count:
        limitations.append("period_outbound_events_missing")
    cogs = (
        Metric(money(known_cogs), "derived", refs, money(known_cogs))
        if not uncovered and complete_period_sources
        else Metric(None, "unknown", refs, money(known_cogs))
    )
    evidence = (
        Evidence("fifo.allocations", "derived" if cogs.value is not None else "unknown", "oldest eligible receipt_date then lot_id", ("inventory_receipt_lot", "outbound_event")),
        Evidence("fifo.aging", "derived" if complete_sources and not uncovered else "unknown", "as_of-receipt_date after outbound reconciliation", ("inventory_receipt_lot", "outbound_event")),
    )
    payload = {
        "algorithm_version": ALGORITHM_VERSION,
        "as_of": as_of,
        "period_start": period_start,
        "allocations": tuple(allocations),
        "cogs": cogs,
        "ending_inventory_value": ending_value,
        "aging_90_units": aging_90 if complete_sources and not uncovered else None,
        "aging_120_units": aging_120 if complete_sources and not uncovered else None,
        "limitations": tuple(limitations),
    }
    return FifoCostAgingResult(
        ALGORITHM_VERSION,
        as_of,
        cogs,
        Metric(ending_value, "derived", ("fifo.aging",))
        if complete_sources and not uncovered
        else Metric(None, "unknown", ("fifo.aging",), ending_value if lots_present else None),
        aging_90 if complete_sources and not uncovered else None,
        aging_120 if complete_sources and not uncovered else None,
        tuple(allocations),
        evidence,
        tuple(limitations),
        stable_hash(payload),
    )


def _iso_date(value: object, field: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{field}_invalid")
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field}_invalid") from error


def _whole(value: Decimal, field: str) -> int:
    if value != value.to_integral_value():
        raise ValueError(f"{field}_not_integer")
    return int(value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field}_invalid")
    return value.strip()
