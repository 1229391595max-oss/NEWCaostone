import assert from "node:assert/strict";
import { test } from "node:test";

import { createAdminAIEffects } from "../../frontend/assets/features/admin-ai/effects.mjs";
import { AdminDataSource } from "../../frontend/assets/data-sources/admin.mjs";

function control(overrides = {}) {
  return {
    revision: 4,
    operator_enabled: true,
    demo_enabled: false,
    credential: {
      configured: true,
      fingerprint: "7fa2c91e",
      verified_at: "2026-08-18T12:00:00Z",
    },
    ...overrides,
  };
}

test("admin data source sends CSRF protected idempotent AI mutations", async () => {
  const calls = [];
  const dataSource = new AdminDataSource({
    async request(path, options) {
      calls.push([path, options]);
      return control();
    },
  });

  await dataSource.updateChannels({
    expectedRevision: 4,
    operatorEnabled: false,
    demoEnabled: true,
    currentPassword: "current-password",
  }, "channels-operation");
  await dataSource.rotateKey({
    expectedRevision: 4,
    candidateKey: "candidate-key",
    currentPassword: "current-password",
  }, "rotation-operation");

  assert.deepEqual(calls, [
    ["/api/v1/admin/ai/channels", {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": "channels-operation",
        "X-CSRF-Token": "",
      },
      body: JSON.stringify({
        expected_revision: 4,
        operator_enabled: false,
        demo_enabled: true,
        current_password: "current-password",
      }),
    }],
    ["/api/v1/admin/ai/key-rotations", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": "rotation-operation",
        "X-CSRF-Token": "",
      },
      body: JSON.stringify({
        expected_revision: 4,
        candidate_key: "candidate-key",
        current_password: "current-password",
      }),
    }],
  ]);
});

test("rotation clears both secret inputs after failure and never dispatches them", async () => {
  const actions = [];
  const clearedFields = [];
  const calls = [];
  const effects = createAdminAIEffects({
    dataSource: {
      async loadAI() { return control(); },
      async rotateKey(payload, idempotencyKey) {
        calls.push({ payload, idempotencyKey });
        const error = new Error("sentinel-key sentinel-password");
        error.code = "ADMIN_AI_KEY_REJECTED";
        throw error;
      },
    },
    dispatch(action) { actions.push(action); },
    clearSecrets(fields) { clearedFields.push(...fields); },
    createIdempotencyKey() { return "opaque-operation-1"; },
  });

  await effects.rotate({
    candidateKey: "sentinel-key",
    currentPassword: "sentinel-password",
    expectedRevision: 4,
  });

  assert.deepEqual(clearedFields, ["candidateKey", "currentPassword"]);
  assert.doesNotMatch(JSON.stringify(actions), /sentinel-key|sentinel-password/);
  assert.deepEqual(actions.map((action) => action.type), [
    "rotation/started",
    "rotation/failed",
    "load/started",
    "load/succeeded",
  ]);
  assert.equal(calls[0].idempotencyKey, "opaque-operation-1");
});

test("channel mutation preserves the other requested channel and refreshes immediately", async () => {
  const actions = [];
  const calls = [];
  let loaded = control();
  const effects = createAdminAIEffects({
    dataSource: {
      async loadAI() { return loaded; },
      async updateChannels(payload, idempotencyKey) {
        calls.push({ payload, idempotencyKey });
        loaded = control({
          revision: 5,
          operator_enabled: payload.operatorEnabled,
          demo_enabled: payload.demoEnabled,
        });
        return loaded;
      },
    },
    dispatch(action) { actions.push(action); },
    clearSecrets() {},
    createIdempotencyKey() { return "opaque-operation-2"; },
  });

  await effects.setChannels({
    operatorEnabled: true,
    demoEnabled: true,
    currentPassword: "password-must-not-dispatch",
    expectedRevision: 4,
  });

  assert.deepEqual(calls[0].payload, {
    operatorEnabled: true,
    demoEnabled: true,
    currentPassword: "password-must-not-dispatch",
    expectedRevision: 4,
  });
  assert.equal(calls[0].idempotencyKey, "opaque-operation-2");
  assert.doesNotMatch(JSON.stringify(actions), /password-must-not-dispatch/);
  assert.deepEqual(actions.map((action) => action.type), [
    "channels/started",
    "channels/succeeded",
    "load/started",
    "load/succeeded",
  ]);
  assert.equal(actions.at(-1).payload.operator_enabled, true);
  assert.equal(actions.at(-1).payload.demo_enabled, true);
});

