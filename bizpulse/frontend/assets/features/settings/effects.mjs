import { loadViewerSettings, saveViewerSettings } from "./state.mjs";

function viewerPayload(server, storage) {
  const defaults = { ...server.preferences, saved_views: server.saved_views ?? [] };
  const local = loadViewerSettings(storage, defaults);
  return {
    ...server,
    preferences: {
      ...server.preferences,
      ...local,
      saved_views: undefined,
      reporting_currency: "BRL",
      timezone: "America/Sao_Paulo",
      revision: 0,
    },
    saved_views: local.saved_views,
  };
}

export function createSettingsEffects({
  dataSource,
  mode,
  dispatch,
  storage = globalThis.sessionStorage,
  initialPayload = null,
}) {
  let current = initialPayload;

  async function load() {
    dispatch({ type: "settings/loading" });
    try {
      const server = await dataSource.loadSettings();
      current = mode === "viewer" ? viewerPayload(server, storage) : server;
      dispatch({ type: "settings/loaded", payload: current });
      return current;
    } catch (error) {
      dispatch({ type: "settings/failed", error: error?.code ?? error?.message ?? "SETTINGS_UNAVAILABLE" });
      return null;
    }
  }

  async function savePreferences(preferences) {
    dispatch({ type: "settings/saving" });
    try {
      if (mode === "viewer") {
        const local = saveViewerSettings({
          ...preferences,
          saved_views: current?.saved_views ?? [],
        }, storage);
        current = {
          ...current,
          preferences: { ...current.preferences, ...local, saved_views: undefined },
          saved_views: local.saved_views,
        };
        dispatch({ type: "settings/loaded", payload: current });
        return current;
      }
      await dataSource.saveSettings({
        expected_revision: current.preferences.revision,
        preferences,
      });
      return load();
    } catch (error) {
      dispatch({ type: "settings/failed", error: error?.code ?? error?.message ?? "SETTINGS_SAVE_FAILED" });
      return null;
    }
  }

  async function createView(name, kind, config) {
    if (mode === "viewer") {
      const item = {
        id: globalThis.crypto?.randomUUID?.() ?? `viewer-${Date.now()}`,
        name,
        kind,
        config,
        revision: 1,
      };
      current = { ...current, saved_views: [...(current.saved_views ?? []), item].slice(0, 20) };
      saveViewerSettings({ ...current.preferences, saved_views: current.saved_views }, storage);
      dispatch({ type: "settings/loaded", payload: current });
      return item;
    }
    await dataSource.createSavedView({ name, kind, config });
    await load();
    return true;
  }

  async function updateView(item, name, config) {
    if (mode === "viewer") {
      current = {
        ...current,
        saved_views: current.saved_views.map((view) => (
          view.id === item.id ? { ...view, name, config, revision: view.revision + 1 } : view
        )),
      };
      saveViewerSettings({ ...current.preferences, saved_views: current.saved_views }, storage);
      dispatch({ type: "settings/loaded", payload: current });
      return true;
    }
    await dataSource.updateSavedView(item.id, {
      expected_revision: item.revision,
      name,
      config,
    });
    await load();
    return true;
  }

  async function deleteView(item) {
    if (mode === "viewer") {
      current = { ...current, saved_views: current.saved_views.filter((view) => view.id !== item.id) };
      saveViewerSettings({ ...current.preferences, saved_views: current.saved_views }, storage);
      dispatch({ type: "settings/loaded", payload: current });
      return true;
    }
    await dataSource.deleteSavedView(item.id, item.revision);
    await load();
    return true;
  }

  async function createTarget(payload) {
    await dataSource.createTarget(payload);
    await load();
  }

  async function setTargetStatus(item, status) {
    await dataSource.setTargetStatus(item.id, {
      expected_revision: item.revision,
      status,
    });
    await load();
  }

  return {
    load,
    savePreferences,
    createView,
    updateView,
    deleteView,
    createTarget,
    setTargetStatus,
  };
}
