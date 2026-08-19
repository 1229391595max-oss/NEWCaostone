import { renderAnalyticsModel } from "../analysis/view.mjs";
import { openEvidenceDrawer } from "../../core/evidence-drawer.mjs";
import {
  INVENTORY_PRIORITY_ORDER,
  toInventoryViewModel,
} from "./view-model.mjs";
import { t } from "../../i18n/catalog.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderInventory(
  root,
  state,
  { onAsk, onSimulate, language = "en" } = {},
) {
  const model = toInventoryViewModel(state, language);
  renderAnalyticsModel(root, model, language, {
    afterCharts(container) {
      renderPriorityList(container, model, { onSimulate, language });
    },
  });
  const runId = (state.payload?.inventory ?? state.payload)?.run?.run_id;
  if (model.status === "ready" && runId && onAsk) {
    const button = element(
      "button",
      "secondary-button ask-about-this",
      t(language, "common.askAbout"),
    );
    button.type = "button";
    button.addEventListener("click", () => onAsk({
      kind: "inventory_analysis",
      reference: "inventory_analysis:pinned",
    }));
    root.append(button);
  }
}

function renderPriorityList(container, model, { onSimulate, language }) {
  const section = element("section", "inventory-priority-section");
  section.append(element("h2", "", t(language, "inventory.listTitle")));
  const filters = element("div", "inventory-priority-filters");
  filters.setAttribute("role", "group");
  filters.setAttribute("aria-label", t(language, "inventory.listTitle"));
  const list = element("div", "table-scroll-region inventory-priority-list");
  let active = "All";

  const renderRows = () => {
    const rows = active === "All"
      ? model.rows
      : model.rows.filter((item) => item.priority === active);
    list.replaceChildren();
    if (!rows.length) {
      list.append(element("p", "empty-inline", t(language, "inventory.noRows")));
      return;
    }
    const table = element("table", "inventory-priority-table");
    const head = element("thead", "");
    const headerRow = element("tr", "");
    for (const key of [
      "sku",
      "onHand",
      "velocity",
      "currentCover",
      "projectedCover",
      "stockoutDate",
      "recommended",
      "latestOrder",
      "reason",
      "actions",
    ]) {
      headerRow.append(element("th", "", t(language, `inventory.${key}`)));
    }
    head.append(headerRow);
    const body = element("tbody", "");
    for (const item of rows) body.append(priorityRow(item, onSimulate, language));
    table.append(head, body);
    list.append(table);
  };

  const filterItems = ["All", ...INVENTORY_PRIORITY_ORDER];
  for (const priority of filterItems) {
    const count = priority === "All" ? model.rows.length : model.counts[priority];
    const label = priority === "All"
      ? t(language, "inventory.filterAll")
      : t(language, `inventory.priority.${priority}`);
    const button = element(
      "button",
      `priority-filter priority-${priority.toLowerCase()}`,
      `${label} · ${count}`,
    );
    button.type = "button";
    button.setAttribute("aria-pressed", String(priority === active));
    button.addEventListener("click", () => {
      active = priority;
      for (const sibling of filters.children) {
        sibling.setAttribute(
          "aria-pressed",
          String(sibling === button),
        );
      }
      renderRows();
    });
    filters.append(button);
  }
  section.append(filters, list);
  renderRows();
  container.append(section);
}

function priorityRow(item, onSimulate, language) {
  const row = element("tr", `inventory-row inventory-row-${item.priority.toLowerCase()}`);
  const sku = element("td", "inventory-sku");
  const skuContent = element("div", "inventory-sku-content");
  skuContent.append(
    element("span", `priority-badge priority-${item.priority.toLowerCase()}`, item.priority),
    element("strong", "", item.skuId),
  );
  sku.append(skuContent);
  row.append(
    sku,
    element("td", "", item.onHand),
    element("td", "", item.dailyVelocity),
    element("td", "", item.currentCover),
    element("td", "", item.projectedCover),
    element("td", "", item.expectedStockoutDate),
    element("td", "", item.recommendedQuantity),
    element("td", "", item.latestOrderDate),
    element("td", "inventory-reason", item.reason),
  );
  const actions = element("td", "inventory-row-actions");
  const actionsContent = element("div", "inventory-row-actions-content");
  if (item.evidence) {
    const evidence = element(
      "button",
      "evidence-button",
      t(language, "common.viewEvidence"),
    );
    evidence.type = "button";
    evidence.addEventListener("click", () => openEvidenceDrawer(item.evidence));
    actionsContent.append(evidence);
  }
  if (item.simulationAvailable && typeof onSimulate === "function") {
    const simulate = element(
      "button",
      "secondary-button",
      t(language, "inventory.simulate"),
    );
    simulate.type = "button";
    simulate.addEventListener("click", () => onSimulate(item));
    actionsContent.append(simulate);
  }
  actions.append(actionsContent);
  row.append(actions);
  return row;
}
