import { t } from "../../i18n/catalog.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function statusItem(language, labelKey, state, detail = null) {
  const item = element("li", "admin-status-item");
  item.append(
    element("span", "admin-status-label", t(language, labelKey)),
    element(
      "strong",
      `admin-status-value status-${state}`,
      t(language, `admin.status.value.${state}`),
    ),
  );
  if (detail) item.append(element("span", "status-note", detail));
  return item;
}

function safeCode(code) {
  return /^[A-Z][A-Z0-9_]{1,63}$/.test(code ?? "")
    ? code
    : "ADMIN_SUMMARY_UNAVAILABLE";
}

function refreshStatus(language, state) {
  const failed = state.status === "stale";
  const key = failed
    ? "admin.status.refreshFailed"
    : state.status === "refreshing"
      ? "admin.status.refreshing"
      : "admin.status.updated";
  const node = element(
    "p",
    failed ? "import-error admin-refresh-status" : "status-note admin-refresh-status",
    t(language, key, failed ? { code: safeCode(state.error) } : {}),
  );
  node.setAttribute("role", failed ? "alert" : "status");
  return node;
}

export function renderAdminStatus(root, state, { language = "en" } = {}) {
  if (state.status === "idle" || state.status === "loading") {
    const node = element("p", "admin-state-message", t(language, "admin.status.loading"));
    node.setAttribute("role", "status");
    root.replaceChildren(node);
    return;
  }
  if (state.status === "failed" || !state.payload) {
    const node = element(
      "p",
      "import-error admin-state-message",
      t(language, "admin.status.failed", { code: safeCode(state.error) }),
    );
    node.setAttribute("role", "alert");
    root.replaceChildren(node);
    return;
  }

  const system = state.payload.system ?? {};
  const ai = state.payload.ai ?? {};
  const aiReady = ai.status === "ready";
  const credential = ai.credential ?? {};
  const shell = element("section", "admin-status");
  if (state.status === "refreshing") shell.setAttribute("aria-busy", "true");
  shell.append(
    element("p", "eyebrow", t(language, "admin.status.eyebrow")),
    element("h2", "", t(language, "admin.status.title")),
    element("p", "admin-boundary", t(language, "admin.status.boundary")),
    refreshStatus(language, state),
  );
  const list = element("ul", "admin-status-list");
  list.append(
    statusItem(language, "admin.status.database", system.database === "ready" ? "ready" : "unavailable"),
    statusItem(language, "admin.status.blob", system.blob === "ready" ? "ready" : "unavailable"),
    statusItem(language, "admin.status.configuration", system.configuration === "valid" ? "valid" : "invalid"),
    statusItem(
      language,
      "admin.status.migration",
      system.migration ? "ready" : "unavailable",
      system.migration ?? t(language, "admin.common.unavailable"),
    ),
    statusItem(
      language,
      "admin.status.credential",
      !aiReady ? "unavailable" : credential.configured ? "verified" : "unconfigured",
      aiReady && credential.configured
        ? t(language, "admin.status.fingerprint", { fingerprint: credential.fingerprint })
        : null,
    ),
    statusItem(
      language,
      "admin.status.ai",
      ai.status === "ready" ? "ready" : "unavailable",
    ),
    statusItem(
      language,
      "admin.ai.operator",
      !aiReady ? "unavailable" : ai.operator_enabled ? "enabled" : "disabled",
    ),
    statusItem(
      language,
      "admin.ai.demo",
      !aiReady ? "unavailable" : ai.demo_enabled ? "enabled" : "disabled",
    ),
  );
  shell.append(list);
  root.replaceChildren(shell);
}
