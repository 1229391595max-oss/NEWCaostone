import { ApiClient } from "./core/api-client.mjs?v=20260814";
import {
  RuntimeSessionController,
  ViewerExpiryGuard,
  runtimeModeForPath,
} from "./core/runtime-session.mjs";
import { PublicDataSource } from "./data-sources/public.mjs";
import { OperatorDataSource } from "./data-sources/operator.mjs";
import {
  applyCatalog,
  loadLanguagePreference,
  persistLanguagePreference,
  t,
} from "./i18n/catalog.mjs";
import { getState, setActiveRoute } from "./state.mjs";
import {
  loadViewerSettings,
  saveViewerSettings,
} from "./features/settings/state.mjs";
import {
  initialStoreScope,
  reduceStoreScope,
} from "./features/store-scope/state.mjs";
import { renderStoreScope } from "./features/store-scope/view.mjs";
import { createViewRenderer } from "./views.mjs?v=20260814";

const viewRoot = document.querySelector("[data-view-root]");
const viewTitle = document.querySelector("[data-view-title]");
const routeButtons = [...document.querySelectorAll("[data-primary-route]")];
const settingsButton = document.querySelector("[data-settings-route]");
const adminEntry = document.querySelector("[data-admin-entry]");
const navigationButtons = [...routeButtons, settingsButton, adminEntry].filter(Boolean);
const datasetLabel = document.querySelector("[data-dataset-label]");
const freshness = document.querySelector("[data-release-freshness]");
const runtimeError = document.querySelector("[data-runtime-error]");
const storeScopeRoot = document.querySelector("[data-store-scope-root]");
const storeScopeNotice = document.querySelector("[data-store-scope-notice]");
let language = loadLanguagePreference();

function renderLanguage() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  applyCatalog(language);
  const toggle = document.querySelector("[data-language-toggle]");
  if (toggle) {
    toggle.textContent = t(language, "language.selector");
    toggle.dataset.short = language === "en" ? "中" : "EN";
    toggle.setAttribute("aria-label", t(language, "accessibility.languageToggle"));
    toggle.title = t(language, "accessibility.languageToggle");
  }
  for (const button of navigationButtons) {
    button.dataset.tooltip = button.textContent;
    button.setAttribute("aria-label", button.textContent);
    button.title = button.textContent;
  }
}

function routeFor(button) {
  return button.dataset.primaryRoute ?? button.dataset.settingsRoute;
}

function applySidebarMode(mode) {
  document.body.classList.toggle("sidebar-compact", mode === "compact");
}

renderLanguage();

