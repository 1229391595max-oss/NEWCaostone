import {
  projectAdminAIControl,
  projectAdminAIRotation,
} from "./state.mjs";

const SECRET_FIELDS = Object.freeze(["candidateKey", "currentPassword"]);

function browserIdempotencyKey() {
  if (typeof globalThis.crypto?.randomUUID !== "function") {
    throw new Error("IDEMPOTENCY_KEY_UNAVAILABLE");
  }
  return globalThis.crypto.randomUUID();
}

export function createAdminAIEffects({
  dataSource,
  dispatch,
  clearSecrets,
  createIdempotencyKey = browserIdempotencyKey,
}) {
  let pendingMutation = null;

  async function load({ preserveOutcome = false } = {}) {
    dispatch({ type: "load/started" });
    try {
      const payload = projectAdminAIControl(await dataSource.loadAI());
      if (!payload) throw new Error("ADMIN_AI_SECRET_UNAVAILABLE");
      dispatch({ type: "load/succeeded", payload });
    } catch (error) {
      dispatch({
        type: "load/failed",
        code: error?.code ?? "ADMIN_AI_SECRET_UNAVAILABLE",
        preserveOutcome,
      });
    }
  }

  function mutate(kind, request) {
    if (pendingMutation !== null) {
      clearSecrets(SECRET_FIELDS);
      return Promise.resolve();
    }
    const operation = (async () => {
      dispatch({ type: `${kind}/started` });
      try {
        const idempotencyKey = createIdempotencyKey();
        const result = await request(idempotencyKey);
        const payload = kind === "channels"
          ? projectAdminAIControl(result)
          : projectAdminAIRotation(result);
        if (!payload) {
          const invalid = new Error("ADMIN_AI_SECRET_UNAVAILABLE");
          invalid.code = "ADMIN_AI_SECRET_UNAVAILABLE";
          throw invalid;
        }
        dispatch({ type: `${kind}/succeeded`, payload });
      } catch (error) {
        dispatch({
          type: `${kind}/failed`,
          code: error?.code ?? "ADMIN_AI_SECRET_UNAVAILABLE",
        });
      } finally {
        clearSecrets(SECRET_FIELDS);
        await load({ preserveOutcome: true });
      }
    })();
    pendingMutation = operation;
    return operation.finally(() => {
      if (pendingMutation === operation) pendingMutation = null;
    });
  }

  function setChannels({
    operatorEnabled,
    demoEnabled,
    currentPassword,
    expectedRevision,
  }) {
    return mutate("channels", (idempotencyKey) => dataSource.updateChannels({
      operatorEnabled,
      demoEnabled,
      currentPassword,
      expectedRevision,
    }, idempotencyKey));
  }

  function rotate({ candidateKey, currentPassword, expectedRevision }) {
    return mutate("rotation", (idempotencyKey) => dataSource.rotateKey({
      candidateKey,
      currentPassword,
      expectedRevision,
    }, idempotencyKey));
  }

  function stop() {
    clearSecrets(SECRET_FIELDS);
  }

  return { load, rotate, setChannels, start: load, stop };
}
