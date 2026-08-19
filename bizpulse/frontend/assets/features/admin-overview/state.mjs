const SAFE_ERROR_CODE = /^[A-Z][A-Z0-9_]{1,63}$/;

export function initialAdminOverviewState() {
  return { status: "idle", payload: null, error: null };
}

export function reduceAdminOverview(state, action) {
  if (action.type === "load/started") {
    return {
      ...state,
      status: state.payload ? "refreshing" : "loading",
      error: null,
    };
  }
  if (action.type === "load/succeeded") {
    return { status: "ready", payload: action.payload, error: null };
  }
  if (action.type === "load/failed") {
    return {
      ...state,
      status: state.payload ? "stale" : "failed",
      error: SAFE_ERROR_CODE.test(action.code ?? "")
        ? action.code
        : "ADMIN_SUMMARY_UNAVAILABLE",
    };
  }
  return state;
}
