export function initialActionState(release, mode) {
  return Object.freeze({
    release,
    mode,
    status: "idle",
    items: [],
    error: null,
    generation: 0,
  });
}

export function reduceActions(state, action) {
  if (action.type === "actions/loading") {
    return Object.freeze({
      ...state,
      status: "loading",
      error: null,
      generation: action.generation,
    });
  }
  if (action.type === "actions/loaded") {
    if (action.generation !== state.generation) return state;
    const items = Array.isArray(action.payload?.items) ? action.payload.items : [];
    return Object.freeze({
      ...state,
      status: items.length ? "ready" : "empty",
      items,
      error: null,
    });
  }
  if (action.type === "actions/failed") {
    if (action.generation !== state.generation) return state;
    return Object.freeze({
      ...state,
      status: "error",
      items: [],
      error: action.error,
    });
  }
  return state;
}
