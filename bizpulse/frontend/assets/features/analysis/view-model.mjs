import { formatBrl as formatBrlDisplay } from "../../core/formatters.mjs";
import { t } from "../../i18n/catalog.mjs";

export function metricValue(metric) {
  if (metric === null || metric === undefined) return null;
  if (typeof metric === "object" && "value" in metric) return metric.value;
  return metric;
}

export function formatBrl(value, language = "en") {
  return formatBrlDisplay(value, language);
}

export function analyticsContext(state, language = "en") {
  const snapshot = state.payload?.snapshot;
  const scope = snapshot?.scope ?? {};
  return {
    period:
      scope.period_start && scope.period_end
        ? `${scope.period_start} — ${scope.period_end}`
        : t(language, "common.periodUnavailable"),
    versionLabel: t(language, "common.currentDataset"),
    evidence: Array.isArray(state.payload?.evidence) ? state.payload.evidence : [],
    limitations: Array.isArray(snapshot?.limitations) ? snapshot.limitations : [],
  };
}

export function unavailableModel(state, title, language = "en") {
  const context = analyticsContext(state, language);
  return {
    title,
    language,
    status: state.status === "loading" ? "loading" : "unavailable",
    message:
      state.status === "loading"
        ? t(language, "common.loadingAnalysis")
        : state.error ?? "ANALYSIS_UNAVAILABLE",
    metrics: [],
    charts: [],
    ...context,
  };
}

export function toAnalysisViewModel(state, language = "en") {
  if (state.status !== "ready" || !state.payload?.snapshot?.result) {
    return unavailableModel(state, t(language, "sales.title"), language);
  }
  const result = state.payload.snapshot.result;
  const context = analyticsContext(state, language);
  const trends = result.daily_trends ?? result.daily_sales ?? [];
  const trendPoints = toKnownTrendPoints(trends);
  return {
    title: t(language, "sales.title"),
    language,
    status: "ready",
    message: t(language, "sales.message"),
    metrics: [
      {
        label: t(language, "sales.grossSales"),
        value: formatBrl(metricValue(result.gross_sales), language),
        definition: t(language, "sales.grossSalesDefinition"),
      },
      {
        label: t(language, "sales.netSales"),
        value: formatBrl(metricValue(result.net_sales), language),
        definition: t(language, "sales.netSalesDefinition"),
      },
      {
        label: t(language, "sales.adSpend"),
        value: formatBrl(metricValue(result.ad_spend), language),
        definition: t(language, "sales.adSpendDefinition"),
      },
    ],
    charts: trendPoints.length
      ? [
          {
            type: "line",
            title: t(language, "sales.trendTitle"),
            summary: t(language, "sales.trendSummary"),
            definition: t(language, "sales.trendDefinition"),
            evidenceAlias: "sales.net",
            points: trendPoints,
          },
        ]
      : [],
    ...context,
  };
}

function toKnownTrendPoints(trends) {
  if (!Array.isArray(trends) || trends.length === 0) return [];
  const points = [];
  for (const item of trends) {
    const raw = metricValue(item?.net_sales);
    if (
      typeof item?.date !== "string" ||
      raw === null ||
      raw === undefined ||
      (typeof raw === "string" && raw.trim() === "") ||
      (typeof raw !== "string" && typeof raw !== "number")
    ) {
      return [];
    }
    const value = Number(raw);
    if (!Number.isFinite(value) || value < 0) return [];
    points.push({ label: item.date, value });
  }
  return points;
}
