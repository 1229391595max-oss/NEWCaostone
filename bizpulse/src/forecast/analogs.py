"""Deterministic analog ranking with component evidence."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal, ROUND_HALF_UP

from src.forecast.contracts import Analog, HistoricalSku, ProductCandidate

SIX_PLACES = Decimal("0.000001")


def select_analogs(
    candidate: ProductCandidate,
    catalog: Sequence[HistoricalSku],
) -> tuple[Analog, ...]:
    """Rank at most five synthetic catalog SKUs without external knowledge."""

    planned_net_price = candidate.planned_net_price_brl
    if planned_net_price <= 0:
        raise ValueError("planned_net_price_invalid")
    category = _token(candidate.category)
    attributes = _tokens(candidate.attributes)
    if not category:
        raise ValueError("candidate_category_invalid")
    seen: set[str] = set()
    analogs: list[Analog] = []
    for historical in catalog:
        if historical.sku_id in seen:
            raise ValueError("historical_sku_duplicate")
        seen.add(historical.sku_id)
        if historical.net_price_brl <= 0:
            continue
        historical_attributes = _tokens(historical.attributes)
        union = attributes | historical_attributes
        components = {
            "category_match": Decimal(
                int(category == _token(historical.category))
            ),
            "attribute_jaccard": (
                Decimal(len(attributes & historical_attributes))
                / Decimal(len(union))
                if union
                else Decimal("0")
            ),
            "price_proximity": max(
                Decimal("0"),
                Decimal("1")
                - abs(historical.net_price_brl - planned_net_price)
                / max(historical.net_price_brl, planned_net_price),
            ),
            "launch_window_coverage": min(
                Decimal("1"),
                Decimal(max(0, historical.history_days)) / Decimal("90"),
            ),
        }
        components = {
            key: value.quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
            for key, value in components.items()
        }
        score = (
            Decimal("0.45") * components["category_match"]
            + Decimal("0.25") * components["attribute_jaccard"]
            + Decimal("0.15") * components["price_proximity"]
            + Decimal("0.15") * components["launch_window_coverage"]
        ).quantize(SIX_PLACES, rounding=ROUND_HALF_UP)
        analogs.append(Analog(historical=historical, score=score, components=components))
    return tuple(
        sorted(analogs, key=lambda item: (-item.score, item.sku_id))[:5]
    )


def _token(value: str) -> str:
    return "_".join(str(value).strip().lower().replace("-", " ").split())


def _tokens(values: Sequence[str]) -> set[str]:
    return {token for value in values if (token := _token(value))}
