import { t } from "../../i18n/catalog.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function secretInput(id, field, autocomplete, labelText) {
  const wrapper = element("label", "admin-ai-secret-field", labelText);
  wrapper.setAttribute("for", id);
  const input = element("input", "admin-secret-input");
  input.id = id;
  input.type = "password";
  input.autocomplete = autocomplete;
  input.required = true;
  input.spellcheck = false;
  input.setAttribute("autocapitalize", "none");
  input.setAttribute("data-admin-ai-secret", field);
  wrapper.append(input);
  return { wrapper, input };
}

function actionButton(action, text) {
  const button = element("button", "secondary-button", text);
  button.type = "button";
  button.setAttribute("data-admin-ai-action", action);
  return button;
}

function message(language, state) {
  let key = "admin.ai.ready";
  if (state.error && state.notice) key = `admin.ai.notice.${state.notice}`;
  else if (state.operation === "rotation") key = "admin.ai.validating";
  else if (state.operation === "channels") key = "admin.ai.savingChannels";
  else if (state.notice) key = `admin.ai.notice.${state.notice}`;
  const node = element(
    "p",
    state.error ? "import-error admin-state-message" : "status-note admin-state-message",
    t(language, key, state.error ? { code: state.error } : {}),
  );
  node.setAttribute("data-admin-ai-status", "message");
  node.setAttribute("role", state.error ? "alert" : "status");
  node.setAttribute("aria-live", state.error ? "assertive" : "polite");
  return node;
}

function credentialDescription(language, credential) {
  if (!credential.configured) return t(language, "admin.ai.credentialUnconfigured");
  return t(language, "admin.ai.credentialVerified", {
    fingerprint: credential.fingerprint,
    date: new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-US", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "UTC",
    }).format(new Date(credential.verified_at)),
  });
}

function channelCard(language, action, enabled) {
  const card = element("article", "admin-metric-card admin-ai-channel");
  const title = element("h3", "", t(language, `admin.ai.${action}`));
  const state = element(
    "p",
    enabled ? "admin-status-value status-enabled" : "admin-status-value status-disabled",
    t(language, enabled ? "admin.status.value.enabled" : "admin.status.value.disabled"),
  );
  const button = actionButton(
    action,
    t(language, enabled ? "admin.ai.disable" : "admin.ai.enable"),
  );
  button.setAttribute("aria-pressed", String(enabled));
  button.setAttribute("aria-label", `${button.textContent}: ${title.textContent}`);
  card.append(title, state, button);
  return { card, button };
}

export function renderAdminAI(root, state, { language = "en", effects } = {}) {
  if (state.status === "idle" || state.status === "loading") {
    const loading = element("p", "admin-state-message", t(language, "admin.ai.loading"));
    loading.setAttribute("role", "status");
    root.replaceChildren(loading);
    return { clearSecrets() {}, focusAction() { return false; } };
  }
  if (state.status === "failed" || !state.payload) {
    const failed = element(
      "p",
      "import-error admin-state-message",
      t(language, "admin.ai.failed", { code: state.error ?? "ADMIN_AI_SECRET_UNAVAILABLE" }),
    );
    failed.setAttribute("role", "alert");
    root.replaceChildren(failed);
    return { clearSecrets() {}, focusAction() { return false; } };
  }

  const { payload } = state;
  const busy = state.operation !== null || state.status === "refreshing";
  const shell = element("section", "admin-overview admin-ai-management");
  if (busy || state.status === "refreshing") shell.setAttribute("aria-busy", "true");
  shell.append(
    element("p", "eyebrow", t(language, "admin.ai.eyebrow")),
    element("h2", "", t(language, "admin.nav.ai")),
    element("p", "admin-boundary", t(language, "admin.ai.sharedBinding")),
    message(language, state),
  );
  if (state.refreshError) {
    const refreshFailure = element(
      "p",
      "import-error admin-state-message",
      t(language, "admin.ai.refreshFailed", { code: state.refreshError }),
    );
    refreshFailure.setAttribute("role", "alert");
    shell.append(refreshFailure);
  }

  const credential = element("section", "admin-activity admin-ai-credential");
  credential.append(
    element("h3", "", t(language, "admin.status.credential")),
    element("p", "status-note", credentialDescription(language, payload.credential)),
  );

  const currentPassword = secretInput(
    "admin-ai-current-password",
    "currentPassword",
    "current-password",
    t(language, "admin.ai.currentPassword"),
  );
  credential.append(currentPassword.wrapper);

  const channels = element("div", "admin-metric-grid admin-ai-channels");
  const operator = channelCard(language, "operator", payload.operator_enabled);
  const demo = channelCard(language, "demo", payload.demo_enabled);
  const credentialMissing = !payload.credential.configured;
  operator.button.disabled = busy || (!payload.operator_enabled && credentialMissing);
  demo.button.disabled = busy || (!payload.demo_enabled && credentialMissing);
  channels.append(operator.card, demo.card);
  credential.append(channels);

  const rotation = element("section", "admin-activity admin-ai-rotation");
  rotation.append(
    element("h3", "", t(language, "admin.ai.rotationTitle")),
    element("p", "admin-boundary", t(language, "admin.ai.rotationBoundary")),
  );
  const candidate = secretInput(
    "admin-ai-candidate-key",
    "candidateKey",
    "off",
    t(language, "admin.ai.candidateKey"),
  );
  const rotateButton = actionButton("rotate", t(language, "admin.ai.rotate"));
  rotateButton.className = "primary-button";
  rotateButton.disabled = busy;
  rotation.append(candidate.wrapper, rotateButton);

  const clearSecrets = () => {
    candidate.input.value = "";
    currentPassword.input.value = "";
  };
  const validate = (...inputs) => {
    const missing = inputs.find((input) => input.value.length === 0);
    if (!missing) return true;
    clearSecrets();
    missing.setAttribute("aria-invalid", "true");
    missing.focus();
    missing.reportValidity?.();
    return false;
  };
  const submitChannels = async (operatorEnabled, demoEnabled) => {
    if (!validate(currentPassword.input)) return;
    try {
      await effects.setChannels({
        operatorEnabled,
        demoEnabled,
        currentPassword: currentPassword.input.value,
        expectedRevision: payload.revision,
      });
    } finally {
      clearSecrets();
    }
  };
  operator.button.addEventListener("click", () => submitChannels(
    !payload.operator_enabled,
    payload.demo_enabled,
  ));
  demo.button.addEventListener("click", () => submitChannels(
    payload.operator_enabled,
    !payload.demo_enabled,
  ));
  rotateButton.addEventListener("click", async () => {
    if (!validate(currentPassword.input, candidate.input)) return;
    try {
      await effects.rotate({
        candidateKey: candidate.input.value,
        currentPassword: currentPassword.input.value,
        expectedRevision: payload.revision,
      });
    } finally {
      clearSecrets();
    }
  });

  shell.append(credential, rotation);
  root.replaceChildren(shell);
  const focusAction = (action) => {
    const target = { operator: operator.button, demo: demo.button, rotate: rotateButton }[action];
    if (!target || target.disabled) return false;
    target.focus();
    return true;
  };
  return { clearSecrets, focusAction };
}
