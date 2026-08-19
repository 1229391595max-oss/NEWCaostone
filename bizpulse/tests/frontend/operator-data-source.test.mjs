import assert from "node:assert/strict";
import test from "node:test";

import { OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";
import { initialStoreScope, reduceStoreScope } from "../../frontend/assets/features/store-scope/state.mjs";

const scopedRelease = {
  dataset_version_id: "version-2",
  store_catalog: [{
    store_id: "SYNTH-STORE-02",
    display_name_en: "Brazil Launch Store",
    display_name_zh: "巴西新店",
    has_data: true,
  }],
};

test("operator data source binds every read and mutation to one exact version", async () => {
  const calls = [];
  const client = {
    request(path, options = {}) {
      calls.push([path, options]);
      if (path.includes("/analyses/versions/")) {
        return Promise.resolve({ run: { dataset_version_id: "version-2" } });
      }
      if (path.includes("/actions")) return Promise.resolve({ items: [] });
      return Promise.resolve({ dataset_version_id: "version-2" });
    },
  };
  const original = new OperatorDataSource(client, "version-1");
  const selected = original.forVersion("version-2");
  const scope = reduceStoreScope(initialStoreScope(scopedRelease), {
    type: "scope/selected",
    storeId: "SYNTH-STORE-02",
  });

  await selected.loadAnalysis("sales_ads", scope);
  await selected.loadForecast(scope);
  await selected.loadProfitBridge(scope);
  await selected.loadActions(scope);
  await selected.prepare();

  assert.equal(original.expectedVersionId, "version-1");
  assert.equal(selected.expectedVersionId, "version-2");
  assert.ok(calls.every(([path]) => !path.includes("version-1")));
  assert.ok(calls.some(([path]) => path === "/api/v1/analyses/versions/version-2/sales_ads?store_id=SYNTH-STORE-02"));
  assert.ok(calls.some(([path]) => path === "/api/v1/forecasts/latest?dataset_version_id=version-2&store_id=SYNTH-STORE-02"));
  assert.ok(calls.some(([path]) => path === "/api/v1/profit-bridges/default?dataset_version_id=version-2&store_id=SYNTH-STORE-02"));
  assert.ok(calls.some(([path]) => path === "/api/v1/actions?dataset_version_id=version-2&store_id=SYNTH-STORE-02"));
  assert.ok(calls.some(([path]) => path === "/api/v1/datasets/versions/version-2/prepare"));
});

test("operator data source builds an encoded conflict CSV URL", () => {
  const dataSource = new OperatorDataSource({ request() {} }, "version-2");

  assert.equal(
    dataSource.conflictDownloadUrl("workflow/with space"),
    "/api/v1/import-workflows/workflow%2Fwith%20space/conflicts.csv",
  );
});
