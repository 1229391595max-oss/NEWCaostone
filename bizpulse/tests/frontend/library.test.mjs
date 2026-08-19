import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { createLibraryEffects } from "../../frontend/assets/features/library/effects.mjs";
import { initialLibraryState, reduceLibrary } from "../../frontend/assets/features/library/state.mjs";
import { toLibraryViewModel } from "../../frontend/assets/features/library/view-model.mjs";
import { OPERATOR_DATA_CAPABILITIES, OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";
import { PUBLIC_DATA_CAPABILITIES, PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";
import { initialStoreScope, reduceStoreScope } from "../../frontend/assets/features/store-scope/state.mjs";

const version = {
  dataset_version_id: "version-opaque",
  version_number: 3,
  lifecycle: "current",
  created_at: "2026-08-16T12:00:00Z",
  period_start: "2026-05-01",
  period_end: "2026-07-31",
  stores: 1,
  skus: 6,
  source_roles: ["daily_sales", "inventory_receipt_lot"],
  row_count: 120,
  quality: { status: "complete", missing_roles: [], issue_count: 0 },
  preparation: { status: "ready", domains: [] },
  preview_available: true,
  export_available: false,
};

test("library model presents current dataset and dated import labels", () => {
  const state = reduceLibrary(initialLibraryState("operator"), {
    type: "library/loaded",
    versions: [version],
  });
  const model = toLibraryViewModel(state, "en");

  assert.equal(model.versions[0].label, "Current dataset");
  assert.equal(model.versions[0].historyLabel, "Imported dataset · Aug 16, 2026");
  assert.equal(model.versions[0].period, "2026-05-01 — 2026-07-31");
  assert.equal(JSON.stringify(model).includes("Version 3"), false);
  assert.equal(JSON.stringify(model).includes("version-opaque"), false);
  assert.equal(JSON.stringify(model).includes("sha256"), false);
});

test("library model preserves server-owned shared and store table labels", () => {
  let state = initialLibraryState("viewer");
  state = reduceLibrary(state, {
    type: "library/detail-loaded",
    detail: {
      ...version,
      tables: [
        { role: "product_catalog", row_count: 6, scope_kind: "shared" },
        { role: "daily_sales", row_count: 10, scope_kind: "store" },
      ],
      provenance: [],
      exports: [],
    },
  });

  const model = toLibraryViewModel(state, "en");
  assert.deepEqual(model.detail.tables.map((item) => item.scopeKind), [
    "shared",
    "store",
  ]);
});

test("operator and viewer library methods preserve mutation boundaries", async () => {
  const calls = [];
  const api = { request(path) { calls.push(path); return Promise.resolve({}); } };
  const operator = new OperatorDataSource(api, "selected-version");
  const viewer = new PublicDataSource(api, "selected-version");
  const scope = reduceStoreScope(initialStoreScope({
    dataset_version_id: "selected-version",
    store_catalog: [{
      store_id: "SYNTH-STORE-02",
      display_name_en: "Brazil Launch Store",
      display_name_zh: "巴西新店",
      has_data: true,
    }],
  }), { type: "scope/selected", storeId: "SYNTH-STORE-02" });

  await operator.listLibraryVersions();
  await operator.loadLibraryVersion("selected-version", scope);
  await viewer.loadLibrary(scope);
  await operator.loadLibraryTable("selected-version", "daily sales", {
    page: 2,
    pageSize: 25,
  }, scope);
  await viewer.loadLibraryTable("daily sales", { page: 3, pageSize: 100 }, scope);

  assert.deepEqual(calls, [
    "/api/v1/library",
    "/api/v1/library/selected-version?store_id=SYNTH-STORE-02",
    "/api/demo/library/current?store_id=SYNTH-STORE-02",
    "/api/v1/library/selected-version/tables/daily%20sales?page=2&page_size=25&store_id=SYNTH-STORE-02",
    "/api/demo/library/current/tables/daily%20sales?page=3&page_size=100&store_id=SYNTH-STORE-02",
  ]);
  assert.ok(OPERATOR_DATA_CAPABILITIES.includes("library"));
  assert.ok(PUBLIC_DATA_CAPABILITIES.includes("library"));
  assert.equal("publish" in viewer, false);
  assert.equal("generateDatasetExport" in viewer, false);
});

test("library state keeps the prior page after a page request fails", () => {
  const page = {
    role: "daily_sales",
    columns: ["date", "gross_sales_brl"],
    rows: [{ date: "2026-05-01", gross_sales_brl: "389.50" }],
    page: 1,
    page_size: 50,
    total_rows: 552,
    total_pages: 12,
  };
  let state = initialLibraryState("viewer");
  state = reduceLibrary(state, { type: "library/table-loaded", page });
  state = reduceLibrary(state, { type: "library/table-loading", role: "daily_sales" });
  state = reduceLibrary(state, { type: "library/table-failed", code: "NETWORK" });

  assert.equal(state.table.status, "error");
  assert.equal(state.table.role, "daily_sales");
  assert.equal(state.table.rows.length, 1);
  assert.equal(state.table.error, "NETWORK");

  state = reduceLibrary(state, { type: "library/row-opened", row: page.rows[0] });
  assert.deepEqual(state.rowDetail, page.rows[0]);
  state = reduceLibrary(state, { type: "library/row-closed" });
  assert.equal(state.rowDetail, null);
});

test("library effects open the first nonempty table for each mode", async () => {
  const detail = {
    ...version,
    tables: [
      { role: "empty_table", row_count: 0, columns: [], preview: [] },
      { role: "daily_sales", row_count: 120, columns: ["date"], preview: [] },
    ],
    provenance: [],
    analyses: [],
    exports: [],
  };
  const page = {
    role: "daily_sales",
    columns: ["date"],
    rows: [{ date: "2026-05-01" }],
    page: 1,
    page_size: 50,
    total_rows: 120,
    total_pages: 3,
  };

  for (const mode of ["operator", "viewer"]) {
    const actions = [];
    const calls = [];
    const dataSource = mode === "operator"
      ? {
          async listLibraryVersions() { return { versions: [version] }; },
          async loadLibraryVersion(versionId) { calls.push(["detail", versionId]); return detail; },
          async loadLibraryTable(versionId, role, options) {
            calls.push(["table", versionId, role, options]);
            return page;
          },
        }
      : {
          async loadLibrary() { return detail; },
          async loadLibraryTable(role, options) {
            calls.push(["table", role, options]);
            return page;
          },
        };
    const effects = createLibraryEffects({
      dataSource,
      mode,
      dispatch(action) { actions.push(action); },
    });

    await effects.load();

    assert.equal(actions.at(-1).type, "library/table-loaded");
    assert.equal(actions.at(-1).page.role, "daily_sales");
    assert.equal(calls.at(-1).at(-2) === "daily_sales" || calls.at(-1)[1] === "daily_sales", true);
  }
});

test("library effects discard an older table page after a tab switch", async () => {
  const pending = new Map();
  const actions = [];
  const dataSource = {
    loadLibraryTable(role) {
      return new Promise((resolve) => pending.set(role, resolve));
    },
  };
  const effects = createLibraryEffects({
    dataSource,
    mode: "viewer",
    dispatch(action) { actions.push(action); },
  });

  const older = effects.loadTable({ role: "daily_sales" });
  const newer = effects.loadTable({ role: "inventory_receipt_lot" });
  pending.get("inventory_receipt_lot")({
    role: "inventory_receipt_lot",
    columns: ["lot_id"],
    rows: [{ lot_id: "lot-1" }],
    page: 1,
    page_size: 50,
    total_rows: 1,
    total_pages: 1,
  });
  await newer;
  pending.get("daily_sales")({
    role: "daily_sales",
    columns: ["date"],
    rows: [{ date: "2026-05-01" }],
    page: 1,
    page_size: 50,
    total_rows: 1,
    total_pages: 1,
  });
  await older;

  const loaded = actions.filter((action) => action.type === "library/table-loaded");
  assert.deepEqual(loaded.map((action) => action.page.role), ["inventory_receipt_lot"]);
});

test("library effects discard a detail response from an invalidated store scope", async () => {
  let resolveDetail;
  const actions = [];
  const effects = createLibraryEffects({
    dataSource: {
      loadLibrary() {
        return new Promise((resolve) => { resolveDetail = resolve; });
      },
    },
    mode: "viewer",
    dispatch(action) { actions.push(action); },
    getScope: () => ({ generation: 1 }),
  });

  const pending = effects.load();
  effects.invalidate();
  resolveDetail({ ...version, tables: [], provenance: [], exports: [] });
  await pending;

  assert.equal(actions.some((action) => action.type === "library/detail-loaded"), false);
  assert.equal(actions.some((action) => action.type === "library/failed"), false);
});

test("library effects discard an older version detail after a rapid selection", async () => {
  const pending = new Map();
  const actions = [];
  const tableCalls = [];
  const dataSource = {
    loadLibraryVersion(versionId) {
      return new Promise((resolve) => pending.set(versionId, resolve));
    },
    async loadLibraryTable(versionId, role) {
      tableCalls.push([versionId, role]);
      return {
        role,
        columns: ["date"],
        rows: [{ date: "2026-08-16" }],
        page: 1,
        page_size: 50,
        total_rows: 1,
        total_pages: 1,
      };
    },
  };
  const effects = createLibraryEffects({
    dataSource,
    mode: "operator",
    dispatch(action) { actions.push(action); },
  });
  const detail = (versionId, role) => ({
    ...version,
    dataset_version_id: versionId,
    tables: [{ role, row_count: 1, columns: ["date"], preview: [] }],
    provenance: [],
    analyses: [],
    exports: [],
  });

  const older = effects.select("version-a");
  const newer = effects.select("version-b");
  pending.get("version-b")(detail("version-b", "daily_sales"));
  await newer;
  pending.get("version-a")(detail("version-a", "refund"));
  await older;

  assert.deepEqual(
    actions
      .filter((action) => action.type === "library/detail-loaded")
      .map((action) => action.detail.dataset_version_id),
    ["version-b"],
  );
  assert.deepEqual(tableCalls, [["version-b", "daily_sales"]]);
  assert.equal(actions.some((action) => action.type === "library/failed"), false);
});

test("operator export refresh keeps the selected table and page", async () => {
  const actions = [];
  const tableCalls = [];
  const detail = {
    ...version,
    dataset_version_id: "version-3",
    tables: [
      { role: "daily_sales", row_count: 120, columns: ["date"], preview: [] },
      { role: "refund", row_count: 18, columns: ["refund_id"], preview: [] },
    ],
    provenance: [],
    analyses: [],
    exports: [],
  };
  const dataSource = {
    async loadLibraryVersion() {
      return { ...detail, exports: [{ id: "export-1", status: "available" }] };
    },
    async loadLibraryTable(versionId, role, options) {
      tableCalls.push([versionId, role, options]);
      return {
        role,
        columns: ["refund_id"],
        rows: [{ refund_id: "refund-1" }],
        page: options.page,
        page_size: options.pageSize,
        total_rows: 18,
        total_pages: 1,
      };
    },
    async generateDatasetExport() {},
  };
  const effects = createLibraryEffects({
    dataSource,
    mode: "operator",
    dispatch(action) { actions.push(action); },
  });

  await effects.loadTable({
    versionId: "version-3",
    role: "refund",
    page: 3,
    pageSize: 25,
  });
  const beforeExport = tableCalls.length;
  await effects.generateExport("version-3");

  assert.equal(tableCalls.length, beforeExport);
  assert.equal(actions.at(-1).type, "export/completed");
  assert.equal(
    actions.filter((action) => action.type === "library/detail-loaded").at(-1)
      .detail.exports[0].id,
    "export-1",
  );
});

test("operator library generates and downloads an exact-version workbook", async () => {
  const calls = [];
  const api = {
    request(path, options) {
      calls.push([path, options]);
      return Promise.resolve({ id: "export-1", status: "available" });
    },
    downloadUrl(path) {
      calls.push([path, { download: true }]);
      return path;
    },
  };
  const operator = new OperatorDataSource(api, "selected-version");

  await operator.generateDatasetExport("version-3", "dataset-export-key");
  const download = operator.datasetExportDownloadUrl("version-3", "export-1");

  assert.equal(download, "/api/v1/datasets/versions/version-3/exports/export-1/download");
  assert.deepEqual(calls[0], [
    "/api/v1/datasets/versions/version-3/exports",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": "dataset-export-key",
        "X-CSRF-Token": "",
      },
      body: JSON.stringify({ format: "xlsx" }),
    },
  ]);
});

