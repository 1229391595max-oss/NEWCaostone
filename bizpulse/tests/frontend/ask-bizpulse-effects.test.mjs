import assert from "node:assert/strict";
import { test } from "node:test";

import { createAskBizPulseEffects } from "../../frontend/assets/features/ask-bizpulse/effects.mjs";
import { OperatorDataSource } from "../../frontend/assets/data-sources/operator.mjs";
import { PublicDataSource } from "../../frontend/assets/data-sources/public.mjs";
import {
  initialAskBizPulseState,
  reduceAskBizPulse,
} from "../../frontend/assets/features/ask-bizpulse/state.mjs";

test("double submit produces one turn request and one idempotency key", async () => {
  const calls = [];
  let resolveRequest;
  const pending = new Promise((resolve) => { resolveRequest = resolve; });
  const api = {
    submitChatTurn(payload, key) {
      calls.push([payload, key]);
      return pending;
    },
  };
  const actions = [];
  const effects = createAskBizPulseEffects({
    api,
    dispatch: (action) => actions.push(action),
    getScope: () => ({ selectedId: "store:launch", storeIds: ["SYNTH-STORE-02"] }),
    idempotencyFactory: () => "chat-key-1",
  });

  const first = effects.submit({ question: "Why did profit change?" });
  const second = effects.submit({ question: "Why did profit change?" });
  assert.equal(first, second);
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0][0].store_ids, ["SYNTH-STORE-02"]);
  assert.equal(calls[0][1], "chat-key-1");
  resolveRequest({ id: "turn-1", status: "answered" });
  await first;
  assert.equal(actions.at(-1).type, "chat/submitted");
});

test("submit sends only the selected store scope and no history dataset id or SQL", async () => {
  const calls = [];
  const effects = createAskBizPulseEffects({
    api: {
      async submitChatTurn(payload, key) {
        calls.push([payload, key]);
        return { id: "turn-1", status: "answered" };
      },
    },
    dispatch() {},
    getScope: () => ({ selectedId: "all", storeIds: [] }),
    idempotencyFactory: () => "chat-key-2",
  });
  await effects.submit({ recommended_question_id: "profit_drivers" });
  assert.deepEqual(calls[0][0], {
    recommended_question_id: "profit_drivers",
    store_ids: [],
  });
  assert.equal(JSON.stringify(calls[0][0]).includes("history"), false);
  assert.equal(JSON.stringify(calls[0][0]).includes("dataset_version_id"), false);
  assert.equal(JSON.stringify(calls[0][0]).toLowerCase().includes("sql"), false);
});

test("operator and viewer use the same server-scoped Chat API with separate CSRF", async () => {
  const calls = [];
  const api = {
    async request(path, options = {}) {
      calls.push([path, options]);
      return path.endsWith("/turns") && options.method !== "POST"
        ? { items: [] }
        : { id: "turn-1" };
    },
  };
  const oldStorage = globalThis.sessionStorage;
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
    await operator.listChatTurns();
    await operator.submitChatTurn({ question: "Why profit?" }, "operator-key");
    await operator.saveChatTurn("turn-1");
    await viewer.submitChatTurn({ recommended_question_id: "profit_drivers" }, "viewer-key");
    await viewer.createChatActionDraft("turn-1", "draft-key");
    await viewer.deleteChatSession();
    assert.equal(calls[0][0], "/api/v1/ai-chat/turns");
    assert.equal(calls[1][1].headers["X-CSRF-Token"], "operator-csrf");
    assert.equal(calls[1][1].headers["Idempotency-Key"], "operator-key");
    assert.equal(calls[2][0], "/api/v1/ai-chat/turns/turn-1/save");
    assert.equal(calls[2][1].headers["X-CSRF-Token"], "operator-csrf");
    assert.equal(calls[3][1].headers["X-CSRF-Token"], "viewer-csrf");
    assert.equal(calls[4][1].headers["Idempotency-Key"], "draft-key");
    assert.equal(calls[5][0], "/api/v1/ai-chat/session");
    assert.equal(calls[5][1].method, "DELETE");
  } finally {
    globalThis.sessionStorage = oldStorage;
  }
});

test("scope change fences an older in-flight Chat response", async () => {
  let resolveRequest;
  const pending = new Promise((resolve) => { resolveRequest = resolve; });
  let state = initialAskBizPulseState(
    { dataset_version_id: "version-1" },
    "viewer",
  );
  const effects = createAskBizPulseEffects({
    api: { submitChatTurn: () => pending },
    dispatch(action) { state = reduceAskBizPulse(state, action); },
    idempotencyFactory: () => "scope-fence-key",
  });
  const request = effects.submit({ question: "Why profit?" });
  effects.selectContext({ kind: "inventory_analysis", reference: "analysis:verified" });
  resolveRequest({
    id: "old-turn",
    dataset_version_id: "version-1",
    status: "answered",
  });
  await request;
  assert.equal(state.context.kind, "inventory_analysis");
  assert.deepEqual(state.turns, []);
  assert.equal(state.submitting, false);
});

