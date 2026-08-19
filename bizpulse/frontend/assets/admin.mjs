import { ApiClient } from "./core/api-client.mjs";
import { csrfToken } from "./core/auth-session.mjs";
import { AdminDataSource } from "./data-sources/admin.mjs";
import { OperatorDataSource } from "./data-sources/operator.mjs";
import {
  createAdminOverviewEffects,
} from "./features/admin-overview/effects.mjs";
import {
  initialAdminOverviewState,
  reduceAdminOverview,
} from "./features/admin-overview/state.mjs";
import { renderAdminOverview } from "./features/admin-overview/view.mjs";
import { createAdminAIEffects } from "./features/admin-ai/effects.mjs";
import {
  initialAdminAIState,
  reduceAdminAI,
} from "./features/admin-ai/state.mjs";
import { renderAdminAI } from "./features/admin-ai/view.mjs";
import { createAdminStatusEffects } from "./features/admin-status/effects.mjs";
import {
  initialAdminStatusState,
  reduceAdminStatus,
} from "./features/admin-status/state.mjs";
import { renderAdminStatus } from "./features/admin-status/view.mjs";
import { renderWorkspace } from "./features/workspace/view.mjs";
import {
  applyCatalog,
  loadLanguagePreference,
  persistLanguagePreference,
  t,
} from "./i18n/catalog.mjs";

const ROUTES = Object.freeze({
  "/admin": "overview",
  "/admin/": "overview",
  "/admin/data": "data",
  "/admin/status": "status",
  "/admin/ai": "ai",
});

const root = document.querySelector("[data-admin-root]");
const title = document.querySelector("[data-admin-title]");
const routeLinks = [...document.querySelectorAll("[data-admin-route]")];
const languageButton = document.querySelector("[data-language-toggle]");
const navigation = document.querySelector("[data-admin-navigation]");
const returnLink = document.querySelector(".sidebar-footer a[href='/app']");
const currentRoute = ROUTES[window.location.pathname] ?? "overview";
let language = loadLanguagePreference();
let activeEffects = null;

function renderLanguage() {
  document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
  applyCatalog(language);
  title.textContent = t(language, `admin.nav.${currentRoute}`);
  if (languageButton) {
    languageButton.textContent = t(language, "language.selector");
    languageButton.dataset.short = language === "en" ? "中" : "EN";
    languageButton.setAttribute("aria-label", t(language, "accessibility.languageToggle"));
  }
  navigation.setAttribute("aria-label", t(language, "admin.nav.label"));
  returnLink.textContent = t(language, "admin.nav.return");
  returnLink.setAttribute("aria-label", t(language, "admin.nav.return"));
  returnLink.title = t(language, "admin.nav.return");
  returnLink.dataset.tooltip = t(language, "admin.nav.return");
  for (const link of routeLinks) {
    if (link.dataset.adminRoute === currentRoute) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
    const label = t(language, `admin.nav.${link.dataset.adminRoute}`);
    link.textContent = label;
    link.setAttribute("aria-label", label);
    link.title = label;
    link.dataset.tooltip = label;
  }
}

function renderDataReauthentication() {
  const shell = document.createElement("section");
  shell.className = "empty-state-card";
  const heading = document.createElement("h2");
  heading.textContent = t(language, "admin.data.reauthenticationTitle");
  const body = document.createElement("p");
  body.textContent = t(language, "admin.data.reauthenticationBody");
  body.setAttribute("role", "alert");
  const link = document.createElement("a");
  link.className = "primary-button";
  link.href = "/login?next=/admin/data";
  link.textContent = t(language, "admin.data.reauthenticate");
  shell.append(heading, body, link);
  root.replaceChildren(shell);
}

async function renderDataWorkspace(api) {
  if (!csrfToken()) {
    renderDataReauthentication();
    return;
  }
  const releaseLoader = new OperatorDataSource(api, null);
  try {
    const release = await releaseLoader.loadRelease();
    const operatorDataSource = new OperatorDataSource(
      api,
      release?.dataset_version_id ?? null,
    );
    renderWorkspace(root, operatorDataSource, release, () => currentRoute === "data", () => null);
  } catch (error) {
    const message = document.createElement("p");
    message.className = "import-error admin-state-message";
    message.setAttribute("role", "alert");
    message.textContent = t(language, "admin.data.failed", {
      code: /^[A-Z][A-Z0-9_]{1,63}$/.test(error?.code ?? "")
        ? error.code
        : "ADMIN_DATA_UNAVAILABLE",
    });
    root.replaceChildren(message);
  }
}

function renderSummaryRoute(dataSource) {
  let state = initialAdminOverviewState();
  const effects = createAdminOverviewEffects({
    dataSource,
    dispatch(action) {
      state = reduceAdminOverview(state, action);
      renderAdminOverview(root, state, { language });
    },
  });
  renderAdminOverview(root, state, { language });
  activeEffects = effects;
  void effects.start();
}

function renderStatusRoute(dataSource) {
  let state = initialAdminStatusState();
  const effects = createAdminStatusEffects({
    dataSource,
    dispatch(action) {
      state = reduceAdminStatus(state, action);
      renderAdminStatus(root, state, { language });
    },
  });
  renderAdminStatus(root, state, { language });
  activeEffects = effects;
  void effects.start();
}

function renderAIRoute(dataSource) {
  let state = initialAdminAIState();
  let viewHandle = null;
  let lastAIAction = null;
  let effects;
  const render = () => {
    const focusedAction = document.activeElement?.getAttribute?.("data-admin-ai-action");
    if (["operator", "demo", "rotate"].includes(focusedAction)) {
      lastAIAction = focusedAction;
    }
    viewHandle?.clearSecrets();
    viewHandle = renderAdminAI(root, state, { language, effects });
    if (state.operation === null && state.status !== "refreshing" && lastAIAction) {
      viewHandle.focusAction(lastAIAction);
    }
  };
  effects = createAdminAIEffects({
    dataSource,
    dispatch(action) {
      state = reduceAdminAI(state, action);
      render();
    },
    clearSecrets() {
      viewHandle?.clearSecrets();
    },
  });
  render();
  activeEffects = effects;
  void effects.start();
}

function bootstrap() {
  renderLanguage();
  const api = new ApiClient();
  const dataSource = new AdminDataSource(api);
  if (currentRoute === "data") {
    void renderDataWorkspace(api);
  } else if (currentRoute === "status") {
    renderStatusRoute(dataSource);
  } else if (currentRoute === "ai") {
    renderAIRoute(dataSource);
  } else {
    renderSummaryRoute(dataSource);
  }
}

languageButton?.addEventListener("click", () => {
  language = persistLanguagePreference(language === "en" ? "zh" : "en");
  globalThis.location.reload();
});
globalThis.addEventListener?.("pagehide", () => activeEffects?.stop());

bootstrap();
