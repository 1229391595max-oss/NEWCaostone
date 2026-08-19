const ALL_STORES = "all";
const MAX_STORES = 50;

function catalogFrom(release) {
  const raw = Array.isArray(release?.store_catalog) ? release.store_catalog : [];
  const seen = new Set();
  const catalog = [];
  for (const item of raw.slice(0, MAX_STORES)) {
    const id = typeof item?.store_id === "string" ? item.store_id.trim() : "";
    if (!id || id.length > 100 || item?.has_data === false || seen.has(id)) continue;
    seen.add(id);
    catalog.push(Object.freeze({
      id,
      labelEn: String(item.display_name_en || id).slice(0, 120),
      labelZh: String(item.display_name_zh || item.display_name_en || id).slice(0, 120),
      lifecycle: item.lifecycle === "new" ? "new" : "established",
    }));
  }
  return catalog.sort((left, right) => {
    const lifecycle = Number(left.lifecycle === "new") - Number(right.lifecycle === "new");
    return lifecycle || left.id.localeCompare(right.id);
  });
}

function selectedState(state, storeId, generation) {
  const selected = state.options.find((item) => item.id === storeId);
  if (!selected) throw new Error("STORE_SCOPE_INVALID");
  return Object.freeze({
    ...state,
    selectedId: storeId,
    storeIds: Object.freeze(storeId === ALL_STORES ? [] : [storeId]),
    generation,
  });
}

export function initialStoreScope(release, defaultStore = ALL_STORES) {
  const options = Object.freeze([
    Object.freeze({ id: ALL_STORES, labelKey: "storeScope.all" }),
    ...catalogFrom(release),
  ]);
  const state = Object.freeze({
    datasetVersionId: release?.dataset_version_id ?? null,
    options,
    selectedId: ALL_STORES,
    storeIds: Object.freeze([]),
    generation: 0,
  });
  const initialId = options.some((item) => item.id === defaultStore)
    ? defaultStore
    : ALL_STORES;
  return selectedState(state, initialId, 0);
}

export function reduceStoreScope(state, action) {
  if (action?.type !== "scope/selected") return state;
  if (action.storeId === state.selectedId) return state;
  return selectedState(state, action.storeId, state.generation + 1);
}

export function scopeQuery(scope) {
  if (!scope || !Array.isArray(scope.storeIds)) {
    throw new Error("STORE_SCOPE_INVALID");
  }
  const query = new URLSearchParams();
  if (scope.selectedId === ALL_STORES && scope.storeIds.length === 0) return query;
  if (
    scope.storeIds.length !== 1
    || scope.storeIds[0] !== scope.selectedId
    || !scope.options?.some?.((item) => item.id === scope.selectedId)
  ) {
    throw new Error("STORE_SCOPE_INVALID");
  }
  query.append("store_id", scope.storeIds[0]);
  return query;
}

export function storeScopeLabel(option, language = "en") {
  if (option?.labelKey) return option.labelKey;
  return language === "zh" ? option?.labelZh : option?.labelEn;
}
