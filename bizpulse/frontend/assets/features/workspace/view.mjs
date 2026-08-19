import {
  clearSourceFile,
  commitWorkflow,
  confirmMapping,
  createAndUpload,
  loadCommitPlan,
  loadPreview,
  newImportKeys,
  recognize,
  removeSourceFile,
  selectSourceFiles,
  standardize,
} from "./effects.mjs";
import { bindFileDropZone } from "../../core/file-drop-zone.mjs";
import { initialWorkspaceState, reduceWorkspace } from "./state.mjs";
import {
  toReleaseControlsModel,
  toWorkspaceViewModel,
} from "./view-model.mjs?v=20260814";
import { t } from "../../i18n/catalog.mjs";
import { createLibraryEffects } from "../library/effects.mjs";
import { initialLibraryState, reduceLibrary } from "../library/state.mjs";
import { renderLibrary } from "../library/view.mjs";
import { renderExports } from "../exports/view.mjs";
import {
  formatBrl,
  formatDecimal,
  formatInteger,
} from "../../core/formatters.mjs";

let state = initialWorkspaceState();
let importKeys = newImportKeys();
let releaseState = {
  status: "idle",
  versions: [],
  current: null,
  error: null,
  preparations: {},
};
let workspaceDataSource = null;
let workspaceIsActive = () => true;
let activeWorkspaceTab = "upload";
let libraryState = initialLibraryState("operator");
let libraryEffects = null;
let libraryScopeGeneration = null;
let workspaceGetScope = () => null;
const WORKSPACE_TABS = Object.freeze([
  ["upload", "workspace.tab.upload"],
  ["library", "workspace.tab.library"],
  ["exports", "workspace.tab.exports"],
]);

