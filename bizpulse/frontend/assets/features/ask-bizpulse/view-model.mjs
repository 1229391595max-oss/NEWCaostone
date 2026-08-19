import { t } from "../../i18n/catalog.mjs";

const fallbackScope = Object.freeze({
  storeIds: ["SYNTH-STORE-01"],
  periodStart: "2026-07-01",
  periodEnd: "2026-07-31",
  currency: "BRL",
});

const failureMessages = Object.freeze({
  en: Object.freeze({
    AI_CHAT_UNAVAILABLE: "AI chat is currently unavailable.",
    AI_BUDGET_EXHAUSTED: "The AI usage budget is exhausted.",
    AI_CHAT_BUDGET_EXHAUSTED: "The AI usage budget is exhausted.",
    AI_RATE_LIMITED: "Too many requests. Please try again later.",
    AI_CHAT_RATE_LIMITED: "Too many requests. Please try again later.",
    AI_PROVIDER_TIMEOUT: "The AI provider timed out.",
    AI_CHAT_PROVIDER_TIMEOUT: "The AI provider timed out.",
    chat_evidence_insufficient: "The available evidence is insufficient for an answer.",
    insufficient_evidence: "The available evidence is insufficient for an answer.",
    provider_outcome_unknown: "The provider outcome is unknown; the request was not retried.",
  }),
  zh: Object.freeze({
    AI_CHAT_UNAVAILABLE: "AI 问答当前不可用。",
    AI_BUDGET_EXHAUSTED: "AI 使用预算已用尽。",
    AI_CHAT_BUDGET_EXHAUSTED: "AI 使用预算已用尽。",
    AI_RATE_LIMITED: "请求过于频繁，请稍后再试。",
    AI_CHAT_RATE_LIMITED: "请求过于频繁，请稍后再试。",
    AI_PROVIDER_TIMEOUT: "AI 服务响应超时。",
    AI_CHAT_PROVIDER_TIMEOUT: "AI 服务响应超时。",
    chat_evidence_insufficient: "现有证据不足，无法生成答案。",
    insufficient_evidence: "现有证据不足，无法生成答案。",
    provider_outcome_unknown: "AI 服务结果未知，本次请求不会自动重试。",
  }),
});

function unavailable(value, language) {
  return value === null || value === undefined || value === ""
    ? t(language, "common.unavailable")
    : String(value);
}

function scopeModel(scope, release, language) {
  if (!scope) return { ...fallbackScope };
  const labels = new Map((release?.store_catalog ?? []).map((item) => [
    item.store_id,
    language === "zh"
      ? item.display_name_zh ?? item.display_name_en ?? item.store_id
      : item.display_name_en ?? item.store_id,
  ]));
  return {
    storeIds: [...(scope.store_ids ?? [])],
    storeLabels: (scope.store_ids ?? []).map((id) => labels.get(id) ?? id),
    periodStart: scope.period_start,
    periodEnd: scope.period_end,
    currency: scope.currency,
  };
}

function selectedScopeModel(scope, release) {
  if (!scope) return { ...fallbackScope };
  return {
    storeIds: [...(scope.storeIds ?? [])],
    periodStart: scope.periodStart ?? release?.current_period?.[0] ?? fallbackScope.periodStart,
    periodEnd: scope.periodEnd ?? release?.current_period?.[1] ?? fallbackScope.periodEnd,
    currency: scope.currency ?? release?.currency ?? fallbackScope.currency,
  };
}

function turnModel(turn, language, release, { savedAudit = false } = {}) {
  const answer = turn.answer;
  return {
    id: turn.id,
    turnSequence: turn.turn_sequence,
    datasetVersionId: turn.dataset_version_id,
    status: turn.status,
    question: turn.question ?? t(language, "ask.legacyPrompt"),
    safeSummary: turn.safe_summary ?? "",
    errorCode: turn.error_code ?? null,
    answerText: answer?.answer ?? "",
    scope: scopeModel(answer?.scope, release, language),
    facts: (answer?.facts ?? []).map((fact) => ({
      factRef: fact.fact_ref,
      label: fact.label,
      displayValue: unavailable(fact.value, language),
      rawValue: fact.value,
      evidenceState: fact.evidence_state,
      evidenceRefs: [...(fact.evidence_refs ?? [])],
    })),
    limitations: [...(answer?.limitations ?? [])],
    suggestedQuestions: [...(answer?.suggested_questions ?? [])],
    actionDraftEligible: Boolean(answer?.action_card_draft_eligible),
    actionDraftId: turn.action_draft_id ?? null,
    actionDraft: turn.action_draft ?? null,
    saved: Boolean(turn.saved),
    savedAudit,
    completedAt: turn.completed_at ?? null,
  };
}

export function toAskBizPulseViewModel(state, language = "en") {
  const releaseId = state.release?.dataset_version_id ?? null;
  const mismatched = state.turns.some((turn) => turn.dataset_version_id !== releaseId);
  const chatAvailable = state.availability !== "unavailable";
  const turns = mismatched
    ? []
    : state.turns.map((turn) => turnModel(turn, language, state.release)).reverse();
  const currentIds = new Set(state.turns.map((turn) => turn.id));
  const savedTurns = (state.savedTurns ?? [])
    .filter((turn) => !currentIds.has(turn.id))
    .map((turn) => turnModel(turn, language, state.release, { savedAudit: true }));
  const latestScope = selectedScopeModel(state.scope, state.release);
  const recommendedQuestions = [...(state.recommendedQuestions ?? [])]
    .filter((question) => !state.context || question.context_kind === state.context.kind)
    .map((question) => ({
      ...question,
      label: question.labels?.[language] ?? question.label ?? question.id,
      template: question.templates?.[language] ?? "",
      templateSha256: question.template_sha256?.[language] ?? null,
      locale: language,
    }));
  const messageCode = mismatched ? "AI_CHAT_RELEASE_MISMATCH" : state.error;
  const messageText = messageCode
    ? failureMessages[language]?.[messageCode] ?? String(messageCode)
    : null;
  return {
    status: mismatched ? "error" : state.status,
    message: messageCode,
    messageCode,
    messageText,
    mode: state.mode,
    versionLabel: t(language, "common.currentDataset"),
    scope: latestScope,
    recommendedQuestions,
    turns,
    savedTurns,
    submitting: state.submitting,
    sessionEnding: Boolean(state.sessionEnding),
    draftText: state.draftText ?? "",
    selectedPreset: state.selectedPreset ?? null,
    pendingReplacement: state.pendingReplacement ?? null,
    composerFocused: Boolean(state.composerFocused),
    composerDisabled: state.submitting || !chatAvailable,
    maxChars: state.selectedPreset?.max_chars ?? 2000,
    draftTurnId: state.draftTurnId,
    savingTurnId: state.savingTurnId,
    context: state.context,
    chatAvailable,
    unavailableCode: chatAvailable
      ? null
      : state.unavailableCode ?? "AI_CHAT_UNAVAILABLE",
  };
}
