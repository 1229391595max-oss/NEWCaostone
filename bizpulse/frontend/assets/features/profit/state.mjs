export function initialProfitState(release = null) {
  return Object.freeze({
    status: "idle",
    generation: 0,
    release,
    payload: null,
    bridge: null,
    bridgeError: null,
    error: null,
  });
}

export function reduceProfit(state, action) {
  if (action.type === "request/started") {
    return Object.freeze({
      ...state,
      status: "loading",
      generation: action.generation,
      error: null,
    });
  }
  if (action.type === "request/completed") {
    if (action.generation !== state.generation) return state;
    return Object.freeze({
      ...state,
      status: "ready",
      payload: action.payload,
      bridge: action.bridge ?? null,
      bridgeError: action.bridgeError ?? null,
      error: null,
    });
  }
  if (action.type === "request/failed") {
    if (action.generation !== state.generation) return state;
    return Object.freeze({
      ...state,
      status: "error",
      payload: null,
      bridge: null,
      bridgeError: null,
      error: action.error,
    });
  }
  return state;
}
