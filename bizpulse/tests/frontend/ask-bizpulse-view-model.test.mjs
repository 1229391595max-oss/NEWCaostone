import assert from "node:assert/strict";
import { test } from "node:test";

import { toAskBizPulseViewModel } from "../../frontend/assets/features/ask-bizpulse/view-model.mjs";

const turn = {
  id: "turn-1",
  dataset_version_id: "version-1",
  question: "Why did profit change?",
  recommended_question_id: null,
  status: "answered",
  safe_summary: "Profit changed from verified drivers.",
  error_code: null,
  action_draft_id: null,
  answer: {
    status: "answered",
    answer: "Verified facts are shown below.",
    scope: {
      dataset_version_id: "version-1",
      store_ids: ["SYNTH-STORE-01"],
      period_start: "2026-07-01",
      period_end: "2026-07-31",
      currency: "BRL",
    },
    facts: [
      {
        fact_ref: "profit.total_change",
        label: "Total change",
        value: null,
        evidence_state: "unknown",
        evidence_refs: ["profit_bridge:bridge-1:total_change"],
      },
    ],
    limitations: ["missing_cost_authority"],
    suggested_questions: ["Which drivers are known?"],
    action_card_draft_eligible: false,
  },
};

const sixPresets = [
  ["monthly_sales_report", "Generate this month's sales report", "生成本月销售报告"],
  ["profit_changes", "Explain profit changes", "分析利润变化原因"],
  ["inventory_risks", "Find inventory risks", "查找库存风险"],
  ["advertising_performance", "Summarize advertising performance", "总结广告表现"],
  ["forecast_30_days", "Summarize the 30-day forecast", "总结未来 30 天预测"],
  ["next_actions", "Prioritize next actions", "给出下一步行动建议"],
].map(([id, en, zh]) => ({
  id,
  labels: { en, zh },
  templates: { en: `${en}.`, zh: `${zh}。` },
  template_version: "2026-08-15.v1",
  template_sha256: { en: "a".repeat(64), zh: "b".repeat(64) },
  context_kind: null,
  intent: id,
  max_chars: 2000,
  available: true,
}));

test("Ask BizPulse model keeps pinned scope evidence and missing values explicit", () => {
  const model = toAskBizPulseViewModel({
    release: {
      version_number: 2,
      dataset_version_id: "version-1",
      store_catalog: [{
        store_id: "SYNTH-STORE-01",
        display_name_en: "Main Store",
        display_name_zh: "主店",
      }],
    },
    mode: "viewer",
    status: "ready",
    turns: [turn],
    generation: 1,
    context: null,
    recommendedQuestions: [
      {
        id: "profit_changes",
        labels: { en: "Explain profit changes", zh: "分析利润变化原因" },
        templates: { en: "Explain profit changes.", zh: "分析利润变化。" },
        template_version: "2026-08-15.v1",
        template_sha256: { en: "a".repeat(64), zh: "b".repeat(64) },
        context_kind: "profit_bridge",
        intent: "profit_changes",
        max_chars: 2000,
        available: true,
      },
    ],
    error: null,
  });

  assert.equal(model.versionLabel, "Current dataset");
  assert.equal(model.turns[0].facts[0].displayValue, "Unavailable");
  assert.equal(model.turns[0].facts[0].evidenceState, "unknown");
  assert.equal(model.turns[0].scope.currency, "BRL");
  assert.deepEqual(model.turns[0].scope.storeLabels, ["Main Store"]);
  assert.deepEqual(model.turns[0].limitations, ["missing_cost_authority"]);
  assert.deepEqual(model.recommendedQuestions, [
    {
      id: "profit_changes",
      labels: { en: "Explain profit changes", zh: "分析利润变化原因" },
      templates: { en: "Explain profit changes.", zh: "分析利润变化。" },
      template_version: "2026-08-15.v1",
      template_sha256: { en: "a".repeat(64), zh: "b".repeat(64) },
      context_kind: "profit_bridge",
      intent: "profit_changes",
      max_chars: 2000,
      available: true,
      label: "Explain profit changes",
      template: "Explain profit changes.",
      templateSha256: "a".repeat(64),
      locale: "en",
    },
  ]);
});

