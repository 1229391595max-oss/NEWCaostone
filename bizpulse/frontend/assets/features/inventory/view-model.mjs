import {
  analyticsContext,
  metricValue,
  unavailableModel,
} from "../analysis/view-model.mjs";
import {
  formatDays,
  formatDecimal,
  formatInteger,
} from "../../core/formatters.mjs";
import { t } from "../../i18n/catalog.mjs";

export const INVENTORY_PRIORITY_ORDER = Object.freeze([
  "P0",
  "P1",
  "P2",
  "Monitor",
  "Unavailable",
]);

export function toInventoryViewModel(state, language = "en") {
  const inventory = state.payload?.inventory ?? state.payload;
  if (state.status !== "ready" || !inventory?.snapshot?.result) {
    return unavailableModel(
      { ...state, payload: inventory },
      t(language, "inventory.title"),
      language,
    );
  }
  const result = inventory.snapshot.result;
  const items = Array.isArray(result.items) ? result.items : [];
  const replenishment = state.payload?.inventory
    ? state.payload?.replenishment
    : null;
  const replenishmentItems = Array.isArray(
    replenishment?.snapshot?.result?.items,
  )
    ? replenishment.snapshot.result.items
    : [];
  const guidanceBySku = new Map(
    replenishmentItems.map((item) => [item.sku_id, item]),
  );
  const evidence = [
    ...(inventory.evidence ?? []),
    ...(replenishment?.evidence ?? []),
  ];
  const asOf = result.as_of ?? replenishment?.snapshot?.result?.as_of ?? null;
  const rows = items
    .map((item) => rowModel(
      item,
      guidanceBySku.get(item.sku_id),
      evidence,
      asOf,
      language,
    ))
    .sort(compareRows);
  const counts = Object.fromEntries(
    INVENTORY_PRIORITY_ORDER.map((priority) => [
      priority,
      rows.filter((item) => item.priority === priority).length,
    ]),
  );
  const knownCovers = items
    .map((item) => knownNumber(metricValue(item.current_cover_days)))
    .filter((value) => value !== null)
    .sort((left, right) => left - right);
  const assessedCount = rows.length - counts.Unavailable;
  const context = analyticsContext({ ...state, payload: inventory }, language);
  return {
    title: t(language, "inventory.title"),
    language,
    status: "ready",
    message: t(language, "inventory.message"),
    metrics: [
      {
        label: t(language, "inventory.assessed"),
        value: assessedCount
          ? formatInteger(assessedCount, language)
          : t(language, "common.unavailable"),
        definition: t(language, "inventory.assessedDefinition"),
      },
      {
        label: t(language, "inventory.immediate"),
        value: rows.length && counts.Unavailable === 0
          ? formatInteger(counts.P0, language)
          : t(language, "common.unavailable"),
        definition: t(language, "inventory.immediateDefinition"),
      },
      {
        label: t(language, "inventory.medianCover"),
        value: medianCover(knownCovers, language),
        definition: t(language, "inventory.medianDefinition"),
      },
    ],
    charts: [],
    rows,
    counts,
    evidence,
    limitations: [
      ...(inventory.snapshot.limitations ?? []),
      ...(replenishment?.snapshot?.limitations ?? []),
    ].filter((item, index, values) => values.indexOf(item) === index),
    period: context.period,
    versionLabel: t(language, "overview.currentData"),
  };
}

function rowModel(item, guidance, evidence, asOf, language) {
  const priority = priorityFor(item, guidance);
  const currentCover = knownNumber(metricValue(item.current_cover_days));
  const projectedCover = knownNumber(metricValue(item.projected_cover_days));
  const recommended = knownNumber(guidance?.recommended_quantity);
  return {
    skuId: String(item.sku_id ?? t(language, "common.unavailable")),
    priority,
    priorityLabel: t(language, `inventory.priority.${priority}`),
    reason: t(language, `inventory.reason.${priority}`),
    onHand: formatInteger(item.on_hand_units, language),
    dailyVelocity: formatDecimal(item.daily_velocity, language),
    currentCover: formatDays(currentCover, language),
    projectedCover: formatDays(projectedCover, language),
    expectedStockoutDate: stockoutDate(asOf, currentCover, language),
    recommendedQuantity: formatInteger(recommended, language),
    latestOrderDate:
      guidance?.latest_order_date ?? t(language, "common.unavailable"),
    evidence: evidence.find((entry) =>
      String(entry?.alias ?? "").includes(String(item.sku_id ?? ""))),
    simulationAvailable: priority !== "Unavailable",
    sortCover: currentCover ?? Number.POSITIVE_INFINITY,
  };
}

function priorityFor(item, guidance) {
  if (guidance?.priority === "urgent") return "P0";
  if (guidance?.priority === "soon") return "P1";
  if (guidance?.priority === "planned") {
    return knownNumber(guidance.recommended_quantity) > 0 ? "P2" : "Monitor";
  }
  if (guidance?.priority === "blocked") return "Unavailable";
  if (item?.risk === "stockout") return "P0";
  if (["balanced", "overstock"].includes(item?.risk)) return "Monitor";
  return "Unavailable";
}

function compareRows(left, right) {
  return (
    INVENTORY_PRIORITY_ORDER.indexOf(left.priority)
      - INVENTORY_PRIORITY_ORDER.indexOf(right.priority)
    || left.sortCover - right.sortCover
    || left.skuId.localeCompare(right.skuId)
  );
}

function medianCover(values, language) {
  if (!values.length) return t(language, "common.unavailable");
  const middle = Math.floor(values.length / 2);
  const value = values.length % 2
    ? values[middle]
    : (values[middle - 1] + values[middle]) / 2;
  return formatDays(value, language);
}

function stockoutDate(asOf, cover, language) {
  if (typeof asOf !== "string" || cover === null) {
    return t(language, "common.unavailable");
  }
  const parsed = new Date(`${asOf}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime())) {
    return t(language, "common.unavailable");
  }
  parsed.setUTCDate(parsed.getUTCDate() + Math.max(0, Math.floor(cover)));
  return parsed.toISOString().slice(0, 10);
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
