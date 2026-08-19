export function initialForecastState(release, mode) {
  return Object.freeze({
    release,
    mode,
    status: "idle",
    forecast: null,
    error: null,
    generation: 0,
  });
}

export function reduceForecast(state, action) {
  if (action.type === "forecast/loading") {
    return Object.freeze({ ...state, status: "loading", error: null, generation: action.generation ?? state.generation + 1 });
  }
  if (action.type === "forecast/loaded") {
    if (action.generation !== undefined && action.generation !== state.generation) return state;
    return Object.freeze({
      ...state,
      status: action.payload ? phase(action.payload.status) : "empty",
      forecast: action.payload,
      error: null,
    });
  }
  if (action.type === "forecast/created") {
    return Object.freeze({ ...state, status: "draft", forecast: action.payload, error: null });
  }
  if (action.type === "forecast/confirmed") {
    return Object.freeze({ ...state, status: "confirmed", forecast: action.payload, error: null });
  }
  if (action.type === "forecast/completed") {
    return Object.freeze({ ...state, status: phase(action.payload.status), forecast: action.payload, error: null });
  }
  if (action.type === "forecast/failed") {
    if (action.generation !== undefined && action.generation !== state.generation) return state;
    return Object.freeze({ ...state, status: "error", error: action.error, forecast: null });
  }
  return state;
}

function phase(status) {
  if (status === "draft") return "draft";
  if (status === "analogs_confirmed") return "confirmed";
  if (status === "completed" || status === "blocked") return "ready";
  return "error";
}
