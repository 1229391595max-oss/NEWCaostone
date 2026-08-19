import assert from "node:assert/strict";
import { test } from "node:test";

import { renderAdminAI } from "../../frontend/assets/features/admin-ai/view.mjs";

class TestElement {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.attributes = new Map();
    this.className = "";
    this.disabled = false;
    this.type = "";
    this.autocomplete = "";
    this.value = "";
    this._textContent = "";
    this.listeners = new Map();
    this.required = false;
  }

  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = [...children]; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  async click() { return this.listeners.get("click")?.({ preventDefault() {} }); }
  focus() { globalThis.document.activeElement = this; }
  reportValidity() { return !this.required || this.value.length > 0; }
  set textContent(value) { this._textContent = String(value); }
  get textContent() {
    return [this._textContent, ...this.children.map((child) => child?.textContent ?? String(child))].join(" ");
  }
}

function installDocument() {
  const original = globalThis.document;
  globalThis.document = {
    activeElement: null,
    createElement(tag) { return new TestElement(tag); },
  };
  return () => { globalThis.document = original; };
}

function walk(node) {
  return [node, ...node.children.flatMap((child) => child instanceof TestElement ? walk(child) : [])];
}

function byAttribute(root, name, value) {
  return walk(root).find((node) => node.attributes.get(name) === value);
}

function readyState(overrides = {}) {
  return {
    status: "ready",
    operation: null,
    notice: null,
    error: null,
    payload: {
      revision: 4,
      operator_enabled: true,
      demo_enabled: false,
      credential: {
        configured: true,
        fingerprint: "7fa2c91e",
        verified_at: "2026-08-18T12:00:00Z",
      },
    },
    ...overrides,
  };
}

test("view says one shared validated binding serves two independently controlled channels", () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    renderAdminAI(root, readyState(), { language: "en", effects: {} });

    assert.match(root.textContent, /one shared validated credential binding/i);
    assert.match(root.textContent, /independent/i);
    assert.match(root.textContent, /Ordinary Login AI/);
    assert.match(root.textContent, /Public Demo AI/);
    assert.match(root.textContent, /Verified fingerprint 7fa2c91e/);
    assert.doesNotMatch(root.textContent, /key.?vault|secret.?name|version|subscription|resource.?id/i);
  } finally {
    restore();
  }
});

test("secret inputs block generic autofill and are cleared after every outcome", async () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    let submitted;
    const handle = renderAdminAI(root, readyState(), {
      language: "en",
      effects: {
        async rotate(payload) {
          submitted = { ...payload };
          throw new Error("safe-test-failure");
        },
      },
    });
    const candidate = byAttribute(root, "data-admin-ai-secret", "candidateKey");
    const currentPassword = byAttribute(root, "data-admin-ai-secret", "currentPassword");
    const rotate = byAttribute(root, "data-admin-ai-action", "rotate");

    assert.equal(candidate.type, "password");
    assert.equal(candidate.autocomplete, "off");
    assert.equal(currentPassword.type, "password");
    assert.equal(currentPassword.autocomplete, "current-password");
    candidate.value = "candidate-not-retained";
    currentPassword.value = "password-not-retained";
    await assert.rejects(rotate.click(), /safe-test-failure/);

    assert.equal(submitted.expectedRevision, 4);
    assert.equal(candidate.value, "");
    assert.equal(currentPassword.value, "");
    candidate.value = "route-leave-candidate";
    currentPassword.value = "route-leave-password";
    handle.clearSecrets();
    assert.equal(candidate.value, "");
    assert.equal(currentPassword.value, "");
  } finally {
    restore();
  }
});

test("independent channel buttons submit the unchanged sibling state", async () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    const submissions = [];
    renderAdminAI(root, readyState(), {
      language: "en",
      effects: {
        async setChannels(payload) { submissions.push(payload); },
      },
    });
    const password = byAttribute(root, "data-admin-ai-secret", "currentPassword");
    password.value = "current-password";
    await byAttribute(root, "data-admin-ai-action", "operator").click();
    password.value = "current-password";
    await byAttribute(root, "data-admin-ai-action", "demo").click();

    assert.deepEqual(submissions, [
      {
        operatorEnabled: false,
        demoEnabled: false,
        currentPassword: "current-password",
        expectedRevision: 4,
      },
      {
        operatorEnabled: true,
        demoEnabled: true,
        currentPassword: "current-password",
        expectedRevision: 4,
      },
    ]);
  } finally {
    restore();
  }
});

test("busy and conflict states disable controls and announce safe status accessibly", () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    renderAdminAI(root, readyState({
      operation: "rotation",
      notice: "conflict",
      error: "ADMIN_AI_STATE_CONFLICT",
    }), { language: "zh", effects: {} });

    const shell = root.children[0];
    const status = byAttribute(root, "data-admin-ai-status", "message");
    assert.equal(shell.attributes.get("aria-busy"), "true");
    assert.equal(status.attributes.get("role"), "alert");
    assert.match(status.textContent, /ADMIN_AI_STATE_CONFLICT/);
    for (const action of ["operator", "demo", "rotate"]) {
      assert.equal(byAttribute(root, "data-admin-ai-action", action).disabled, true);
    }
  } finally {
    restore();
  }
});

test("unconfigured credentials cannot enable either channel", () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    const state = readyState();
    state.payload.operator_enabled = false;
    state.payload.demo_enabled = false;
    state.payload.credential = { configured: false, fingerprint: null, verified_at: null };
    renderAdminAI(root, state, { language: "en", effects: {} });

    assert.equal(byAttribute(root, "data-admin-ai-action", "operator").disabled, true);
    assert.equal(byAttribute(root, "data-admin-ai-action", "demo").disabled, true);
    assert.equal(byAttribute(root, "data-admin-ai-action", "rotate").disabled, false);
    assert.match(root.textContent, /validate and replace/i);
  } finally {
    restore();
  }
});

test("refreshing is a deterministic busy state that disables every mutation", () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    renderAdminAI(root, readyState({ status: "refreshing" }), {
      language: "en",
      effects: {},
    });

    assert.equal(root.children[0].attributes.get("aria-busy"), "true");
    for (const action of ["operator", "demo", "rotate"]) {
      assert.equal(byAttribute(root, "data-admin-ai-action", action).disabled, true);
    }
  } finally {
    restore();
  }
});

test("view handle restores keyboard focus to the initiating action", () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    const handle = renderAdminAI(root, readyState(), { language: "en", effects: {} });

    assert.equal(handle.focusAction("demo"), true);
    assert.equal(globalThis.document.activeElement, byAttribute(root, "data-admin-ai-action", "demo"));
    assert.equal(handle.focusAction("unknown"), false);
  } finally {
    restore();
  }
});

test("empty confirmation fields do not submit and clear any adjacent secret", async () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    let calls = 0;
    renderAdminAI(root, readyState(), {
      language: "en",
      effects: {
        async rotate() { calls += 1; },
      },
    });
    const candidate = byAttribute(root, "data-admin-ai-secret", "candidateKey");
    const password = byAttribute(root, "data-admin-ai-secret", "currentPassword");
    candidate.value = "adjacent-secret";

    await byAttribute(root, "data-admin-ai-action", "rotate").click();

    assert.equal(calls, 0);
    assert.equal(candidate.value, "");
    assert.equal(password.value, "");
    assert.equal(globalThis.document.activeElement, password);
  } finally {
    restore();
  }
});
