import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  renderAnswerText,
  renderAskBizPulse,
} from "../../frontend/assets/features/ask-bizpulse/view.mjs";
import {
  initialAskBizPulseState,
  reduceAskBizPulse,
} from "../../frontend/assets/features/ask-bizpulse/state.mjs";

class FakeElement {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.attributes = new Map();
    this.className = "";
    this.textContent = "";
    this.disabled = false;
    this.listeners = new Map();
    this.value = "";
    this.selectionStart = 0;
    this.selectionEnd = 0;
    this.focused = false;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  addEventListener(name, handler) {
    this.listeners.set(name, handler);
  }

  focus() {
    this.focused = true;
  }

  setSelectionRange(start, end) {
    this.selectionStart = start;
    this.selectionEnd = end;
  }
}

function descendants(node) {
  return [node, ...node.children.flatMap((child) => descendants(child))];
}

test("answer text is escaped and cannot inject HTML", () => {
  const html = renderAnswerText("<img src=x onerror=alert(1)>");
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img/);
});

test("Ask BizPulse UI keeps the approved decision-center information architecture", async () => {
  const files = await Promise.all([
    "state.mjs",
    "effects.mjs",
    "view-model.mjs",
    "view.mjs",
  ].map((name) => readFile(
    new URL(`../../frontend/assets/features/ask-bizpulse/${name}`, import.meta.url),
    "utf8",
  )));
  const source = files.join("\n");
  assert.match(source, /decision\.ask/);
  assert.match(source, /ask\.recommended/);
  assert.match(source, /common\.evidence/);
  assert.match(source, /common\.limitations/);
  assert.match(source, /ask\.createDraft/);
  assert.match(source, /ask\.endSession/);
  assert.match(source, /aria-busy/);
  assert.match(source, /ask\.save/);
  assert.match(source, /ask\.context/);
  assert.match(source, /ask\.returnGeneral/);
  assert.match(source, /ask\.savedAudit/);
  assert.match(source, /actionDraftEligible && !turn\.savedAudit/);
  assert.doesNotMatch(source, /innerHTML\s*=/);
  assert.doesNotMatch(source, /https?:\/\//);
});

test("restricted no-AI Chat renders a boundary notice and disabled composer", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new FakeElement(tag);
    },
  };
  try {
    const root = new FakeElement("main");
    renderAskBizPulse(
      root,
      {
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
      },
      { effects: {}, onShowForecast: () => {}, onShowActions: () => {} },
    );

    const nodes = descendants(root);
    const notice = nodes.find((node) => node.textContent.includes(
      "AI chat is currently disabled for this workspace.",
    ));
    const question = nodes.find((node) => node.tag === "textarea");
    const submit = nodes.find(
      (node) => node.tag === "button" && node.textContent === "Send",
    );
    const recommended = nodes.find(
      (node) => node.className === "chat-recommended-grid",
    );

    assert.ok(notice);
    assert.equal(question.disabled, true);
    assert.equal(submit.disabled, true);
    assert.equal(recommended.children.length, 1);
    assert.equal(recommended.children[0].disabled, true);
    assert.equal(recommended.children[0].listeners.has("click"), false);
  } finally {
    globalThis.document = originalDocument;
  }
});

test("viewer cannot end chat before history is ready and deletion has an exact UI state", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new FakeElement(tag);
    },
  };
  try {
    const root = new FakeElement("main");
    const effects = { endSession: () => Promise.resolve() };
    const base = {
      ...initialAskBizPulseState(
        { version_number: 2, dataset_version_id: "version-1" },
        "viewer",
      ),
      status: "loading",
    };
    renderAskBizPulse(
      root,
      base,
      { effects, onShowForecast: () => {}, onShowActions: () => {} },
    );
    let end = descendants(root).find(
      (node) => node.tag === "button" && node.textContent === "End Chat Session",
    );
    assert.equal(end.disabled, true);
    assert.equal(root.attributes.get("data-chat-session-state"), "loading");

    renderAskBizPulse(
      root,
      { ...base, status: "ready", sessionEnding: true },
      { effects, onShowForecast: () => {}, onShowActions: () => {} },
    );
    end = descendants(root).find(
      (node) => node.tag === "button" && node.textContent === "End Chat Session",
    );
    assert.equal(end.disabled, true);
    assert.equal(root.attributes.get("data-chat-session-state"), "ending");

    renderAskBizPulse(
      root,
      { ...base, status: "ready", sessionEnding: false },
      { effects, onShowForecast: () => {}, onShowActions: () => {} },
    );
    end = descendants(root).find(
      (node) => node.tag === "button" && node.textContent === "End Chat Session",
    );
    assert.equal(end.disabled, false);
    assert.equal(root.attributes.get("data-chat-session-state"), "empty");
  } finally {
    globalThis.document = originalDocument;
  }
});

