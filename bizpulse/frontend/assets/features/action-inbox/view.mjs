import { formatBrl, formatDays } from "../../core/formatters.mjs";
import { localizeCode, t } from "../../i18n/catalog.mjs";
import {
  commandAction,
  exportAction,
  recordSyntheticOutcome,
  resetActionSandbox,
} from "./effects.mjs";
import { toActionInboxViewModel } from "./view-model.mjs";
import {
  estimateSimulation,
  normalizeSimulationAdjustment,
} from "./simulation.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function line(label, value) {
  const row = element("p", "action-detail");
  row.append(element("strong", "", `${label}: `), document.createTextNode(value));
  return row;
}

function decisionNav(language, onShowForecast, onShowAsk) {
  const nav = element("nav", "decision-center-subnav");
  nav.setAttribute("aria-label", t(language, "ai.title"));
  const items = [
    [t(language, "decision.ask"), () => onShowAsk?.({ kind: "action_cards", reference: "action_cards:pinned" })],
    [t(language, "decision.forecast"), onShowForecast],
    [t(language, "decision.actions"), null],
  ];
  for (const [label, handler] of items) {
    const button = element("button", handler ? "" : "active", label);
    button.type = "button";
    if (handler) button.addEventListener("click", handler);
    else {
      button.disabled = true;
      button.setAttribute("aria-current", "page");
    }
    nav.append(button);
  }
  return nav;
}

function evidenceBlock(item, language) {
  const section = element("section", "action-evidence");
  section.append(element("h3", "", t(language, "actions.evidence")));
  const list = element("ul", "evidence-list");
  for (const fact of item.evidence) {
    list.append(element("li", "", `${fact.alias} · ${fact.state} · ${fact.value} · ${fact.sourceRef}`));
  }
  section.append(list);
  return section;
}

function historyBlock(item, dataSource, mode, language) {
  const history = element("div", "action-history-grid");
  const revisions = element("section", "action-history");
  revisions.append(element("h3", "", t(language, "actions.revisions")));
  for (const revision of item.revisions) {
    revisions.append(line(`v${revision.revision}`, `${revision.suggestion} · ${revision.quantity} · ${revision.budget}`));
  }
  const decisions = element("section", "action-history");
  decisions.append(element("h3", "", t(language, "actions.decisions")));
  if (!item.decisions.length) decisions.append(line(t(language, "actions.state"), t(language, "actions.noDecision")));
  for (const decision of item.decisions) {
    decisions.append(line(decision.command, `v${decision.revision} · ${decision.reason} · ${decision.decidedBy}`));
  }
  const exports = element("section", "action-history");
  exports.append(element("h3", "", t(language, "actions.exportStatus")));
  if (!item.exports.length) exports.append(line(t(language, "actions.state"), t(language, "actions.notExported")));
  for (const entry of item.exports) {
    const row = line(entry.status, entry.note);
    if (mode === "operator") {
      const link = element("a", "text-link", t(language, "actions.download"));
      link.href = dataSource.actionExportDownloadUrl(item.id, entry.id);
      row.append(" ", link);
    }
    exports.append(row);
  }
  const outcomes = element("section", "action-history");
  outcomes.append(element("h3", "", t(language, "actions.outcomes")));
  if (!item.outcomes.length) outcomes.append(line(t(language, "actions.state"), t(language, "actions.noReview")));
  for (const outcome of item.outcomes) {
    outcomes.append(line(
      `v${outcome.revision} · ${outcome.conclusion}`,
      `${outcome.reviewDate} · ${outcome.result.join(", ")} · ${outcome.reason}`,
    ));
  }
  history.append(revisions, decisions, exports, outcomes);
  if (mode === "viewer") {
    const simulations = element("section", "action-history");
    simulations.append(element("h3", "", t(language, "actions.mySimulation")));
    if (!item.overlays.length) simulations.append(line(t(language, "actions.state"), t(language, "actions.notStarted")));
    for (const overlay of item.overlays) {
      const changed = Object.entries(overlay.adjustment).map(([name, value]) => `${name}=${value}`).join(", ");
      simulations.append(line(
        `v${overlay.revision} · ${overlay.command}`,
        `${overlay.status} · ${changed || t(language, "actions.noFieldChange")} · ${overlay.reason}`,
      ));
    }
    history.append(simulations);
  }
  return history;
}

