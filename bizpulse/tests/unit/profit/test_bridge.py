from datetime import date
from decimal import Decimal

from src.profit.bridge import DRIVER_ORDER, build_profit_bridge
from src.profit.contracts import ProfitPeriod, ProfitSku


def _period(
    *,
    current: bool,
    fulfillment_brl: Decimal | None = None,
) -> ProfitPeriod:
    if current:
        return ProfitPeriod(
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            skus=(
                ProfitSku("SYNTH-SKU-001", 12, Decimal("105"), Decimal("42")),
                ProfitSku("SYNTH-SKU-002", 8, Decimal("75"), Decimal("28")),
            ),
            contribution_profit_brl=Decimal("891.00"),
            platform_fee_brl=Decimal("110.00"),
            advertising_brl=Decimal("60.00"),
            refund_loss_brl=Decimal("15.00"),
            fulfillment_brl=(
                Decimal("42.00") if fulfillment_brl is None else fulfillment_brl
            ),
            tax_brl=Decimal("0.00"),
            fx_effect_brl=Decimal("-2.00"),
            other_mapped_brl=Decimal("12.00"),
        )
    return ProfitPeriod(
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        skus=(
            ProfitSku("SYNTH-SKU-001", 10, Decimal("100"), Decimal("40")),
            ProfitSku("SYNTH-SKU-002", 10, Decimal("80"), Decimal("30")),
        ),
        contribution_profit_brl=Decimal("885.00"),
        platform_fee_brl=Decimal("100.00"),
        advertising_brl=Decimal("50.00"),
        refund_loss_brl=Decimal("20.00"),
        fulfillment_brl=Decimal("40.00"),
        tax_brl=Decimal("0.00"),
        fx_effect_brl=Decimal("5.00"),
        other_mapped_brl=Decimal("10.00"),
    )


def test_complete_bridge_reconciles_to_one_cent() -> None:
    bridge = build_profit_bridge(_period(current=True), _period(current=False))

    assert tuple(item.driver for item in bridge.items) == DRIVER_ORDER
    assert bridge.total_change_brl == Decimal("6.00")
    assert sum(item.amount_brl for item in bridge.items) == bridge.total_change_brl
    assert bridge.item("volume").amount_brl == Decimal("0.00")
    assert bridge.item("price_discount").amount_brl == Decimal("20.00")
    assert bridge.item("mix").amount_brl == Decimal("20.00")
    assert bridge.item("cogs").amount_brl == Decimal("-8.00")
    assert bridge.item("refunds").amount_brl == Decimal("5.00")
    assert bridge.residual_brl == Decimal("0.00")
    assert bridge.reconciled is True


def test_missing_fulfillment_is_unknown_not_allocated() -> None:
    current = _period(current=True)
    current = ProfitPeriod(
        **{
            **current.as_dict(),
            "fulfillment_brl": None,
        }
    )

    bridge = build_profit_bridge(current, _period(current=False))

    assert bridge.item("fulfillment").amount_brl is None
    assert bridge.item("fulfillment").evidence_state == "unknown"
    assert bridge.item("residual").evidence_state == "unknown"
    assert bridge.residual_brl != Decimal("0")
    assert bridge.reconciled is False
    assert "fulfillment_missing" in bridge.limitations


def test_new_sku_uses_explicit_nearest_baseline_assumption() -> None:
    baseline = _period(current=False)
    current = ProfitPeriod(
        **{
            **_period(current=True).as_dict(),
            "skus": (
                ProfitSku("SYNTH-SKU-001", 12, Decimal("105"), Decimal("42")),
                ProfitSku("SYNTH-SKU-003", 8, Decimal("79"), Decimal("29")),
            ),
        }
    )

    bridge = build_profit_bridge(current, baseline)

    assert bridge.item("volume").evidence_state == "assumed"
    assert bridge.item("price_discount").evidence_state == "assumed"
    assert "new_sku_baseline_assumption:SYNTH-SKU-003:SYNTH-SKU-002" in (
        bridge.limitations
    )


def test_discontinued_sku_zero_quantity_is_an_explicit_assumption() -> None:
    current = _period(current=True)
    current = ProfitPeriod(
        **{
            **current.as_dict(),
            "skus": (current.skus[0],),
        }
    )

    bridge = build_profit_bridge(current, _period(current=False))

    assert bridge.item("volume").evidence_state == "assumed"
    assert bridge.item("mix").evidence_state == "assumed"
    assert "discontinued_sku_current_assumption:SYNTH-SKU-002" in (
        bridge.limitations
    )