test("lost Chat response retry reuses the exact idempotency key", async () => {
  const keys = [];
  let attempt = 0;
  const effects = createAskBizPulseEffects({
    api: {
      async submitChatTurn(_payload, key) {
        keys.push(key);
        attempt += 1;
        if (attempt === 1) throw new Error("response_lost");
        return { id: "turn-replayed", status: "answered" };
      },
    },
    dispatch() {},
    idempotencyFactory: () => `generated-${attempt}`,
  });
  const payload = { question: "Why did profit change?" };
  await assert.rejects(effects.submit(payload));
  await effects.submit(payload);
  assert.deepEqual(keys, [keys[0], keys[0]]);
});

test("context change fences a loading history request and permits a fresh load", async () => {
  let resolveHistory;
  const history = new Promise((resolve) => { resolveHistory = resolve; });
  let state = initialAskBizPulseState(
    { dataset_version_id: "version-1" },
    "viewer",
  );
  const effects = createAskBizPulseEffects({
    api: { listChatTurns: () => history },
    dispatch(action) { state = reduceAskBizPulse(state, action); },
  });

  const staleLoad = effects.load();
  effects.selectContext({
    kind: "inventory_analysis",
    reference: "inventory_analysis:pinned",
  });
  assert.equal(state.status, "idle");
  resolveHistory({ items: [{ id: "stale" }], recommended_questions: [] });
  await staleLoad;
  assert.deepEqual(state.turns, []);
});

test("failed session deletion keeps generations aligned for the next submit", async () => {
  let state = initialAskBizPulseState(
    { dataset_version_id: "version-1" },
    "viewer",
  );
  let submitCalls = 0;
  const effects = createAskBizPulseEffects({
    api: {
      async deleteChatSession() { throw new Error("delete_failed"); },
      async submitChatTurn() {
        submitCalls += 1;
        return { id: "turn-after-failure", dataset_version_id: "version-1" };
      },
    },
    dispatch(action) { state = reduceAskBizPulse(state, action); },
    idempotencyFactory: () => "generation-alignment-key",
  });

  await assert.rejects(effects.endSession());
  await effects.submit({ question: "Why did profit change?" });
  assert.equal(submitCalls, 1);
  assert.equal(state.turns[0].id, "turn-after-failure");
});

test("session deletion waits for an in-flight history read before advancing its epoch", async () => {
  let resolveHistory;
  const history = new Promise((resolve) => { resolveHistory = resolve; });
  let deleteCalls = 0;
  const effects = createAskBizPulseEffects({
    api: {
      listChatTurns: () => history,
      async deleteChatSession() {
        deleteCalls += 1;
        return { deleted_turns: 1 };
      },
    },
    dispatch() {},
  });

  const loading = effects.load();
  const ending = effects.endSession();
  await Promise.resolve();
  assert.equal(deleteCalls, 0);

  resolveHistory({ items: [], recommended_questions: [] });
  await Promise.all([loading, ending]);
  assert.equal(deleteCalls, 1);
});

test("context change starts a distinct request with a server-validated pinned reference", async () => {
  const calls = [];
  let resolveFirst;
  const first = new Promise((resolve) => { resolveFirst = resolve; });
  const effects = createAskBizPulseEffects({
    api: {
      submitChatTurn(payload) {
        calls.push(payload);
        return calls.length === 1
          ? first
          : Promise.resolve({ id: "turn-new-context" });
      },
    },
    dispatch() {},
    idempotencyFactory: () => `context-key-${calls.length}`,
  });
  const stale = effects.submit({ question: "Why did profit change?" });
  effects.selectContext({
    kind: "profit_bridge",
    reference: "profit_bridge:pinned",
  });
  const current = effects.submit({ question: "Why did profit change?" });
  assert.notEqual(current, stale);
  resolveFirst({ id: "turn-old-context" });
  await Promise.all([stale, current]);
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1].context, {
    kind: "profit_bridge",
    reference: "profit_bridge:pinned",
  });
});

test("successful session deletion invalidates cached viewer actions", async () => {
  let invalidations = 0;
  const effects = createAskBizPulseEffects({
    api: { async deleteChatSession() { return { deleted_turns: 1 }; } },
    dispatch() {},
    onSessionEnded() { invalidations += 1; },
  });
  await effects.endSession();
  assert.equal(invalidations, 1);
});

test("operator can clear pinned context before returning to general Ask", async () => {
  const calls = [];
  const effects = createAskBizPulseEffects({
    api: {
      async submitChatTurn(payload) {
        calls.push(payload);
        return { id: `turn-${calls.length}` };
      },
    },
    dispatch() {},
    idempotencyFactory: () => `clear-context-${calls.length}`,
  });
  effects.selectContext({
    kind: "inventory_analysis",
    reference: "inventory_analysis:pinned",
  });
  effects.selectContext(null);
  await effects.submit({ question: "What data limitations exist?" });
  assert.deepEqual(calls[0], {
    question: "What data limitations exist?",
    store_ids: [],
  });
});
