import { formatInteger } from "../../core/formatters.mjs";
import { localizeCode, t } from "../../i18n/catalog.mjs";
import {
  confirmForecast,
  createForecast,
  runForecast,
} from "./effects.mjs";
import { toForecastViewModel } from "./view-model.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function field(form, label, name, value, type = "text", options = {}) {
  const wrapper = element("label", "forecast-field");
  wrapper.append(element("span", "", label));
  const input = element("input", "");
  input.name = name;
  input.type = type;
  input.value = value;
  input.required = options.required !== false;
  if (type === "number") {
    input.min = "0";
    input.step = options.step ?? "1";
  }
  wrapper.append(input);
  form.append(wrapper);
}

function createForm(model, dataSource, dispatch, language) {
  const card = element("section", "forecast-workflow-card");
  card.append(
    element("h2", "", t(language, "forecast.inputTitle")),
    element("p", "", t(language, "forecast.inputBody")),
  );
  const form = element("form", "forecast-form");
  const idempotencyKey = globalThis.crypto.randomUUID();
  field(form, t(language, "forecast.productName"), "product_name", "Portable Organizer");
  field(form, t(language, "forecast.category"), "category", "travel_bag");
  field(form, t(language, "forecast.attributes"), "attributes", "portable,zippered,compact");
  field(form, t(language, "forecast.launchDate"), "planned_launch_date", "2026-08-20", "date");
  field(form, t(language, "forecast.price"), "planned_price_brl", "119.90", "number", { step: "0.01" });
  field(form, t(language, "forecast.discount"), "expected_discount_brl", "5.00", "number", { step: "0.01" });
  field(form, t(language, "forecast.unitCost"), "unit_cost_brl", "42.00", "number", { step: "0.01", required: false });
  field(form, t(language, "forecast.openingInventory"), "opening_inventory_units", "80", "number");
  field(form, t(language, "forecast.moq"), "moq_units", "24", "number");
  field(form, t(language, "forecast.leadTime"), "lead_time_days", "18", "number");
  field(form, t(language, "forecast.dailyAd"), "planned_daily_ad_brl", "12.00", "number", { step: "0.01" });
  field(form, t(language, "forecast.safetyStock"), "safety_stock_units", "20", "number");
  const submit = element("button", "primary-button", t(language, "forecast.rankAnalogs"));
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const values = new FormData(form);
    const payload = {
      dataset_version_id: model.releaseId,
      candidate: {
        product_name: values.get("product_name"),
        category: values.get("category"),
        attributes: String(values.get("attributes")).split(",").map((item) => item.trim()).filter(Boolean),
        planned_launch_date: values.get("planned_launch_date"),
        planned_price_brl: values.get("planned_price_brl"),
        expected_discount_brl: values.get("expected_discount_brl"),
        unit_cost_brl: values.get("unit_cost_brl") || null,
        opening_inventory_units: Number(values.get("opening_inventory_units")),
        moq_units: Number(values.get("moq_units")),
        lead_time_days: Number(values.get("lead_time_days")),
        planned_daily_ad_brl: values.get("planned_daily_ad_brl"),
      },
      safety_stock_units: Number(values.get("safety_stock_units")),
      assumptions: ["synthetic_launch_ramp"],
      missing_fields: values.get("unit_cost_brl") ? [] : ["unit_cost_brl"],
    };
    void createForecast(dataSource, dispatch, payload, idempotencyKey);
  });
  card.append(form);
  return card;
}

function analogControls(forecast, dataSource, dispatch, language) {
  const card = element("section", "forecast-workflow-card");
  card.append(element("h2", "", t(language, "forecast.rankedEvidence")));
  const list = element("div", "forecast-analog-list");
  for (const analog of forecast.analogs ?? []) {
    const label = element("label", "forecast-analog");
    const input = element("input", "");
    input.type = "checkbox";
    input.value = analog.sku_id;
    input.checked = analog.confirmed;
    input.disabled = forecast.status !== "draft";
    const evidence = element("span", "forecast-analog-evidence");
    evidence.append(
      element("strong", "", `${analog.sku_id} · ${t(language, "forecast.score")} ${analog.score}`),
      element("small", "", Object.entries(analog.components ?? {})
        .sort(([left], [right]) => left.localeCompare(right))
        .map(([name, value]) => `${name} ${value}`)
        .join(" · ")),
    );
    label.append(input, evidence);
    list.append(label);
  }
  card.append(list);
  if (forecast.status === "draft") {
    const confirm = element("button", "primary-button", t(language, "forecast.confirmAnalogs"));
    confirm.type = "button";
    confirm.addEventListener("click", () => {
      const selected = [...list.querySelectorAll("input:checked")].map((item) => item.value);
      void confirmForecast(dataSource, dispatch, forecast.id, selected);
    });
    card.append(confirm);
  } else if (forecast.status === "analogs_confirmed") {
    const run = element("button", "primary-button", t(language, "forecast.run"));
    run.type = "button";
    run.addEventListener("click", () => void runForecast(dataSource, dispatch, forecast.id));
    card.append(run);
  }
  return card;
}

