import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";
import { PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";
import {
  initialActionState,
  reduceActions,
} from "../../frontend/assets/features/action-inbox/state.mjs";
import { toActionInboxViewModel } from "../../frontend/assets/features/action-inbox/view-model.mjs";
import { commandAction } from "../../frontend/assets/features/action-inbox/effects.mjs";
import { estimateSimulation } from "../../frontend/assets/features/action-inbox/simulation.mjs";

const action = {
  id: "action-1",
  dataset_version_id: "version-1",
  source_type: "deterministic_rule",
  status: "approved",
  current_revision: 2,
  revisions: [
    {
      revision: 1,
      suggestion: "Reorder 40 units",
      target: "SYNTH-SKU-001",
      period_start: "2026-07-01",
      period_end: "2026-07-30",
      scope: { store_id: "SYNTH-STORE-01", currency: "BRL" },
      quantity: "40",
      budget_brl: "800.00",
      action_date: "2026-08-20",
      threshold: "12",
      expected_impact: { stockout_days_avoided: "8" },
      confidence: "medium",
      limitations: ["synthetic_demo_only"],
      facts: [{
        alias: "replenishment.quantity",
        evidence_state: "derived",
        source_ref: "analysis:run-1:replenishment.quantity",
        value: null,
      }],
      analysis_run_id: "run-1",
      forecast_id: null,
      bridge_id: null,
      chat_turn_id: null,
      chat_tool: null,
      answer_version: null,
      created_at: "2026-08-14T15:00:00Z",
    },
    {
      revision: 2,
      suggestion: "Reorder 48 units",
      target: "SYNTH-SKU-001",
      period_start: "2026-07-01",
      period_end: "2026-07-30",
      scope: { store_id: "SYNTH-STORE-01", currency: "BRL" },
      quantity: "48",
      budget_brl: null,
      action_date: "2026-08-20",
      threshold: "12",
      expected_impact: { stockout_days_avoided: "8" },
      confidence: "medium",
      limitations: ["synthetic_demo_only"],
      facts: [{
        alias: "replenishment.quantity",
        evidence_state: "derived",
        source_ref: "analysis:run-1:replenishment.quantity",
        value: null,
      }],
      analysis_run_id: "run-1",
      forecast_id: null,
      bridge_id: null,
      chat_turn_id: null,
      chat_tool: null,
      answer_version: null,
      created_at: "2026-08-14T15:01:00Z",
    },
  ],
  decisions: [
    { command: "review", action_revision: 1, reason: "Reviewed", decided_by: "single_operator", created_at: "2026-08-14T15:02:00Z" },
    { command: "adjust", action_revision: 2, reason: "MOQ", decided_by: "single_operator", created_at: "2026-08-14T15:03:00Z" },
    { command: "approve", action_revision: 2, reason: "Approved", decided_by: "single_operator", created_at: "2026-08-14T15:04:00Z" },
  ],
  exports: [{ id: "export-1", status: "available", note: "Not sent to an external platform", created_at: "2026-08-14T15:05:00Z" }],
  outcomes: [{ outcome_revision: 1, review_date: "2026-08-31", conclusion: "achieved", reason: "Synthetic target reached", synthetic_result: { units_received: "48" } }],
  viewer_overlays: [],
  simulation_inputs: {
    unit_cost_brl: "12.50",
    precomputed_daily_velocity: "5",
    baseline_budget_brl: "500.00",
    currency: "BRL",
  },
};

test("sandbox calculates only the three allowlisted estimates", () => {
  assert.deepEqual(estimateSimulation({
    quantity: "40",
    unitCostBrl: "12.50",
    simulatedBudgetBrl: "650.00",
    baselineBudgetBrl: "500.00",
    precomputedDailyVelocity: "5",
  }), {
    purchaseCashBrl: "500.00",
    budgetDeltaBrl: "150.00",
    additionalCoverDays: "8",
  });
});

test("sandbox returns unavailable instead of invented zero for missing authority", () => {
  assert.deepEqual(estimateSimulation({
    quantity: "40",
    unitCostBrl: null,
    simulatedBudgetBrl: "650.00",
    baselineBudgetBrl: null,
    precomputedDailyVelocity: "0",
  }), {
    purchaseCashBrl: "unavailable",
    budgetDeltaBrl: "unavailable",
    additionalCoverDays: "unavailable",
  });
});

test("simulation module is pure and cannot request analysis or AI", async () => {
  const source = await readFile(
    new URL("../../frontend/assets/features/action-inbox/simulation.mjs", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(source, /fetch\s*\(|loadAnalysis|submitChatTurn|runAnalysis/);
});

test("action reducer fences stale loads", () => {
  let state = initialActionState({ dataset_version_id: "version-1" }, "operator");
  state = reduceActions(state, { type: "actions/loading", generation: 2 });
  const stale = reduceActions(state, {
    type: "actions/loaded",
    generation: 1,
    payload: { items: [action] },
  });
  assert.equal(stale, state);
  const current = reduceActions(state, {
    type: "actions/loaded",
    generation: 2,
    payload: { items: [action] },
  });
  assert.equal(current.status, "ready");
  assert.equal(current.items.length, 1);
});

test("action model exposes evidence history and state-specific operator controls", () => {
  const model = toActionInboxViewModel({
    ...initialActionState({ version_number: 3, dataset_version_id: "version-1" }, "operator"),
    status: "ready",
    items: [action],
  });

  assert.equal(model.items[0].quantity, "48 units");
  assert.equal(model.items[0].budget, "—");
  assert.deepEqual(model.items[0].controls, ["export", "record_outcome"]);
  assert.equal(model.items[0].revisions.length, 2);
  assert.equal(model.items[0].decisions.at(-1).reason, "Approved");
  assert.equal(model.items[0].evidence[0].state, "derived");
  assert.equal(model.items[0].outcomes[0].conclusion, "achieved");
});

test("viewer controls follow only its own overlay state", () => {
  const payload = structuredClone(action);
  payload.viewer_overlays = [
    { status: "reviewed", command: "review", adjustment: {}, overlay_revision: 1 },
    {
      status: "reviewed",
      command: "adjust",
      adjustment: { quantity: "52", budget_brl: "900.00" },
      overlay_revision: 2,
      reason: "My simulation",
    },
  ];
  const model = toActionInboxViewModel({
    ...initialActionState({ dataset_version_id: "version-1" }, "viewer"),
    status: "ready",
    items: [payload],
  });

  assert.deepEqual(model.items[0].controls, ["adjust", "approve", "dismiss"]);
  assert.equal(model.items[0].displayStatus, "reviewed");
  assert.equal(model.items[0].quantity, "52 units");
  assert.match(model.items[0].budget, /900/);
  assert.equal(model.items[0].overlays[1].reason, "My simulation");
});

test("action mutation reuses one idempotency key after a lost response", async () => {
  const keys = [];
  const payloads = [];
  let attempt = 0;
  const dataSource = {
    async commandAction(_actionId, outbound, key) {
      keys.push(key);
      payloads.push(outbound);
      attempt += 1;
      if (attempt === 1) throw new Error("response_lost");
    },
  };
  const load = async () => {};
  const payload = { revision: 2, command: "approve", reason: "Approved" };
  const scope = { selectedId: "store:main", storeIds: ["SYNTH-STORE-01"] };
  await assert.rejects(commandAction(dataSource, load, "action-1", payload, scope));
  await commandAction(dataSource, load, "action-1", payload, scope);
  assert.equal(keys.length, 2);
  assert.equal(keys[0], keys[1]);
  assert.deepEqual(payloads[0].store_ids, ["SYNTH-STORE-01"]);
  assert.deepEqual(payloads[1], payloads[0]);
});

test("operator and viewer data sources keep mutation authority separate", async () => {
  const calls = [];
  const api = {
    async request(path, options) {
      calls.push([path, options]);
      if (path.endsWith("/overlays")) return { items: [] };
      return path.includes("actions") ? { items: [action] } : action;
    },
  };
  const oldSessionStorage = globalThis.sessionStorage;
  globalThis.sessionStorage = {
    getItem(key) {
      if (key === "bp_csrf_token") return "operator-csrf";
      if (key === "bp_demo_csrf_token") return "viewer-csrf";
      return null;
    },
  };
  try {
    const operator = new OperatorDataSource(api, "version-1");
    const viewer = new PublicDataSource(api, "version-1");
    await operator.loadActions();
    await operator.commandAction("action-1", { revision: 2, command: "approve" }, "operator-action-key");
    await viewer.loadActions();
    await viewer.commandAction("action-1", { base_revision: 2, command: "review", adjustment: {} }, "viewer-action-key");
    await viewer.resetActionSandbox();

    assert.match(calls[0][0], /^\/api\/v1\/actions\?/);
    assert.equal(calls[1][1].headers["X-CSRF-Token"], "operator-csrf");
    assert.equal(calls[1][1].headers["Idempotency-Key"], "operator-action-key");
    assert.equal(calls[2][0], "/api/demo/release/actions");
    assert.equal(calls[4][1].headers["X-CSRF-Token"], "viewer-csrf");
    assert.equal(calls[5][0], "/api/demo/action-sandbox");
    assert.equal(calls[5][1].method, "DELETE");
    assert.equal("exportAction" in viewer, false);
  } finally {
    globalThis.sessionStorage = oldSessionStorage;
  }
});

test("action feature is localized evidence-first UI without execution claims", async () => {
  const files = await Promise.all([
    "view.mjs",
    "view-model.mjs",
    "effects.mjs",
    "state.mjs",
  ].map((name) => readFile(
    new URL(`../../frontend/assets/features/action-inbox/${name}`, import.meta.url),
    "utf8",
  )));
  const source = files.join("\n");

  assert.match(source, /decision\.actions/);
  assert.match(source, /actions\.evidence/);
  assert.match(source, /actions\.export/);
  assert.match(source, /actions\.recordOutcome/);
  assert.match(source, /actions\.reviewDate/);
  assert.match(source, /partially_achieved/);
  assert.match(source, /synthetic_result: syntheticEntries/);
  assert.match(source, /actions\.saveFailed/);
  assert.match(source, /aria-live/);
  assert.match(source, /t\(language,/);
  assert.doesNotMatch(source, /\s\/\s[^"'`]*[\u3400-\u9fff]/);
  assert.doesNotMatch(source, /review_date: "2026-08-31"|recorded_in_demo/);
  assert.match(source, /actions\.boundary/);
  assert.doesNotMatch(source, /\bExecuted\b|\bCompleted\b|\b执行完成\b/i);
  assert.doesNotMatch(source, /fetch\s*\(|https?:\/\//);
});