function controlPanel(item, model, dataSource, load, getScope, language) {
  const panel = element("section", "action-controls");
  panel.append(element("h3", "", t(language, "actions.humanControls")));
  const reason = element("textarea", "action-reason");
  reason.setAttribute("aria-label", t(language, "actions.reason"));
  reason.value = t(language, model.mode === "viewer" ? "actions.simulationReason" : "actions.operatorReason");
  panel.append(reason);
  const quantity = element("input", "action-number");
  quantity.type = "number";
  quantity.min = "0";
  quantity.step = "1";
  quantity.value = item.quantityRaw;
  quantity.setAttribute("aria-label", t(language, "actions.adjustedQuantity"));
  const budget = element("input", "action-number");
  budget.type = "number";
  budget.min = "0";
  budget.step = "0.01";
  budget.value = item.budgetRaw;
  budget.setAttribute("aria-label", t(language, "actions.adjustedBudget"));
  panel.append(quantity, budget);
  if (model.mode === "viewer") {
    const estimates = element("section", "action-simulation-estimates");
    const renderEstimates = () => {
      const result = estimateSimulation({
        quantity: quantity.value,
        unitCostBrl: item.simulationInputs.unitCostBrl,
        simulatedBudgetBrl: budget.value,
        baselineBudgetBrl: item.simulationInputs.baselineBudgetBrl,
        precomputedDailyVelocity: item.simulationInputs.precomputedDailyVelocity,
      });
      const display = (value, kind) => value === "unavailable"
        ? t(language, "common.unavailable")
        : kind === "money" ? formatBrl(value, language) : formatDays(value, language);
      estimates.replaceChildren(
        element("h4", "", t(language, "actions.simulationEstimate")),
        line(t(language, "actions.purchaseCash"), display(result.purchaseCashBrl, "money")),
        line(t(language, "actions.budgetDelta"), display(result.budgetDeltaBrl, "money")),
        line(t(language, "actions.additionalCover"), display(result.additionalCoverDays, "days")),
      );
    };
    quantity.addEventListener("input", renderEstimates);
    budget.addEventListener("input", renderEstimates);
    renderEstimates();
    panel.append(estimates);
  }
  const outcomeDate = element("input", "action-number");
  outcomeDate.type = "date";
  outcomeDate.value = item.periodEnd;
  outcomeDate.setAttribute("aria-label", t(language, "actions.reviewDate"));
  const conclusion = element("select", "action-number");
  conclusion.setAttribute("aria-label", t(language, "actions.conclusion"));
  for (const [value, key] of [
    ["achieved", "actions.achieved"],
    ["partially_achieved", "actions.partiallyAchieved"],
    ["not_achieved", "actions.notAchieved"],
    ["inconclusive", "actions.inconclusive"],
  ]) {
    const option = element("option", "", t(language, key));
    option.value = value;
    conclusion.append(option);
  }
  const syntheticResult = element("textarea", "action-reason");
  syntheticResult.maxLength = 2000;
  syntheticResult.value = "result=sample_value";
  syntheticResult.setAttribute("aria-label", t(language, "actions.resultLines"));
  if (item.controls.includes("record_outcome")) panel.append(outcomeDate, conclusion, syntheticResult);
  const feedback = element("p", "action-feedback", "");
  feedback.setAttribute("role", "status");
  feedback.setAttribute("aria-live", "polite");
  const buttons = element("div", "action-button-row");
  const commandKeys = {
    review: "actions.review",
    adjust: "actions.adjust",
    approve: "actions.approve",
    dismiss: "actions.dismiss",
    export: "actions.export",
    record_outcome: "actions.recordOutcome",
  };
  for (const command of item.controls) {
    const button = element("button", command === "approve" ? "primary-button" : "secondary-button", t(language, commandKeys[command]));
    button.type = "button";
    button.addEventListener("click", async () => {
      button.disabled = true;
      feedback.textContent = "";
      try {
        if (command === "export") {
          await exportAction(dataSource, load, item.id, item.currentRevision, getScope());
        } else if (command === "record_outcome") {
          const syntheticEntries = Object.fromEntries(
            syntheticResult.value.split("\n").map((entry) => entry.trim()).filter(Boolean).map((entry) => {
              const separator = entry.indexOf("=");
              if (separator < 1 || separator === entry.length - 1) throw new Error("ACTION_OUTCOME_RESULT_INVALID");
              return [entry.slice(0, separator).trim(), entry.slice(separator + 1).trim()];
            }),
          );
          if (!outcomeDate.value || !Object.keys(syntheticEntries).length) throw new Error("ACTION_OUTCOME_RESULT_INVALID");
          await recordSyntheticOutcome(dataSource, load, item.id, {
            revision: item.currentRevision,
            review_date: outcomeDate.value,
            synthetic_result: syntheticEntries,
            evidence: item.evidence.map((fact) => ({
              alias: fact.alias,
              evidence_state: fact.state,
              source_ref: fact.sourceRef,
              value: fact.value === t(language, "common.unavailable") ? null : fact.value,
            })),
            conclusion: conclusion.value,
            reason: reason.value,
          }, getScope());
        } else {
          const adjustment = command === "adjust"
            ? model.mode === "viewer"
              ? normalizeSimulationAdjustment({ quantity: quantity.value, budgetBrl: budget.value })
              : { quantity: quantity.value || null, budget_brl: budget.value || null }
            : undefined;
          const payload = model.mode === "viewer"
            ? { base_revision: item.currentRevision, command, reason: reason.value, adjustment: adjustment ?? {} }
            : { revision: item.currentRevision, command, reason: reason.value, ...(adjustment ? { adjustment } : {}) };
          await commandAction(dataSource, load, item.id, payload, getScope());
        }
      } catch (error) {
        feedback.setAttribute("role", "alert");
        feedback.textContent = t(language, "actions.saveFailed", { code: error?.code ?? error?.message ?? "ACTION_UNAVAILABLE" });
      } finally {
        button.disabled = false;
      }
    });
    buttons.append(button);
  }
  if (model.mode === "viewer" && item.overlays.length) {
    const reset = element("button", "text-button", t(language, "actions.reset"));
    reset.type = "button";
    reset.addEventListener("click", async () => {
      reset.disabled = true;
      feedback.textContent = "";
      try {
        await resetActionSandbox(dataSource, load, getScope());
      } catch (error) {
        feedback.setAttribute("role", "alert");
        feedback.textContent = t(language, "actions.resetFailed", { code: error?.code ?? error?.message ?? "ACTION_UNAVAILABLE" });
      } finally {
        reset.disabled = false;
      }
    });
    buttons.append(reset);
  }
  panel.append(buttons, feedback);
  return panel;
}

