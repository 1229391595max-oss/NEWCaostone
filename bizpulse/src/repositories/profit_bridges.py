"""PostgreSQL authority for immutable contribution-profit bridges."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import Connection, select

from src.db.schema import profit_bridge_items, profit_bridges
from src.profit.contracts import ProfitBridge


@dataclass(frozen=True, slots=True)
class ProfitBridgeProjection:
    id: UUID
    workspace_id: str
    dataset_version_id: UUID
    baseline_analysis_id: UUID
    current_analysis_id: UUID
    formula_version: str
    scope: dict[str, object]
    total_delta_brl: Decimal | None
    residual_brl: Decimal | None
    reconciled: bool
    evidence: dict[str, object]
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ProfitBridgeItemProjection:
    id: UUID
    bridge_id: UUID
    driver: str
    ordinal: int
    amount_brl: Decimal | None
    evidence_state: str
    formula: str
    source_refs: list[str]
    created_at: datetime


class ProfitBridgeRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def get(
        self,
        workspace_id: str,
        bridge_id: UUID,
    ) -> ProfitBridgeProjection | None:
        row = self._connection.execute(
            select(*profit_bridges.c).where(
                profit_bridges.c.workspace_id == workspace_id,
                profit_bridges.c.id == bridge_id,
            )
        ).mappings().one_or_none()
        return ProfitBridgeProjection(**row) if row is not None else None

    def find_exact(
        self,
        workspace_id: str,
        baseline_analysis_id: UUID,
        current_analysis_id: UUID,
        formula_version: str,
    ) -> ProfitBridgeProjection | None:
        row = self._connection.execute(
            select(*profit_bridges.c).where(
                profit_bridges.c.workspace_id == workspace_id,
                profit_bridges.c.baseline_analysis_id == baseline_analysis_id,
                profit_bridges.c.current_analysis_id == current_analysis_id,
                profit_bridges.c.formula_version == formula_version,
            )
        ).mappings().one_or_none()
        return ProfitBridgeProjection(**row) if row is not None else None

    def latest_for_version(
        self,
        workspace_id: str,
        dataset_version_id: UUID,
    ) -> ProfitBridgeProjection | None:
        row = self._connection.execute(
            select(*profit_bridges.c)
            .where(
                profit_bridges.c.workspace_id == workspace_id,
                profit_bridges.c.dataset_version_id == dataset_version_id,
            )
            .order_by(profit_bridges.c.created_at.desc(), profit_bridges.c.id.desc())
            .limit(1)
        ).mappings().one_or_none()
        return ProfitBridgeProjection(**row) if row is not None else None

    def find_for_scope(
        self,
        workspace_id: str,
        dataset_version_id: UUID,
        formula_version: str,
        scope: dict[str, object],
    ) -> ProfitBridgeProjection | None:
        row = self._connection.execute(
            select(*profit_bridges.c).where(
                profit_bridges.c.workspace_id == workspace_id,
                profit_bridges.c.dataset_version_id == dataset_version_id,
                profit_bridges.c.formula_version == formula_version,
                profit_bridges.c.scope == scope,
            )
        ).mappings().one_or_none()
        return ProfitBridgeProjection(**row) if row is not None else None

    def items(self, bridge_id: UUID) -> tuple[ProfitBridgeItemProjection, ...]:
        rows = self._connection.execute(
            select(*profit_bridge_items.c)
            .where(profit_bridge_items.c.bridge_id == bridge_id)
            .order_by(profit_bridge_items.c.ordinal)
        ).mappings().all()
        return tuple(ProfitBridgeItemProjection(**row) for row in rows)

    def insert(
        self,
        *,
        bridge_id: UUID,
        workspace_id: str,
        dataset_version_id: UUID,
        baseline_analysis_id: UUID,
        current_analysis_id: UUID,
        scope: dict[str, object],
        bridge: ProfitBridge,
        now: datetime,
    ) -> ProfitBridgeProjection:
        existing = self.find_exact(
            workspace_id,
            baseline_analysis_id,
            current_analysis_id,
            bridge.formula_version,
        )
        if existing is not None:
            return existing
        row = self._connection.execute(
            profit_bridges.insert()
            .values(
                id=bridge_id,
                workspace_id=workspace_id,
                dataset_version_id=dataset_version_id,
                baseline_analysis_id=baseline_analysis_id,
                current_analysis_id=current_analysis_id,
                formula_version=bridge.formula_version,
                scope=scope,
                total_delta_brl=bridge.total_change_brl,
                residual_brl=bridge.residual_brl,
                reconciled=bridge.reconciled,
                evidence={
                    "baseline_period": [
                        value.isoformat() for value in bridge.baseline_period
                    ],
                    "current_period": [
                        value.isoformat() for value in bridge.current_period
                    ],
                    "baseline_contribution_profit_brl": _json_decimal(
                        bridge.baseline_contribution_profit_brl
                    ),
                    "current_contribution_profit_brl": _json_decimal(
                        bridge.current_contribution_profit_brl
                    ),
                    "limitations": list(bridge.limitations),
                },
                created_at=now,
            )
            .returning(*profit_bridges.c)
        ).mappings().one()
        for item in bridge.items:
            self._connection.execute(
                profit_bridge_items.insert().values(
                    id=uuid4(),
                    bridge_id=bridge_id,
                    driver=item.driver,
                    ordinal=item.ordinal,
                    amount_brl=item.amount_brl,
                    evidence_state=item.evidence_state,
                    formula=item.formula,
                    source_refs=list(item.source_refs),
                    created_at=now,
                )
            )
        return ProfitBridgeProjection(**row)


def _json_decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None
