import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { waterfallChartSvg } from "../../frontend/assets/core/charts.mjs";
import { OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";
import { PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";
import {
  initialProfitState,
  reduceProfit,
} from "../../frontend/assets/features/profit/state.mjs";
import { toProfitViewModel } from "../../frontend/assets/features/profit/view-model.mjs";

const driverOrder = [
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
];

function bridgePayload() {
  return {
    id: "bridge-1",
    dataset_version_id: "version-1",
    baseline_analysis_id: "analysis-0",
    current_analysis_id: "analysis-1",
    formula_version: "profit_bridge.v1",
    scope: {
      store_id: "SYNTH-STORE-01",
      currency: "BRL",
      comparison_period: ["2026-06-01", "2026-06-30"],
      current_period: ["2026-07-01", "2026-07-30"],
    },
    baseline_period: ["2026-06-01", "2026-06-30"],
    current_period: ["2026-07-01", "2026-07-30"],
    baseline_contribution_profit_brl: "100.00",
    current_contribution_profit_brl: "106.00",
    total_delta_brl: "6.00",
    residual_brl: "4.00",
    reconciled: false,
    limitations: ["fulfillment_missing", "bridge_inputs_incomplete"],
    items: driverOrder.map((driver, index) => ({
      driver,
      ordinal: index + 1,
      amount_brl: driver === "fulfillment" ? null : driver === "residual" ? "4.00" : "0.20",
      evidence_state: driver === "fulfillment" || driver === "residual" ? "unknown" : "derived",
      formula: `${driver}_formula`,
      source_refs: [`${driver}_source`],
    })),
  };
}

function readyState() {
  return {
    ...initialProfitState({ version_number: 3, dataset_version_id: "version-1" }),
    status: "ready",
    payload: {
      run: {
        run_id: "analysis-1",
        dataset_version_id: "version-1",
      },
      snapshot: {
        scope: {
          store_id: "SYNTH-STORE-01",
          currency: "BRL",
          period_start: "2026-07-01",
          period_end: "2026-07-30",
        },
        limitations: [],
        result: {
          net_revenue: { value: "200.00" },
          contribution_profit: { value: "106.00" },
          operating_profit: { value: "80.00" },
          components: [],
        },
      },
      evidence: [],
    },
    bridge: bridgePayload(),
  };
}

test("profit bridge keeps fixed driver order and unknown values explicit", () => {
  const model = toProfitViewModel(readyState());

  assert.equal(model.status, "ready");
  assert.deepEqual(model.bridge.items.map((item) => item.driver), driverOrder);
  const fulfillment = model.bridge.items.find((item) => item.driver === "fulfillment");
  assert.equal(fulfillment.value, null);
  assert.equal(fulfillment.displayValue, "Unavailable");
  assert.equal(model.bridge.reconciled, false);
  assert.match(model.bridge.periodLabel, /2026-06-01.*2026-07-30/);
  assert.deepEqual(model.limitations, [
    "fulfillment_missing",
    "bridge_inputs_incomplete",
  ]);
});

test("profit reducer fences stale combined analysis and bridge results", () => {
  let state = initialProfitState({ dataset_version_id: "version-1" });
  state = reduceProfit(state, { type: "request/started", generation: 2 });
  const stale = reduceProfit(state, {
    type: "request/completed",
    generation: 1,
    payload: {},
    bridge: bridgePayload(),
  });
  assert.equal(stale, state);
  const current = reduceProfit(state, {
    type: "request/completed",
    generation: 2,
    payload: readyState().payload,
    bridge: bridgePayload(),
    bridgeError: null,
  });
  assert.equal(current.status, "ready");
  assert.equal(current.bridge.id, "bridge-1");
});

test("profit model rejects a bridge from a different analysis authority", () => {
  const state = readyState();
  state.bridge = { ...state.bridge, current_analysis_id: "analysis-other" };

  const model = toProfitViewModel(state);

  assert.equal(model.status, "ready");
  assert.equal(model.bridge.status, "unavailable");
  assert.equal(model.bridge.message, "PROFIT_BRIDGE_AUTHORITY_MISMATCH");
});

test("waterfall chart exposes signed values, unknowns, and exact context", () => {
  const svg = waterfallChartSvg({
    title: "Contribution profit bridge",
    summary: "Known drivers reconcile baseline to current; unknowns remain explicit.",
    period: "2026-06-01 — 2026-06-30 vs 2026-07-01 — 2026-07-30",
    definition: "Fixed-order contribution-profit change in BRL.",
    version: "Current dataset",
    baseline: 100,
    current: 106,
    items: [
      { label: "Volume", value: 10, evidenceState: "derived" },
      { label: "Fulfillment", value: null, evidenceState: "unknown" },
      { label: "Residual", value: -4, evidenceState: "derived" },
    ],
  });

  assert.match(svg, /role="img"/);
  assert.match(svg, /<title>Contribution profit bridge/);
  assert.match(svg, /Baseline.*R\$100\.00/);
  assert.match(svg, /Current.*R\$106\.00/);
  assert.match(svg, /\+R\$10\.00/);
  assert.match(svg, /Unavailable/);
  assert.doesNotMatch(svg, /NaN|Infinity/);
});

test("public bridge read is session pinned and only operator can run", async () => {
  const calls = [];
  const api = {
    async request(path, options) {
      calls.push([path, options]);
      return bridgePayload();
    },
  };
  const publicSource = new PublicDataSource(api, "version-1");
  const operatorSource = new OperatorDataSource(api, "version-1");

  await publicSource.loadProfitBridge();
  await operatorSource.loadProfitBridge();
  await operatorSource.runProfitBridge({ dataset_version_id: "version-1" });

  assert.equal("runProfitBridge" in publicSource, false);
  assert.deepEqual(calls[0], [
    "/api/demo/release/profit-bridge/current",
    { cache: "no-store" },
  ]);
  assert.match(calls[1][0], /^\/api\/v1\/profit-bridges\/default/);
  assert.equal(calls[2][0], "/api/v1/profit-bridges");
  assert.equal(calls[2][1].method, "POST");
});

test("profit feature is localized UI with evidence and no external calls", async () => {
  const files = await Promise.all([
    "view.mjs",
    "view-model.mjs",
    "effects.mjs",
    "state.mjs",
  ].map((name) => readFile(
    new URL(`../../frontend/assets/features/profit/${name}`, import.meta.url),
    "utf8",
  )));
  const source = files.join("\n");

  assert.match(source, /profit\.bridge/);
  assert.match(source, /profit\.residual/);
  assert.match(source, /common\.evidence/);
  assert.match(source, /common\.unavailable/);
  assert.doesNotMatch(source, /\s\/\s[^"'`]*[\u3400-\u9fff]/);
  assert.doesNotMatch(source, /fetch\s*\(|https?:\/\//);
});
