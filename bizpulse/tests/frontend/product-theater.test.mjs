import assert from "node:assert/strict";
import { readFile, stat } from "node:fs/promises";
import { test } from "node:test";

import {
  PRODUCT_SLIDES,
  createProductTheater,
} from "../../frontend/assets/core/product-theater.mjs";

const frontendRoot = new URL("../../frontend/", import.meta.url);

function fakeScheduler() {
  let now = 0;
  let nextId = 1;
  const tasks = new Map();
  return {
    setTimeout(callback, delay) {
      const id = nextId++;
      tasks.set(id, { callback, due: now + delay });
      return id;
    },
    clearTimeout(id) {
      tasks.delete(id);
    },
    advance(milliseconds) {
      const target = now + milliseconds;
      while (true) {
        const pending = [...tasks.entries()]
          .filter(([, task]) => task.due <= target)
          .sort((left, right) => left[1].due - right[1].due)[0];
        if (!pending) break;
        const [id, task] = pending;
        tasks.delete(id);
        now = task.due;
        task.callback();
      }
      now = target;
    },
  };
}

function eventTarget(properties = {}) {
  const listeners = new Map();
  return {
    ...properties,
    addEventListener(name, callback) {
      const callbacks = listeners.get(name) ?? new Set();
      callbacks.add(callback);
      listeners.set(name, callbacks);
    },
    removeEventListener(name, callback) {
      listeners.get(name)?.delete(callback);
    },
    dispatch(name) {
      for (const callback of listeners.get(name) ?? []) callback();
    },
  };
}

function fakeNode(slideId = null) {
  return eventTarget({
    dataset: slideId ? { productSlide: slideId } : {},
    hidden: false,
    attributes: new Map(),
    setAttribute(name, value) {
      this.attributes.set(name, String(value));
    },
    removeAttribute(name) {
      this.attributes.delete(name);
    },
  });
}

function fakeRoot() {
  const slides = PRODUCT_SLIDES.map((id) => fakeNode(id));
  const dots = PRODUCT_SLIDES.map((id) => {
    const node = fakeNode();
    node.dataset.productDot = id;
    return node;
  });
  const previous = fakeNode();
  const next = fakeNode();
  return eventTarget({
    dataset: {},
    slides,
    dots,
    querySelectorAll(selector) {
      if (selector === "[data-product-slide]") return slides;
      if (selector === "[data-product-dot]") return dots;
      return [];
    },
    querySelector(selector) {
      if (selector === "[data-product-previous]") return previous;
      if (selector === "[data-product-next]") return next;
      return null;
    },
  });
}

function visibleDocument() {
  return eventTarget({ hidden: false });
}

function motionAllowedWindow() {
  return { matchMedia: () => ({ matches: false }) };
}

function reducedMotionWindow() {
  return { matchMedia: () => ({ matches: true }) };
}

test("theater advances every six seconds and manual navigation resets time", () => {
  const scheduler = fakeScheduler();
  const controller = createProductTheater(fakeRoot(), {
    intervalMs: 6000,
    documentRef: visibleDocument(),
    windowRef: motionAllowedWindow(),
    scheduler,
  });

  scheduler.advance(5999);
  assert.equal(controller.currentIndex(), 0);
  scheduler.advance(1);
  assert.equal(controller.currentIndex(), 1);
  controller.goTo(3);
  scheduler.advance(5999);
  assert.equal(controller.currentIndex(), 3);
  scheduler.advance(1);
  assert.equal(controller.currentIndex(), 0);
});

test("reduced motion keeps the first useful static slide", () => {
  const controller = createProductTheater(fakeRoot(), {
    documentRef: visibleDocument(),
    windowRef: reducedMotionWindow(),
    scheduler: fakeScheduler(),
  });

  assert.equal(controller.currentIndex(), 0);
  assert.equal(controller.autoplayEnabled(), false);
});

test("pause reasons and document visibility control autoplay", () => {
  const scheduler = fakeScheduler();
  const documentRef = visibleDocument();
  const controller = createProductTheater(fakeRoot(), {
    documentRef,
    windowRef: motionAllowedWindow(),
    scheduler,
  });

  controller.pause("focus");
  scheduler.advance(12000);
  assert.equal(controller.currentIndex(), 0);
  controller.resume("focus");
  scheduler.advance(6000);
  assert.equal(controller.currentIndex(), 1);
  documentRef.hidden = true;
  documentRef.dispatch("visibilitychange");
  scheduler.advance(12000);
  assert.equal(controller.currentIndex(), 1);
});

test("both entry shells use the same four local product assets", async () => {
  for (const shell of ["welcome.html", "login.html"]) {
    const html = await readFile(new URL(shell, frontendRoot), "utf8");
    const assets = [...html.matchAll(/src="(\/assets\/product-theater\/[^"]+\.svg)"/g)]
      .map((match) => match[1]);
    assert.deepEqual(assets, [
      "/assets/product-theater/overview.svg",
      "/assets/product-theater/profit-bridge.svg",
      "/assets/product-theater/inventory-forecast.svg",
      "/assets/product-theater/ask-bizpulse.svg",
    ]);
    assert.doesNotMatch(html, /(?:src|href)="https?:\/\//i);
  }

  for (const asset of [
    "overview.svg",
    "profit-bridge.svg",
    "inventory-forecast.svg",
    "ask-bizpulse.svg",
  ]) {
    const path = new URL(`assets/product-theater/${asset}`, frontendRoot);
    assert.ok((await stat(path)).size > 0);
    const source = await readFile(path, "utf8");
    const withoutNamespace = source.replace(
      'xmlns="http://www.w3.org/2000/svg"',
      "",
    );
    assert.doesNotMatch(withoutNamespace, /<(?:script|image)\b|https?:\/\//i);
  }
});

test("welcome and login initialize the shared controller", async () => {
  for (const sourcePath of ["assets/welcome.mjs", "assets/login.mjs"]) {
    const source = await readFile(new URL(sourcePath, frontendRoot), "utf8");
    assert.match(source, /createProductTheater/);
    assert.match(source, /querySelector\("\[data-product-theater\]"\)/);
  }
});
