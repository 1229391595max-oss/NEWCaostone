import { openEvidenceDrawer } from "../../core/evidence-drawer.mjs";
import { toAskBizPulseViewModel } from "./view-model.mjs";
import { localizeCode, t } from "../../i18n/catalog.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderAnswerText(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function decisionNav({ onShowForecast, onShowActions, language }) {
  const nav = element("nav", "decision-center-subnav");
  nav.setAttribute("aria-label", t(language, "ai.title"));
  const items = [
    [t(language, "decision.ask"), true, null],
    [t(language, "decision.forecast"), false, onShowForecast],
    [t(language, "decision.actions"), false, onShowActions],
  ];
  for (const [label, active, handler] of items) {
    const item = element("button", active ? "active" : "", label);
    item.type = "button";
    if (handler) {
      item.addEventListener("click", handler);
    } else {
      item.disabled = true;
    }
    if (active) item.setAttribute("aria-current", "page");
    nav.append(item);
  }
  return nav;
}

function factCard(fact, language) {
  const item = element("article", "chat-fact");
  item.append(
    element("p", "metric-label", `${fact.label} · ${fact.evidenceState}`),
    element("p", "metric-value", fact.displayValue),
  );
  const evidence = element("button", "text-button", t(language, "common.evidence"));
  evidence.type = "button";
  evidence.addEventListener("click", () => openEvidenceDrawer({
    evidence_id: fact.factRef,
    alias: fact.factRef,
    evidence_state: fact.evidenceState,
    formula: t(language, "ask.evidenceFormula"),
    source_refs: fact.evidenceRefs,
  }));
  item.append(evidence);
  return item;
}

function answerCard(turn, effects, model, language) {
  const card = element("article", "chat-answer-card");
  card.append(
    element("p", "eyebrow", turn.status),
    element("h3", "", turn.question),
  );
  card.append(element(
    "p",
    "metric-definition",
    `${turn.savedAudit ? `${t(language, "ask.savedAudit")} · ` : ""}dataset ${turn.datasetVersionId} · ${(turn.scope.storeLabels ?? turn.scope.storeIds).join(", ")} · ${turn.scope.periodStart} — ${turn.scope.periodEnd} · ${turn.scope.currency}`,
  ));
  if (turn.answerText) card.append(element("p", "chat-answer-text", turn.answerText));
  else if (turn.safeSummary) card.append(element("p", "chat-answer-text", turn.safeSummary));
  if (turn.errorCode) card.append(element("p", "action-feedback", turn.errorCode));

  if (turn.facts.length) {
    const facts = element("section", "chat-facts");
    facts.append(element("h4", "", t(language, "ask.authoritativeFacts")));
    for (const fact of turn.facts) facts.append(factCard(fact, language));
    card.append(facts);
  }
  const limits = element("section", "chat-limitations");
  limits.append(element("h4", "", t(language, "common.limitations")));
  const list = element("ul", "evidence-list");
  const values = turn.limitations.length
    ? turn.limitations
    : [t(language, "ask.noneReported")];
  for (const value of values) {
    list.append(element("li", "", localizeCode(language, value)));
  }
  limits.append(list);
  card.append(limits);

  if (turn.suggestedQuestions.length) {
    const suggestions = element("p", "metric-definition");
    suggestions.textContent = `${t(language, "ask.suggested")}: ${turn.suggestedQuestions.join(" · ")}`;
    card.append(suggestions);
  }
  if (turn.actionDraftId) {
    card.append(element("p", "action-feedback", t(language, "ask.draftCreated")));
  } else if (turn.actionDraftEligible && !turn.savedAudit) {
    const draft = element("button", "secondary-button", t(language, "ask.createDraft"));
    draft.type = "button";
    draft.disabled = model.draftTurnId === turn.id;
    draft.addEventListener("click", () => {
      draft.disabled = true;
      void effects.createActionDraft(turn.id).catch((error) => {
        draft.disabled = false;
        if (error?.code === "IDEMPOTENCY_CONFLICT") {
          draft.textContent = t(language, "ask.evidenceChanged");
        }
      });
    });
    card.append(draft);
  }
  if (model.mode === "operator") {
    if (turn.saved) {
      card.append(element("p", "action-feedback", t(language, "ask.saved")));
    } else if (turn.status === "answered") {
      const save = element("button", "text-button", t(language, "ask.save"));
      save.type = "button";
      save.disabled = model.savingTurnId === turn.id;
      save.addEventListener("click", () => {
        void effects.saveTurn(turn.id).catch(() => {});
      });
      card.append(save);
    }
  }
  return card;
}

