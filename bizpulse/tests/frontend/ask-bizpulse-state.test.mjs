import assert from "node:assert/strict";
import { test } from "node:test";

import {
  initialAskBizPulseState,
  reduceAskBizPulse,
} from "../../frontend/assets/features/ask-bizpulse/state.mjs";
import { getState, setActiveRoute } from "../../frontend/assets/state.mjs";

test("Ask BizPulse state fences stale history and submit responses", () => {
  let state = initialAskBizPulseState(
    { version_number: 4, dataset_version_id: "version-4" },
    "viewer",
  );
  state = reduceAskBizPulse(state, { type: "chat/loading", generation: 2 });
  const stale = reduceAskBizPulse(state, {
    type: "chat/loaded",
    generation: 1,
    payload: { items: [{ id: "stale" }] },
  });
  assert.equal(stale, state);

  state = reduceAskBizPulse(state, {
    type: "chat/loaded",
    generation: 2,
    payload: { items: [{ id: "turn-1", status: "answered" }] },
  });
  assert.equal(state.status, "ready");
  assert.equal(state.turns[0].id, "turn-1");

  const newScope = reduceAskBizPulse(state, {
    type: "chat/context-selected",
    context: { kind: "profit_bridge", reference: "profit_bridge:verified" },
  });
  assert.equal(newScope.context.kind, "profit_bridge");
  assert.ok(newScope.generation > state.generation);
});

test("session end clears only the current Ask BizPulse state", () => {
  const state = {
    ...initialAskBizPulseState({ dataset_version_id: "version-1" }, "viewer"),
    status: "ready",
    turns: [{ id: "turn-1" }],
  };
  const ended = reduceAskBizPulse(state, { type: "chat/session-ended" });
  assert.equal(ended.status, "ready");
  assert.equal(ended.sessionEnding, false);
  assert.deepEqual(ended.turns, []);
});

test("session end exposes a deterministic pending state until success or failure", () => {
  const initial = {
    ...initialAskBizPulseState({ dataset_version_id: "version-1" }, "viewer"),
    status: "ready",
    turns: [{ id: "turn-1" }],
  };
  const ending = reduceAskBizPulse(initial, {
    type: "chat/session-ending",
    generation: 2,
  });
  assert.equal(ending.sessionEnding, true);
  assert.deepEqual(ending.turns, initial.turns);

  const failed = reduceAskBizPulse(ending, {
    type: "chat/session-end-failed",
    generation: 2,
    error: "AI_CHAT_UNAVAILABLE",
  });
  assert.equal(failed.sessionEnding, false);
  assert.deepEqual(failed.turns, initial.turns);
});

test("unavailable Chat projection remains ready and carries its closed code", () => {
  let state = initialAskBizPulseState(
    { dataset_version_id: "version-1" },
    "viewer",
  );
  state = reduceAskBizPulse(state, { type: "chat/loading", generation: 1 });
  state = reduceAskBizPulse(state, {
    type: "chat/loaded",
    generation: 1,
    payload: {
      items: [],
      saved_items: [],
      recommended_questions: [{ id: "data_quality", label: "Data quality" }],
      availability: "unavailable",
      unavailable_code: "AI_CHAT_UNAVAILABLE",
    },
  });

  assert.equal(state.status, "ready");
  assert.equal(state.availability, "unavailable");
  assert.equal(state.unavailableCode, "AI_CHAT_UNAVAILABLE");
  assert.equal(state.error, null);
});

test("session end failure stays on the new generation and history load failure clears cached turns", () => {
  let state = {
    ...initialAskBizPulseState({ dataset_version_id: "version-1" }, "viewer"),
    status: "ready",
    turns: [{ id: "sensitive-turn" }],
  };
  state = reduceAskBizPulse(state, { type: "chat/session-ending", generation: 4 });
  state = reduceAskBizPulse(state, {
    type: "chat/session-end-failed",
    generation: 4,
    error: "SESSION_EXPIRED",
  });
  assert.equal(state.generation, 4);
  state = reduceAskBizPulse(state, { type: "chat/loading", generation: 5 });
  state = reduceAskBizPulse(state, {
    type: "chat/load-failed",
    generation: 5,
    error: "SESSION_EXPIRED",
  });
  assert.deepEqual(state.turns, []);
});

