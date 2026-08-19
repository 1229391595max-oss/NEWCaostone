import {
  formatBrl,
  formatDecimal,
  formatInteger,
} from "../../core/formatters.mjs";
import { t } from "../../i18n/catalog.mjs";

function present(value) {
  return value !== null && value !== undefined && String(value).trim() !== "";
}

function unit(value, language) {
  return present(value)
    ? t(language, "forecast.unitCount", { count: formatInteger(value, language) })
    : t(language, "common.unavailable");
}

function controls(mode, status) {
  if (status === "new") return ["review"];
  if (status === "reviewed") return ["adjust", "approve", "dismiss"];
  if (mode === "operator" && status === "approved") return ["export", "record_outcome"];
  return [];
}

function actionModel(item, mode, expectedVersionId, language) {
  if (item?.dataset_version_id !== expectedVersionId) {
    return { invalid: true, message: "ACTION_RELEASE_MISMATCH" };
  }
  const revisions = Array.isArray(item.revisions) ? item.revisions : [];
  const revision = revisions.find((entry) => entry.revision === item.current_revision);
  if (!revision) return { invalid: true, message: "ACTION_REVISION_MISSING" };
  const overlays = Array.isArray(item.viewer_overlays) ? item.viewer_overlays : [];
  const viewerAdjustment = mode === "viewer"
    ? overlays.filter((entry) => entry.command === "adjust").reduce(
        (current, entry) => ({
          ...current,
          ...Object.fromEntries(
            Object.entries(entry.adjustment ?? {}).filter(
              ([name]) => name === "quantity" || name === "budget_brl",
            ),
          ),
        }),
        {},
      )
    : {};
  const displayStatus = mode === "viewer" ? overlays.at(-1)?.status ?? "new" : item.status;
  const budgetValue = viewerAdjustment.budget_brl
    ?? revision.budget_brl
    ?? (mode === "viewer" ? item.simulation_inputs?.baseline_budget_brl : null);
  const quantityValue = viewerAdjustment.quantity ?? revision.quantity;
  const unavailable = t(language, "common.unavailable");
  return {
    id: item.id,
    datasetVersionId: item.dataset_version_id,
    sourceType: item.source_type,
    authorityStatus: item.status,
    displayStatus,
    currentRevision: item.current_revision,
    suggestion: viewerAdjustment.suggestion ?? revision.suggestion,
    target: viewerAdjustment.target ?? revision.target,
    period: `${revision.period_start} — ${revision.period_end}`,
    periodEnd: revision.period_end,
    quantity: unit(quantityValue, language),
    quantityRaw: present(quantityValue) ? String(quantityValue) : "",
    budget: formatBrl(budgetValue, language),
    budgetRaw: present(budgetValue) ? String(budgetValue) : "",
    actionDate: viewerAdjustment.action_date ?? revision.action_date ?? unavailable,
    threshold: present(viewerAdjustment.threshold ?? revision.threshold)
      ? formatDecimal(viewerAdjustment.threshold ?? revision.threshold, language)
      : unavailable,
    expectedImpact: Object.entries(viewerAdjustment.expected_impact ?? revision.expected_impact ?? {})
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([name, value]) => `${name}: ${formatDecimal(value, language)}`),
    confidence: viewerAdjustment.confidence ?? revision.confidence,
    limitations: viewerAdjustment.limitations ?? revision.limitations ?? [],
    evidence: (revision.facts ?? []).map((fact) => ({
      alias: fact.alias,
      state: fact.evidence_state,
      sourceRef: fact.source_ref,
      value: present(fact.value) ? String(fact.value) : unavailable,
    })),
    revisions: revisions.map((entry) => ({
      revision: entry.revision,
      suggestion: entry.suggestion,
      quantity: unit(entry.quantity, language),
      budget: formatBrl(entry.budget_brl, language),
      createdAt: entry.created_at,
    })),
    decisions: (item.decisions ?? []).map((entry) => ({
      command: entry.command,
      revision: entry.action_revision,
      reason: entry.reason,
      decidedBy: entry.decided_by,
      createdAt: entry.created_at,
    })),
    exports: (item.exports ?? []).map((entry) => ({
      id: entry.id,
      status: entry.status,
      note: entry.note,
      createdAt: entry.created_at,
    })),
    outcomes: (item.outcomes ?? []).map((entry) => ({
      revision: entry.outcome_revision,
      reviewDate: entry.review_date,
      conclusion: entry.conclusion,
      reason: entry.reason,
      result: Object.entries(entry.synthetic_result ?? {})
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([name, value]) => `${name}: ${value}`),
    })),
    overlays: overlays.map((entry) => ({
      revision: entry.overlay_revision,
      command: entry.command,
      status: entry.status,
      adjustment: entry.adjustment ?? {},
      reason: entry.reason,
      createdAt: entry.created_at,
    })),
    simulationInputs: {
      unitCostBrl: present(item.simulation_inputs?.unit_cost_brl)
        ? String(item.simulation_inputs.unit_cost_brl)
        : null,
      precomputedDailyVelocity: present(item.simulation_inputs?.precomputed_daily_velocity)
        ? String(item.simulation_inputs.precomputed_daily_velocity)
        : null,
      baselineBudgetBrl: present(item.simulation_inputs?.baseline_budget_brl)
        ? String(item.simulation_inputs.baseline_budget_brl)
        : null,
      currency: item.simulation_inputs?.currency === "BRL" ? "BRL" : null,
    },
    controls: controls(mode, displayStatus),
  };
}

export function toActionInboxViewModel(state, language = "en") {
  const expectedVersionId = state.release?.dataset_version_id ?? null;
  const items = (state.items ?? []).map((item) => (
    actionModel(item, state.mode, expectedVersionId, language)
  ));
  const invalid = items.find((item) => item.invalid);
  return {
    status: invalid ? "error" : state.status,
    message: invalid?.message ?? state.error,
    mode: state.mode,
    language,
    versionLabel: t(language, "common.currentDataset"),
    items: invalid ? [] : items,
  };
}
