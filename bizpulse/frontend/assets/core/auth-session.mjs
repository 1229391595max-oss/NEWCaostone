export function csrfToken() {
  return globalThis.sessionStorage?.getItem("bp_csrf_token") ?? "";
}

export function mutationHeaders(extra = {}) {
  return {
    ...extra,
    "X-CSRF-Token": csrfToken(),
  };
}

export function demoMutationHeaders(extra = {}) {
  return {
    ...extra,
    "X-CSRF-Token": globalThis.sessionStorage?.getItem("bp_demo_csrf_token") ?? "",
  };
}

export function storeViewerCsrf(token) {
  if (typeof token !== "string" || token.length < 1) {
    throw new Error("CSRF_TOKEN_INVALID");
  }
  globalThis.sessionStorage?.setItem("bp_demo_csrf_token", token);
}
