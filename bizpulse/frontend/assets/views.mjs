import { createAnalysisLoader } from "./features/analysis/effects.mjs";
import {
  initialAnalysisState,
  reduceAnalysis,
} from "./features/analysis/state.mjs";
import { renderAnalyticsModel } from "./features/analysis/view.mjs?v=20260814";
import { toAnalysisViewModel } from "./features/analysis/view-model.mjs";
import { createInventoryLoader } from "./features/inventory/effects.mjs";
import { renderInventory } from "./features/inventory/view.mjs";
import { createOverviewLoader } from "./features/overview/effects.mjs";
import { renderOverview } from "./features/overview/view.mjs";
import { createProfitLoader } from "./features/profit/effects.mjs";
import { initialProfitState, reduceProfit } from "./features/profit/state.mjs";
import { renderProfit } from "./features/profit/view.mjs";
import { renderWorkspace } from "./features/workspace/view.mjs?v=20260814";
import { renderPublicDataEvidence } from "./features/workspace/public-view.mjs";
import { createActionLoader } from "./features/action-inbox/effects.mjs";
import {
  initialActionState,
  reduceActions,
} from "./features/action-inbox/state.mjs";
import { renderActionInbox } from "./features/action-inbox/view.mjs";
import { createForecastLoader } from "./features/forecast/effects.mjs";
import { initialForecastState, reduceForecast } from "./features/forecast/state.mjs";
import { renderForecast } from "./features/forecast/view.mjs";
import { createAskBizPulseEffects } from "./features/ask-bizpulse/effects.mjs";
import {
  initialAskBizPulseState,
  reduceAskBizPulse,
} from "./features/ask-bizpulse/state.mjs";
import { renderAskBizPulse } from "./features/ask-bizpulse/view.mjs";
import { createSettingsEffects } from "./features/settings/effects.mjs";
import {
  initialSettingsState,
  reduceSettings,
} from "./features/settings/state.mjs";
import { renderSettings } from "./features/settings/view.mjs";
import { t } from "./i18n/catalog.mjs";