test("approved analytical pages expose one shared Ask-about-this handoff", async () => {
  const sources = await Promise.all([
    "inventory/view.mjs",
    "profit/view.mjs",
    "forecast/view.mjs",
    "action-inbox/view.mjs",
  ].map((name) => readFile(
    new URL(`../../frontend/assets/features/${name}`, import.meta.url),
    "utf8",
  )));
  for (const source of sources) {
    assert.match(source, /common\.askAbout/);
    assert.doesNotMatch(source, /fetch\s*\(/);
  }
});

test("prompt preset click fills the draft without sending", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new FakeElement(tag);
    },
  };
  try {
    const submitted = [];
    const preset = {
      id: "inventory_risks",
      labels: { en: "Find inventory risks", zh: "查找库存风险" },
      templates: {
        en: "Identify the material inventory risks in the current release.",
        zh: "识别当前发布版本中的重大库存风险。",
      },
      template_version: "2026-08-15.v1",
      template_sha256: { en: "a".repeat(64), zh: "b".repeat(64) },
      context_kind: "inventory_analysis",
      intent: "inventory_risks",
      max_chars: 2000,
      available: true,
    };
    const root = new FakeElement("main");
    let state = {
      ...initialAskBizPulseState(
        { version_number: 2, dataset_version_id: "version-1" },
        "viewer",
      ),
      status: "ready",
      recommendedQuestions: [preset],
      context: { kind: "inventory_analysis", reference: "inventory_analysis:pinned" },
    };
    const options = {
      effects: { submit: (payload) => { submitted.push(payload); return Promise.resolve(); } },
      onShowForecast: () => {},
      onShowActions: () => {},
      language: "en",
      onStateAction(action, { render = true } = {}) {
        state = reduceAskBizPulse(state, action);
        if (render) renderAskBizPulse(root, state, options);
      },
    };
    renderAskBizPulse(root, state, options);

    const button = descendants(root).find(
      (node) => node.tag === "button" && node.textContent === "Find inventory risks",
    );
    assert.ok(button);
    button.listeners.get("click")();
    const textarea = descendants(root).find((node) => node.tag === "textarea");
    assert.equal(textarea.value, preset.templates.en);
    assert.equal(textarea.focused, true);
    assert.equal(textarea.selectionStart, preset.templates.en.length);
    assert.deepEqual(submitted, []);
  } finally {
    globalThis.document = originalDocument;
  }
});

test("nonempty draft requires replacement and explicit Send carries visible text", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new FakeElement(tag);
    },
  };
  try {
    const submitted = [];
    const preset = {
      id: "monthly_sales_report",
      labels: { en: "Generate monthly sales report", zh: "生成月度销售报告" },
      templates: { en: "Generate the latest completed monthly sales report.", zh: "生成最近完整月份销售报告。" },
      template_version: "2026-08-15.v1",
      template_sha256: { en: "c".repeat(64), zh: "d".repeat(64) },
      context_kind: null,
      intent: "monthly_sales_report",
      max_chars: 2000,
      available: true,
    };
    const root = new FakeElement("main");
    let state = {
      ...initialAskBizPulseState(
        { version_number: 2, dataset_version_id: "version-1" },
        "viewer",
      ),
      status: "ready",
      recommendedQuestions: [preset],
      draftText: "My question",
    };
    const options = {
      effects: { submit: (payload) => { submitted.push(payload); return Promise.resolve(); } },
      onShowForecast: () => {},
      onShowActions: () => {},
      language: "en",
      onStateAction(action, { render = true } = {}) {
        state = reduceAskBizPulse(state, action);
        if (render) renderAskBizPulse(root, state, options);
      },
    };
    renderAskBizPulse(root, state, options);
    descendants(root).find(
      (node) => node.tag === "button" && node.textContent === preset.labels.en,
    ).listeners.get("click")();

    let textarea = descendants(root).find((node) => node.tag === "textarea");
    assert.equal(textarea.value, "My question");
    const dialog = descendants(root).find(
      (node) => node.attributes.get("role") === "alertdialog",
    );
    assert.ok(dialog);
    const replaceButton = descendants(dialog).find(
      (node) => node.tag === "button" && node.textContent === "Replace",
    );
    assert.equal(replaceButton.focused, true);
    replaceButton.listeners.get("click")();

    textarea = descendants(root).find((node) => node.tag === "textarea");
    textarea.value += " Focus on the top three SKUs.";
    textarea.listeners.get("input")({ target: textarea });
    const form = descendants(root).find((node) => node.tag === "form");
    form.listeners.get("submit")({ preventDefault() {} });

    assert.deepEqual(submitted, [{ question: textarea.value }]);
  } finally {
    globalThis.document = originalDocument;
  }
});

