import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";
import { OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";
import {
  initialForecastState,
  reduceForecast,
} from "../../frontend/assets/features/forecast/state.mjs";
import { toForecastViewModel } from "../../frontend/assets/features/forecast/view-model.mjs";

const completed = {
  id: "forecast-1",
  dataset_version_id: "version-1",
  status: "completed",
  confidence: "medium",
  assumptions: ["synthetic_launch_ramp"],
  evidence: { source_classification: "pure_synthetic" },
  analogs: [
    {
      sku_id: "SYNTH-SKU-001",
      score: "0.91",
      confirmed: true,
      components: { category_match: "1.0", attribute_jaccard: "0.8" },
    },
    {
      sku_id: "SYNTH-SKU-006",
      score: "0.82",
      confirmed: true,
      components: { category_match: "0.7", attribute_jaccard: "0.6" },
    },
  ],
  result: {
    by_horizon: {
      7: {
        units: { low: 20, base: 30, high: 42 },
        revenue_brl: { low: "2000.00", base: "3000.00", high: "4200.00" },
        contribution_profit_brl: { low: "600.00", base: "1000.00", high: "1500.00" },
        stock_cover_days: { low: "28.00", base: "18.67", high: "13.33" },
      },
      30: {
        units: { low: 90, base: 150, high: 210 },
        revenue_brl: { low: "9000.00", base: "15000.00", high: "21000.00" },
        contribution_profit_brl: { low: "2700.00", base: "5000.00", high: "7500.00" },
        stock_cover_days: { low: "26.67", base: "16.00", high: "11.43" },
      },
      90: {
        units: { low: 270, base: 450, high: 630 },
        revenue_brl: { low: "27000.00", base: "45000.00", high: "63000.00" },
        contribution_profit_brl: { low: "8100.00", base: "15000.00", high: "22500.00" },
        stock_cover_days: { low: "26.67", base: "16.00", high: "11.43" },
      },
    },
    recommended_first_order_units: 150,
    moq_compliant_first_order_units: 168,
    confidence_reasons: ["at_least_two_confirmed_analogs"],
    missing_fields: [],
    limitations: [],
  },
  backtest: {
    mae_units: "4.00",
    wape: "0.050000",
    interval_coverage: "1.000000",
    exact_repeat: true,
    synthetic_demo_only: true,
  },
};

test("forecast state keeps explicit workflow phases", () => {
  let state = initialForecastState({ dataset_version_id: "version-1" }, "operator");
  state = reduceForecast(state, { type: "forecast/loaded", payload: null });
  assert.equal(state.status, "empty");
  state = reduceForecast(state, { type: "forecast/created", payload: { ...completed, status: "draft" } });
  assert.equal(state.status, "draft");
  state = reduceForecast(state, { type: "forecast/confirmed", payload: { ...completed, status: "analogs_confirmed" } });
  assert.equal(state.status, "confirmed");
  state = reduceForecast(state, { type: "forecast/completed", payload: completed });
  assert.equal(state.status, "ready");
});

test("forecast view model exposes 7 30 90 intervals and evidence", () => {
  const model = toForecastViewModel({
    ...initialForecastState({ version_number: 4, dataset_version_id: "version-1" }, "viewer"),
    status: "ready",
    forecast: completed,
  });

  assert.equal(model.status, "ready");
  assert.deepEqual(model.horizons.map((item) => item.days), [7, 30, 90]);
  assert.deepEqual(model.horizons[1].units, { low: 90, base: 150, high: 210 });
  assert.equal(model.confidence, "medium");
  assert.equal(model.recommendedFirstOrder, "150 units");
  assert.equal(model.moqFirstOrder, "168 units");
  assert.equal(model.actionDraftEligible, true);
  assert.equal(model.backtest.syntheticOnly, true);
  assert.deepEqual(model.analogIds, ["SYNTH-SKU-001", "SYNTH-SKU-006"]);
  assert.deepEqual(model.analogs[0].components, [
    "attribute_jaccard 0.8",
    "category_match 1",
  ]);
});

test("unknown contribution profit never formats as zero", () => {
  const payload = structuredClone(completed);
  payload.result.by_horizon[30].contribution_profit_brl.base = null;
  const model = toForecastViewModel({
    ...initialForecastState({ version_number: 1 }, "viewer"),
    status: "ready",
    forecast: payload,
  });

  assert.equal(
    model.horizons[1].contributionProfit.base,
    "—",
  );
});

test("unknown unit intervals and order guidance never format as zero", () => {
  const payload = structuredClone(completed);
  payload.result.by_horizon[30].units = { low: null, base: null, high: null };
  payload.result.recommended_first_order_units = null;
  payload.result.moq_compliant_first_order_units = null;
  const model = toForecastViewModel({
    ...initialForecastState({ version_number: 1 }, "viewer"),
    status: "ready",
    forecast: payload,
  });

  assert.deepEqual(model.horizons.map((item) => item.days), [7, 90]);
  assert.equal(model.recommendedFirstOrder, "Unavailable");
  assert.equal(model.moqFirstOrder, "Unavailable");
});

test("public forecast read is version pinned and operator owns mutations", async () => {
  const calls = [];
  const api = {
    async request(path, options) {
      calls.push([path, options]);
      return completed;
    },
  };
  const publicSource = new PublicDataSource(api, "version-1");
  const operatorSource = new OperatorDataSource(api, "version-1");

  await publicSource.loadForecast();
  await operatorSource.createForecast(
    { dataset_version_id: "version-1" },
    "frontend-forecast-001",
  );
  await operatorSource.confirmForecast("forecast-1", ["SYNTH-SKU-001"]);
  await operatorSource.runForecast("forecast-1");

  assert.equal("createForecast" in publicSource, false);
  assert.deepEqual(calls[0], [
    "/api/demo/release/forecasts/latest",
    { cache: "no-store" },
  ]);
  assert.match(calls[1][0], /^\/api\/v1\/forecasts$/);
  assert.equal(calls[1][1].method, "POST");
  assert.equal(calls[1][1].headers["Idempotency-Key"], "frontend-forecast-001");
  assert.match(calls[2][0], /\/analogs\/confirm$/);
  assert.match(calls[3][0], /\/run$/);
});

test("forecast feature is localized sample-data UI with intervals tabs and confirmation", async () => {
  const files = await Promise.all([
    "view.mjs",
    "view-model.mjs",
    "effects.mjs",
    "state.mjs",
  ].map((name) => readFile(
    new URL(`../../frontend/assets/features/forecast/${name}`, import.meta.url),
    "utf8",
  )));
  const source = files.join("\n");

  assert.match(source, /7.*30.*90/s);
  assert.match(source, /forecast\.confirmAnalogs/);
  assert.match(source, /forecast\.backtest/);
  assert.match(source, /interval/i);
  assert.match(source, /t\(language,/);
  assert.doesNotMatch(source, /\s\/\s[^"'`]*[\u3400-\u9fff]/);
  assert.doesNotMatch(source, /fetch\s*\(/);
  assert.doesNotMatch(source, /trends|scrap|search engine/i);
});