function actionCard(item, model, dataSource, load, getScope, onShowAsk, language) {
  const card = element("article", "action-card");
  card.append(
    element("p", "context-chip", `${item.sourceType} · ${item.displayStatus}`),
    element("h2", "", item.suggestion),
    line(t(language, "actions.target"), item.target),
    line(t(language, "actions.period"), item.period),
    line(t(language, "actions.quantity"), item.quantity),
    line(t(language, "actions.budget"), item.budget),
    line(t(language, "actions.date"), item.actionDate),
    line(t(language, "actions.threshold"), item.threshold),
    line(t(language, "actions.confidence"), item.confidence),
    line(t(language, "actions.expectedImpact"), item.expectedImpact.join(", ") || t(language, "common.unavailable")),
    line(
      t(language, "common.limitations"),
      item.limitations.map((value) => localizeCode(language, value)).join(", ") || t(language, "common.none"),
    ),
    evidenceBlock(item, language),
    historyBlock(item, dataSource, model.mode, language),
  );
  if (item.controls.length || (model.mode === "viewer" && item.overlays.length)) {
    card.append(controlPanel(item, model, dataSource, load, getScope, language));
  }
  if (onShowAsk) {
    const ask = element("button", "secondary-button ask-about-this", t(language, "common.askAbout"));
    ask.type = "button";
    ask.addEventListener("click", () => onShowAsk({ kind: "action_cards", reference: "action_cards:pinned" }));
    card.append(ask);
  }
  card.append(element("p", "demo-only-note", t(language, "actions.boundary")));
  return card;
}

export function renderActionInbox(
  root,
  state,
  { dataSource, load, getScope = () => null, onShowForecast, onShowAsk, language = "en" },
) {
  const model = toActionInboxViewModel(state, language);
  root.replaceChildren();
  const heading = element("section", "feature-heading");
  heading.append(
    element("h2", "", t(language, "actions.title")),
    element("p", "", `${t(language, "actions.summary")} · ${model.versionLabel}`),
  );
  root.append(heading, decisionNav(language, onShowForecast, onShowAsk));
  if (model.status === "loading") {
    root.append(element("article", "empty-state-card", t(language, "actions.loading")));
    return;
  }
  if (model.status === "error") {
    root.append(element("article", "empty-state-card", t(language, "actions.unavailable", { message: model.message })));
    return;
  }
  if (!model.items.length) {
    root.append(element("article", "empty-state-card", t(language, "actions.empty")));
    return;
  }
  const list = element("section", "action-card-list");
  for (const item of model.items) list.append(actionCard(item, model, dataSource, load, getScope, onShowAsk, language));
  root.append(list);
}
