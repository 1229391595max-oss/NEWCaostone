import assert from "node:assert/strict";
import { test } from "node:test";

import {
  initialAdminAIState,
  projectAdminAIControl,
  reduceAdminAI,
} from "../../frontend/assets/features/admin-ai/state.mjs";

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

test("operator and demo toggles remain independent", () => {
  const state = reduceAdminAI(initialAdminAIState(), {
    type: "load/succeeded",
    payload: control(),
  });

  assert.equal(state.payload.operator_enabled, true);
  assert.equal(state.payload.demo_enabled, false);
});

test("safe projection drops secret locators and unexpected response fields", () => {
  const projected = projectAdminAIControl({
    ...control(),
    key_version: "version-must-not-survive",
    key_vault_uri: "vault-must-not-survive",
    candidate_key: "candidate-must-not-survive",
    current_password: "password-must-not-survive",
    credential: {
      ...control().credential,
      secret_name: "name-must-not-survive",
      fingerprint: "7FA2C91E",
    },
  });

  assert.deepEqual(projected, control());
  assert.doesNotMatch(JSON.stringify(projected), /version-must|vault-must|candidate-must|password-must|name-must/);
});

test("invalid projections fail closed without retaining server values", () => {
  assert.equal(projectAdminAIControl({ ...control(), revision: -1 }), null);
  assert.equal(projectAdminAIControl({ ...control(), operator_enabled: "yes" }), null);
  assert.equal(projectAdminAIControl({
    ...control(),
    credential: { ...control().credential, fingerprint: "not-redacted-metadata" },
  }), null);
});

test("mutation failures map to deterministic safe conflict busy and rollback states", () => {
  const ready = reduceAdminAI(initialAdminAIState(), {
    type: "load/succeeded",
    payload: control(),
  });

  const conflict = reduceAdminAI(ready, {
    type: "channels/failed",
    code: "ADMIN_AI_STATE_CONFLICT",
  });
  assert.equal(conflict.notice, "conflict");
  assert.equal(conflict.error, "ADMIN_AI_STATE_CONFLICT");

  const busy = reduceAdminAI(ready, {
    type: "rotation/failed",
    code: "ADMIN_AI_OPERATION_BUSY",
  });
  assert.equal(busy.notice, "busy");

  const rolledBack = reduceAdminAI(ready, {
    type: "rotation/failed",
    code: "ADMIN_AI_SECRET_UNAVAILABLE",
  });
  assert.equal(rolledBack.notice, "rollback");

  const unsafe = reduceAdminAI(ready, {
    type: "rotation/failed",
    code: "provider detail must not render",
  });
  assert.equal(unsafe.error, "ADMIN_AI_SECRET_UNAVAILABLE");
  assert.equal(unsafe.notice, "rollback");
});

test("loading and operation states preserve the last safe projection", () => {
  const ready = reduceAdminAI(initialAdminAIState(), {
    type: "load/succeeded",
    payload: control(),
  });
  const mutating = reduceAdminAI(ready, { type: "rotation/started" });
  const refreshing = reduceAdminAI(mutating, { type: "load/started" });

  assert.equal(mutating.operation, "rotation");
  assert.equal(mutating.status, "ready");
  assert.equal(refreshing.status, "refreshing");
  assert.equal(refreshing.payload.revision, 4);
});

test("successful mutation projections become authoritative before refresh", () => {
  const ready = reduceAdminAI(initialAdminAIState(), {
    type: "load/succeeded",
    payload: control(),
  });
  const channels = reduceAdminAI(ready, {
    type: "channels/succeeded",
    payload: control({ revision: 5, operator_enabled: false, demo_enabled: true }),
  });
  const rotation = reduceAdminAI(channels, {
    type: "rotation/succeeded",
    payload: {
      revision: 6,
      credential: {
        configured: true,
        fingerprint: "12ab34cd",
        verified_at: "2026-08-18T13:00:00Z",
      },
    },
  });

  assert.equal(channels.payload.revision, 5);
  assert.equal(channels.payload.operator_enabled, false);
  assert.equal(channels.payload.demo_enabled, true);
  assert.deepEqual(rotation.payload, control({
    revision: 6,
    operator_enabled: false,
    demo_enabled: true,
    credential: {
      configured: true,
      fingerprint: "12ab34cd",
      verified_at: "2026-08-18T13:00:00Z",
    },
  }));
});

test("post-mutation refresh failure preserves the specific outcome and projection", () => {
  const ready = reduceAdminAI(initialAdminAIState(), {
    type: "load/succeeded",
    payload: control(),
  });
  const succeeded = reduceAdminAI(ready, {
    type: "channels/succeeded",
    payload: control({ revision: 5, demo_enabled: true }),
  });
  const successRefreshFailed = reduceAdminAI(succeeded, {
    type: "load/failed",
    code: "ADMIN_AI_SECRET_UNAVAILABLE",
    preserveOutcome: true,
  });
  assert.equal(successRefreshFailed.payload.revision, 5);
  assert.equal(successRefreshFailed.notice, "channels-saved");
  assert.equal(successRefreshFailed.error, null);
  assert.equal(successRefreshFailed.refreshError, "ADMIN_AI_SECRET_UNAVAILABLE");

  const unknown = reduceAdminAI(ready, {
    type: "rotation/failed",
    code: "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN",
  });
  const failureRefreshFailed = reduceAdminAI(unknown, {
    type: "load/failed",
    code: "ADMIN_AI_SECRET_UNAVAILABLE",
    preserveOutcome: true,
  });
  assert.equal(failureRefreshFailed.notice, "unknown");
  assert.equal(failureRefreshFailed.error, "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN");
  assert.equal(failureRefreshFailed.refreshError, "ADMIN_AI_SECRET_UNAVAILABLE");
});