const titleKeys = Object.freeze({
  workspace: "workspace.title",
  overview: "overview.title",
  sales: "sales.title",
  inventory: "inventory.title",
  profit: "profit.title",
  briefing: "ai.title",
  settings: "settings.title",
});

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function createViewRenderer({
  root,
  title,
  dataSource,
  release,
  mode,
  navigate,
  getLanguage = () => "en",
  getScope = () => null,
  onImportDemoData,
  initialSettingsPayload = null,
  onLanguageChange,
  onSidebarModeChange,
}) {
  let disposed = false;
  let activeRoute = "overview";
  let decisionPage = "ask";
  const states = {
    overview: initialAnalysisState(release),
    sales: initialAnalysisState(release),
    inventory: initialAnalysisState(release),
    profit: initialProfitState(release),
    briefing: initialForecastState(release, mode),
    actions: initialActionState(release, mode),
    ask: initialAskBizPulseState(release, mode, getScope()),
    settings: initialSettingsState(mode, initialSettingsPayload),
  };
  const dispatch = (route) => (action) => {
    if (disposed) return;
    states[route] = route === "ask"
      ? reduceAskBizPulse(states[route], action)
      : route === "settings"
      ? reduceSettings(states[route], action)
      : route === "actions"
      ? reduceActions(states[route], action)
      : route === "briefing"
      ? reduceForecast(states[route], action)
      : route === "profit"
        ? reduceProfit(states[route], action)
        : reduceAnalysis(states[route], action);
    const visible = activeRoute === route
      || (activeRoute === "briefing" && route === decisionPage);
    if (visible) renderRoute(activeRoute);
  };
  const loaders = {
    overview: createOverviewLoader(dataSource, dispatch("overview"), getScope),
    sales: createAnalysisLoader(dataSource, "sales_ads", dispatch("sales"), getScope),
    inventory: createInventoryLoader(dataSource, dispatch("inventory"), getScope),
    profit: createProfitLoader(dataSource, dispatch("profit"), getScope),
    briefing: createForecastLoader(dataSource, dispatch("briefing"), getScope),
    actions: createActionLoader(dataSource, dispatch("actions"), getScope),
  };
  const dispatchAsk = dispatch("ask");
  const updateAskState = (action, { render = true } = {}) => {
    if (render) {
      dispatchAsk(action);
      return;
    }
    states.ask = reduceAskBizPulse(states.ask, action);
  };
  const askEffects = createAskBizPulseEffects({
    api: dataSource,
    dispatch: dispatchAsk,
    getScope,
    onSessionEnded() {
      states.actions = initialActionState(release, mode);
    },
  });
  const settingsEffects = createSettingsEffects({
    dataSource,
    mode,
    dispatch: dispatch("settings"),
    initialPayload: initialSettingsPayload,
  });

  function showDecisionPage(page, context = null) {
    const enteringAsk = page === "ask" && decisionPage !== "ask";
    if (page === "ask" && context) {
      askEffects.selectContext(context);
    }
    decisionPage = page;
    renderRoute("briefing");
    if (
      enteringAsk &&
      states.ask.status !== "idle" &&
      states.ask.status !== "loading"
    ) {
      void askEffects.load();
    }
  }

  function navigateToAsk(context) {
    if (navigate) navigate("briefing", { decisionPage: "ask", context });
    else showDecisionPage("ask", context);
  }

  function renderRoute(route, options = {}) {
    if (disposed) return;
    const returningToAsk = route === "briefing"
      && (options.decisionPage ?? decisionPage) === "ask"
      && activeRoute !== "briefing";
    if (route === "briefing" && options.decisionPage) {
      decisionPage = options.decisionPage;
      if (options.context) {
        askEffects.selectContext(options.context);
      }
    }
    activeRoute = route;
    const language = getLanguage();
    title.textContent =
      mode === "viewer" && route === "workspace"
        ? t(language, "nav.viewerWorkspace")
        : t(language, titleKeys[route] ?? titleKeys.overview);
    if (route === "settings") {
      renderSettings(root, states.settings, {
        effects: settingsEffects,
        language,
        onLanguageChange,
        onSidebarModeChange,
        onApplyView(config) {
          const target = config?.route ?? "overview";
          if (navigate) navigate(target);
          else renderRoute(target);
        },
      });
      if (states.settings.status === "idle") void settingsEffects.load();
      return;
    }
    if (route === "workspace") {
      root.replaceChildren();
      if (mode === "operator") {
        renderWorkspace(
          root,
          dataSource,
          release,
          () => activeRoute === "workspace",
          getScope,
        );
      }
      else {
        const evidenceRoutes = {
          sales_ads: "sales",
          inventory_risk: "inventory",
          fifo_cost_aging: "profit",
          operating_profit: "profit",
          replenishment: "inventory",
        };
        renderPublicDataEvidence(root, release, {
          language: getLanguage(),
          dataSource,
          getScope,
          onImportDemoData,
          onOpenEvidence(kind) {
            const target = evidenceRoutes[kind] ?? "overview";
            if (navigate) navigate(target);
            else renderRoute(target);
          },
        });
      }
      return;
    }
    if (route === "overview") {
      renderOverview(root, states.overview, {
        language,
        kpiKeys: states.settings.payload?.preferences?.overview_kpis ?? null,
        onShowActions: () => showDecisionPage("actions"),
        onShowInventory: () => navigate?.("inventory"),
        onAsk: () => showDecisionPage("ask"),
      });
    }
    else if (route === "sales") {
      renderAnalyticsModel(
        root,
        toAnalysisViewModel(states.sales, language),
        language,
      );
    } else if (route === "inventory") {
      renderInventory(root, states.inventory, {
        onAsk: navigateToAsk,
        onSimulate: () => showDecisionPage("actions"),
        language,
      });
    }
    else if (route === "profit") {
      renderProfit(root, states.profit, {
        onAsk: navigateToAsk,
        language,
      });
    }
    else if (route === "briefing") {
      if (decisionPage === "ask") {
        renderAskBizPulse(root, states.ask, {
          effects: askEffects,
          onShowForecast: () => showDecisionPage("forecast"),
          onShowActions: () => showDecisionPage("actions"),
          language: getLanguage(),
          onStateAction: updateAskState,
        });
        if (states.ask.status === "idle" || returningToAsk) void askEffects.load();
      } else if (decisionPage === "actions") {
        renderActionInbox(root, states.actions, {
          dataSource,
          load: loaders.actions,
          getScope,
          onShowForecast: () => showDecisionPage("forecast"),
          onShowAsk: (context) => showDecisionPage("ask", context),
          language,
        });
        if (states.actions.status === "idle") void loaders.actions();
      } else {
        renderForecast(root, states.briefing, {
          dataSource,
          dispatch: dispatch("briefing"),
          onShowActions: () => showDecisionPage("actions"),
          onShowAsk: (context) => showDecisionPage("ask", context),
          language,
        });
        if (states.briefing.status === "idle") void loaders.briefing();
      }
    } else return;
    if (route !== "briefing" && states[route]?.status === "idle") void loaders[route]();
  }

  return {
    render: renderRoute,
    dispose() {
      disposed = true;
    },
  };
}

export function renderView(root, title, route) {
  title.textContent = t("en", titleKeys[route] ?? titleKeys.overview);
  root.replaceChildren();
  const unavailable = element("article", "empty-state-card");
  unavailable.append(element("h2", "", "Runtime session required"));
  root.append(unavailable);
}
