from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import UUID

from src.ai.contracts import QueryScope
from src.ai.monthly_sales_report import (
    PrecomputedMonthlyReportReaders,
    read_monthly_sales_report,
)


def july_scope() -> QueryScope:
    return QueryScope(
        workspace_id="synthetic-demo",
        actor_kind="demo",
        dataset_version_id=UUID("00000000-0000-0000-0000-000000000001"),
        store_ids=("SYNTH-STORE-01",),
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        currency="BRL",
    )


def metric(value: str | None, state: str = "measured") -> dict[str, object]:
    return {
        "value": value,
        "evidence_state": state if value is not None else "unknown",
        "evidence_refs": ("metric",),
    }


class SnapshotReaders:
    def __init__(self) -> None:
        self.completed_snapshot_kinds: list[tuple[str, bool]] = []
        self.run_calls: list[object] = []
        self.raw_table_calls: list[object] = []

    def completed_analysis(self, connection, kind, scope, *, previous=False):
        del connection, scope
        self.completed_snapshot_kinds.append((kind, previous))
        run = SimpleNamespace(run_id=f"{kind}-{'prior' if previous else 'current'}")
        if kind == "sales_ads" and not previous:
            return run, {
                "result": {
                    "net_sales": metric("12400.50", "derived"),
                    "orders": metric("310"),
                    "units": metric("412"),
                    "aov": metric("40.00", "derived"),
                    "ad_spend": metric("1200.00"),
                    "roas": metric(None),
                    "sku_ranking": (
                        {"sku_id": "SYNTH-SKU-001", "net_sales": "4500.00", "units": 80},
                        {"sku_id": "SYNTH-SKU-003", "net_sales": "900.00", "units": 24},
                    ),
                },
                "limitations": ("attributed_revenue_missing",),
            }
        if kind == "sales_ads":
            return run, {
                "result": {
                    "net_sales": metric("11000.00", "derived"),
                    "orders": metric("280"),
                    "units": metric("370"),
                    "aov": metric("39.29", "derived"),
                    "ad_spend": metric("1000.00"),
                },
                "limitations": (),
            }
        if kind == "operating_profit":
            return run, {
                "result": {
                    "contribution_profit": metric("2600.00", "derived"),
                    "operating_profit": metric("2100.00", "derived"),
                },
                "limitations": ("fx_effect_unavailable_brl_only_inputs",),
            }
        if kind == "inventory_risk":
            return run, {
                "result": {
                    "items": (
                        {"sku_id": "SYNTH-SKU-001", "risk": "stockout"},
                        {"sku_id": "SYNTH-SKU-002", "risk": "balanced"},
                    )
                },
                "limitations": (),
            }
        if kind == "replenishment":
            return run, {
                "result": {
                    "items": (
                        {
                            "sku_id": "SYNTH-SKU-001",
                            "priority": "high",
                            "recommended_quantity": "40",
                            "cash_required": {"value": "500.00"},
                        },
                    )
                },
                "limitations": (),
            }
        raise AssertionError(kind)

    def pinned_actions(self, connection, scope):
        del connection, scope
        return (
            SimpleNamespace(
                id="action-1",
                status="approved",
                current_revision=2,
            ),
        )


def fact(report, label: str):
    return next(item for item in report.facts if item["label"] == label)


def test_previous_snapshot_is_the_previous_complete_calendar_month() -> None:
    class AnalysisReads:
        def __init__(self) -> None:
            self.scopes = []

        def read_exact_completed(self, connection, kind, dataset_version_id, scope):
            del connection, kind, dataset_version_id
            self.scopes.append(scope)
            return SimpleNamespace(run_id="prior"), {"result": {}}, ()

    analyses = AnalysisReads()
    readers = PrecomputedMonthlyReportReaders(analyses, object())

    readers.completed_analysis(
        object(),
        "sales_ads",
        july_scope(),
        previous=True,
    )

    assert analyses.scopes == [
        {
            "store_id": "SYNTH-STORE-01",
            "period_start": "2026-06-01",
            "period_end": "2026-06-30",
            "currency": "BRL",
        }
    ]


def test_monthly_report_reads_only_bounded_precomputed_authority() -> None:
    readers = SnapshotReaders()

    report = read_monthly_sales_report(object(), july_scope(), readers)

    assert len(report.facts) <= 25
    assert len({ref for item in report.facts for ref in item["evidence_refs"]}) <= 10
    assert fact(report, "report_period")["value"] == "2026-07-01..2026-07-31"
    assert fact(report, "currency")["value"] == "BRL"
    assert fact(report, "net_sales_brl")["value"] == "12400.50"
    assert fact(report, "previous_net_sales_brl")["value"] == "11000.00"
    assert fact(report, "top_sku")["value"] == "SYNTH-SKU-001; net_sales_brl=4500.00"
    assert fact(report, "bottom_sku")["value"] == "SYNTH-SKU-003; net_sales_brl=900.00"
    assert fact(report, "stockout_risk_skus")["value"] == "1"
    assert fact(report, "pinned_action_count")["value"] == "1"
    assert readers.run_calls == []
    assert readers.raw_table_calls == []
    assert set(readers.completed_snapshot_kinds) == {
        ("sales_ads", False),
        ("sales_ads", True),
        ("operating_profit", False),
        ("inventory_risk", False),
        ("replenishment", False),
    }


def test_missing_optional_snapshots_add_limitations_without_fallback() -> None:
    class MissingReaders(SnapshotReaders):
        def completed_analysis(self, connection, kind, scope, *, previous=False):
            if kind in {"operating_profit", "inventory_risk", "replenishment"}:
                self.completed_snapshot_kinds.append((kind, previous))
                return None
            return super().completed_analysis(
                connection,
                kind,
                scope,
                previous=previous,
            )

    readers = MissingReaders()
    report = read_monthly_sales_report(object(), july_scope(), readers)

    assert "monthly_report_operating_profit_unavailable" in report.limitations
    assert "monthly_report_inventory_risk_unavailable" in report.limitations
    assert "monthly_report_replenishment_unavailable" in report.limitations
    assert readers.run_calls == readers.raw_table_calls == []
