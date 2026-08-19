import assert from "node:assert/strict";
import { test } from "node:test";

import {
  openEvidenceDrawer,
  toEvidenceDrawerModel,
} from "../../frontend/assets/core/evidence-drawer.mjs";
import {
  createDisclosure,
  visibleItems,
} from "../../frontend/assets/core/disclosure.mjs";

test("evidence disclosure defaults to four without truncating its source", () => {
  const source = Array.from({ length: 7 }, (_value, index) => `evidence-${index}`);
  const disclosure = createDisclosure({ itemCount: source.length, collapsedCount: 4 });

  assert.deepEqual(visibleItems(source, disclosure.expanded, 4), source.slice(0, 4));
  assert.deepEqual(disclosure.visibleIndexes(), [0, 1, 2, 3]);
  disclosure.expand();
  assert.deepEqual(visibleItems(source, disclosure.expanded, 4), source);
  disclosure.collapse();
  assert.equal(disclosure.totalCount, 7);
  assert.deepEqual(disclosure.visibleIndexes(), [0, 1, 2, 3]);
});

test("evidence drawer keeps traceability fields and drops internal storage fields", () => {
  const model = toEvidenceDrawerModel({
    evidence_id: "evidence-1",
    alias: "sales.gross",
    evidence_state: "measured",
    formula: "sum(gross_sales_brl)",
    source_refs: ["daily_sales"],
    object_key: "must-not-render",
  });

  assert.deepEqual(model, {
    id: "evidence-1",
    alias: "sales.gross",
    state: "measured",
    formula: "sum(gross_sales_brl)",
    sources: ["daily_sales"],
  });
  assert.doesNotMatch(JSON.stringify(model), /object_key|must-not-render/);
});

test("invalid evidence states fail closed", () => {
  assert.throws(
    () =>
      toEvidenceDrawerModel({
        evidence_id: "evidence-1",
        alias: "sales.gross",
        evidence_state: "certain",
        formula: "sum",
        source_refs: [],
      }),
    /EVIDENCE_INVALID/,
  );
});

test("evidence drawer traps focus, closes with Escape, and restores its trigger", () => {
  const originalDocument = globalThis.document;
  const listeners = new Map();
  const bodyChildren = [];
  let documentRef;
  class FakeElement {
    constructor(tag) {
      this.tag = tag;
      this.children = [];
      this.dataset = {};
      this.attributes = new Map();
      this.removed = false;
    }

    append(...items) {
      this.children.push(...items);
    }

    setAttribute(name, value) {
      this.attributes.set(name, String(value));
    }

    addEventListener(name, handler) {
      listeners.set(`${this.tag}:${name}`, handler);
    }

    focus() {
      documentRef.activeElement = this;
    }

    remove() {
      this.removed = true;
    }
  }
  const trigger = new FakeElement("trigger");
  documentRef = {
    activeElement: trigger,
    documentElement: { lang: "en" },
    body: { append: (node) => bodyChildren.push(node) },
    createElement: (tag) => new FakeElement(tag),
    querySelector: () => null,
  };
  globalThis.document = documentRef;
  try {
    openEvidenceDrawer({
      evidence_id: "evidence-1",
      alias: "sales.gross",
      evidence_state: "measured",
      formula: "sum(gross_sales_brl)",
      source_refs: ["daily_sales"],
    });
    const drawer = bodyChildren[0];
    const close = drawer.children[0];
    assert.equal(documentRef.activeElement, close);
    let prevented = false;
    listeners.get("aside:keydown")({
      key: "Tab",
      preventDefault: () => { prevented = true; },
    });
    assert.equal(prevented, true);
    assert.equal(documentRef.activeElement, close);
    listeners.get("aside:keydown")({ key: "Escape", preventDefault() {} });
    assert.equal(drawer.removed, true);
    assert.equal(documentRef.activeElement, trigger);
  } finally {
    globalThis.document = originalDocument;
  }
});
