import assert from "node:assert/strict";
import { test } from "node:test";

import {
  createAdminOverviewEffects,
} from "../../frontend/assets/features/admin-overview/effects.mjs";
import {
  initialAdminOverviewState,
  reduceAdminOverview,
} from "../../frontend/assets/features/admin-overview/state.mjs";
import {
  renderAdminOverview,
} from "../../frontend/assets/features/admin-overview/view.mjs";
import {
  initialAdminStatusState,
  reduceAdminStatus,
} from "../../frontend/assets/features/admin-status/state.mjs";
import {
  renderAdminStatus,
} from "../../frontend/assets/features/admin-status/view.mjs";
import {
  createAdminStatusEffects,
} from "../../frontend/assets/features/admin-status/effects.mjs";

class TestElement {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.attributes = new Map();
    this.className = "";
    this._textContent = "";
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

  set textContent(value) {
    this._textContent = String(value);
  }

  get textContent() {
    return [
      this._textContent,
      ...this.children.map((child) => child?.textContent ?? String(child)),
    ].join(" ");
  }
}

function installDocument() {
  const original = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new TestElement(tag);
    },
  };
  return () => {
    globalThis.document = original;
  };
}

function summaryFixture() {
  return {
    system: {
      database: "ready",
      blob: "unavailable",
      configuration: "valid",
      migration: "0017_ai_turn_credential_binding",
    },
    published_dataset: {
      dataset_version_id: "dataset-secret-looking-id-must-not-render",
      version_number: 7,
      released_at: "2026-08-18T12:00:00Z",
    },
    latest_import: {
      workflow_id: "workflow-secret-looking-id-must-not-render",
      status: "rejected",
      failure_code: "UPLOAD_INVALID",
      updated_at: "2026-08-18T11:00:00Z",
    },
    actionable_failure_count: 2,
    recent_activity: [
      { kind: "publish", status: "published", occurred_at: "2026-08-18T12:00:00Z" },
      { kind: "import", status: "rejected", occurred_at: "2026-08-18T11:00:00Z" },
    ],
    ai: {
      status: "ready",
      revision: 4,
      operator_enabled: true,
      demo_enabled: false,
      credential: {
        configured: true,
        fingerprint: "7fa2c91e",
        verified_at: "2026-08-18T10:00:00Z",
      },
    },
    unexpected_secret: "must-not-render",
  };
}

test("summary refresh is bounded to thirty seconds and does not overlap", async () => {
  let resolveLoad;
  let loadCount = 0;
  const actions = [];
  const interval = { callback: null, delay: null };
  const effects = createAdminOverviewEffects({
    dataSource: {
      loadSummary() {
        loadCount += 1;
        return new Promise((resolve) => { resolveLoad = resolve; });
      },
    },
    dispatch(action) { actions.push(action); },
    setInterval(callback, delay) {
      interval.callback = callback;
      interval.delay = delay;
      return 9;
    },
    clearInterval() {},
  });

  const first = effects.start();
  assert.equal(interval.delay, 30_000);
  const overlapping = effects.refresh();
  assert.equal(loadCount, 1);
  resolveLoad(summaryFixture());
  await Promise.all([first, overlapping]);

  assert.deepEqual(actions.map((action) => action.type), [
    "load/started",
    "load/succeeded",
  ]);
});

test("overview reducer keeps safe failure codes and rejects arbitrary messages", () => {
  let state = reduceAdminOverview(initialAdminOverviewState(), {
    type: "load/succeeded",
    payload: summaryFixture(),
  });
  assert.equal(state.status, "ready");
  assert.equal(state.payload.actionable_failure_count, 2);

  state = reduceAdminOverview(state, {
    type: "load/failed",
    code: "postgres-password-must-not-render",
  });
  assert.equal(state.status, "stale");
  assert.equal(state.error, "ADMIN_SUMMARY_UNAVAILABLE");
});

test("background refresh preserves the last safe summary and marks stale failures", () => {
  const ready = reduceAdminOverview(initialAdminOverviewState(), {
    type: "load/succeeded",
    payload: summaryFixture(),
  });
  const refreshing = reduceAdminOverview(ready, { type: "load/started" });
  const stale = reduceAdminOverview(refreshing, {
    type: "load/failed",
    code: "ADMIN_SUMMARY_UNAVAILABLE",
  });

  assert.equal(refreshing.status, "refreshing");
  assert.equal(refreshing.payload.published_dataset.version_number, 7);
  assert.equal(stale.status, "stale");
  assert.equal(stale.payload.published_dataset.version_number, 7);
});