function currentLanguage() {
  return document.documentElement?.lang?.startsWith("zh") ? "zh" : "en";
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function dispatch(root, action) {
  state = reduceWorkspace(state, action);
  if (workspaceIsActive()) renderWorkspace(root);
}

async function run(root, operation, completedType) {
  dispatch(root, { type: "request/started" });
  try {
    const result = await operation();
    dispatch(root, { type: completedType, ...result });
    if (completedType === "commit/completed" && workspaceDataSource) {
      await loadReleaseControls(root, workspaceDataSource);
    }
  } catch (error) {
    dispatch(root, { type: "request/failed", code: error.message });
  }
}

function stageList(model) {
  const language = currentLanguage();
  const list = element("ol", "import-stages");
  const current = model.stages.indexOf(model.phase);
  for (const [index, stage] of model.stages.entries()) {
    const item = element(
      "li",
      "import-stage",
      `${index + 1}. ${t(language, `workspace.stage.${stage}`)}`,
    );
    if (index === current) item.setAttribute("aria-current", "step");
    if (index < current) item.dataset.complete = "true";
    list.append(item);
  }
  return list;
}

async function uploadQueuedFiles(root) {
  const pending = state.queue.filter((item) =>
    ["ready", "failed"].includes(item.status),
  );
  if (!pending.length) return;
  dispatch(root, { type: "request/started" });
  let workflow = state.workflow;
  for (const item of pending) {
    dispatch(root, { type: "queue/item-uploading", localKey: item.localKey });
    const keys = newImportKeys();
    try {
      const result = await createAndUpload(keys, workflow, item.localKey);
      workflow = result.workflow;
      dispatch(root, {
        type: "queue/item-uploaded",
        localKey: item.localKey,
        ...result,
      });
    } catch (error) {
      dispatch(root, {
        type: "queue/item-failed",
        localKey: item.localKey,
        code: error.message,
      });
    }
  }
  dispatch(root, { type: "queue/finished" });
}

function renderSourceQueue(root, card) {
  const language = currentLanguage();
  const input = document.createElement("input");
  input.type = "file";
  input.accept = ".csv,.xlsx";
  input.multiple = true;
  input.hidden = true;
  const zone = element("div", "operator-drop-zone");
  zone.tabIndex = 0;
  zone.setAttribute("role", "button");
  zone.setAttribute("aria-label", t(language, "workspace.dropFiles"));
  zone.append(
    element("strong", "", t(language, "workspace.dropFiles")),
    element("span", "status-note", t(language, "workspace.acceptedFiles")),
  );
  bindFileDropZone({
    zone,
    input,
    onFiles: (items) => {
      const descriptors = selectSourceFiles(items);
      importKeys = newImportKeys();
      dispatch(root, { type: "queue/added", items: descriptors });
    },
    onState: (status) => {
      zone.dataset.state = status;
    },
  });

  const list = element("ul", "operator-upload-queue");
  for (const item of state.queue) {
    const row = element("li", "operator-upload-item");
    const details = element("div", "");
    details.append(
      element("strong", "", item.name),
      element(
        "span",
        "status-note",
        t(language, `workspace.queue.${item.status}`),
      ),
    );
    const remove = actionButton(
      t(language, "workspace.removeFile"),
      () => {
        removeSourceFile(item.localKey);
        dispatch(root, { type: "queue/item-removed", localKey: item.localKey });
      },
      item.status === "uploading" || item.status === "uploaded",
    );
    remove.className = "secondary-button compact-button";
    row.append(details, remove);
    list.append(row);
  }
  const canUpload = state.queue.some((item) =>
    ["ready", "failed"].includes(item.status),
  );
  card.append(
    input,
    zone,
    list,
    actionButton(
      state.queue.some((item) => item.status === "failed")
        ? t(language, "workspace.retryFiles")
        : t(language, "workspace.uploadFiles"),
      () => uploadQueuedFiles(root),
      state.busy || !canUpload,
    ),
  );
}

function actionButton(label, handler, disabled = false) {
  const button = element("button", "primary-button", label);
  button.type = "button";
  button.disabled = disabled;
  button.addEventListener("click", handler);
  return button;
}

function renderWorkspaceTabs(root, dataSource, language) {
  const tabs = element("div", "workspace-tabs");
  tabs.setAttribute("role", "tablist");
  for (const [name, labelKey] of WORKSPACE_TABS) {
    const button = element(
      "button",
      "workspace-tab",
      t(language, labelKey),
    );
    button.type = "button";
    button.setAttribute("role", "tab");
    button.setAttribute("aria-selected", String(activeWorkspaceTab === name));
    button.addEventListener("click", () => {
      activeWorkspaceTab = name;
      renderWorkspace(root, dataSource);
    });
    tabs.append(button);
  }
  root.append(tabs);
}

function ensureLibraryEffects(root, dataSource) {
  const scopeGeneration = workspaceGetScope()?.generation ?? null;
  if (
    libraryEffects
    && workspaceDataSource === dataSource
    && libraryScopeGeneration === scopeGeneration
  ) return libraryEffects;
  libraryEffects?.invalidate?.();
  libraryState = initialLibraryState("operator");
  libraryScopeGeneration = scopeGeneration;
  libraryEffects = createLibraryEffects({
    dataSource,
    mode: "operator",
    getScope: workspaceGetScope,
    dispatch(action) {
      libraryState = reduceLibrary(libraryState, action);
      if (
        workspaceIsActive()
        && ["library", "exports"].includes(activeWorkspaceTab)
      ) {
        renderWorkspace(root, dataSource);
      }
    },
  });
  return libraryEffects;
}

function detailPre(value) {
  const pre = element("pre", "import-detail");
  pre.textContent = JSON.stringify(value, null, 2);
  return pre;
}

function readableField(value) {
  return String(value ?? "").replaceAll("_", " ");
}

function previewValue(field, value, language) {
  if (value === null || value === undefined || value === "") return "—";
  if (field.endsWith("_brl")) return formatBrl(value, language);
  if (typeof value === "number") return formatDecimal(value, language);
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function renderPreview(records, language) {
  const rows = Array.isArray(records) ? records : [];
  const section = element("section", "import-preview");
  section.append(element("h3", "", t(language, "workspace.previewTable")));
  if (!rows.length) {
    section.append(
      element("p", "status-note", t(language, "workspace.noPreviewRows")),
    );
    return section;
  }
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  const scroll = element("div", "import-table-scroll");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", t(language, "workspace.previewTable"));
  const table = element("table", "import-data-table import-preview-table");
  const head = element("thead");
  const heading = element("tr");
  for (const column of columns) {
    heading.append(element("th", "", readableField(column)));
  }
  head.append(heading);
  const body = element("tbody");
  for (const row of rows) {
    const tr = element("tr");
    for (const column of columns) {
      tr.append(element("td", "", previewValue(column, row[column], language)));
    }
    body.append(tr);
  }
  table.append(head, body);
  scroll.append(table);
  section.append(scroll);
  return section;
}

function metric(label, value, language) {
  const item = element("div", "import-quality-metric");
  item.append(
    element("dt", "", label),
    element("dd", "", formatInteger(value ?? 0, language)),
  );
  return item;
}

function sourceOrigin(origin, language) {
  const parts = [origin?.source_name, origin?.sheet_name].filter(Boolean);
  if (origin?.row_number !== null && origin?.row_number !== undefined) {
    parts.push(
      t(language, "workspace.rowNumber", {
        row: formatInteger(origin.row_number, language),
      }),
    );
  }
  return parts.join(" · ") || "—";
}

function businessKeyLabel(entries) {
  return (Array.isArray(entries) ? entries : [])
    .map(([field, value]) => `${readableField(field)}=${value}`)
    .join(" · ");
}

function renderDedupeSummary(language) {
  const summary = state.dedupe ?? {};
  const section = element("section", "import-dedupe-summary");
  section.append(element("h3", "", t(language, "workspace.importQuality")));
  const totals = element("dl", "import-quality-metrics");
  totals.append(
    metric(t(language, "workspace.rowsRead"), summary.rows_read, language),
    metric(t(language, "workspace.rowsRetained"), summary.rows_retained, language),
    metric(
      t(language, "workspace.duplicatesRemoved"),
      summary.duplicates_removed,
      language,
    ),
    metric(t(language, "workspace.conflicts"), summary.conflicts, language),
  );
  section.append(totals);

  const roles = Object.entries(summary.per_role ?? {}).sort(([left], [right]) =>
    left.localeCompare(right),
  );
  if (roles.length) {
    const scroll = element("div", "import-table-scroll");
    scroll.tabIndex = 0;
    scroll.setAttribute("role", "region");
    scroll.setAttribute("aria-label", t(language, "workspace.importQuality"));
    const table = element("table", "import-data-table import-dedupe-role-table");
    const head = element("thead");
    const heading = element("tr");
    for (const key of [
      "workspace.table",
      "workspace.rowsRead",
      "workspace.rowsRetained",
      "workspace.duplicatesRemoved",
      "workspace.conflicts",
    ]) {
      heading.append(element("th", "", t(language, key)));
    }
    head.append(heading);
    const body = element("tbody");
    for (const [role, values] of roles) {
      const row = element("tr");
      row.append(
        element("th", "", readableField(role)),
        element("td", "", formatInteger(values.rows_read, language)),
        element("td", "", formatInteger(values.rows_retained, language)),
        element("td", "", formatInteger(values.duplicates_removed, language)),
        element("td", "", formatInteger(values.conflicts, language)),
      );
      body.append(row);
    }
    table.append(head, body);
    scroll.append(table);
    section.append(scroll);
  }
  return section;
}

function renderConflicts(language) {
  if (!state.conflicts.length) return null;
  const section = element("section", "import-conflicts");
  const notice = element(
    "p",
    "import-error",
    t(language, "workspace.commitBlockedByConflicts"),
  );
  notice.setAttribute("role", "alert");
  section.append(notice);
  const download = element(
    "a",
    "secondary-button",
    t(language, "workspace.downloadConflicts"),
  );
  const workflowId = state.workflow?.id ?? state.commitPlan?.workflow_id;
  download.href = state.commitPlan?.conflict_download_url
    ?? workspaceDataSource?.conflictDownloadUrl(workflowId);
  download.setAttribute("download", "");
  section.append(download);
  if (state.commitPlan?.conflicts_truncated) {
    section.append(
      element(
        "p",
        "status-note",
        t(language, "workspace.conflictPreview", {
          count: formatInteger(state.conflicts.length, language),
        }),
      ),
    );
  }
  const scroll = element("div", "import-table-scroll");
  scroll.tabIndex = 0;
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", t(language, "workspace.conflicts"));
  const table = element("table", "import-data-table import-conflict-table");
  const head = element("thead");
  const heading = element("tr");
  for (const key of [
    "workspace.table",
    "workspace.businessKey",
    "workspace.conflictFields",
    "workspace.existingSource",
    "workspace.incomingSource",
  ]) {
    heading.append(element("th", "", t(language, key)));
  }
  head.append(heading);
  const body = element("tbody");
  for (const conflict of state.conflicts.slice(0, 50)) {
    const row = element("tr");
    row.append(
      element("td", "", readableField(conflict.role)),
      element("td", "", businessKeyLabel(conflict.business_key)),
      element("td", "", (conflict.fields ?? []).map(readableField).join(", ")),
      element("td", "", sourceOrigin(conflict.existing, language)),
      element("td", "", sourceOrigin(conflict.incoming, language)),
    );
    body.append(row);
  }
  table.append(head, body);
  scroll.append(table);
  section.append(scroll);
  return section;
}

function renderAction(root, card) {
  const language = currentLanguage();
  if (state.phase === "source") {
    renderSourceQueue(root, card);
    return;
  }
  if (state.phase === "recognition") {
    card.append(
      actionButton(
        t(language, "workspace.recognizeSource"),
        () =>
          run(
            root,
            () => recognize(state.workflow, state.upload),
            "recognition/completed",
          ),
        state.busy,
      ),
    );
    return;
  }
  if (state.phase === "mapping") {
    card.append(detailPre(state.upload.recognition));
    card.append(
      actionButton(
        t(language, "workspace.confirmMapping"),
        async () => {
          dispatch(root, { type: "request/started" });
          try {
            const mapped = await confirmMapping(state.workflow, state.upload);
            const quality = await standardize(mapped.workflow, mapped.upload);
            dispatch(root, { type: "quality/completed", ...quality });
          } catch (error) {
            dispatch(root, { type: "request/failed", code: error.message });
          }
        },
        state.busy,
      ),
    );
    return;
  }
  if (state.phase === "quality") {
    card.append(detailPre(state.upload.quality_report));
    card.append(
      actionButton(
        t(language, "workspace.loadPreview"),
        () =>
          run(
            root,
            () => loadPreview(state.workflow, state.upload),
            "preview/completed",
          ),
        state.busy,
      ),
    );
    return;
  }
  if (state.phase === "preview") {
    card.append(renderPreview(state.preview.records, language));
    const actions = element("div", "button-row");
    const nextUpload = state.uploads.find((item) => item.status === "staged");
    const addSource = actionButton(
      nextUpload
        ? t(currentLanguage(), "workspace.processNext")
        : t(currentLanguage(), "workspace.addFiles"),
      () => {
        if (nextUpload) dispatch(root, { type: "source/next" });
        else {
          clearSourceFile();
          importKeys = newImportKeys();
          dispatch(root, { type: "source/add" });
        }
      },
    );
    addSource.className = "secondary-button";
    actions.append(
      addSource,
      actionButton(
        t(language, "workspace.prepareCommit"),
        () =>
          run(
            root,
            () => loadCommitPlan(state.workflow),
            "commit/planned",
          ),
        state.busy,
      ),
    );
    card.append(actions);
    return;
  }
  if (state.committed) {
    card.append(detailPre(state.committed));
    const reset = actionButton(t(language, "workspace.importAnother"), () => {
      clearSourceFile();
      importKeys = newImportKeys();
      dispatch(root, { type: "workflow/reset" });
    });
    reset.className = "secondary-button";
    card.append(reset);
    return;
  }
  card.append(renderDedupeSummary(language));
  const conflicts = renderConflicts(language);
  if (conflicts) card.append(conflicts);
  card.append(
    actionButton(
      t(language, "workspace.commitDataset"),
      () =>
        run(
          root,
          () => commitWorkflow(state.workflow, importKeys.commit),
          "commit/completed",
        ),
      state.busy || !state.commitPlan?.ready || state.conflicts.length > 0,
    ),
  );
}

async function loadReleaseControls(root, dataSource) {
  releaseState = { ...releaseState, status: "loading", error: null };
  if (workspaceIsActive()) renderWorkspace(root, dataSource);
  try {
    const [versions, current] = await Promise.all([
      dataSource.listVersions(),
      dataSource.loadRelease(),
    ]);
    releaseState = {
      status: "ready",
      versions: versions.versions,
      current,
      error: null,
      preparations: releaseState.preparations,
    };
  } catch (error) {
    releaseState = {
      ...releaseState,
      status: "error",
      error: error.code ?? error.message ?? "RELEASES_UNAVAILABLE",
    };
  }
  if (workspaceIsActive()) renderWorkspace(root, dataSource);
}

async function publishVersion(root, dataSource, versionId) {
  const expectedCurrentId = releaseState.current?.dataset_version_id ?? null;
  releaseState = { ...releaseState, status: "publishing", error: null };
  if (workspaceIsActive()) renderWorkspace(root, dataSource);
  try {
    await dataSource.publish(
      versionId,
      expectedCurrentId,
      `publish-${globalThis.crypto.randomUUID()}`,
    );
    const [versions, current] = await Promise.all([
      dataSource.listVersions(),
      dataSource.loadRelease(),
    ]);
    releaseState = {
      status: "ready",
      versions: versions.versions,
      current,
      error: null,
      preparations: releaseState.preparations,
    };
    globalThis.location?.reload?.();
  } catch (error) {
    releaseState = {
      ...releaseState,
      status: "error",
      error: error.code ?? error.message ?? "PUBLISH_FAILED",
    };
  }
  if (workspaceIsActive()) renderWorkspace(root, dataSource);
}

async function prepareVersion(root, dataSource, versionId) {
  releaseState = { ...releaseState, status: "preparing", error: null };
  if (workspaceIsActive()) renderWorkspace(root, dataSource);
  try {
    const bound = dataSource.forVersion(versionId);
    const preparation = await bound.prepare();
    releaseState = {
      ...releaseState,
      status: "ready",
      preparations: {
        ...releaseState.preparations,
        [versionId]: preparation,
      },
    };
  } catch (error) {
    releaseState = {
      ...releaseState,
      status: "error",
      error: error.code ?? error.message ?? "CALCULATION_FAILED",
    };
  }
  if (workspaceIsActive()) renderWorkspace(root, dataSource);
}

function renderReleaseControls(root, dataSource) {
  const model = toReleaseControlsModel(releaseState);
  const language = currentLanguage();
  const shell = element("section", "release-controls");
  shell.append(
    element("p", "eyebrow", t(language, "workspace.publicData")),
    element(
      "h2",
      "",
      model.currentVersion
        ? t(language, "workspace.currentData")
        : t(language, "workspace.noPublishedData"),
    ),
  );
  if (model.status === "loading") {
    shell.setAttribute("aria-busy", "true");
    shell.append(element("p", "", t(language, "workspace.loadingData")));
  } else {
    const list = element("ul", "release-version-list");
    for (const version of model.versions) {
      const item = element("li", "release-version-card");
      item.dataset.versionId = version.id;
      item.append(
        element(
          "p",
          "release-version-title",
          t(
            language,
            version.isCurrent
              ? "workspace.currentDataset"
              : "workspace.preparedDataset",
          ),
        ),
        element(
          "p",
          "status-note",
          t(language, "workspace.dataStatus", { status: version.status }),
        ),
      );
      const preparation = version.preparation;
      if (preparation) {
        const domains = element("ul", "preparation-domains");
        for (const domain of preparation.domains) {
          domains.append(
            element(
              "li",
              `preparation-domain status-${domain.status}`,
              t(language, "workspace.domainStatus", {
                domain: t(language, `workspace.domain.${domain.name}`),
                status: t(language, `workspace.calculation.${domain.status}`),
              }),
            ),
          );
        }
        item.append(domains);
      }
      const calculate = actionButton(
        preparation && preparation.status !== "ready"
          ? t(language, "workspace.retryCalculations")
          : t(language, "workspace.calculate"),
        () => prepareVersion(root, dataSource, version.id),
        version.isCurrent || model.status === "preparing",
      );
      calculate.className = "secondary-button";
      const publish = actionButton(
        version.isCurrent
          ? t(language, "workspace.verifyData")
          : t(language, "workspace.publishData"),
        () => publishVersion(root, dataSource, version.id),
        !version.publishable || model.status === "publishing",
      );
      publish.className = "secondary-button";
      publish.dataset.versionId = version.id;
      item.append(calculate, publish);
      list.append(item);
    }
    shell.append(list);
  }
  if (model.error) {
    const error = element(
      "p",
      "import-error",
      t(language, "workspace.releaseFailed", { code: model.error }),
    );
    error.setAttribute("role", "alert");
    shell.append(error);
  }
  root.append(shell);
}

export function renderWorkspace(
  root,
  dataSource = null,
  runtimeRelease = null,
  isActive = null,
  getScope = null,
) {
  if (dataSource) workspaceDataSource = dataSource;
  if (isActive) workspaceIsActive = isActive;
  if (getScope) workspaceGetScope = getScope;
  if (!workspaceIsActive()) return;
  const resolvedDataSource = dataSource ?? workspaceDataSource;
  if (runtimeRelease && releaseState.current === null) {
    releaseState = { ...releaseState, current: runtimeRelease };
  }
  const model = toWorkspaceViewModel(state);
  const language = currentLanguage();
  const fileName = state.upload?.fileName ?? state.upload?.source_filename;
  const sourceSummary = fileName
    ? t(language, "workspace.sourceReady", {
        file: fileName,
        count: state.uploads?.length ?? 0,
      })
    : t(language, "workspace.noSource");
  root.replaceChildren();
  renderWorkspaceTabs(root, resolvedDataSource, language);
  if (activeWorkspaceTab === "library") {
    const effects = ensureLibraryEffects(root, resolvedDataSource);
    renderLibrary(root, libraryState, effects, { language });
    if (libraryState.status === "idle") void effects.load();
    return;
  }
  if (activeWorkspaceTab === "exports") {
    const effects = ensureLibraryEffects(root, resolvedDataSource);
    renderExports(root, {
      mode: "operator",
      language,
      libraryState,
      effects,
    });
    if (libraryState.status === "idle") void effects.load();
    else if (!libraryState.detail && libraryState.versions[0]) {
      void effects.select(libraryState.versions[0].dataset_version_id);
    }
    return;
  }
  const shell = element("article", "import-workspace");
  shell.append(stageList(model));
  const card = element("section", "import-card");
  card.append(
    element(
      "p",
      "eyebrow",
      t(language, "workspace.stageLabel", {
        stage: t(language, `workspace.stage.${model.phase}`),
      }),
    ),
  );
  card.append(element("h2", "", sourceSummary));
  card.append(
    element(
      "p",
      "import-description",
      t(language, `workspace.description.${model.phase}`),
    ),
  );
  if (model.error) {
    const error = element(
      "p",
      "import-error",
      t(language, "workspace.requestFailed", { code: model.error }),
    );
    error.setAttribute("role", "alert");
    card.append(error);
  }
  renderAction(root, card);
  shell.append(card);
  root.append(shell);
  if (resolvedDataSource) {
    renderReleaseControls(root, resolvedDataSource);
    if (releaseState.status === "idle") {
      void loadReleaseControls(root, resolvedDataSource);
    }
  }
}
