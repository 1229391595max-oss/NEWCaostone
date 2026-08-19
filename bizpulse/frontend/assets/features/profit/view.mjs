import { waterfallChartSvg } from "../../core/charts.mjs?v=20260814";
import { renderAnalyticsModel } from "../analysis/view.mjs";
import { toProfitViewModel } from "./view-model.mjs";
import { t } from "../../i18n/catalog.mjs";

export function renderProfit(root, state, { onAsk, language = "en" } = {}) {
  const model = toProfitViewModel(state, language);
  renderAnalyticsModel(root, model, language);
  if (model.status !== "ready") return;
  const section = element("section", "profit-bridge-section");
  section.append(element("h2", "", t(language, "profit.bridge")));
  if (model.bridge.status !== "ready") {
    const unavailable = element("article", "empty-state-card");
    unavailable.append(
      element("h3", "", t(language, "profit.bridgeUnavailable")),
      element("p", "", model.bridge.message),
    );
    section.append(unavailable);
    root.append(section);
    return;
  }
  section.append(
    element("p", "metric-definition", model.bridge.periodLabel),
    element(
      "p",
      "metric-definition",
      model.bridge.reconciled
        ? t(language, "profit.reconciled")
        : t(language, "profit.notReconciled"),
    ),
  );
  const metrics = element("section", "metric-grid");
  for (const item of [
    [t(language, "profit.baselineContribution"), model.bridge.baselineDisplay],
    [t(language, "profit.currentContribution"), model.bridge.currentDisplay],
    [t(language, "profit.totalChange"), model.bridge.totalDeltaDisplay],
    [t(language, "profit.residual"), model.bridge.residualDisplay],
  ]) {
    const card = element("article", "metric-card");
    card.append(
      element("p", "metric-label", item[0]),
      element("p", "metric-value", item[1]),
    );
    metrics.append(card);
  }
  section.append(metrics);
  if (model.bridge.chart) {
    const figure = element("figure", "chart-card");
    figure.innerHTML = waterfallChartSvg(model.bridge.chart);
    figure.append(
      element(
        "figcaption",
        "chart-caption",
        model.bridge.chart.summary,
      ),
    );
    section.append(figure);
  }
  const evidence = element("section", "profit-bridge-evidence");
  evidence.append(element("h3", "", t(language, "common.evidence")));
  for (const item of model.bridge.items) {
    const details = element("details", "");
    details.append(
      element(
        "summary",
        "",
        `${item.ordinal}. ${item.label} · ${item.displayValue} · ${item.evidenceState}`,
      ),
      element("p", "evidence-formula", item.formula),
      element(
        "p",
        "metric-definition",
        `${t(language, "common.sources")}: ${
          item.sourceRefs.length
            ? item.sourceRefs.join(", ")
            : t(language, "common.unavailable")
        }`,
      ),
    );
    evidence.append(details);
  }
  section.append(evidence);
  if (onAsk) {
    const ask = element(
      "button",
      "secondary-button ask-about-this",
      t(language, "common.askAbout"),
    );
    ask.type = "button";
    ask.addEventListener("click", () => onAsk({
      kind: "profit_bridge",
      reference: "profit_bridge:pinned",
    }));
    section.append(ask);
  }
  root.append(section);
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}