test("overview renders cockpit cards and activity from allowlisted fields", () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    const state = reduceAdminOverview(initialAdminOverviewState(), {
      type: "load/succeeded",
      payload: summaryFixture(),
    });

    renderAdminOverview(root, state, { language: "en" });

    assert.match(root.textContent, /Published dataset/);
    assert.match(root.textContent, /Version 7/);
    assert.match(root.textContent, /Actionable failures/);
    assert.match(root.textContent, /UPLOAD_INVALID/);
    assert.match(root.textContent, /Recent activity/);
    assert.doesNotMatch(root.textContent, /must-not-render/);
    assert.equal(root.children[0].attributes.has("role"), false);
    assert.equal(root.children[0].children[2].attributes.get("role"), "status");
  } finally {
    restore();
  }
});

test("unavailable projections remain unavailable instead of becoming empty or zero", () => {
  const restore = installDocument();
  try {
    const unavailable = summaryFixture();
    unavailable.system.database = "unavailable";
    unavailable.published_dataset = null;
    unavailable.latest_import = null;
    unavailable.actionable_failure_count = null;
    unavailable.ai = {
      status: "unavailable",
      revision: null,
      operator_enabled: false,
      demo_enabled: false,
      credential: { configured: false, fingerprint: null, verified_at: null },
    };
    const overviewRoot = new TestElement();
    const statusRoot = new TestElement();
    const overviewState = reduceAdminOverview(initialAdminOverviewState(), {
      type: "load/succeeded",
      payload: unavailable,
    });
    const statusState = reduceAdminStatus(initialAdminStatusState(), {
      type: "load/succeeded",
      payload: unavailable,
    });

    renderAdminOverview(overviewRoot, overviewState, { language: "en" });
    renderAdminStatus(statusRoot, statusState, { language: "en" });

    assert.doesNotMatch(overviewRoot.textContent, /Not published|No import activity|\b0\b/);
    assert.match(overviewRoot.textContent, /Unavailable/);
    assert.doesNotMatch(statusRoot.textContent, /Unconfigured|Disabled/);
    assert.match(statusRoot.textContent, /AI controls Unavailable/);
    assert.match(statusRoot.textContent, /Ordinary Login AI Unavailable/);
    assert.match(statusRoot.textContent, /Public Demo AI Unavailable/);
  } finally {
    restore();
  }
});

test("overview failure and loading states are announced accessibly", () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    renderAdminOverview(root, initialAdminOverviewState(), { language: "zh" });
    assert.equal(root.children[0].attributes.get("role"), "status");

    renderAdminOverview(root, {
      status: "failed",
      payload: null,
      error: "ADMIN_SUMMARY_UNAVAILABLE",
    }, { language: "zh" });
    assert.equal(root.children[0].attributes.get("role"), "alert");
    assert.match(root.textContent, /ADMIN_SUMMARY_UNAVAILABLE/);
  } finally {
    restore();
  }
});

test("system status renders only safe application projections", () => {
  const restore = installDocument();
  try {
    const root = new TestElement();
    const state = reduceAdminStatus(initialAdminStatusState(), {
      type: "load/succeeded",
      payload: summaryFixture(),
    });

    renderAdminStatus(root, state, { language: "en" });

    assert.match(root.textContent, /Database/);
    assert.match(root.textContent, /Blob storage/);
    assert.match(root.textContent, /Configuration/);
    assert.match(root.textContent, /Migration/);
    assert.match(root.textContent, /AI controls/);
    assert.match(root.textContent, /Ordinary Login AI/);
    assert.match(root.textContent, /Public Demo AI/);
    assert.match(root.textContent, /7fa2c91e/);
    assert.doesNotMatch(root.textContent, /dataset-secret|workflow-secret|must-not-render/);
    assert.equal(root.children[0].attributes.has("role"), false);
    assert.equal(root.children[0].children[3].attributes.get("role"), "status");
  } finally {
    restore();
  }
});

test("system status uses the same bounded summary refresh contract", async () => {
  const actions = [];
  const interval = { delay: null };
  const effects = createAdminStatusEffects({
    dataSource: { async loadSummary() { return summaryFixture(); } },
    dispatch(action) { actions.push(action); },
    setInterval(_callback, delay) {
      interval.delay = delay;
      return 4;
    },
    clearInterval() {},
  });

  await effects.start();

  assert.equal(interval.delay, 30_000);
  assert.deepEqual(actions.map((action) => action.type), [
    "load/started",
    "load/succeeded",
  ]);
});
