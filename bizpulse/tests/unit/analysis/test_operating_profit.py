from decimal import Decimal

from src.analysis.operating_profit_calculator import calculate_operating_profit


def _inputs() -> dict[str, tuple[dict[str, object], ...]]:
    return {
        "daily_sales": ({"gross_sales_brl": "1000.00", "discount_brl": "50.00"},),
        "refund": ({"refund_brl": "20.00"},),
        "fifo_cogs": ({"cogs_brl": "300.00"},),
        "settlement": ({"fee_brl": "140.00"},),
        "shopee_advertising": ({"spend_brl": "80.00"},),
        "fulfillment_cost": ({"cost_brl": "65.00"},),
        "operating_expense": ({"amount_brl": "45.00"},),
    }


def test_operating_profit_layers_are_exact_and_evidenced() -> None:
    result = calculate_operating_profit(_inputs())

    assert result.net_revenue.value == Decimal("930.00")
    assert result.gross_profit.value == Decimal("630.00")
    assert result.contribution_profit.value is None
    assert result.contribution_profit.known_subtotal == Decimal("345.00")
    assert result.operating_profit.value is None
    assert result.operating_profit.known_subtotal == Decimal("300.00")
    assert result.operating_profit.evidence_state == "unknown"


def test_missing_cost_is_unknown_not_zero() -> None:
    inputs = _inputs()
    inputs.pop("fulfillment_cost")

    result = calculate_operating_profit(inputs)

    assert result.contribution_profit.value is None
    assert result.contribution_profit.known_subtotal == Decimal("410.00")
    assert result.contribution_profit.evidence_state == "unknown"
    assert "fulfillment_cost_missing" in result.limitations


def test_missing_revenue_component_known_subtotal_has_correct_sign() -> None:
    inputs = _inputs()
    inputs.pop("refund")

    result = calculate_operating_profit(inputs)

    assert result.net_revenue.value is None
    assert result.net_revenue.known_subtotal == Decimal("950.00")
    assert "refund_missing" in result.limitations


def test_present_role_with_missing_amount_is_unknown_not_zero() -> None:
    inputs = _inputs()
    inputs["fulfillment_cost"] = ({"fulfilled_units": 10},)

    result = calculate_operating_profit(inputs)

    assert result.contribution_profit.value is None
    assert "fulfillment_cost.cost_brl_missing" in result.limitations


def test_present_tax_rows_with_missing_amount_are_unknown() -> None:
    inputs = _inputs()
    inputs["tax"] = ({},)

    result = calculate_operating_profit(inputs)

    assert result.contribution_profit.value is None
    assert result.operating_profit.value is None
    assert "tax.tax_brl_missing" in result.limitations


def test_fx_effect_is_explicitly_unavailable_for_brl_only_inputs() -> None:
    inputs = _inputs()
    inputs["fx_assumption"] = (
        {
            "currency": "USD",
            "brl_per_usd": "5.25",
            "period_start": "2026-07-01",
            "period_end": "2026-07-31",
        },
    )

    result = calculate_operating_profit(inputs)

    assert ("fx_effect", None) in result.components
    assert "fx_effect_unavailable_brl_only_inputs" in result.limitations
    assert result.evidence[-1].alias == "profit.fx_effect"
    assert result.evidence[-1].evidence_state == "unknown"


def test_explicit_fx_and_other_variable_cost_complete_contribution_profit() -> None:
    inputs = _inputs()
    inputs["fx_effect"] = ({"effect_brl": "5.00"},)
    inputs["other_variable_cost"] = ({"cost_brl": "25.00"},)

    result = calculate_operating_profit(inputs)

    assert result.contribution_profit.value == Decimal("325.00")
    assert result.operating_profit.value == Decimal("280.00")
    assert ("fx_effect", Decimal("5.00")) in result.components
    assert ("other_mapped", Decimal("25.00")) in result.components
    assert "fx_effect_unavailable_brl_only_inputs" not in result.limitations
    assert result.evidence[-1].evidence_state == "measured"


def test_known_subtotal_includes_known_fx_when_other_cost_is_missing() -> None:
    inputs = _inputs()
    inputs["fx_effect"] = ({"effect_brl": "5.00"},)

    result = calculate_operating_profit(inputs)

    assert result.contribution_profit.value is None
    assert result.contribution_profit.known_subtotal == Decimal("350.00")
    assert result.operating_profit.known_subtotal == Decimal("305.00")
    assert "other_variable_cost_missing" in result.limitations