test("effects do not overlap mutations or automatically retry unknown outcomes", async () => {
  let release;
  let mutationCalls = 0;
  let clearCalls = 0;
  const effects = createAdminAIEffects({
    dataSource: {
      async loadAI() { return control(); },
      async rotateKey() {
        mutationCalls += 1;
        return new Promise((resolve) => { release = resolve; });
      },
    },
    dispatch() {},
    clearSecrets() { clearCalls += 1; },
    createIdempotencyKey() { return "opaque-operation-3"; },
  });

  const first = effects.rotate({
    candidateKey: "first",
    currentPassword: "password",
    expectedRevision: 4,
  });
  await Promise.resolve();
  await effects.rotate({
    candidateKey: "second",
    currentPassword: "password",
    expectedRevision: 4,
  });
  assert.equal(mutationCalls, 1);
  release(control({ revision: 5 }));
  await first;
  assert.equal(clearCalls, 2);
});

test("stop clears sensitive fields even without a submission", () => {
  const cleared = [];
  const effects = createAdminAIEffects({
    dataSource: {},
    dispatch() {},
    clearSecrets(fields) { cleared.push(...fields); },
    createIdempotencyKey() { return "opaque-operation-4"; },
  });

  effects.stop();
  assert.deepEqual(cleared, ["candidateKey", "currentPassword"]);
});

test("successful mutation is dispatched safely before a failed refresh", async () => {
  const actions = [];
  const effects = createAdminAIEffects({
    dataSource: {
      async updateChannels() {
        return control({ revision: 5, operator_enabled: false, demo_enabled: true });
      },
      async loadAI() {
        const error = new Error("refresh-detail-must-not-dispatch");
        error.code = "ADMIN_AI_SECRET_UNAVAILABLE";
        throw error;
      },
    },
    dispatch(action) { actions.push(action); },
    clearSecrets() {},
    createIdempotencyKey() { return "opaque-operation-5"; },
  });

  await effects.setChannels({
    operatorEnabled: false,
    demoEnabled: true,
    currentPassword: "secret-must-not-dispatch",
    expectedRevision: 4,
  });

  assert.deepEqual(actions.map((action) => action.type), [
    "channels/started",
    "channels/succeeded",
    "load/started",
    "load/failed",
  ]);
  assert.equal(actions[1].payload.revision, 5);
  assert.equal(actions[3].preserveOutcome, true);
  assert.doesNotMatch(JSON.stringify(actions), /secret-must-not-dispatch|refresh-detail/);
});

test("rotation failure remains specific when its immediate refresh also fails", async () => {
  const actions = [];
  const effects = createAdminAIEffects({
    dataSource: {
      async rotateKey() {
        const error = new Error("provider-detail");
        error.code = "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN";
        throw error;
      },
      async loadAI() {
        throw new Error("refresh-detail");
      },
    },
    dispatch(action) { actions.push(action); },
    clearSecrets() {},
    createIdempotencyKey() { return "opaque-operation-6"; },
  });

  await effects.rotate({
    candidateKey: "candidate-secret",
    currentPassword: "password-secret",
    expectedRevision: 4,
  });

  assert.equal(actions[1].code, "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN");
  assert.equal(actions[3].code, "ADMIN_AI_SECRET_UNAVAILABLE");
  assert.equal(actions[3].preserveOutcome, true);
  assert.doesNotMatch(JSON.stringify(actions), /candidate-secret|password-secret|provider-detail|refresh-detail/);
});

test("local idempotency setup failure still clears secrets and refreshes safely", async () => {
  const actions = [];
  let clearCalls = 0;
  const effects = createAdminAIEffects({
    dataSource: {
      async loadAI() { return control(); },
      async rotateKey() { assert.fail("mutation must not be sent"); },
    },
    dispatch(action) { actions.push(action); },
    clearSecrets() { clearCalls += 1; },
    createIdempotencyKey() { throw new Error("random source unavailable"); },
  });

  await effects.rotate({
    candidateKey: "candidate-secret",
    currentPassword: "password-secret",
    expectedRevision: 4,
  });

  assert.equal(clearCalls, 1);
  assert.deepEqual(actions.map((action) => action.type), [
    "rotation/started",
    "rotation/failed",
    "load/started",
    "load/succeeded",
  ]);
  assert.doesNotMatch(JSON.stringify(actions), /candidate-secret|password-secret|random source/);
});