test("workspace exposes reachable Upload Library and Exports tabs", async () => {
  const source = await readFile(new URL("../../frontend/assets/features/workspace/view.mjs", import.meta.url), "utf8");
  const publicSource = await readFile(new URL("../../frontend/assets/features/workspace/public-view.mjs", import.meta.url), "utf8");
  for (const token of ["workspace.tab.upload", "workspace.tab.library", "workspace.tab.exports"]) {
    assert.ok(source.includes(token));
    assert.ok(publicSource.includes(token));
  }
});

test("library renderer is one accessible workbook instead of a card wall", async () => {
  const workbook = await readFile(
    new URL("../../frontend/assets/features/library/workbook-view.mjs", import.meta.url),
    "utf8",
  );
  const view = await readFile(
    new URL("../../frontend/assets/features/library/view.mjs", import.meta.url),
    "utf8",
  );
  const styles = await readFile(
    new URL("../../frontend/assets/styles.css", import.meta.url),
    "utf8",
  );

  for (const token of [
    'setAttribute("role", "tablist")',
    'setAttribute("role", "tab")',
    'setAttribute("role", "tabpanel")',
    'setAttribute("aria-selected"',
    "library-page-size",
    "library-data-table",
    "library-row-drawer",
    'element("dialog", "library-row-drawer")',
    "showModal()",
    "library.column.${column}",
  ]) {
    assert.ok(workbook.includes(token), token);
  }
  assert.equal(view.includes("library-table-grid"), false);
  assert.ok(styles.includes(".library-table-tabs"));
  assert.ok(styles.includes(".library-table-scroll"));
  assert.ok(styles.includes("overflow-x: auto"));
});

test("library loading remembers the requested page for retry", () => {
  let state = initialLibraryState("viewer");
  state = reduceLibrary(state, {
    type: "library/table-loading",
    role: "daily_sales",
    page: 3,
    pageSize: 25,
  });
  state = reduceLibrary(state, { type: "library/table-failed", code: "NETWORK" });

  assert.equal(state.table.requestPage, 3);
  assert.equal(state.table.requestPageSize, 25);
  assert.equal(state.table.error, "NETWORK");
});