export function renderAskBizPulse(
  root,
  state,
  {
    effects,
    onShowForecast,
    onShowActions,
    language = "en",
    onStateAction = () => {},
  },
) {
  const model = toAskBizPulseViewModel(state, language);
  root.replaceChildren();
  root.setAttribute("aria-busy", model.submitting ? "true" : "false");
  const chatSessionState = model.sessionEnding
    ? "ending"
    : model.status !== "ready"
      ? "loading"
      : model.turns.length
        ? "active"
        : "empty";
  root.setAttribute("data-chat-session-state", chatSessionState);
  root.append(decisionNav({ onShowForecast, onShowActions, language }));

  root.append(element(
    "p",
    "metric-definition",
    `${model.scope.periodStart} — ${model.scope.periodEnd} · ${model.scope.currency}`,
  ));
  if (model.context) {
    root.append(element(
      "p",
      "metric-definition",
      t(language, "ask.context", { kind: model.context.kind }),
    ));
    const clearContext = element(
      "button",
      "text-button",
      t(language, "ask.returnGeneral"),
    );
    clearContext.type = "button";
    clearContext.addEventListener("click", () => effects.selectContext(null));
    root.append(clearContext);
  }

  const composer = element("section", "chat-composer");
  composer.append(
    element("h2", "", t(language, "decision.ask")),
    element("h3", "", t(language, "ask.recommended")),
  );
  if (!model.chatAvailable) {
    const notice = element(
      "p",
      "action-feedback",
      t(language, "ask.disabled"),
    );
    notice.setAttribute("role", "status");
    notice.setAttribute("aria-live", "polite");
    composer.append(notice);
  }
  const composerDisabled = model.composerDisabled;
  const recommended = element("div", "chat-recommended-grid");
  for (const question of model.recommendedQuestions) {
    const button = element("button", "secondary-button", question.label);
    button.type = "button";
    button.disabled = composerDisabled || !question.available;
    if (model.chatAvailable && question.available) {
      button.addEventListener("click", () => {
        onStateAction({
          type: "chat/preset-fill-requested",
          preset: question,
        });
      });
    }
    recommended.append(button);
  }
  composer.append(recommended);
  const form = element("form", "chat-form");
  const label = element("label", "chat-question-label");
  label.append(element("span", "", t(language, "ask.freeText")));
  const question = element("textarea", "chat-question");
  question.name = "question";
  question.maxLength = model.maxChars;
  question.required = true;
  question.disabled = composerDisabled;
  question.value = model.draftText;
  label.append(question);
  const remaining = element(
    "span",
    "chat-character-count",
    `${model.draftText.length}/${model.maxChars}`,
  );
  remaining.setAttribute("aria-live", "polite");
  question.addEventListener("input", (event) => {
    const value = String(event.target?.value ?? "").slice(0, model.maxChars);
    question.value = value;
    remaining.textContent = `${value.length}/${model.maxChars}`;
    onStateAction(
      { type: "chat/draft-changed", value },
      { render: false },
    );
  });
  const submit = element("button", "primary-button", t(language, "ask.send"));
  submit.type = "submit";
  submit.disabled = composerDisabled;
  form.append(label, remaining, submit);
  if (model.chatAvailable) {
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const value = question.value.trim();
      if (!value) return;
      onStateAction(
        { type: "chat/draft-changed", value },
        { render: false },
      );
      const payload = { question: value };
      if (
        model.selectedPreset &&
        value === model.selectedPreset.template
      ) {
        Object.assign(payload, {
          recommended_question_id: model.selectedPreset.id,
          prompt_locale: model.selectedPreset.locale,
          prompt_template_version: model.selectedPreset.template_version,
          prompt_template_sha256: model.selectedPreset.templateSha256,
        });
      }
      void effects.submit(payload).catch(() => {});
    });
  }
  composer.append(form);
  let replacementDialog = null;
  let replacementInitialFocus = null;
  if (model.pendingReplacement) {
    const dialog = element("section", "chat-replacement-dialog");
    replacementDialog = dialog;
    dialog.tabIndex = -1;
    dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-modal", "true");
    const title = element("h3", "", t(language, "ask.replaceQuestion"));
    title.setAttribute("id", "ask-preset-replacement-title");
    const body = element(
      "p",
      "metric-definition",
      t(language, "ask.replaceBody"),
    );
    body.setAttribute("id", "ask-preset-replacement-body");
    dialog.setAttribute("aria-labelledby", "ask-preset-replacement-title");
    dialog.setAttribute("aria-describedby", "ask-preset-replacement-body");
    dialog.append(title, body);
    const replace = element("button", "primary-button", t(language, "ask.replace"));
    replace.type = "button";
    replacementInitialFocus = replace;
    replace.addEventListener("click", () => onStateAction({
      type: "chat/preset-replacement-confirmed",
    }));
    const keep = element(
      "button",
      "secondary-button",
      t(language, "ask.keepEditing"),
    );
    keep.type = "button";
    keep.addEventListener("click", () => onStateAction({
      type: "chat/preset-replacement-kept",
    }));
    dialog.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onStateAction({ type: "chat/preset-replacement-kept" });
      } else if (event.key === "Tab") {
        event.preventDefault();
        const controls = [replace, keep];
        const current = controls.indexOf(event.target);
        const direction = event.shiftKey ? -1 : 1;
        const next = (current + direction + controls.length) % controls.length;
        controls[next].focus();
      }
    });
    dialog.append(replace, keep);
    composer.append(dialog);
  }
  if (model.messageCode) {
    const feedback = element("p", "action-feedback", model.messageText);
    feedback.setAttribute("data-message-code", model.messageCode);
    feedback.setAttribute("role", "status");
    feedback.setAttribute("aria-live", "polite");
    composer.append(feedback);
  }
  const history = element("section", "chat-history");
  history.setAttribute("aria-label", t(language, "ask.currentHistory"));
  history.append(element("h2", "", t(language, "ask.currentHistory")));
  if (!model.turns.length) {
    history.append(element("p", "metric-definition", t(language, "ask.noQuestions")));
  }
  for (const turn of model.turns) {
    history.append(answerCard(turn, effects, model, language));
  }
  root.append(history);

  if (model.savedTurns.length) {
    const saved = element("section", "chat-history");
    saved.setAttribute("aria-label", t(language, "ask.savedAuditRecords"));
    saved.append(element("h2", "", t(language, "ask.saved")));
    for (const turn of model.savedTurns) {
      saved.append(answerCard(turn, effects, model, language));
    }
    root.append(saved);
  }

  if (model.submitting) {
    const progress = element("p", "action-feedback", t(language, "ask.asking"));
    progress.setAttribute("role", "status");
    progress.setAttribute("aria-live", "polite");
    composer.append(progress);
  }
  if (
    model.message === "IDEMPOTENCY_CONFLICT" ||
    model.message === "AI_CHAT_CONFLICT" ||
    model.message === "chat_evidence_changed"
  ) {
    const feedback = composer.querySelector?.(".action-feedback");
    if (feedback) {
      feedback.textContent = t(language, "ask.evidenceChanged");
    }
  }
  root.append(composer);
  if (replacementDialog && replacementInitialFocus) {
    replacementInitialFocus.focus();
  } else if (model.composerFocused && !composerDisabled) {
    question.focus();
    question.setSelectionRange(question.value.length, question.value.length);
    onStateAction(
      { type: "chat/composer-focus-consumed" },
      { render: false },
    );
  }

  if (model.mode === "viewer") {
    const end = element("button", "text-button", t(language, "ask.endSession"));
    end.type = "button";
    end.disabled = model.status !== "ready" || model.sessionEnding;
    end.addEventListener("click", () => {
      end.disabled = true;
      void effects.endSession().catch(() => { end.disabled = false; });
    });
    root.append(end);
  }
}
