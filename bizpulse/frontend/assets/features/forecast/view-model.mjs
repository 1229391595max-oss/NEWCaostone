import {
  formatBrl,
  formatDays,
  formatDecimal,
  formatInteger,
  formatPercentRatio,
  formatScore,
} from "../../core/formatters.mjs";
import { t } from "../../i18n/catalog.mjs";

function units(value, language) {
  if (value == null || value === "") return t(language, "common.unavailable");
  const numeric = Number(value);
  return Number.isInteger(numeric) && numeric >= 0
    ? t(language, "forecast.unitCount", { count: formatInteger(numeric, language) })
    : t(language, "common.unavailable");
}

function projection(result, days, language) {
  const item = result?.by_horizon?.[String(days)] ?? result?.by_horizon?.[days];
  if (!item) return null;
  const raw = [item.units?.low, item.units?.base, item.units?.high];
  if (raw.some((value) => value == null || value === "")) return null;
  const values = raw.map(Number);
  if (values.some((value) => !Number.isFinite(value) || value < 0)) return null;
  return {
    days,
    units: { low: values[0], base: values[1], high: values[2] },
    revenue: Object.fromEntries(
      ["low", "base", "high"].map((name) => [name, formatBrl(item.revenue_brl?.[name], language)]),
    ),
    contributionProfit: Object.fromEntries(
      ["low", "base", "high"].map((name) => [name, formatBrl(item.contribution_profit_brl?.[name], language)]),
    ),
    stockCover: Object.fromEntries(
      ["low", "base", "high"].map((name) => [name, formatDays(item.stock_cover_days?.[name], language)]),
    ),
  };
}

export function toForecastViewModel(state, language = "en") {
  const base = {
    status: state.status,
    mode: state.mode,
    language,
    versionLabel: t(language, "common.currentDataset"),
    message: state.error ?? t(language, "forecast.noCompleted"),
    forecast: state.forecast,
    horizons: [],
    analogIds: [],
    analogs: [],
    assumptions: [],
    missingFields: [],
    limitations: [],
    backtest: null,
    factors: [],
  };
  if (!state.forecast) return base;
  const result = state.forecast.result ?? {};
  const horizons = [7, 30, 90]
    .map((days) => projection(result, days, language))
    .filter(Boolean);
  const backtest = state.forecast.backtest;
  return {
    ...base,
    confidence: state.forecast.confidence ?? "pending",
    confidenceReasons: result.confidence_reasons ?? [],
    horizons,
    recommendedFirstOrder: units(result.recommended_first_order_units, language),
    moqFirstOrder: units(result.moq_compliant_first_order_units, language),
    actionDraftEligible: state.forecast.status === "completed" && state.forecast.confidence !== "low",
    analogIds: (state.forecast.analogs ?? []).filter((item) => item.confirmed).map((item) => item.sku_id),
    analogs: (state.forecast.analogs ?? []).map((item) => ({
      skuId: item.sku_id,
      score: formatScore(item.score, language),
      confirmed: item.confirmed,
      components: Object.entries(item.components ?? {})
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([name, value]) => `${name} ${formatDecimal(value, language)}`),
    })),
    factors: Object.entries(result.factors ?? {})
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([name, value]) => `${name} ${formatDecimal(value, language)}`),
    assumptions: result.assumptions ?? state.forecast.assumptions ?? [],
    missingFields: result.missing_fields ?? [],
    limitations: result.limitations ?? [],
    backtest: backtest ? {
      mae: formatDecimal(backtest.mae_units, language),
      wape: formatPercentRatio(backtest.wape, language),
      coverage: formatPercentRatio(backtest.interval_coverage, language),
      exactRepeat: backtest.exact_repeat,
      syntheticOnly: backtest.synthetic_demo_only,
    } : null,
  };
}
