import {
  analyticsContext,
  formatBrl,
  metricValue,
  unavailableModel,
} from "../analysis/view-model.mjs";
import { formatDecimal, formatInteger } from "../../core/formatters.mjs";
import { t } from "../../i18n/catalog.mjs";
import { toInventoryViewModel } from "../inventory/view-model.mjs";

const coverageAreas = Object.freeze([
  ["sales", "overview.coverage.sales"],
  ["inventory", "overview.coverage.inventory"],
  ["profit", "overview.coverage.profit"],
  ["replenishment", "overview.coverage.replenishment"],
]);

const profitComponents = Object.freeze(new Set([
  "gross_sales",
  "discounts",
  "refunds",
  "cogs",
  "platform_fees",
  "advertising",
  "fulfillment",
  "tax",
  "other_mapped",
  "operating_expense",
  "fx_effect",
]));

export function toOverviewViewModel(state, language = "en", kpiKeys = null) {
  const sales = state.payload?.sales;
  const inventory = state.payload?.inventory;
  const profit = state.payload?.profit;
  if (
    state.status !== "ready" ||
    !sales?.snapshot?.result ||
    !inventory?.snapshot?.result ||
    !profit?.snapshot?.result
  ) {
    return unavailableModel(state, t(language, "overview.title"), language);
  }
  const context = analyticsContext({ ...state, payload: sales }, language);
  const inventoryItems = inventory.snapshot.result.items ?? [];
  const inventoryRiskComplete =
    inventoryItems.length > 0 &&
    inventoryItems.every((item) =>
      ["stockout", "balanced", "overstock"].includes(item.risk),
    );
  const trends = knownTrendPoints(sales.snapshot.result.daily_trends ?? []);
  const componentBars = knownComponentBars(
    profit.snapshot.result.components ?? [],
    language,
  );
  const limitations = [
    ...(sales.snapshot.limitations ?? []),
    ...(inventory.snapshot.limitations ?? []),
    ...(profit.snapshot.limitations ?? []),
    ...(state.payload?.replenishment?.snapshot?.limitations ?? []),
  ].filter((item, index, items) => items.indexOf(item) === index);
  const inventoryModel = toInventoryViewModel({
    status: "ready",
    release: state.release,
    payload: {
      inventory,
      replenishment: state.payload?.replenishment ?? null,
    },
  }, language);
  const metricsByKey = {
    net_sales: {
      key: "net_sales",
      label: t(language, "overview.netSales"),
      value: formatBrl(metricValue(sales.snapshot.result.net_sales), language),
      definition: t(language, "overview.netSalesDefinition"),
    },
    orders: {
      key: "orders",
      label: t(language, "overview.orders"),
      value: formatInteger(metricValue(sales.snapshot.result.orders), language),
      definition: t(language, "overview.ordersDefinition"),
    },
    roas: {
      key: "roas",
      label: t(language, "overview.roas"),
      value: ratioDisplay(metricValue(sales.snapshot.result.roas), language),
      definition: t(language, "overview.roasDefinition"),
    },
    ad_spend: {
      key: "ad_spend",
      label: t(language, "overview.adSpend"),
      value: formatBrl(metricValue(sales.snapshot.result.ad_spend), language),
      definition: t(language, "overview.adSpendDefinition"),
    },
    contribution_profit: {
      key: "contribution_profit",
      label: t(language, "overview.contributionProfit"),
      value: formatBrl(metricValue(profit.snapshot.result.contribution_profit), language),
      definition: t(language, "overview.contributionDefinition"),
    },
    stockout_skus: {
      key: "stockout_skus",
      label: t(language, "overview.stockoutSkus"),
      value: inventoryRiskComplete
        ? formatInteger(inventoryItems.filter((item) => item.risk === "stockout").length, language)
        : t(language, "common.unavailable"),
      definition: t(language, "overview.stockoutDefinition"),
    },
  };
  const metricOrder = Array.isArray(kpiKeys) && kpiKeys.length
    ? kpiKeys.filter((key) => key in metricsByKey)
    : Object.keys(metricsByKey);
  return {
    title: t(language, "overview.title"),
    language,
    status: "ready",
    message: t(language, "overview.message"),
    metrics: metricOrder.map((key) => metricsByKey[key]),
    charts: [
      ...(trends.length
        ? [{
            type: "line",
            title: t(language, "overview.salesTrendTitle"),
            summary: t(language, "overview.salesTrendSummary"),
            definition: t(language, "overview.salesTrendDefinition"),
            evidenceAlias: "sales.net",
            points: trends,
          }]
        : []),
      ...(componentBars.length
        ? [{
            type: "bar",
            title: t(language, "overview.profitDriversTitle"),
            summary: t(language, "overview.profitDriversSummary"),
            definition: t(language, "overview.profitDriversDefinition"),
            evidenceAlias: "profit.contribution",
            bars: componentBars,
          }]
        : []),
    ],
    evidence: [
      ...(sales.evidence ?? []),
      ...(inventory.evidence ?? []),
      ...(profit.evidence ?? []),
    ],
    limitations,
    coverage: coverageAreas.map(([name, labelKey]) => ({
      name,
      label: t(language, labelKey),
      status: state.payload?.[name]?.snapshot?.result ? "ready" : "unavailable",
    })),
    alerts: (sales.snapshot.result.anomalies ?? []).map((item) =>
      anomalyModel(item, language)),
    pendingActions: Array.isArray(state.payload?.actions?.items)
      ? state.payload.actions.items.length
      : 0,
    urgentInventory: (inventoryModel.rows ?? [])
      .filter((item) => ["P0", "P1", "P2"].includes(item.priority))
      .slice(0, 4),
    period: context.period,
    versionLabel: t(language, "overview.currentData"),
  };
}

function ratioDisplay(value, language) {
  const displayed = formatDecimal(value, language);
  return displayed === "—" ? t(language, "common.unavailable") : `${displayed}×`;
}

function knownTrendPoints(items) {
  if (!Array.isArray(items) || !items.length) return [];
  const points = [];
  for (const item of items) {
    const value = knownNumber(metricValue(item?.net_sales));
    if (typeof item?.date !== "string" || value === null || value < 0) return [];
    points.push({ label: item.date, value });
  }
  return points;
}

function knownComponentBars(items, language) {
  if (!Array.isArray(items)) return [];
  return items.flatMap((item) => {
    if (!Array.isArray(item) || !profitComponents.has(item[0])) return [];
    const value = knownNumber(item[1]);
    return value === null
      ? []
      : [{
          label: t(language, `overview.component.${item[0]}`),
          value: Math.abs(value),
        }];
  });
}

function anomalyModel(value, language) {
  const [code, detail] = String(value).split(":", 2);
  return code === "sales_spike" && detail
    ? t(language, "overview.alert.salesSpike", { date: detail })
    : t(language, "overview.alert.review");
}

function knownNumber(value) {
  if (
    value === null ||
    value === undefined ||
    (typeof value === "string" && value.trim() === "") ||
    (typeof value !== "string" && typeof value !== "number")
  ) return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}
