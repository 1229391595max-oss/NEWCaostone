import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiClient } from "../../frontend/assets/core/api-client.mjs";
import { PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";
import { OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";

function fakeApi() {
  return { request: async () => ({}) };
}

test("default browser fetch keeps its required global receiver", async () => {
  const originalFetch = globalThis.fetch;
  globalThis.fetch = function browserFetch(path, options) {
    assert.equal(this, globalThis);
    assert.equal(path, "/api/example");
    assert.equal(options.credentials, "same-origin");
    return Promise.resolve({
      ok: true,
      headers: { get: () => "application/json" },
      json: async () => ({ ready: true }),
    });
  };
  try {
    assert.deepEqual(await new ApiClient().request("/api/example"), {
      ready: true,
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("client rejects non-relative and protocol-relative paths", async () => {
  const client = new ApiClient(async () => {
    throw new Error("fetch_must_not_run");
  });

  await assert.rejects(client.request("https://example.test"), /SAME_ORIGIN/);
  await assert.rejects(client.request("//example.test"), /SAME_ORIGIN/);
  await assert.rejects(client.request("/\\evil.example"), /SAME_ORIGIN/);
  await assert.rejects(client.request("/\\\\evil.example"), /SAME_ORIGIN/);
});

test("viewer data source has no operator data mutation capability", () => {
  const viewer = new PublicDataSource(fakeApi(), "version-1");
  for (const name of [
    "upload",
    "import",
    "mapping",
    "commit",
    "publish",
    "runAnalysis",
    "runProfitBridge",
    "createForecast",
    "exportAction",
    "recordActionOutcome",
  ]) {
    assert.equal(typeof viewer[name], "undefined");
    assert.equal(viewer.capabilities.includes(name), false);
  }
});

test("viewer demo activation uses only the session marker endpoint", async () => {
  const calls = [];
  const originalStorage = globalThis.sessionStorage;
  globalThis.sessionStorage = {
    getItem(key) {
      return key === "bp_demo_csrf_token" ? "demo-csrf" : null;
    },
  };
  try {
    const viewer = new PublicDataSource({
      async request(path, options) {
        calls.push([path, options]);
        return { session: { demo_data_imported: true } };
      },
    }, null);

    await viewer.importDemoData();

    assert.deepEqual(calls, [[
      "/api/demo/sessions/current/import-demo-data",
      {
        method: "POST",
        headers: { "X-CSRF-Token": "demo-csrf" },
      },
    ]]);
    assert.doesNotMatch(JSON.stringify(calls), /api\/v1\/imports|FormData/);
  } finally {
    globalThis.sessionStorage = originalStorage;
  }
});

test("operator data source keeps the complete workflow capability map", () => {
  const operator = new OperatorDataSource(fakeApi(), "version-1");
  for (const name of [
    "import",
    "mapping",
    "commit",
    "publish",
    "runProfitBridge",
    "createForecast",
    "exportAction",
    "recordActionOutcome",
  ]) {
    assert.equal(operator.capabilities.includes(name), true);
  }
  for (const name of [
    "publish",
    "runProfitBridge",
    "createForecast",
    "exportAction",
    "recordActionOutcome",
  ]) {
    assert.equal(typeof operator[name], "function");
  }
});
