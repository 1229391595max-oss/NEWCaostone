function errorCode(error) {
  return error?.code ?? error?.message ?? "ACTION_UNAVAILABLE";
}

const retryKeys = new Map();

function stable(value) {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(
        ([key, item]) => [key, stable(item)],
      ),
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

function retrySlot(kind, actionId, payload) {
  return `bp_action_retry:${kind}:${actionId}:${fingerprint(payload)}`;
}

function storedRetryKey(slot) {
  const stored = globalThis.sessionStorage?.getItem?.(slot) ?? retryKeys.get(slot);
  if (stored) return stored;
  const created = globalThis.crypto.randomUUID();
  retryKeys.set(slot, created);
  globalThis.sessionStorage?.setItem?.(slot, created);
  return created;
}

function clearRetryKey(slot) {
  retryKeys.delete(slot);
  globalThis.sessionStorage?.removeItem?.(slot);
}

async function mutate(kind, dataSource, actionId, payload, operation) {
  const slot = retrySlot(kind, actionId, payload);
  const key = storedRetryKey(slot);
  const result = await operation(key);
  clearRetryKey(slot);
  return result;
}

export function createActionLoader(dataSource, dispatch, getScope = () => null) {
  let generation = 0;
  return async function loadActions() {
    const current = ++generation;
    dispatch({ type: "actions/loading", generation: current });
    try {
      const payload = await dataSource.loadActions(getScope());
      dispatch({ type: "actions/loaded", generation: current, payload });
    } catch (error) {
      dispatch({ type: "actions/failed", generation: current, error: errorCode(error) });
    }
  };
}

function scopedPayload(payload, scope) {
  return { ...payload, store_ids: [...(scope?.storeIds ?? [])] };
}

export async function commandAction(dataSource, load, actionId, payload, scope = null) {
  const outbound = scopedPayload(payload, scope);
  await mutate("command", dataSource, actionId, outbound, (key) => (
    dataSource.commandAction(actionId, outbound, key)
  ));
  await load();
}

export async function resetActionSandbox(dataSource, load, scope = null) {
  await dataSource.resetActionSandbox(scope);
  await load();
}

export async function exportAction(dataSource, load, actionId, revision, scope = null) {
  const payload = scopedPayload({ revision, format: "xlsx" }, scope);
  await mutate("export", dataSource, actionId, payload, (key) => (
    dataSource.exportAction(actionId, payload, key)
  ));
  await load();
}

export async function recordSyntheticOutcome(
  dataSource,
  load,
  actionId,
  payload,
  scope = null,
) {
  const outbound = scopedPayload(payload, scope);
  await mutate("outcome", dataSource, actionId, outbound, (key) => (
    dataSource.recordActionOutcome(actionId, outbound, key)
  ));
  await load();
}