function intervalChart(horizons, language) {
  const max = Math.max(...horizons.map((item) => item.units.high), 1);
  const rows = horizons.map((item, index) => {
    const y = 60 + index * 58;
    const low = 130 + (item.units.low / max) * 430;
    const base = 130 + (item.units.base / max) * 430;
    const high = 130 + (item.units.high / max) * 430;
    const period = t(language, "forecast.days", { count: formatInteger(item.days, language) });
    return `<text x="16" y="${y + 5}">${period}</text><line class="forecast-interval" x1="${low}" x2="${high}" y1="${y}" y2="${y}"/><circle class="forecast-baseline" cx="${base}" cy="${y}" r="7"/><text x="570" y="${y + 5}">${item.units.low} / ${item.units.base} / ${item.units.high}</text>`;
  }).join("");
  const summary = horizons.map((item) => [
    t(language, "forecast.days", { count: formatInteger(item.days, language) }),
    `${t(language, "forecast.low")} ${item.units.low}`,
    `${t(language, "forecast.base")} ${item.units.base}`,
    `${t(language, "forecast.high")} ${item.units.high}`,
  ].join(", ")).join("; ");
  return `<svg viewBox="0 0 760 250" role="img" xmlns="http://www.w3.org/2000/svg"><title>${t(language, "forecast.intervalTitle")}</title><desc>${summary}</desc>${rows}<text x="130" y="235">${t(language, "forecast.intervalLegend")}</text></svg>`;
}

function scenarioLine(label, values, language) {
  return `${label}: ${t(language, "forecast.low")} ${values.low} · ${t(language, "forecast.base")} ${values.base} · ${t(language, "forecast.high")} ${values.high}`;
}

function startAnotherButton(dispatch, language) {
  const button = element("button", "secondary-button", t(language, "forecast.new"));
  button.type = "button";
  button.addEventListener("click", () => dispatch({ type: "forecast/loaded", payload: null }));
  return button;
}

function completedView(model, dispatch, language) {
  const fragment = document.createDocumentFragment();
  const metrics = element("section", "metric-grid");
  for (const [label, value] of [
    [t(language, "forecast.confidence"), model.confidence],
    [t(language, "forecast.recommendedOrder"), model.recommendedFirstOrder],
    [t(language, "forecast.moqOrder"), model.moqFirstOrder],
    [t(language, "forecast.actionDraft"), t(language, model.actionDraftEligible ? "forecast.eligible" : "forecast.blocked")],
  ]) {
    const card = element("article", "metric-card");
    card.append(element("p", "metric-label", label), element("p", "metric-value", value));
    metrics.append(card);
  }
  fragment.append(metrics);
  const chart = element("figure", "chart-card forecast-chart");
  chart.innerHTML = intervalChart(model.horizons, language);
  chart.append(
    element("figcaption", "chart-caption", t(language, "forecast.chartCaption")),
    element("p", "chart-text-summary", model.horizons.map((item) => scenarioLine(
      t(language, "forecast.days", { count: formatInteger(item.days, language) }),
      item.units,
      language,
    )).join("; ")),
  );
  fragment.append(chart);
  const tabs = element("section", "forecast-tabs");
  const panels = [];
  for (const horizon of model.horizons) {
    const count = formatInteger(horizon.days, language);
    const button = element("button", "forecast-tab", t(language, "forecast.days", { count }));
    button.type = "button";
    const panel = element("article", "forecast-horizon-card");
    panel.hidden = horizon.days !== 30;
    panel.append(
      element("h3", "", t(language, "forecast.horizonBaseline", { count })),
      element("p", "", scenarioLine(t(language, "forecast.units"), horizon.units, language)),
      element("p", "", scenarioLine(t(language, "forecast.revenue"), horizon.revenue, language)),
      element("p", "", scenarioLine(t(language, "forecast.contributionProfit"), horizon.contributionProfit, language)),
      element("p", "", scenarioLine(t(language, "forecast.stockCover"), horizon.stockCover, language)),
    );
    button.addEventListener("click", () => {
      for (const item of panels) item.hidden = item !== panel;
    });
    tabs.append(button);
    panels.push(panel);
  }
  tabs.append(...panels);
  fragment.append(tabs);
  if (model.backtest) {
    const backtest = element("section", "forecast-workflow-card");
    backtest.append(
      element("h2", "", t(language, "forecast.backtest")),
      element("p", "", t(language, "forecast.backtestResult", model.backtest)),
      element("p", "", t(language, "forecast.backtestBoundary")),
    );
    fragment.append(backtest);
  }
  const evidence = element("section", "forecast-workflow-card");
  const fallback = t(language, "common.unavailable");
  const none = t(language, "common.none");
  evidence.append(
    element("h2", "", t(language, "forecast.evidenceLimits")),
    element("p", "", `${t(language, "forecast.confirmedAnalogs")}: ${model.analogIds.join(", ") || fallback}`),
    element("p", "", `${t(language, "forecast.analogComponents")}: ${model.analogs.filter((item) => item.confirmed).flatMap((item) => item.components.map((component) => `${item.skuId} ${component}`)).join("; ") || fallback}`),
    element("p", "", `${t(language, "forecast.factors")}: ${model.factors.join(", ") || fallback}`),
    element("p", "", `${t(language, "forecast.confidenceReasons")}: ${model.confidenceReasons.join(", ") || fallback}`),
    element("p", "", `${t(language, "forecast.assumptions")}: ${model.assumptions.join(", ") || none}`),
    element("p", "", `${t(language, "forecast.missing")}: ${model.missingFields.join(", ") || none}`),
    element("p", "", `${t(language, "common.limitations")}: ${model.limitations.map((item) => localizeCode(language, item)).join(", ") || none}`),
  );
  if (model.mode === "operator") evidence.append(startAnotherButton(dispatch, language));
  fragment.append(evidence);
  return fragment;
}

