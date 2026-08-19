export const VIEWER_SETTINGS_STORAGE_KEY = "bp_viewer_settings";

export const DEFAULT_VIEWER_SETTINGS = Object.freeze({
  locale: "en",
  sidebar_mode: "full",
  default_store: "all",
  period_preset: "current_month",
  comparison_preset: "previous_period",
  overview_kpis: Object.freeze([
    "net_sales", "orders", "roas", "ad_spend",
    "contribution_profit", "stockout_skus",
  ]),
  reporting_currency: "BRL",
  timezone: "America/Sao_Paulo",
  revision: 0,
  saved_views: Object.freeze([]),
});

const allowed = Object.freeze({
  locale: new Set(["en", "zh"]),
  sidebar_mode: new Set(["full", "compact"]),
  period_preset: new Set(["current_month", "previous_month", "last_30_days"]),
  comparison_preset: new Set(["none", "previous_period", "previous_year"]),
  overview_kpis: new Set([
    "net_sales", "orders", "roas", "ad_spend",
    "contribution_profit", "stockout_skus",
  ]),
});

function safeSettings(value, defaults = DEFAULT_VIEWER_SETTINGS) {
  const source = value && typeof value === "object" ? value : {};
  const kpis = Array.isArray(source.overview_kpis)
    ? [...new Set(source.overview_kpis)].filter((item) => allowed.overview_kpis.has(item)).slice(0, 6)
    : [...defaults.overview_kpis];
  const views = Array.isArray(source.saved_views)
    ? source.saved_views.filter((item) => item && typeof item.name === "string").slice(0, 20)
    : [...(defaults.saved_views ?? [])];
  return {
    locale: allowed.locale.has(source.locale) ? source.locale : defaults.locale,
    sidebar_mode: allowed.sidebar_mode.has(source.sidebar_mode)
      ? source.sidebar_mode : defaults.sidebar_mode,
    default_store: typeof source.default_store === "string" && source.default_store.length <= 100
      ? source.default_store : defaults.default_store,
    period_preset: allowed.period_preset.has(source.period_preset)
      ? source.period_preset : defaults.period_preset,
    comparison_preset: allowed.comparison_preset.has(source.comparison_preset)
      ? source.comparison_preset : defaults.comparison_preset,
    overview_kpis: kpis.length >= 2 ? kpis : [...defaults.overview_kpis],
    reporting_currency: "BRL",
    timezone: "America/Sao_Paulo",
    revision: 0,
    saved_views: views,
  };
}

export function loadViewerSettings(
  storage = globalThis.sessionStorage,
  defaults = DEFAULT_VIEWER_SETTINGS,
) {
  try {
    const raw = storage?.getItem(VIEWER_SETTINGS_STORAGE_KEY);
    return safeSettings(raw ? JSON.parse(raw) : null, defaults);
  } catch {
    return safeSettings(null, defaults);
  }
}

export function saveViewerSettings(value, storage = globalThis.sessionStorage) {
  const saved = safeSettings(value);
  storage?.setItem(VIEWER_SETTINGS_STORAGE_KEY, JSON.stringify(saved));
  return saved;
}

export function initialSettingsState(mode, payload = null) {
  return {
    mode,
    status: payload ? "ready" : "idle",
    payload,
    error: null,
    saving: false,
  };
}

export function reduceSettings(state, action) {
  switch (action.type) {
    case "settings/loading":
      return { ...state, status: "loading", error: null };
    case "settings/loaded":
      return { ...state, status: "ready", payload: action.payload, error: null, saving: false };
    case "settings/saving":
      return { ...state, saving: true, error: null };
    case "settings/failed":
      return { ...state, status: state.payload ? "ready" : "error", saving: false, error: action.error };
    default:
      return state;
  }
}
