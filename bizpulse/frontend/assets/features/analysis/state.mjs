export function initialAnalysisState(release = null) {
  return {
    status: "idle",
    generation: 0,
    release,
    payload: null,
    error: null,
  };
}

export function reduceAnalysis(state, action) {
  switch (action.type) {
    case "request/started":
      return {
        ...state,
        status: "loading",
        generation: action.generation,
        error: null,
      };
    case "request/completed":
      if (action.generation !== state.generation) return state;
      return { ...state, status: "ready", payload: action.payload, error: null };
    case "request/failed":
      if (action.generation !== state.generation) return state;
      return {
        ...state,
        status: "error",
        payload: null,
        error: action.error,
      };
    default:
      return state;
  }
}
