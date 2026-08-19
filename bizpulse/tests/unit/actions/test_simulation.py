from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from src.actions.contracts import ActionSimulationInputs
from src.actions.simulation import project_simulation_inputs


def _revision(*, budget_brl=Decimal("500.00")):
    return SimpleNamespace(target="SYNTH-SKU-001", budget_brl=budget_brl)


def _snapshot(*, velocity="5", unit_cost="12.50", quantity="40"):
    cash = None
    if unit_cost is not None and quantity is not None:
        cash = str(Decimal(unit_cost) * Decimal(quantity))
    return {
        "result": {
            "items": [
                {
                    "sku_id": "SYNTH-SKU-001",
                    "base_daily": velocity,
                    "recommended_quantity": quantity,
                    "cash_required": {
                        "value": cash,
                        "evidence_state": "derived" if cash is not None else "unknown",
                    },
                }
            ]
        }
    }


def test_projection_uses_only_precomputed_structured_inputs() -> None:
    inputs = project_simulation_inputs(_revision(), _snapshot())

    assert inputs == ActionSimulationInputs(
        unit_cost_brl=Decimal("12.50"),
        precomputed_daily_velocity=Decimal("5"),
        baseline_budget_brl=Decimal("500.00"),
        currency="BRL",
    )


def test_missing_or_nonpositive_velocity_is_unavailable_not_zero() -> None:
    assert project_simulation_inputs(
        _revision(),
        _snapshot(velocity=None),
    ).precomputed_daily_velocity is None
    assert project_simulation_inputs(
        _revision(),
        _snapshot(velocity="0"),
    ).precomputed_daily_velocity is None


def test_projection_never_parses_human_labels_or_unrelated_skus() -> None:
    snapshot = _snapshot()
    snapshot["result"]["items"][0]["label"] = "Cost R$ 999.99 velocity 99"
    snapshot["result"]["items"].append(
        {
            "sku_id": "SYNTH-SKU-999",
            "base_daily": "99",
            "unit_cost_brl": "999.99",
        }
    )

    assert project_simulation_inputs(_revision(), snapshot) == ActionSimulationInputs(
        unit_cost_brl=Decimal("12.50"),
        precomputed_daily_velocity=Decimal("5"),
        baseline_budget_brl=Decimal("500.00"),
        currency="BRL",
    )