test("mismatched turn version fails closed", () => {
  const model = toAskBizPulseViewModel({
    release: { version_number: 2, dataset_version_id: "version-2" },
    mode: "viewer",
    status: "ready",
    turns: [turn],
    generation: 1,
    context: null,
    recommendedQuestions: [],
    error: null,
  });
  assert.equal(model.status, "error");
  assert.equal(model.turns.length, 0);
});

test("unavailable Chat projection keeps question affordances visible but disabled", () => {
  const model = toAskBizPulseViewModel({
    release: { version_number: 2, dataset_version_id: "version-1" },
    mode: "viewer",
    status: "ready",
    turns: [],
    savedTurns: [],
    recommendedQuestions: [{ id: "data_quality", label: "Data quality" }],
    availability: "unavailable",
    unavailableCode: "AI_CHAT_UNAVAILABLE",
    submitting: false,
    context: null,
    error: null,
  });

  assert.equal(model.chatAvailable, false);
  assert.equal(model.unavailableCode, "AI_CHAT_UNAVAILABLE");
  assert.deepEqual(model.recommendedQuestions.map((item) => item.id), ["data_quality"]);
  assert.equal(model.composerDisabled, true);
});

for (const [language, expected] of [
  ["en", sixPresets.map((item) => item.labels.en)],
  ["zh", sixPresets.map((item) => item.labels.zh)],
]) {
  for (const availability of ["available", "unavailable"]) {
    test(`all six ${language} preset labels survive ${availability} projection`, () => {
      const model = toAskBizPulseViewModel({
        release: { version_number: 2, dataset_version_id: "version-1" },
        mode: "viewer",
        status: "ready",
        turns: [],
        savedTurns: [],
        recommendedQuestions: sixPresets,
        availability,
        unavailableCode: availability === "unavailable"
          ? "AI_CHAT_UNAVAILABLE"
          : null,
        submitting: false,
        context: null,
        error: null,
      }, language);

      assert.deepEqual(
        model.recommendedQuestions.map((item) => item.label),
        expected,
      );
      assert.equal(model.composerDisabled, availability === "unavailable");
    });
  }
}

for (const code of [
  "AI_CHAT_UNAVAILABLE",
  "AI_BUDGET_EXHAUSTED",
  "AI_RATE_LIMITED",
  "AI_PROVIDER_TIMEOUT",
  "chat_evidence_insufficient",
  "provider_outcome_unknown",
]) {
  test(`composer keeps a distinct localized failure state for ${code}`, () => {
    const model = toAskBizPulseViewModel({
      release: { version_number: 2, dataset_version_id: "version-1" },
      mode: "viewer",
      status: "ready",
      turns: [],
      savedTurns: [],
      recommendedQuestions: [],
      availability: "available",
      submitting: false,
      draftText: "",
      selectedPreset: null,
      pendingReplacement: null,
      context: null,
      error: code,
    }, "en");
    assert.equal(model.messageCode, code);
    assert.ok(model.messageText.length > 0);
  });
}

test("pinned context shows only legal server questions and historical saves stay audit-only", () => {
  const model = toAskBizPulseViewModel({
    release: { version_number: 2, dataset_version_id: "version-2" },
    mode: "operator",
    status: "ready",
    turns: [],
    savedTurns: [{ ...turn, saved: true }],
    generation: 1,
    context: { kind: "inventory_analysis", reference: "inventory_analysis:pinned" },
    recommendedQuestions: [
      { id: "inventory_risks", label: "Inventory", context_kind: "inventory_analysis" },
      { id: "profit_drivers", label: "Profit", context_kind: "profit_bridge" },
      { id: "data_quality", label: "Quality", context_kind: null },
    ],
    error: null,
  });
  assert.deepEqual(model.recommendedQuestions.map((item) => item.id), [
    "inventory_risks",
  ]);
  assert.equal(model.savedTurns[0].datasetVersionId, "version-1");
  assert.equal(model.savedTurns[0].savedAudit, true);
});
