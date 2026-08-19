import { t } from "../../i18n/catalog.mjs";
import { toSettingsViewModel } from "./view-model.mjs";

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function option(value, selected, label) {
  return `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
}

function field(label, control) {
  return `<label class="settings-field"><span>${escapeHtml(label)}</span>${control}</label>`;
}

function savedViews(model, language) {
  const items = model.savedViews.map((item) => `
    <article class="settings-list-row" data-settings-view="${escapeHtml(item.id)}">
      <input value="${escapeHtml(item.name)}" maxlength="80" aria-label="${escapeHtml(t(language, "settings.viewName"))}">
      <span>${escapeHtml(t(language, item.kind === "actions" ? "settings.actionsView" : "settings.todayView"))}</span>
      <div class="settings-row-actions">
        <button type="button" data-settings-action="apply-view">${escapeHtml(t(language, "settings.apply"))}</button>
        <button type="button" data-settings-action="rename-view">${escapeHtml(t(language, "settings.rename"))}</button>
        <button type="button" data-settings-action="update-view">${escapeHtml(t(language, "settings.update"))}</button>
        <button type="button" data-settings-action="delete-view">${escapeHtml(t(language, "settings.delete"))}</button>
      </div>
    </article>`).join("");
  return items || `<p class="settings-muted">${escapeHtml(t(language, "settings.noSavedViews"))}</p>`;
}

function targets(model, language) {
  const controls = model.permissions.targets === "editable";
  const rows = model.targets.map((item) => `
    <article class="settings-target-card" data-settings-target="${escapeHtml(item.id)}">
      <div><strong>${escapeHtml(item.period)}</strong><span class="settings-status">${escapeHtml(t(language, item.status === "active" ? "settings.active" : "settings.archived"))}</span></div>
      <dl><div><dt>${escapeHtml(t(language, "settings.revenueTarget"))}</dt><dd>R$${escapeHtml(item.revenue_brl)}</dd></div><div><dt>${escapeHtml(t(language, "settings.ordersTarget"))}</dt><dd>${escapeHtml(item.orders)}</dd></div><div><dt>${escapeHtml(t(language, "settings.roasTarget"))}</dt><dd>${escapeHtml(item.roas)}</dd></div><div><dt>${escapeHtml(t(language, "settings.profitTarget"))}</dt><dd>R$${escapeHtml(item.profit_brl)}</dd></div></dl>
      ${controls ? `<button type="button" data-settings-action="target-status">${escapeHtml(t(language, item.status === "active" ? "settings.archive" : "settings.restore"))}</button>` : `<p class="settings-muted">${escapeHtml(t(language, "settings.readOnlyExample"))}</p>`}
    </article>`).join("");
  return rows || `<p class="settings-muted">${escapeHtml(t(language, "settings.noTargets"))}</p>`;
}

function pageMarkup(model, language) {
  const preferences = model.preferences;
  const readOnly = model.permissions.reporting_defaults !== "editable";
  const allKpis = [
    "net_sales", "orders", "roas", "ad_spend", "contribution_profit", "stockout_skus",
  ];
  const kpiOrder = [
    ...preferences.overview_kpis,
    ...allKpis.filter((key) => !preferences.overview_kpis.includes(key)),
  ];
  const kpiOptions = kpiOrder.map((key) => `<span class="settings-choice" data-settings-kpi-row><label><input type="checkbox" value="${key}" data-settings-kpi${preferences.overview_kpis.includes(key) ? " checked" : ""}>${escapeHtml(t(language, `settings.kpi.${key}`))}</label><button type="button" data-settings-kpi-move="up" aria-label="${escapeHtml(t(language, "settings.moveUp"))}">↑</button><button type="button" data-settings-kpi-move="down" aria-label="${escapeHtml(t(language, "settings.moveDown"))}">↓</button></span>`).join("");
  const aiKey = ["available", "disabled", "unavailable"].includes(model.ai.status)
    ? model.ai.status : "unavailable";
  return `
    <header class="feature-heading"><p class="eyebrow">${escapeHtml(t(language, "settings.eyebrow"))}</p><h2>${escapeHtml(t(language, "settings.title"))}</h2><p>${escapeHtml(t(language, model.mode === "viewer" ? "settings.viewerSummary" : "settings.operatorSummary"))}</p></header>
    ${model.error ? `<p class="import-error" role="alert">${escapeHtml(t(language, "settings.failed", { code: model.error }))}</p>` : ""}
    <section class="settings-card"><h3>${escapeHtml(t(language, "settings.personal"))}</h3><div class="settings-grid">
      ${field(t(language, "settings.language"), `<select data-settings-field="locale">${option("en", preferences.locale, "English")}${option("zh", preferences.locale, "中文")}</select>`)}
      ${field(t(language, "settings.sidebar"), `<select data-settings-field="sidebar_mode">${option("full", preferences.sidebar_mode, t(language, "settings.sidebarFull"))}${option("compact", preferences.sidebar_mode, t(language, "settings.sidebarCompact"))}</select>`)}
      ${field(t(language, "settings.defaultStore"), `<input data-settings-field="default_store" maxlength="100" value="${escapeHtml(preferences.default_store)}">`)}
      ${field(t(language, "settings.period"), `<select data-settings-field="period_preset">${option("current_month", preferences.period_preset, t(language, "settings.currentMonth"))}${option("previous_month", preferences.period_preset, t(language, "settings.previousMonth"))}${option("last_30_days", preferences.period_preset, t(language, "settings.last30Days"))}</select>`)}
      ${field(t(language, "settings.comparison"), `<select data-settings-field="comparison_preset">${option("none", preferences.comparison_preset, t(language, "settings.none"))}${option("previous_period", preferences.comparison_preset, t(language, "settings.previousPeriod"))}${option("previous_year", preferences.comparison_preset, t(language, "settings.previousYear"))}</select>`)}
    </div><fieldset class="settings-kpis"><legend>${escapeHtml(t(language, "settings.overviewKpis"))}</legend>${kpiOptions}</fieldset>
    <div class="settings-grid">${field(t(language, "settings.currency"), `<select data-settings-field="reporting_currency"${readOnly ? " disabled" : ""}>${option("BRL", preferences.reporting_currency, "BRL")}${option("USD", preferences.reporting_currency, "USD")}</select>`)}${field(t(language, "settings.timezone"), `<select data-settings-field="timezone"${readOnly ? " disabled" : ""}>${option("America/Sao_Paulo", preferences.timezone, "America/Sao_Paulo")}${option("America/Chicago", preferences.timezone, "America/Chicago")}${option("UTC", preferences.timezone, "UTC")}</select>`)}</div>
    ${readOnly ? `<p class="settings-muted">${escapeHtml(t(language, "settings.reportingReadOnly"))}</p>` : ""}
    <button class="primary-action" type="button" data-settings-action="save"${model.saving ? " disabled" : ""}>${escapeHtml(t(language, model.saving ? "settings.saving" : "settings.save"))}</button></section>
    <section class="settings-card"><h3>${escapeHtml(t(language, "settings.savedViews"))}</h3><div class="settings-create-row"><input data-settings-new-view-name maxlength="80" placeholder="${escapeHtml(t(language, "settings.viewName"))}"><select data-settings-new-view-kind><option value="today">${escapeHtml(t(language, "settings.todayView"))}</option><option value="actions">${escapeHtml(t(language, "settings.actionsView"))}</option></select><button type="button" data-settings-action="create-view">${escapeHtml(t(language, "settings.createView"))}</button></div><div class="settings-list">${savedViews(model, language)}</div></section>
    <section class="settings-card"><h3>${escapeHtml(t(language, "settings.targets"))}</h3>${model.permissions.targets === "editable" ? `<div class="settings-target-form"><input data-target-field="period" type="month" value="2026-08"><input data-target-field="revenue_brl" type="number" min="0" step="0.01" placeholder="${escapeHtml(t(language, "settings.revenueTarget"))}"><input data-target-field="orders" type="number" min="0" step="1" placeholder="${escapeHtml(t(language, "settings.ordersTarget"))}"><input data-target-field="roas" type="number" min="0" step="0.01" placeholder="${escapeHtml(t(language, "settings.roasTarget"))}"><input data-target-field="profit_brl" type="number" step="0.01" placeholder="${escapeHtml(t(language, "settings.profitTarget"))}"><button type="button" data-settings-action="create-target">${escapeHtml(t(language, "settings.createTarget"))}</button></div>` : ""}<div class="settings-target-grid">${targets(model, language)}</div></section>
    <section class="settings-card settings-ai"><div><h3>${escapeHtml(t(language, "settings.aiStatus"))}</h3><p>${escapeHtml(t(language, "settings.aiBoundary"))}</p></div><span class="settings-ai-badge status-${escapeHtml(aiKey)}">${escapeHtml(t(language, `settings.ai.${aiKey}`))}</span></section>`;
}

function readPreferences(root, current) {
  const value = (name) => root.querySelector(`[data-settings-field="${name}"]`)?.value;
  return {
    locale: value("locale"),
    sidebar_mode: value("sidebar_mode"),
    default_store: value("default_store") || "all",
    period_preset: value("period_preset"),
    comparison_preset: value("comparison_preset"),
    overview_kpis: [...root.querySelectorAll("[data-settings-kpi]:checked")].map((input) => input.value),
    reporting_currency: value("reporting_currency") ?? current.reporting_currency,
    timezone: value("timezone") ?? current.timezone,
    revision: current.revision,
  };
}

export function renderSettings(root, state, {
  effects,
  language = "en",
  onLanguageChange,
  onSidebarModeChange,
  onApplyView,
} = {}) {
  const model = toSettingsViewModel(state, language);
  root.replaceChildren();
  const section = document.createElement("section");
  section.className = "settings-page";
  section.dataset.page = "settings";
  if (model.status === "loading") {
    section.textContent = t(language, "settings.loading");
    root.append(section);
    return;
  }
  if (model.status === "unavailable") {
    section.innerHTML = `<p class="import-error" role="alert">${escapeHtml(t(language, "settings.failed", { code: model.error }))}</p><button type="button" data-settings-action="retry">${escapeHtml(t(language, "settings.retry"))}</button>`;
    section.querySelector("[data-settings-action=retry]")?.addEventListener("click", () => effects.load());
    root.append(section);
    return;
  }
  section.innerHTML = pageMarkup(model, language);
  root.append(section);

  section.querySelector("[data-settings-action=save]")?.addEventListener("click", async () => {
    const preferences = readPreferences(section, model.preferences);
    if (preferences.overview_kpis.length < 2) return;
    const saved = await effects.savePreferences(preferences);
    if (saved) {
      onLanguageChange?.(preferences.locale);
      onSidebarModeChange?.(preferences.sidebar_mode);
    }
  });
  for (const row of section.querySelectorAll("[data-settings-kpi-row]")) {
    row.querySelector("[data-settings-kpi-move=up]")?.addEventListener("click", () => {
      row.previousElementSibling?.before(row);
    });
    row.querySelector("[data-settings-kpi-move=down]")?.addEventListener("click", () => {
      row.nextElementSibling?.after(row);
    });
  }
  section.querySelector("[data-settings-action=create-view]")?.addEventListener("click", async () => {
    const name = section.querySelector("[data-settings-new-view-name]")?.value.trim();
    const kind = section.querySelector("[data-settings-new-view-kind]")?.value;
    if (!name) return;
    await effects.createView(name, kind, {
      route: kind === "actions" ? "briefing" : "overview",
      period_preset: model.preferences.period_preset,
      comparison_preset: model.preferences.comparison_preset,
    });
  });
  for (const [index, row] of [...section.querySelectorAll("[data-settings-view]")].entries()) {
    const item = model.savedViews[index];
    row.querySelector("[data-settings-action=apply-view]")?.addEventListener("click", () => onApplyView?.(item.config));
    row.querySelector("[data-settings-action=rename-view]")?.addEventListener("click", () => effects.updateView(item, row.querySelector("input").value.trim(), item.config));
    row.querySelector("[data-settings-action=update-view]")?.addEventListener("click", () => effects.updateView(item, row.querySelector("input").value.trim(), { ...item.config, period_preset: model.preferences.period_preset, comparison_preset: model.preferences.comparison_preset }));
    row.querySelector("[data-settings-action=delete-view]")?.addEventListener("click", () => effects.deleteView(item));
  }
  section.querySelector("[data-settings-action=create-target]")?.addEventListener("click", () => {
    const value = (name) => section.querySelector(`[data-target-field="${name}"]`)?.value;
    effects.createTarget({
      period: value("period"), revenue_brl: value("revenue_brl"),
      orders: Number(value("orders")), roas: value("roas"), profit_brl: value("profit_brl"),
    });
  });
  for (const [index, card] of [...section.querySelectorAll("[data-settings-target]")].entries()) {
    const item = model.targets[index];
    card.querySelector("[data-settings-action=target-status]")?.addEventListener("click", () => effects.setTargetStatus(item, item.status === "active" ? "archived" : "active"));
  }
}
