import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";
import { OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";
import { toOverviewViewModel } from "../../frontend/assets/features/overview/view-model.mjs";
import {
  formatBrl,
  toAnalysisViewModel,
} from "../../frontend/assets/features/analysis/view-model.mjs";
import { toInventoryViewModel } from "../../frontend/assets/features/inventory/view-model.mjs";
import { toProfitViewModel } from "../../frontend/assets/features/profit/view-model.mjs";
import { initialStoreScope, reduceStoreScope } from "../../frontend/assets/features/store-scope/state.mjs";

test("public data source exposes reads only and sends one catalog-validated store scope", async () => {
  const calls = [];
  const source = new PublicDataSource({
    async request(path, options) {
      calls.push([path, options]);
      return {
        run: { kind: "sales_ads", dataset_version_id: "version-1" },
        snapshot: {},
        evidence: [],
      };
    },
  }, "version-1");

  const scope = reduceStoreScope(initialStoreScope({
    dataset_version_id: "version-1",
    store_catalog: [{
      store_id: "SYNTH-STORE-02",
      display_name_en: "Brazil Launch Store",
      display_name_zh: "巴西新店",
      has_data: true,
    }],
  }), { type: "scope/selected", storeId: "SYNTH-STORE-02" });
  await source.loadAnalysis("sales_ads", scope);

  assert.deepEqual(calls, [[
    "/api/demo/release/analyses/sales_ads?store_id=SYNTH-STORE-02",
    { cache: "no-store" },
  ]]);
  assert.equal("publish" in source, false);
  assert.equal("upload" in source, false);
});

test("public and operator data sources fail closed on release drift", async () => {
  const api = {
    async request() {
      return {
        run: { kind: "sales_ads", dataset_version_id: "version-new" },
        snapshot: {},
        evidence: [],
      };
    },
  };

  await assert.rejects(
    new PublicDataSource(api, "version-pinned").loadAnalysis("sales_ads"),
    /ANALYSIS_RELEASE_MISMATCH/,
  );
  await assert.rejects(
    new OperatorDataSource(api, "version-at-bootstrap").loadAnalysis("sales_ads"),
    /ANALYSIS_RELEASE_MISMATCH/,
  );
});

test("analytical view models expose unavailable state instead of fallback numbers", () => {
  const failed = { status: "error", payload: null, error: "ANALYSIS_NOT_FOUND" };

  for (const model of [
    toOverviewViewModel(failed),
    toAnalysisViewModel(failed),
    toInventoryViewModel(failed),
    toProfitViewModel(failed),
  ]) {
    assert.equal(model.status, "unavailable");
    assert.deepEqual(model.metrics, []);
    assert.doesNotMatch(JSON.stringify(model), /mock|fallback|sample/i);
  }
});

test("missing money never renders as zero while measured zero stays explicit", () => {
  assert.equal(formatBrl(null), "—");
  assert.equal(formatBrl(undefined), "—");
  assert.equal(formatBrl(""), "—");
  assert.equal(formatBrl("0.00"), "R$0.00");
});

test("sales and inventory projections retain definition period version and evidence", () => {
  const payload = {
    status: "ready",
    error: null,
    release: { version_number: 3, dataset_version_id: "version-3" },
    payload: {
      run: { kind: "sales_ads", dataset_version_id: "version-3" },
      snapshot: {
        scope: {
          period_start: "2026-07-01",
          period_end: "2026-07-30",
          currency: "BRL",
        },
        result: {
          gross_sales: { value: "100.00", evidence_state: "measured" },
          net_sales: { value: "90.00", evidence_state: "derived" },
          daily_sales: [
            { date: "2026-07-01", net_sales: "40.00" },
            { date: "2026-07-02", net_sales: "50.00" },
          ],
        },
      },
      evidence: [{ alias: "sales.gross", evidence_state: "measured" }],
    },
  };

  const model = toAnalysisViewModel(payload);

  assert.equal(model.metrics[0].value, "R$100.00");
  assert.equal(model.period, "2026-07-01 — 2026-07-30");
  assert.equal(model.versionLabel, "Current dataset");
  assert.equal(model.evidence.length, 1);
  assert.equal(model.charts[0].type, "line");
  assert.equal(model.title, "Sales and advertising");
  assert.equal(model.metrics[0].label, "Gross sales");
});

test("sales trend is withheld when any daily value is missing", () => {
  const model = toAnalysisViewModel({
    status: "ready",
    release: { version_number: 1 },
    payload: {
      snapshot: {
        scope: {
          period_start: "2026-07-01",
          period_end: "2026-07-02",
        },
        result: {
          gross_sales: { value: "10.00" },
          net_sales: { value: "10.00" },
          ad_spend: { value: "1.00" },
          daily_sales: [
            { date: "2026-07-01", net_sales: "10.00" },
            {
              date: "2026-07-02",
              net_sales: { value: null, evidence_state: "unknown" },
            },
          ],
        },
      },
      evidence: [],
    },
  });

  assert.deepEqual(model.charts, []);
});

test("inventory median excludes unknown cover instead of treating it as zero", () => {
  const model = toInventoryViewModel({
    status: "ready",
    release: { version_number: 1 },
    payload: {
      snapshot: {
        scope: {
          period_start: "2026-07-01",
          period_end: "2026-07-02",
        },
        result: {
          items: [
            { risk: "balanced", current_cover_days: { value: "2.0" } },
            { risk: "unknown", current_cover_days: { value: null } },
          ],
        },
      },
      evidence: [],
    },
  });

  assert.equal(model.metrics[2].value, "2 days");
  assert.equal(model.metrics[1].value, "Unavailable");
});

test("inventory uses a stable P0 P1 P2 Monitor list instead of a one-color chart", () => {
  const scope = { period_start: "2026-07-01", period_end: "2026-07-31" };
  const inventoryItems = [
    { sku_id: "SKU-P2", on_hand_units: 80, daily_velocity: "4.1234", current_cover_days: { value: "19.402" }, projected_cover_days: { value: "19.402" }, risk: "balanced" },
    { sku_id: "SKU-P0", on_hand_units: 0, daily_velocity: "5", current_cover_days: { value: "0" }, projected_cover_days: { value: "0" }, risk: "stockout" },
    { sku_id: "SKU-M", on_hand_units: 400, daily_velocity: "2", current_cover_days: { value: "200" }, projected_cover_days: { value: "200" }, risk: "overstock" },
    { sku_id: "SKU-U", on_hand_units: 12, daily_velocity: null, current_cover_days: { value: null }, projected_cover_days: { value: null }, risk: "unknown" },
    { sku_id: "SKU-P1", on_hand_units: 28, daily_velocity: "4", current_cover_days: { value: "7" }, projected_cover_days: { value: "7" }, risk: "balanced" },
  ];
  const replenishmentItems = [
    { sku_id: "SKU-P2", priority: "planned", recommended_quantity: 40, latest_order_date: "2026-08-20" },
    { sku_id: "SKU-P0", priority: "urgent", recommended_quantity: 100, latest_order_date: "2026-07-31" },
    { sku_id: "SKU-M", priority: "planned", recommended_quantity: 0, latest_order_date: "2026-11-01" },
    { sku_id: "SKU-U", priority: "blocked", recommended_quantity: null, latest_order_date: null },
    { sku_id: "SKU-P1", priority: "soon", recommended_quantity: 60, latest_order_date: "2026-08-05" },
  ];
  const model = toInventoryViewModel({
    status: "ready",
    release: { version_number: 2 },
    payload: {
      inventory: {
        run: { run_id: "inventory-run" },
        snapshot: { scope, result: { as_of: "2026-07-31", items: inventoryItems } },
        evidence: [],
      },
      replenishment: {
        snapshot: { scope, result: { as_of: "2026-07-31", items: replenishmentItems } },
        evidence: [],
      },
    },
  });

  assert.deepEqual(model.rows.map((item) => item.priority), [
    "P0",
    "P1",
    "P2",
    "Monitor",
    "Unavailable",
  ]);
  assert.deepEqual(model.counts, { P0: 1, P1: 1, P2: 1, Monitor: 1, Unavailable: 1 });
  assert.equal(model.rows[2].dailyVelocity, "4.12");
  assert.equal(model.rows[2].currentCover, "19.4 days");
  assert.deepEqual(model.charts, []);
});

test("missing inventory and overview risk stay unavailable with limitations", () => {
  const inventoryPayload = {
    run: { dataset_version_id: "version-1" },
    snapshot: {
      scope: { period_start: "2026-07-01", period_end: "2026-07-30" },
      limitations: ["inventory_missing"],
      result: { items: [] },
    },
    evidence: [],
  };
  const inventory = toInventoryViewModel({
    status: "ready",
    release: { version_number: 1 },
    payload: inventoryPayload,
  });
  const overview = toOverviewViewModel({
    status: "ready",
    release: { version_number: 1 },
    payload: {
      sales: {
        snapshot: { scope: inventoryPayload.snapshot.scope, result: {} },
        evidence: [],
      },
      inventory: inventoryPayload,
      profit: { snapshot: { result: {} }, evidence: [] },
    },
  });

  assert.equal(inventory.metrics[0].value, "Unavailable");
  assert.equal(inventory.metrics[1].value, "Unavailable");
  assert.deepEqual(inventory.limitations, ["inventory_missing"]);
  assert.equal(overview.metrics[5].value, "Unavailable");
  assert.deepEqual(overview.limitations, ["inventory_missing"]);
});

test("overview is a dense operating dashboard rather than four empty KPI cards", () => {
  const scope = {
    period_start: "2026-07-01",
    period_end: "2026-07-31",
    currency: "BRL",
  };
  const model = toOverviewViewModel({
    status: "ready",
    release: { version_number: 4, dataset_version_id: "version-4" },
    payload: {
      sales: {
        snapshot: {
          scope,
          result: {
            net_sales: { value: "12500.456" },
            orders: { value: "168" },
            roas: { value: "3.4567" },
            ad_spend: { value: "820.129" },
            daily_trends: [
              { date: "2026-07-01", net_sales: "300.00" },
              { date: "2026-07-02", net_sales: "420.00" },
            ],
            anomalies: ["sales_spike:2026-07-02"],
          },
        },
        evidence: [{ alias: "sales.net", evidence_state: "derived" }],
      },
      inventory: {
        snapshot: {
          scope,
          result: {
            items: [
              { sku_id: "SKU-A", risk: "stockout" },
              { sku_id: "SKU-B", risk: "balanced" },
            ],
          },
        },
        evidence: [{ alias: "inventory:SKU-A", evidence_state: "derived" }],
      },
      profit: {
        snapshot: {
          scope,
          result: {
            contribution_profit: { value: "2400.765" },
            components: [
              ["gross_sales", "14000.00"],
              ["advertising", "820.129"],
            ],
          },
        },
        evidence: [{ alias: "profit.contribution", evidence_state: "derived" }],
      },
      replenishment: {
        snapshot: { scope, result: { items: [] } },
        evidence: [],
      },
      actions: { items: [{ id: "action-1" }, { id: "action-2" }] },
    },
  });

  assert.equal(model.metrics.length, 6);
  assert.deepEqual(
    model.metrics.map((item) => item.value),
    ["R$12,500.46", "168", "3.46×", "R$820.13", "R$2,400.77", "1"],
  );
  assert.deepEqual(model.charts.map((item) => item.type), ["line", "bar"]);
  assert.equal(model.coverage.filter((item) => item.status === "ready").length, 4);
  assert.equal(model.alerts.length, 1);
  assert.equal(model.pendingActions, 2);
  assert.deepEqual(model.urgentInventory.map((item) => item.skuId), ["SKU-A"]);
  assert.doesNotMatch(JSON.stringify(model), /\bv4\b|version-4/);
});

test("analysis renderer exposes limitations instead of hiding missing coverage", async () => {
  const source = await readFile(
    new URL("../../frontend/assets/features/analysis/view.mjs", import.meta.url),
    "utf8",
  );

  assert.match(source, /common\.limitations/);
  assert.match(source, /model\.limitations/);
});

test("analysis renderer collapses Evidence to four and keeps one accessible chart summary", async () => {
  const source = await readFile(
    new URL("../../frontend/assets/features/analysis/view.mjs", import.meta.url),
    "utf8",
  );

  assert.match(source, /visibleItems\(model\.evidence, expandedEvidence, 4\)/);
  assert.match(source, /dataset\.evidenceItem/);
  assert.match(source, /aria-expanded/);
  assert.match(source, /chart-text-summary visually-hidden/);
  assert.match(source, /caption\.setAttribute\("aria-hidden", "true"\)/);
});

test("responsive analytics CSS includes compact laptop and mobile contracts", async () => {
  const css = await readFile(
    new URL("../../frontend/assets/styles.css", import.meta.url),
    "utf8",
  );

  assert.match(css, /@media \(max-width: 820px\)/);
  assert.match(css, /@media \(max-width: 390px\)/);
  assert.match(css, /\.analytics-grid/);
  assert.match(css, /\.chart-card/);
});

test("inventory row dividers use table-cell geometry across every column", async () => {
  const [view, css] = await Promise.all([
    readFile(
      new URL("../../frontend/assets/features/inventory/view.mjs", import.meta.url),
      "utf8",
    ),
    readFile(new URL("../../frontend/assets/styles.css", import.meta.url), "utf8"),
  ]);

  assert.match(view, /inventory-sku-content/);
  assert.match(view, /inventory-row-actions-content/);
  assert.doesNotMatch(css, /\.inventory-sku\s*\{[^}]*display:\s*flex/);
  assert.doesNotMatch(css, /\.inventory-row-actions\s*\{[^}]*display:\s*grid/);
  assert.match(css, /\.inventory-sku-content\s*\{[^}]*display:\s*flex/);
  assert.match(css, /\.inventory-row-actions-content\s*\{[^}]*display:\s*grid/);
});