function decisionNav(language, onShowActions, onShowAsk) {
  const nav = element("nav", "decision-center-subnav");
  nav.setAttribute("aria-label", t(language, "ai.title"));
  for (const [label, active, handler] of [
    [t(language, "decision.ask"), false, () => onShowAsk?.({ kind: "forecast", reference: "forecast:pinned" })],
    [t(language, "decision.forecast"), true, null],
    [t(language, "decision.actions"), false, onShowActions],
  ]) {
    const item = element("button", active ? "active" : "", label);
    item.type = "button";
    if (handler) item.addEventListener("click", handler);
    else item.disabled = true;
    if (active) item.setAttribute("aria-current", "page");
    nav.append(item);
  }
  return nav;
}

export function renderForecast(
  root,
  state,
  { dataSource, dispatch, onShowActions, onShowAsk, language = "en" },
) {
  const model = {
    ...toForecastViewModel(state, language),
    releaseId: state.release?.dataset_version_id ?? null,
  };
  root.replaceChildren();
  const heading = element("section", "feature-heading");
  heading.append(
    element("h2", "", t(language, "forecast.title")),
    element("p", "", `${t(language, "forecast.summary")} · ${model.versionLabel}`),
  );
  root.append(heading, decisionNav(language, onShowActions, onShowAsk));
  if (state.forecast?.id && onShowAsk) {
    const ask = element("button", "secondary-button ask-about-this", t(language, "common.askAbout"));
    ask.type = "button";
    ask.addEventListener("click", () => onShowAsk({ kind: "forecast", reference: "forecast:pinned" }));
    root.append(ask);
  }
  if (model.status === "loading") {
    root.append(element("article", "empty-state-card", t(language, "forecast.loading")));
    return;
  }
  if (model.status === "error") {
    root.append(element("article", "empty-state-card", t(language, "forecast.unavailable", { message: model.message })));
    return;
  }
  if (model.status === "ready" && model.horizons.length) {
    root.append(completedView(model, dispatch, language));
    return;
  }
  if (model.status === "ready" && state.forecast) {
    const fallback = t(language, "common.unavailable");
    const blocked = element("article", "empty-state-card");
    blocked.append(
      element("h2", "", t(language, "forecast.preciseBlocked")),
      element("p", "", `${t(language, "forecast.confidence")}: ${model.confidence}`),
      element("p", "", `${t(language, "common.limitations")}: ${model.limitations.map((item) => localizeCode(language, item)).join(", ") || t(language, "forecast.insufficientEvidence")}`),
      element("p", "", `${t(language, "forecast.confirmedAnalogs")}: ${model.analogIds.join(", ") || fallback}`),
      element("p", "", t(language, "forecast.preciseBoundary")),
    );
    if (model.mode === "operator") blocked.append(startAnotherButton(dispatch, language));
    root.append(blocked);
    return;
  }
  if (state.mode !== "operator") {
    root.append(element("article", "empty-state-card", t(language, "forecast.noViewerForecast")));
    return;
  }
  if (!model.releaseId) {
    root.append(element("article", "empty-state-card", t(language, "forecast.publishFirst")));
    return;
  }
  if (state.forecast) root.append(analogControls(state.forecast, dataSource, dispatch, language));
  else root.append(createForm(model, dataSource, dispatch, language));
}
