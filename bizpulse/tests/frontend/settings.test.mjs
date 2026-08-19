import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  loadViewerSettings,
  saveViewerSettings,
} from "../../frontend/assets/features/settings/state.mjs";
import { OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";
import { PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";
import { createSettingsEffects } from "../../frontend/assets/features/settings/effects.mjs";

const frontendRoot = new URL("../../frontend/", import.meta.url);

test("Viewer settings use session storage only and keep reporting defaults read only", () => {
  const writes = [];
  const storage = {
    getItem() { return null; },
    setItem(key, value) { writes.push([key, JSON.parse(value)]); },
  };
  const initial = loadViewerSettings(storage);
  const saved = saveViewerSettings({ ...initial, locale: "zh", sidebar_mode: "compact" }, storage);

  assert.equal(saved.locale, "zh");
  assert.equal(writes[0][0], "bp_viewer_settings");
  assert.equal(saved.reporting_currency, "BRL");
  assert.equal(saved.timezone, "America/Sao_Paulo");
  assert.equal("decimal_places" in saved, false);
});

test("Viewer can save startup-provided settings before an explicit reload", async () => {
  const writes = [];
  const storage = {
    getItem() { return null; },
    setItem(key, value) { writes.push([key, JSON.parse(value)]); },
  };
  const initialPayload = {
    preferences: loadViewerSettings(storage),
    saved_views: [],
    targets: [],
    permissions: {},
    ai_connection: { status: "available" },
  };
  const effects = createSettingsEffects({
    dataSource: {},
    mode: "viewer",
    dispatch() {},
    storage,
    initialPayload,
  });

  const saved = await effects.savePreferences({
    ...initialPayload.preferences,
    sidebar_mode: "compact",
  });

  assert.equal(saved.preferences.sidebar_mode, "compact");
  assert.equal(writes.at(-1)[1].sidebar_mode, "compact");
});

test("data sources expose mode-appropriate Settings persistence", async () => {
  const calls = [];
  const api = { async request(path, options) { calls.push([path, options]); return {}; } };
  const viewer = new PublicDataSource(api, "version-1");
  const operator = new OperatorDataSource(api, "version-1");

  await viewer.loadSettings();
  assert.equal("saveSettings" in viewer, false);
  await operator.loadSettings();
  await operator.saveSettings({ expected_revision: 0, preferences: {} });

  assert.deepEqual(calls.map(([path]) => path), [
    "/api/demo/preferences",
    "/api/v1/preferences",
    "/api/v1/preferences",
  ]);
});

test("Settings page is reachable and contains no key or decimal preference", async () => {
  const [html, view] = await Promise.all([
    readFile(new URL("index.html", frontendRoot), "utf8"),
    readFile(new URL("assets/features/settings/view.mjs", frontendRoot), "utf8"),
  ]);
  assert.match(html, /data-settings-route="settings"/);
  assert.match(view, /data-settings-field="locale"/);
  assert.match(view, /data-settings-action="save"/);
  assert.match(view, /data-settings-action="create-view"/);
  assert.match(view, /data-settings-action="create-target"/);
  assert.doesNotMatch(view, /api.?key|decimal.?places/i);
});
