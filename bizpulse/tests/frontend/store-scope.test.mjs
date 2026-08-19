import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  initialStoreScope,
  reduceStoreScope,
  scopeQuery,
} from "../../frontend/assets/features/store-scope/state.mjs";
import {
  loadViewerSettings,
  saveViewerSettings,
} from "../../frontend/assets/features/settings/state.mjs";
import { PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";

const release = Object.freeze({
  dataset_version_id: "version-2",
  store_catalog: Object.freeze([
    Object.freeze({
      store_id: "SYNTH-STORE-01",
      display_name_en: "Brazil Main Store",
      display_name_zh: "巴西主店",
      has_data: true,
    }),
    Object.freeze({
      store_id: "SYNTH-STORE-02",
      display_name_en: "Brazil Launch Store",
      display_name_zh: "巴西新店",
      has_data: true,
    }),
  ]),
});

test("store scope initializes from a valid default and keeps approved option order", () => {
  const state = initialStoreScope(release, "SYNTH-STORE-02");

  assert.equal(state.selectedId, "SYNTH-STORE-02");
  assert.equal(state.generation, 0);
  assert.deepEqual(state.options.map((item) => item.id), [
    "all",
    "SYNTH-STORE-01",
    "SYNTH-STORE-02",
  ]);
  assert.deepEqual(state.storeIds, ["SYNTH-STORE-02"]);
});

test("store scope fails closed to all and rejects unknown or multi-store client scope", () => {
  const initial = initialStoreScope(release, "unknown-store");
  assert.equal(initial.selectedId, "all");
  assert.deepEqual(initial.storeIds, []);

  assert.throws(
    () => reduceStoreScope(initial, { type: "scope/selected", storeId: "unknown-store" }),
    /STORE_SCOPE_INVALID/,
  );
  assert.throws(
    () => scopeQuery({ selectedId: "custom", storeIds: ["one", "two"] }),
    /STORE_SCOPE_INVALID/,
  );
});

test("scope query omits all-store selection and encodes one validated store", () => {
  const all = initialStoreScope(release, "all");
  const launch = reduceStoreScope(all, {
    type: "scope/selected",
    storeId: "SYNTH-STORE-02",
  });

  assert.equal(scopeQuery(all).toString(), "");
  assert.equal(scopeQuery(launch).toString(), "store_id=SYNTH-STORE-02");
  assert.equal(launch.generation, all.generation + 1);
});

test("same selection is stable while a changed selection invalidates old generations", () => {
  const initial = initialStoreScope(release, "all");
  const same = reduceStoreScope(initial, { type: "scope/selected", storeId: "all" });
  const changed = reduceStoreScope(initial, {
    type: "scope/selected",
    storeId: "SYNTH-STORE-01",
  });

  assert.equal(same, initial);
  assert.notEqual(changed.generation, initial.generation);
  assert.equal(initial.generation === changed.generation, false);
});

test("viewer store selection persists only through injected session storage", () => {
  const values = new Map();
  const storage = {
    getItem(key) { return values.get(key) ?? null; },
    setItem(key, value) { values.set(key, value); },
  };
  saveViewerSettings({ default_store: "SYNTH-STORE-02" }, storage);

  assert.equal(loadViewerSettings(storage).default_store, "SYNTH-STORE-02");
  assert.equal(values.size, 1);
});

test("viewer business reads propagate the same exact store scope across pages", async () => {
  const paths = [];
  const source = new PublicDataSource({
    async request(path) {
      paths.push(path);
      if (path.includes("/analyses/")) {
        return { run: { dataset_version_id: "version-2" } };
      }
      if (path.includes("/forecasts/")) return { dataset_version_id: "version-2" };
      if (path.includes("profit-bridge")) return { dataset_version_id: "version-2" };
      if (path.includes("/actions/") && path.includes("/overlays")) return { items: [] };
      if (path.endsWith("store_id=SYNTH-STORE-02") && path.includes("/actions")) {
        return { items: [{ id: "action-1", dataset_version_id: "version-2" }] };
      }
      return { dataset_version_id: "version-2", tables: [] };
    },
  }, "version-2");
  const scope = reduceStoreScope(initialStoreScope(release), {
    type: "scope/selected",
    storeId: "SYNTH-STORE-02",
  });

  await source.loadAnalysis("sales_ads", scope);
  await source.loadForecast(scope);
  await source.loadProfitBridge(scope);
  await source.loadActions(scope);
  await source.loadLibrary(scope);

  assert.equal(paths.length, 6);
  assert.ok(paths.every((path) => path.includes("store_id=SYNTH-STORE-02")));
});

test("global selector is localized, accessible, narrow-screen safe, and mounted only once", async () => {
  const [html, app, view, stateSource, catalog, css] = await Promise.all([
    readFile(new URL("../../frontend/index.html", import.meta.url), "utf8"),
    readFile(new URL("../../frontend/assets/app.mjs", import.meta.url), "utf8"),
    readFile(new URL("../../frontend/assets/features/store-scope/view.mjs", import.meta.url), "utf8"),
    readFile(new URL("../../frontend/assets/features/store-scope/state.mjs", import.meta.url), "utf8"),
    readFile(new URL("../../frontend/assets/i18n/catalog.mjs", import.meta.url), "utf8"),
    readFile(new URL("../../frontend/assets/styles.css", import.meta.url), "utf8"),
  ]);

  assert.equal((html.match(/data-store-scope-root/g) ?? []).length, 1);
  assert.match(app, /dispose\?\.\(\)/);
  assert.match(view, /aria-label/);
  assert.match(`${view}\n${stateSource}`, /storeScope\.all/);
  for (const key of [
    "storeScope.label",
    "storeScope.all",
    "storeScope.changed",
    "storeScope.shared",
  ]) {
    assert.equal((catalog.match(new RegExp(`"${key}"`, "g")) ?? []).length, 2);
  }
  assert.match(css, /\.store-scope-control/);
  assert.match(css, /@media \(max-width: 720px\)/);
});
