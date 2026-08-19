import { t } from "../../i18n/catalog.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function safeDate(language, value) {
  const date = new Date(value ?? "");
  if (!Number.isFinite(date.getTime())) return t(language, "admin.common.unavailable");
  return new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(date);
}

function metric(label, value, description) {
  const card = element("article", "admin-metric-card");
  card.append(
    element("p", "metric-label", label),
    element("p", "metric-value", value),
    element("p", "metric-definition", description),
  );
  return card;
}

function loading(language) {
  const node = element("p", "admin-state-message", t(language, "admin.summary.loading"));
  node.setAttribute("role", "status");
  return node;
}

function failure(language, code) {
  const node = element(
    "p",
    "import-error admin-state-message",
    t(language, "admin.summary.failed", { code }),
  );
  node.setAttribute("role", "alert");
  return node;
}

function refreshStatus(language, state) {
  const failed = state.status === "stale";
  const key = failed
    ? "admin.summary.refreshFailed"
    : state.status === "refreshing"
      ? "admin.summary.refreshing"
      : "admin.summary.updated";
  const node = element(
    "p",
    failed ? "import-error admin-refresh-status" : "status-note admin-refresh-status",
    t(language, key, failed ? { code: state.error } : {}),
  );
  node.setAttribute("role", failed ? "alert" : "status");
  return node;
}

export function renderAdminOverview(root, state, { language = "en" } = {}) {
  if (state.status === "idle" || state.status === "loading") {
    root.replaceChildren(loading(language));
    return;
  }
  if (state.status === "failed" || !state.payload) {
    root.replaceChildren(failure(language, state.error ?? "ADMIN_SUMMARY_UNAVAILABLE"));
    return;
  }

  const payload = state.payload;
  const databaseReady = payload.system?.database === "ready";
  const aiReady = payload.ai?.status === "ready";
  const published = payload.published_dataset;
  const latestImport = payload.latest_import;
  const credential = payload.ai?.credential;
  const shell = element("section", "admin-overview");
  if (state.status === "refreshing") shell.setAttribute("aria-busy", "true");
  shell.append(
    element("p", "eyebrow", t(language, "admin.overview.eyebrow")),
    element("h2", "", t(language, "admin.overview.title")),
    refreshStatus(language, state),
  );

  const metrics = element("div", "admin-metric-grid");
  metrics.append(
    metric(
      t(language, "admin.overview.published"),
      !databaseReady
        ? t(language, "admin.common.unavailable")
        : published
        ? t(language, "admin.overview.version", { number: published.version_number })
        : t(language, "admin.overview.noPublished"),
      !databaseReady
        ? t(language, "admin.overview.databaseUnavailable")
        : published
        ? t(language, "admin.overview.released", {
          date: safeDate(language, published.released_at),
        })
        : t(language, "admin.overview.publishPending"),
    ),
    metric(
      t(language, "admin.overview.latestImport"),
      !databaseReady
        ? t(language, "admin.common.unavailable")
        : latestImport?.status ?? t(language, "admin.common.none"),
      !databaseReady
        ? t(language, "admin.overview.databaseUnavailable")
        : latestImport
        ? t(language, "admin.overview.importUpdated", {
          date: safeDate(language, latestImport.updated_at),
          code: latestImport.failure_code ?? t(language, "admin.common.none"),
        })
        : t(language, "admin.overview.noImport"),
    ),
    metric(
      t(language, "admin.overview.failures"),
      databaseReady && Number.isInteger(payload.actionable_failure_count)
        ? String(payload.actionable_failure_count)
        : t(language, "admin.common.unavailable"),
      databaseReady
        ? t(language, "admin.overview.failuresDefinition")
        : t(language, "admin.overview.databaseUnavailable"),
    ),
    metric(
      t(language, "admin.overview.credential"),
      !aiReady
        ? t(language, "admin.common.unavailable")
        : credential?.configured
        ? t(language, "admin.credential.verified")
        : t(language, "admin.credential.unconfigured"),
      !aiReady
        ? t(language, "admin.overview.aiUnavailable")
        : credential?.configured
        ? t(language, "admin.overview.credentialVerified", {
          date: safeDate(language, credential.verified_at),
        })
        : t(language, "admin.overview.credentialBoundary"),
    ),
  );
  shell.append(metrics);

  const activity = element("section", "admin-activity");
  activity.append(element("h3", "", t(language, "admin.overview.activity")));
  const list = element("ol", "admin-activity-list");
  const items = databaseReady && Array.isArray(payload.recent_activity)
    ? payload.recent_activity.slice(0, 10)
    : [];
  if (!items.length) {
    list.append(element(
      "li",
      "",
      databaseReady
        ? t(language, "admin.overview.noActivity")
        : t(language, "admin.common.unavailable"),
    ));
  }
  for (const item of items) {
    const kind = item.kind === "publish" ? "publish" : "import";
    list.append(
      element(
        "li",
        "admin-activity-item",
        t(language, `admin.activity.${kind}`, {
          status: item.status ?? t(language, "admin.common.unavailable"),
          date: safeDate(language, item.occurred_at),
        }),
      ),
    );
  }
  activity.append(list);
  shell.append(activity);
  root.replaceChildren(shell);
}
