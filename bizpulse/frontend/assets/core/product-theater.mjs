export const PRODUCT_SLIDES = Object.freeze([
  "overview",
  "profit_bridge",
  "inventory_forecast",
  "ask_bizpulse",
]);

function defaultScheduler() {
  return {
    setTimeout: globalThis.setTimeout.bind(globalThis),
    clearTimeout: globalThis.clearTimeout.bind(globalThis),
  };
}

export function createProductTheater(root, options = {}) {
  if (!root) throw new Error("PRODUCT_THEATER_ROOT_REQUIRED");
  const intervalMs = options.intervalMs ?? 6000;
  if (intervalMs !== 6000) throw new Error("PRODUCT_THEATER_INTERVAL_INVALID");
  const documentRef = options.documentRef ?? globalThis.document;
  const windowRef = options.windowRef ?? globalThis.window;
  const scheduler = options.scheduler ?? defaultScheduler();
  const slides = [...root.querySelectorAll("[data-product-slide]")];
  const dots = [...root.querySelectorAll("[data-product-dot]")];
  if (
    slides.length !== PRODUCT_SLIDES.length
    || slides.some((slide, index) => slide.dataset.productSlide !== PRODUCT_SLIDES[index])
  ) {
    throw new Error("PRODUCT_THEATER_SLIDES_INVALID");
  }

  const reducedMotion = Boolean(
    windowRef?.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches,
  );
  const pauseReasons = new Set();
  const listeners = [];
  let index = 0;
  let timer = null;
  let destroyed = false;

  function listen(target, event, callback) {
    if (!target?.addEventListener) return;
    target.addEventListener(event, callback);
    listeners.push(() => target.removeEventListener(event, callback));
  }

  function clearTimer() {
    if (timer !== null) scheduler.clearTimeout(timer);
    timer = null;
  }

  function autoplayEnabled() {
    return !reducedMotion;
  }

  function schedule() {
    clearTimer();
    if (destroyed || !autoplayEnabled() || pauseReasons.size > 0) return;
    timer = scheduler.setTimeout(() => {
      timer = null;
      goTo(index + 1);
    }, intervalMs);
  }

  function render() {
    root.dataset.productTheaterIndex = String(index);
    root.dataset.productTheaterSlide = PRODUCT_SLIDES[index];
    for (const [slideIndex, slide] of slides.entries()) {
      const active = slideIndex === index;
      slide.hidden = !active;
      slide.setAttribute("aria-hidden", String(!active));
    }
    for (const [dotIndex, dot] of dots.entries()) {
      if (dotIndex === index) dot.setAttribute("aria-current", "true");
      else dot.removeAttribute("aria-current");
    }
  }

  function goTo(nextIndex) {
    if (!Number.isInteger(nextIndex)) {
      throw new Error("PRODUCT_THEATER_INDEX_INVALID");
    }
    index = ((nextIndex % slides.length) + slides.length) % slides.length;
    render();
    schedule();
    return index;
  }

  function next() {
    return goTo(index + 1);
  }

  function previous() {
    return goTo(index - 1);
  }

  function pause(reason) {
    if (typeof reason !== "string" || !reason) {
      throw new Error("PRODUCT_THEATER_PAUSE_REASON_INVALID");
    }
    pauseReasons.add(reason);
    clearTimer();
  }

  function resume(reason) {
    pauseReasons.delete(reason);
    schedule();
  }

  function onVisibilityChange() {
    if (documentRef?.hidden) pause("document-hidden");
    else resume("document-hidden");
  }

  listen(root, "mouseenter", () => pause("hover"));
  listen(root, "mouseleave", () => resume("hover"));
  listen(root, "focusin", () => pause("focus-within"));
  listen(root, "focusout", () => resume("focus-within"));
  listen(documentRef, "visibilitychange", onVisibilityChange);
  listen(root.querySelector("[data-product-previous]"), "click", previous);
  listen(root.querySelector("[data-product-next]"), "click", next);
  for (const [dotIndex, dot] of dots.entries()) {
    listen(dot, "click", () => goTo(dotIndex));
  }
  if (documentRef?.hidden) pauseReasons.add("document-hidden");
  render();
  schedule();

  return Object.freeze({
    autoplayEnabled,
    currentIndex: () => index,
    destroy() {
      destroyed = true;
      clearTimer();
      for (const remove of listeners.splice(0)) remove();
    },
    goTo,
    next,
    pause,
    previous,
    resume,
  });
}
