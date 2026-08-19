import { renderAnalyticsModel } from "../analysis/view.mjs";
import { t } from "../../i18n/catalog.mjs";
import { toOverviewViewModel } from "./view-model.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderOverview(
  root,
  state,
  {
    language = "en",
    onShowActions = null,
    onShowInventory = null,
    onAsk = null,
    kpiKeys = null,
  } = {},
) {
  renderAnalyticsModel(root, toOverviewViewModel(state, language, kpiKeys), language, {
    afterCharts(container, model) {
      const signals = element("section", "overview-signal-grid");
      const coverage = element("article", "overview-signal-card");
      coverage.append(element("h2", "", t(language, "overview.coverageTitle")));
      const coverageList = element("ul", "overview-coverage-list");
      for (const item of model.coverage) {
        const row = element("li", "");
        row.append(
          element("span", "", item.label),
          element(
            "span",
            `readiness-badge readiness-${item.status}`,
            t(language, `overview.status.${item.status}`),
          ),
        );
        coverageList.append(row);
      }
      coverage.append(coverageList);

      const priorities = element("article", "overview-signal-card");
      priorities.append(element("h2", "", t(language, "overview.alertsTitle")));
      if (model.urgentInventory.length) {
        const urgent = element("ul", "overview-urgent-list");
        for (const item of model.urgentInventory) {
          const row = element("li", "");
          row.append(
            element(
              "span",
              `priority-badge priority-${item.priority.toLowerCase()}`,
              item.priority,
            ),
            element("strong", "", item.skuId),
            element("span", "", item.reason),
          );
          urgent.append(row);
        }
        priorities.append(urgent);
      }
      const alerts = element("ul", "overview-alert-list");
      const alertItems = model.alerts.length
        ? model.alerts
        : [t(language, "overview.noAlerts")];
      for (const item of alertItems) alerts.append(element("li", "", item));
      priorities.append(
        alerts,
        element(
          "p",
          "metric-definition",
          t(language, "overview.pendingActions", { count: model.pendingActions }),
        ),
      );
      const controls = element("div", "overview-actions");
      if (typeof onShowActions === "function") {
        const actionButton = element(
          "button",
          "secondary-button",
          t(language, "overview.openActions"),
        );
        actionButton.type = "button";
        actionButton.addEventListener("click", onShowActions);
        controls.append(actionButton);
      }
      if (typeof onShowInventory === "function") {
        const inventoryButton = element(
          "button",
          "secondary-button",
          t(language, "overview.openInventory"),
        );
        inventoryButton.type = "button";
        inventoryButton.addEventListener("click", onShowInventory);
        controls.append(inventoryButton);
      }
      if (typeof onAsk === "function") {
        const askButton = element(
          "button",
          "primary-button",
          t(language, "overview.askBizPulse"),
        );
        askButton.type = "button";
        askButton.addEventListener("click", onAsk);
        controls.append(askButton);
      }
      priorities.append(controls);
      signals.append(coverage, priorities);
      container.append(signals);
    },
  });
}
