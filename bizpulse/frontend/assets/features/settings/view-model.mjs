export function toSettingsViewModel(state, language = "en") {
  if (state.status === "loading" || state.status === "idle") {
    return { status: "loading", language };
  }
  if (!state.payload) {
    return { status: "unavailable", language, error: state.error ?? "SETTINGS_UNAVAILABLE" };
  }
  return {
    status: "ready",
    language,
    mode: state.mode,
    saving: state.saving,
    error: state.error,
    preferences: state.payload.preferences,
    savedViews: state.payload.saved_views ?? [],
    targets: state.payload.targets ?? [],
    ai: state.payload.ai ?? { status: "unavailable" },
    permissions: state.payload.permissions,
  };
}
