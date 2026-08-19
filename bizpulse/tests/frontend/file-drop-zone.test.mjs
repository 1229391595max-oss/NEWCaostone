import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bindFileDropZone,
  normalizeSelectedFiles,
} from "../../frontend/assets/core/file-drop-zone.mjs";

class FakeTarget {
  constructor() {
    this.listeners = new Map();
    this.clicked = 0;
    this.value = "selected";
  }

  addEventListener(name, handler) {
    this.listeners.set(name, handler);
  }

  removeEventListener(name) {
    this.listeners.delete(name);
  }

  click() {
    this.clicked += 1;
  }

  emit(name, event = {}) {
    this.listeners.get(name)?.({ preventDefault() {}, ...event });
  }
}

test("file selection reports metadata without reading payload bytes", () => {
  let reads = 0;
  const file = {
    name: "sales.csv",
    size: 10,
    type: "text/csv",
    text() { reads += 1; },
    arrayBuffer() { reads += 1; },
    stream() { reads += 1; },
  };

  const selected = normalizeSelectedFiles([file]);

  assert.equal(selected.length, 1);
  assert.equal(selected[0].file, file);
  assert.equal(selected[0].accepted, true);
  assert.equal(reads, 0);
});

test("custom drop zone handles keyboard click and drop without uploading", () => {
  const zone = new FakeTarget();
  const input = new FakeTarget();
  const selected = [];
  const cleanup = bindFileDropZone({
    zone,
    input,
    onFiles(files) { selected.push(files); },
  });
  const file = { name: "inventory.xlsx", size: 20, type: "" };

  zone.emit("keydown", { key: "Enter" });
  assert.equal(input.clicked, 1);
  zone.emit("drop", { dataTransfer: { files: [file] } });
  assert.equal(selected.length, 1);
  assert.equal(selected[0][0].file, file);
  assert.equal(input.value, "");

  cleanup();
  assert.equal(zone.listeners.size, 0);
  assert.equal(input.listeners.size, 0);
});
