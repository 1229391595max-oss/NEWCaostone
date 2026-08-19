function defaultIdempotencyKey(prefix) {
  const value = globalThis.crypto?.randomUUID?.();
  if (!value) throw new Error("SECURE_IDEMPOTENCY_REQUIRED");
  return `${prefix}-${value}`;
}

function errorCode(error) {
  return error?.code ?? error?.message ?? "AI_CHAT_UNAVAILABLE";
}

const retryKeys = new Map();

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value)
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([key, item]) => [key, stable(item)]),
    );
  }
  return value;
}

function fingerprint(value) {
  const input = JSON.stringify(stable(value));
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function retryKey(slot, factory) {
  const stored = globalThis.sessionStorage?.getItem?.(slot) ?? retryKeys.get(slot);
  if (stored) return stored;
  const created = factory();
  retryKeys.set(slot, created);
  globalThis.sessionStorage?.setItem?.(slot, created);
  return created;
}

function clearRetryKey(slot) {
  retryKeys.delete(slot);
  globalThis.sessionStorage?.removeItem?.(slot);
}

export function createAskBizPulseEffects({
  api,
  dispatch,
  getScope = () => ({ storeIds: [] }),
  onSessionEnded = () => {},
  idempotencyFactory = () => defaultIdempotencyKey("chat"),
}) {
  let generation = 0;
  let submitPromise = null;
  let staleSubmitPromise = null;
  let selectedContext = null;
  const loadPromises = new Set();
  const draftPromises = new Map();
  const savePromises = new Map();

  function load() {
    generation += 1;
    const current = generation;
    dispatch({ type: "chat/loading", generation: current });
    const pending = Promise.resolve(api.listChatTurns())
      .then((payload) => {
        dispatch({ type: "chat/loaded", generation: current, payload });
        return payload;
      })
      .catch((error) => {
        dispatch({ type: "chat/load-failed", generation: current, error: errorCode(error) });
        return null;
      })
      .finally(() => { loadPromises.delete(pending); });
    loadPromises.add(pending);
    return pending;
  }

  function submit(payload) {
    if (submitPromise) return submitPromise;
    const scope = getScope();
    const outbound = {
      ...payload,
      store_ids: [...(scope?.storeIds ?? [])],
      ...(selectedContext ? { context: selectedContext } : {}),
    };
    const slot = `bp_chat_retry:${fingerprint(outbound)}`;
    const key = retryKey(slot, idempotencyFactory);
    const current = generation;
    dispatch({ type: "chat/submitting", generation: current });
    const start = () => {
      try {
        return api.submitChatTurn(outbound, key);
      } catch (error) {
        return Promise.reject(error);
      }
    };
    const request = staleSubmitPromise
      ? staleSubmitPromise.catch(() => {}).then(start)
      : start();
    const pending = Promise.resolve(request)
      .then((turn) => {
        clearRetryKey(slot);
        dispatch({ type: "chat/submitted", generation: current, payload: turn });
        return turn;
      })
      .catch((error) => {
        dispatch({
          type: "chat/submit-failed",
          generation: current,
          error: errorCode(error),
        });
        throw error;
      })
      .finally(() => {
        if (submitPromise === pending) submitPromise = null;
        if (staleSubmitPromise === pending) staleSubmitPromise = null;
      });
    submitPromise = pending;
    return pending;
  }

  function createActionDraft(turnId) {
    if (draftPromises.has(turnId)) return draftPromises.get(turnId);
    const slot = `bp_chat_draft_retry:${turnId}`;
    const key = retryKey(slot, idempotencyFactory);
    const current = generation;
    dispatch({ type: "chat/drafting", generation: current, turnId });
    const pending = Promise.resolve()
      .then(() => api.createChatActionDraft(turnId, key))
      .then((turn) => {
        clearRetryKey(slot);
        dispatch({ type: "chat/drafted", generation: current, payload: turn });
        return turn;
      })
      .catch((error) => {
        dispatch({
          type: "chat/draft-failed",
          generation: current,
          error: errorCode(error),
        });
        throw error;
      })
      .finally(() => { draftPromises.delete(turnId); });
    draftPromises.set(turnId, pending);
    return pending;
  }

  function saveTurn(turnId) {
    if (savePromises.has(turnId)) return savePromises.get(turnId);
    const current = generation;
    dispatch({ type: "chat/saving", generation: current, turnId });
    const pending = Promise.resolve()
      .then(() => api.saveChatTurn(turnId))
      .then((turn) => {
        dispatch({ type: "chat/saved", generation: current, payload: turn });
        return turn;
      })
      .catch((error) => {
        dispatch({
          type: "chat/save-failed",
          generation: current,
          error: errorCode(error),
        });
        throw error;
      })
      .finally(() => { savePromises.delete(turnId); });
    savePromises.set(turnId, pending);
    return pending;
  }

  function endSession() {
    generation += 1;
    const current = generation;
    if (submitPromise) staleSubmitPromise = submitPromise;
    submitPromise = null;
    draftPromises.clear();
    savePromises.clear();
    dispatch({ type: "chat/session-ending", generation: current });
    const historyFence = Promise.allSettled([...loadPromises]);
    return historyFence
      .then(() => api.deleteChatSession())
      .then((result) => {
        selectedContext = null;
        onSessionEnded();
        dispatch({ type: "chat/session-ended", generation: current });
        return result;
      })
      .catch((error) => {
        dispatch({
          type: "chat/session-end-failed",
          generation: current,
          error: errorCode(error),
        });
        throw error;
      });
  }

  function selectContext(context) {
    generation += 1;
    if (submitPromise) staleSubmitPromise = submitPromise;
    submitPromise = null;
    draftPromises.clear();
    savePromises.clear();
    selectedContext = context ?? null;
    dispatch({ type: "chat/context-selected", generation, context });
  }

  return {
    load,
    submit,
    createActionDraft,
    saveTurn,
    endSession,
    selectContext,
    settle: () => submitPromise ?? Promise.resolve(),
  };
}
