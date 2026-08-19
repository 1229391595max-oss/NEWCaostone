import {
  barChartSvg,
  lineChartSvg,
  segmentedBarSvg,
} from "../../core/charts.mjs?v=20260814";
import { openEvidenceDrawer } from "../../core/evidence-drawer.mjs";
import { visibleItems } from "../../core/disclosure.mjs";
import { localizeCode, t } from "../../i18n/catalog.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function chartSvg(chart, context) {
  const spec = {
    ...chart,
    period: context.period,
    version: context.versionLabel,
    language: context.language ?? "en",
  };
  if (chart.type === "line") return lineChartSvg(spec);
  if (chart.type === "bar") return barChartSvg(spec);
  if (chart.type === "segmented") return segmentedBarSvg(spec);
  throw new Error("CHART_TYPE_INVALID");
}

export function renderAnalyticsModel(
  root,
  model,
  language = model.language ?? "en",
  { afterCharts = null } = {},
) {
  root.replaceChildren();
  const header = element("header", "report-heading");
  header.append(
    element("h2", "", model.title),
    element("p", "metric-definition", `${model.period} · ${model.versionLabel}`),
  );
  root.append(header);
  if (model.status === "loading") {
    const loading = element("article", "empty-state-card");
    loading.setAttribute("aria-busy", "true");
    loading.append(element("h2", "", t(language, "common.loadingAnalysis")));
    root.append(loading);
    return;
  }
  if (model.status !== "ready") {
    const unavailable = element("article", "empty-state-card");
    unavailable.append(
      element("h2", "", t(language, "common.analysisUnavailable")),
      element("p", "", model.message),
    );
    root.append(unavailable);
    return;
  }
  const metrics = element("section", "metric-grid");
  for (const item of model.metrics) {
    const card = element("article", "metric-card");
    card.append(
      element("p", "metric-label", item.label),
      element("p", "metric-value", item.value),
      element("p", "metric-definition", item.definition),
    );
    metrics.append(card);
  }
  root.append(metrics);
  const charts = element("section", "analytics-grid");
  for (const chart of model.charts) {
    const card = element("figure", "chart-card");
    card.innerHTML = chartSvg(chart, model);
    const caption = element("figcaption", "chart-caption", chart.summary);
    caption.setAttribute("aria-hidden", "true");
    card.append(caption);
    const textSummary = element(
      "p",
      "chart-text-summary visually-hidden",
      chart.summary,
    );
    textSummary.setAttribute("aria-label", t(language, "accessibility.chartSummary"));
    card.append(textSummary);
    const chartEvidence =
      model.evidence.find((item) => item.alias === chart.evidenceAlias) ??
      model.evidence[0];
    if (chartEvidence) {
      const control = element(
        "button",
        "evidence-button",
        t(language, "common.viewEvidence"),
      );
      control.type = "button";
      control.addEventListener("click", () => openEvidenceDrawer(chartEvidence));
      card.append(control);
    }
    charts.append(card);
  }
  if (model.charts.length) root.append(charts);
  if (typeof afterCharts === "function") afterCharts(root, model);
  if (model.evidence.length) {
    const evidence = element("section", "evidence-list");
    let expandedEvidence = false;
    const renderEvidence = () => {
      evidence.replaceChildren();
      evidence.append(
        element(
          "h2",
          "",
          `${t(language, "common.evidence")} · ${model.evidence.length}`,
        ),
      );
      for (const item of visibleItems(model.evidence, expandedEvidence, 4)) {
        const button = element(
          "button",
          "evidence-button",
          `${item.alias} · ${item.evidence_state}`,
        );
        button.type = "button";
        button.dataset.evidenceItem = "";
        button.addEventListener("click", () => openEvidenceDrawer(item));
        evidence.append(button);
      }
      if (model.evidence.length > 4) {
        const toggle = element(
          "button",
          "secondary-button evidence-disclosure",
          t(language, expandedEvidence ? "evidence.showLess" : "evidence.showAll"),
        );
        toggle.type = "button";
        toggle.setAttribute("aria-expanded", String(expandedEvidence));
        toggle.addEventListener("click", () => {
          expandedEvidence = !expandedEvidence;
          renderEvidence();
          toggle.focus();
        });
        evidence.append(toggle);
      }
    };
    renderEvidence();
    root.append(evidence);
  }
  if (model.limitations.length) {
    const limitations = element("section", "limitations-list");
    limitations.append(element("h2", "", t(language, "common.limitations")));
    const list = element("ul", "");
    for (const item of model.limitations) {
      list.append(element("li", "", localizeCode(language, item)));
    }
    limitations.append(list);
    root.append(limitations);
  }
}
