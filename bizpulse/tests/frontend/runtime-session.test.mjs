import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ViewerExpiryGuard,
  RuntimeSessionController,
  runtimeModeForPath,
} from "../../frontend/assets/core/runtime-session.mjs";

test("runtime mode is derived from the server-guarded entry path", () => {
  assert.equal(runtimeModeForPath("/demo"), "viewer");
  assert.equal(runtimeModeForPath("/app"), "operator");
  assert.throws(() => runtimeModeForPath("/unexpected"), /RUNTIME_PATH_INVALID/);
});

test("viewer runtime stores the exact pinned release without browser-selected scope", async () => {
  const calls = [];
  const controller = new RuntimeSessionController({
    async request(path, options) {
      calls.push([path, options]);
      if (path === "/api/demo/sessions/current") {
        return {
          session: {
            session_id: "session-1",
            dataset_version_id: "version-1",
            demo_data_imported: true,
          },
        };
      }
      return {
        dataset_version_id: "version-1",
        version_number: 7,
        source_classification: "pure_synthetic",
        session_pinned: true,
      };
    },
  });

  const state = await controller.load("viewer");

  assert.deepEqual(calls, [
    ["/api/demo/sessions/current", { cache: "no-store" }],
    ["/api/demo/release/current", { cache: "no-store" }],
  ]);
  assert.equal(state.release.dataset_version_id, "version-1");
  assert.equal(state.release.session_pinned, true);
  assert.equal("scope" in state, false);
});

test("viewer runtime is ready without loading release before demo data import", async () => {
  const calls = [];
  const controller = new RuntimeSessionController({
    async request(path, options) {
      calls.push([path, options]);
      return {
        session: {
          session_id: "session-1",
          dataset_version_id: "version-1",
          demo_data_imported: false,
        },
      };
    },
  });

  const state = await controller.load("viewer");

  assert.deepEqual(calls, [
    ["/api/demo/sessions/current", { cache: "no-store" }],
  ]);
  assert.equal(state.status, "ready");
  assert.equal(state.release, null);
  assert.equal(state.principal.session.demo_data_imported, false);
});

test("late runtime responses cannot replace a newer generation", async () => {
  let resolveFirst;
  const first = new Promise((resolve) => {
    resolveFirst = resolve;
  });
  let call = 0;
  const controller = new RuntimeSessionController({
    async request() {
      call += 1;
      if (call === 1) return first;
      return call === 2
        ? { session: { dataset_version_id: "new", demo_data_imported: true } }
        : {
            dataset_version_id: "new",
            source_classification: "pure_synthetic",
            session_pinned: true,
          };
    },
  });

  const stale = controller.load("viewer");
  const latest = controller.load("viewer");
  resolveFirst({ session: { dataset_version_id: "old" } });

  assert.equal((await stale).stale, true);
  assert.equal((await latest).release.dataset_version_id, "new");
});

test("operator runtime remains ready before the first public release", async () => {
  const controller = new RuntimeSessionController({
    async request(path, options) {
      assert.equal(path, "/api/v1/datasets/public-release");
      assert.deepEqual(options, { cache: "no-store" });
      const error = new Error("PUBLIC_RELEASE_NOT_FOUND");
      error.code = "PUBLIC_RELEASE_NOT_FOUND";
      error.status = 404;
      throw error;
    },
  });

  const state = await controller.load("operator");

  assert.equal(state.status, "ready");
  assert.equal(state.mode, "operator");
  assert.equal(state.release, null);
});

test("viewer expiry guard revalidates at the earliest TTL and clears on expiry", async () => {
  const timers = [];
  let expired = 0;
  const guard = new ViewerExpiryGuard(
    {
      async request(path, options) {
        assert.equal(path, "/api/demo/sessions/current");
        assert.deepEqual(options, { cache: "no-store" });
        const error = new Error("SESSION_EXPIRED");
        error.status = 401;
        throw error;
      },
    },
    {
      now: () => Date.parse("2026-08-14T12:00:00Z"),
      setTimer(callback, delay) {
        timers.push({ callback, delay });
        return timers.length;
      },
      clearTimer() {},
      onExpired() { expired += 1; },
    },
  );
  guard.start({
    idle_expires_at: "2026-08-14T12:05:00Z",
    absolute_expires_at: "2026-08-14T14:00:00Z",
  });
  assert.equal(timers[0].delay, 300_000);
  await timers[0].callback();
  assert.equal(expired, 1);
});