test("replacement alertdialog labels itself and traps keyboard focus between decisions", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new FakeElement(tag);
    },
  };
  try {
    const root = new FakeElement("main");
    const pending = {
      id: "profit_changes",
      template: "Explain profit changes.",
      locale: "en",
      template_version: "2026-08-15.v1",
      templateSha256: "a".repeat(64),
      available: true,
    };
    const state = {
      ...initialAskBizPulseState(
        { version_number: 2, dataset_version_id: "version-1" },
        "viewer",
      ),
      status: "ready",
      draftText: "Keep this draft",
      pendingReplacement: pending,
    };
    const actions = [];
    renderAskBizPulse(root, state, {
      effects: {},
      onShowForecast: () => {},
      onShowActions: () => {},
      onStateAction(action) { actions.push(action); },
    });

    const dialog = descendants(root).find(
      (node) => node.attributes.get("role") === "alertdialog",
    );
    const replace = descendants(dialog).find(
      (node) => node.tag === "button" && node.textContent === "Replace",
    );
    const keep = descendants(dialog).find(
      (node) => node.tag === "button" && node.textContent === "Keep editing",
    );
    assert.ok(dialog.attributes.get("aria-labelledby"));
    assert.ok(dialog.attributes.get("aria-describedby"));
    assert.equal(replace.focused, true);

    let prevented = false;
    dialog.listeners.get("keydown")({
      key: "Tab",
      shiftKey: false,
      target: replace,
      preventDefault() { prevented = true; },
    });
    assert.equal(prevented, true);
    assert.equal(keep.focused, true);

    dialog.listeners.get("keydown")({
      key: "Tab",
      shiftKey: true,
      target: replace,
      preventDefault() {},
    });
    assert.equal(keep.focused, true);

    dialog.listeners.get("keydown")({
      key: "Escape",
      target: keep,
      preventDefault() {},
    });
    assert.equal(actions.at(-1).type, "chat/preset-replacement-kept");
  } finally {
    globalThis.document = originalDocument;
  }
});

test("manual Send of an unedited preset carries the complete audit quartet", () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new FakeElement(tag);
    },
  };
  try {
    const submitted = [];
    const preset = {
      id: "forecast_30_days",
      labels: { en: "Summarize the 30-day forecast", zh: "总结未来 30 天预测" },
      templates: { en: "Summarize the pinned 30-day forecast.", zh: "总结固定的未来 30 天预测。" },
      template_version: "2026-08-15.v1",
      template_sha256: { en: "e".repeat(64), zh: "f".repeat(64) },
      context_kind: "forecast",
      intent: "forecast_30_days",
      max_chars: 2000,
      available: true,
    };
    const root = new FakeElement("main");
    let state = {
      ...initialAskBizPulseState(
        { version_number: 2, dataset_version_id: "version-1" },
        "viewer",
      ),
      status: "ready",
      recommendedQuestions: [preset],
      context: { kind: "forecast", reference: "forecast:pinned" },
    };
    const options = {
      effects: { submit: (payload) => { submitted.push(payload); return Promise.resolve(); } },
      onShowForecast: () => {},
      onShowActions: () => {},
      language: "en",
      onStateAction(action, { render = true } = {}) {
        state = reduceAskBizPulse(state, action);
        if (render) renderAskBizPulse(root, state, options);
      },
    };
    renderAskBizPulse(root, state, options);

    descendants(root).find(
      (node) => node.tag === "button" && node.textContent === preset.labels.en,
    ).listeners.get("click")();
    const form = descendants(root).find((node) => node.tag === "form");
    form.listeners.get("submit")({ preventDefault() {} });

    assert.deepEqual(submitted, [{
      question: preset.templates.en,
      recommended_question_id: preset.id,
      prompt_locale: "en",
      prompt_template_version: preset.template_version,
      prompt_template_sha256: preset.template_sha256.en,
    }]);
  } finally {
    globalThis.document = originalDocument;
  }
});