test("cross-feature navigation stores only a bounded server reference", () => {
  setActiveRoute("briefing", {
    kind: "profit_bridge",
    reference: "profit_bridge:pinned",
  });
  assert.deepEqual(getState().decisionContext, {
    kind: "profit_bridge",
    reference: "profit_bridge:pinned",
  });
  assert.throws(
    () => setActiveRoute("briefing", {
      kind: "database",
      reference: "postgresql://unsafe",
    }),
    /DECISION_CONTEXT_INVALID/,
  );
});

test("turn sequence preserves causal order when an older exact replay returns", () => {
  let state = initialAskBizPulseState(
    { dataset_version_id: "version-1" },
    "operator",
  );
  state = reduceAskBizPulse(state, { type: "chat/loading", generation: 1 });
  state = reduceAskBizPulse(state, {
    type: "chat/loaded",
    generation: 1,
    payload: {
      items: [
        { id: "older", turn_sequence: 1, created_at: "2026-08-14T12:00:00Z" },
        { id: "newer", turn_sequence: 2, created_at: "2026-08-14T12:00:00Z" },
      ],
    },
  });
  state = reduceAskBizPulse(state, {
    type: "chat/submitted",
    generation: 1,
    payload: { id: "older", turn_sequence: 1, created_at: "2026-08-14T12:00:00Z" },
  });
  assert.deepEqual(state.turns.map((item) => item.id), ["older", "newer"]);
});

test("preset fill and replacement are deterministic state transitions", () => {
  const preset = {
    id: "monthly_sales_report",
    template: "Generate the latest completed monthly sales report.",
    locale: "en",
    template_version: "2026-08-15.v1",
    templateSha256: "a".repeat(64),
  };
  let state = initialAskBizPulseState(
    { dataset_version_id: "version-1" },
    "viewer",
  );

  state = reduceAskBizPulse(state, {
    type: "chat/preset-fill-requested",
    preset,
  });
  assert.equal(state.draftText, preset.template);
  assert.equal(state.selectedPreset.id, "monthly_sales_report");
  assert.equal(state.pendingReplacement, null);
  assert.equal(state.composerFocused, true);

  state = reduceAskBizPulse(state, {
    type: "chat/draft-changed",
    value: "My existing question",
  });
  assert.equal(state.selectedPreset, null);
  state = reduceAskBizPulse(state, {
    type: "chat/preset-fill-requested",
    preset: { ...preset, id: "profit_changes", template: "Explain profit." },
  });
  assert.equal(state.draftText, "My existing question");
  assert.equal(state.pendingReplacement.id, "profit_changes");

  state = reduceAskBizPulse(state, { type: "chat/preset-replacement-kept" });
  assert.equal(state.draftText, "My existing question");
  assert.equal(state.pendingReplacement, null);
  assert.equal(state.composerFocused, true);
});

test("successful submit and session end reset only composer-local draft state", () => {
  const initial = {
    ...initialAskBizPulseState({ dataset_version_id: "version-1" }, "viewer"),
    draftText: "Visible prompt",
    selectedPreset: { id: "monthly_sales_report" },
    pendingReplacement: { id: "profit_changes" },
    composerFocused: true,
  };

  const submitted = reduceAskBizPulse(initial, {
    type: "chat/submitted",
    generation: 0,
    payload: { id: "turn-1", turn_sequence: 1, question: "Visible prompt" },
  });
  assert.equal(submitted.draftText, "");
  assert.equal(submitted.selectedPreset, null);
  assert.equal(submitted.pendingReplacement, null);

  const ended = reduceAskBizPulse(initial, {
    type: "chat/session-ended",
    generation: 1,
  });
  assert.equal(ended.draftText, "");
  assert.equal(ended.pendingReplacement, null);
  assert.equal(ended.selectedPreset, null);
});