async function bootstrap() {
  const mode = runtimeModeForPath(window.location.pathname);
  if (adminEntry) adminEntry.hidden = mode !== "operator";
  const api = new ApiClient();
  const runtime = await new RuntimeSessionController(api).load(mode);
  if (runtime.status !== "ready") {
    runtimeError.hidden = false;
    runtimeError.textContent = t(language, "error.runtimeUnavailable", {
      code: runtime.error,
    });
    return;
  }
  const dataSource =
    mode === "viewer"
      ? new PublicDataSource(api, runtime.release?.dataset_version_id ?? null)
      : new OperatorDataSource(api, runtime.release?.dataset_version_id ?? null);
  let release = runtime.release;
  let initialSettingsPayload = null;
  try {
    const serverSettings = await dataSource.loadSettings();
    if (mode === "viewer") {
      const defaults = {
        ...serverSettings.preferences,
        locale: language,
        saved_views: serverSettings.saved_views ?? [],
      };
      const local = loadViewerSettings(globalThis.sessionStorage, defaults);
      initialSettingsPayload = {
        ...serverSettings,
        preferences: { ...serverSettings.preferences, ...local, saved_views: undefined },
        saved_views: local.saved_views,
      };
    } else initialSettingsPayload = serverSettings;
    language = persistLanguagePreference(initialSettingsPayload.preferences.locale);
    applySidebarMode(initialSettingsPayload.preferences.sidebar_mode);
  } catch {
    initialSettingsPayload = null;
  }
  if (release) {
    try {
      const library = mode === "viewer"
        ? await dataSource.loadLibrary()
        : await dataSource.loadLibraryVersion(release.dataset_version_id);
      release = { ...release, store_catalog: library.store_catalog ?? [] };
    } catch {
      release = { ...release, store_catalog: [] };
    }
  }
  let storeScope = initialStoreScope(
    release,
    initialSettingsPayload?.preferences?.default_store ?? "all",
  );
  let operatorScopeWrites = Promise.resolve();

  function persistOperatorDefaultStore(storeId) {
    if (mode !== "operator") return;
    operatorScopeWrites = operatorScopeWrites.then(async () => {
      const current = await dataSource.loadSettings();
      const saved = await dataSource.saveSettings({
        expected_revision: current.preferences.revision,
        preferences: { ...current.preferences, default_store: storeId },
      });
      if (saved?.preferences && storeScope.selectedId === storeId) {
        initialSettingsPayload = {
          ...current,
          ...saved,
          saved_views: current.saved_views ?? [],
        };
      }
    }).catch(() => undefined);
  }
  if (mode === "viewer") {
    const expiryGuard = new ViewerExpiryGuard(api, {
      onExpired() {
        sessionStorage.removeItem("bp_demo_csrf_token");
        viewTitle.textContent = t(language, "error.sessionExpired");
        viewRoot.replaceChildren();
        window.location.assign("/");
      },
    });
    expiryGuard.start(runtime.principal?.session);
  }
  function renderReleaseLabels() {
    datasetLabel.textContent = t(
      language,
      mode === "viewer" ? "shell.viewerWorkspace" : "shell.operatorWorkspace",
    );
    freshness.textContent = release
      ? t(language, "shell.dataReady")
      : t(language, "shell.setupRequired");
  }
  renderReleaseLabels();
  const workspaceButton = routeButtons.find(
    (button) => button.dataset.primaryRoute === "workspace",
  );
  if (mode === "viewer" && workspaceButton) {
    workspaceButton.dataset.i18n = "nav.workspace";
  }
  let renderer;
  function activate(route, options = {}) {
    const state = setActiveRoute(route, options.context ?? null);
    for (const button of navigationButtons) {
      if (routeFor(button) === state.activeRoute) {
        button.setAttribute("aria-current", "page");
      } else button.removeAttribute("aria-current");
    }
    renderer.render(state.activeRoute, options);
  }

  function renderScopeControl() {
    if (!storeScopeRoot) return;
    renderStoreScope(storeScopeRoot, storeScope, {
      language,
      onSelect(storeId) {
        const next = reduceStoreScope(storeScope, {
          type: "scope/selected",
          storeId,
        });
        if (next === storeScope) return;
        storeScope = next;
        if (initialSettingsPayload) {
          initialSettingsPayload = {
            ...initialSettingsPayload,
            preferences: {
              ...initialSettingsPayload.preferences,
              default_store: storeScope.selectedId,
            },
          };
        }
        if (mode === "viewer") {
          const saved = saveViewerSettings({
            ...(initialSettingsPayload?.preferences ?? {}),
            default_store: storeScope.selectedId,
            saved_views: initialSettingsPayload?.saved_views ?? [],
          });
          if (initialSettingsPayload) {
            initialSettingsPayload = {
              ...initialSettingsPayload,
              preferences: {
                ...initialSettingsPayload.preferences,
                ...saved,
                saved_views: undefined,
              },
              saved_views: saved.saved_views,
            };
          }
        }
        persistOperatorDefaultStore(storeScope.selectedId);
        renderScopeControl();
        if (storeScopeNotice) {
          storeScopeNotice.textContent = t(language, "storeScope.changed");
          storeScopeNotice.hidden = false;
        }
        const route = getState().activeRoute;
        createRenderer();
        activate(route);
      },
    });
  }

  function createRenderer() {
    renderer?.dispose?.();
    renderer = createViewRenderer({
      root: viewRoot,
      title: viewTitle,
      dataSource,
      release,
      mode,
      navigate: activate,
      getLanguage: () => language,
      getScope: () => storeScope,
      async onImportDemoData() {
        await dataSource.importDemoData();
        window.location.reload();
      },
      initialSettingsPayload,
      onLanguageChange(nextLanguage) {
        language = persistLanguagePreference(nextLanguage);
        renderLanguage();
        renderReleaseLabels();
        renderScopeControl();
        activate(getState().activeRoute);
      },
      onSidebarModeChange: applySidebarMode,
    });
  }

  createRenderer();
  renderScopeControl();

  for (const button of routeButtons) {
    button.addEventListener("click", () => activate(button.dataset.primaryRoute));
  }
  settingsButton?.addEventListener("click", () => activate("settings"));
  document.querySelector("[data-language-toggle]")?.addEventListener("click", () => {
    language = persistLanguagePreference(language === "en" ? "zh" : "en");
    renderLanguage();
    renderReleaseLabels();
    renderScopeControl();
    activate(getState().activeRoute);
  });
  renderLanguage();
  activate(
    mode === "viewer" && !release
      ? "workspace"
      : mode === "viewer"
        ? "overview"
        : getState().activeRoute,
  );
}

void bootstrap();
