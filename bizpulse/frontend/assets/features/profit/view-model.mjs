import {
  analyticsContext,
  formatBrl,
  metricValue,
  unavailableModel,
} from "../analysis/view-model.mjs";
import { formatBrl as formatBrlDisplay } from "../../core/formatters.mjs";
import { t } from "../../i18n/catalog.mjs";

export function toProfitViewModel(state, language = "en") {
  if (state.status !== "ready" || !state.payload?.snapshot?.result) {
    return unavailableModel(state, t(language, "profit.title"), language);
  }
  const result = state.payload.snapshot.result;
  const context = analyticsContext(state, language);
  const components = Array.isArray(result.components) ? result.components : [];
  const knownComponents = components.flatMap(([label, value]) => {
    if (typeof label !== "string") return [];
    const number = knownNumber(value);
    return number === null ? [] : [{ label, value: Math.abs(number) }];
  });
  const bridge = toBridgeModel(
    state.bridge,
    state.bridgeError,
    context,
    state.payload,
    state.release,
    language,
  );
  return {
    title: t(language, "profit.title"),
    language,
    status: "ready",
    message: t(language, "profit.message"),
    metrics: [
      {
        label: t(language, "profit.netRevenue"),
        value: formatBrl(metricValue(result.net_revenue), language),
        definition: t(language, "profit.netRevenueDefinition"),
      },
      {
        label: t(language, "profit.contribution"),
        value: formatBrl(metricValue(result.contribution_profit), language),
        definition: t(language, "profit.contributionDefinition"),
      },
      {
        label: t(language, "profit.operating"),
        value: formatBrl(metricValue(result.operating_profit), language),
        definition: t(language, "profit.operatingDefinition"),
      },
    ],
    charts: knownComponents.length
      ? [
          {
            type: "bar",
            title: t(language, "profit.components"),
            summary: t(language, "profit.componentsSummary"),
            definition: t(language, "profit.componentsDefinition"),
            evidenceAlias: "profit.contribution",
            bars: knownComponents,
          },
        ]
      : [],
    ...context,
    limitations: [
      ...context.limitations,
      ...(bridge.status === "ready" ? bridge.limitations : []),
    ].filter((item, index, items) => items.indexOf(item) === index),
    bridge,
  };
}

const driverNames = Object.freeze([
  "volume",
  "price_discount",
  "mix",
  "advertising",
  "refunds",
  "fulfillment",
  "platform_fees",
  "cogs",
  "fx",
  "tax",
  "other_mapped",
  "residual",
]);

function toBridgeModel(payload, error, context, analysis, release, language) {
  if (!payload) {
    return {
      status: "unavailable",
      message: error ?? "PROFIT_BRIDGE_UNAVAILABLE",
      items: [],
      limitations: [],
    };
  }
  if (!bridgeMatchesAnalysis(payload, analysis, release)) {
    return {
      status: "unavailable",
      message: "PROFIT_BRIDGE_AUTHORITY_MISMATCH",
      items: [],
      limitations: [],
    };
  }
  const items = Array.isArray(payload.items) ? payload.items : [];
  const orderedDrivers = driverNames;
  if (
    items.length !== orderedDrivers.length ||
    items.some(
      (item, index) =>
        item?.driver !== orderedDrivers[index] || item?.ordinal !== index + 1,
    )
  ) {
    return {
      status: "unavailable",
      message: "PROFIT_BRIDGE_INVALID",
      items: [],
      limitations: [],
    };
  }
  const baseline = knownNumber(payload.baseline_contribution_profit_brl);
  const current = knownNumber(payload.current_contribution_profit_brl);
  const modelItems = items.map((item) => {
    const value = knownNumber(item.amount_brl);
    return {
      driver: item.driver,
      label: t(language, `profit.driver.${item.driver}`),
      ordinal: item.ordinal,
      value,
      displayValue: formatSignedBrl(value, language),
      evidenceState: item.evidence_state,
      formula: typeof item.formula === "string"
        ? item.formula
        : t(language, "common.unavailable"),
      sourceRefs: Array.isArray(item.source_refs) ? item.source_refs : [],
    };
  });
  const baselinePeriod = formatPeriod(payload.baseline_period, language);
  const currentPeriod = formatPeriod(payload.current_period, language);
  return {
    status: "ready",
    id: payload.id,
    periodLabel: `${baselinePeriod} vs ${currentPeriod}`,
    baseline,
    baselineDisplay: formatBrl(baseline, language),
    current,
    currentDisplay: formatBrl(current, language),
    totalDelta: knownNumber(payload.total_delta_brl),
    totalDeltaDisplay: formatSignedBrl(knownNumber(payload.total_delta_brl), language),
    residual: knownNumber(payload.residual_brl),
    residualDisplay: formatSignedBrl(knownNumber(payload.residual_brl), language),
    reconciled: payload.reconciled === true,
    items: modelItems,
    limitations: Array.isArray(payload.limitations) ? payload.limitations : [],
    chart:
      baseline === null || current === null
        ? null
        : {
            title: t(language, "profit.bridge"),
            summary: t(language, "profit.bridgeSummary"),
            period: `${baselinePeriod} vs ${currentPeriod}`,
            definition: t(language, "profit.bridgeDefinition"),
            language,
            version: context.versionLabel,
            baseline,
            current,
            items: modelItems.map((item) => ({
              label: item.label,
              value: item.value,
              evidenceState: item.evidenceState,
            })),
          },
  };
}

function bridgeMatchesAnalysis(bridge, analysis, release) {
  const run = analysis?.run;
  const scope = analysis?.snapshot?.scope;
  const bridgeScope = bridge?.scope;
  const currentPeriod = bridge?.current_period;
  const scopedCurrentPeriod = bridgeScope?.current_period;
  return Boolean(
    run?.run_id &&
      run.dataset_version_id &&
      scope?.period_start &&
      scope?.period_end &&
      bridge?.dataset_version_id === run.dataset_version_id &&
      bridge.dataset_version_id === release?.dataset_version_id &&
      bridge.current_analysis_id === run.run_id &&
      Array.isArray(currentPeriod) &&
      currentPeriod[0] === scope.period_start &&
      currentPeriod[1] === scope.period_end &&
      Array.isArray(scopedCurrentPeriod) &&
      scopedCurrentPeriod[0] === scope.period_start &&
      scopedCurrentPeriod[1] === scope.period_end &&
      bridgeScope?.store_id === scope.store_id &&
      bridgeScope?.currency === scope.currency &&
      !Object.hasOwn(bridgeScope, "sku_ids")
  );
}

function formatPeriod(value, language) {
  return Array.isArray(value) && value.length === 2
    ? `${value[0]} — ${value[1]}`
    : t(language, "common.periodUnavailable");
}

function formatSignedBrl(value, language) {
  if (value === null) return t(language, "common.unavailable");
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${formatBrlDisplay(Math.abs(value), language)}`;
}

function knownNumber(value) {
  if (
    value === null ||
    value === undefined ||
    (typeof value === "string" && value.trim() === "") ||
    (typeof value !== "string" && typeof value !== "number")
  ) {
    return null;
  }
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
