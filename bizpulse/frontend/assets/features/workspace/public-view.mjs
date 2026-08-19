import { t } from "../../i18n/catalog.mjs";
import { bindFileDropZone } from "../../core/file-drop-zone.mjs";
import { createLibraryEffects } from "../library/effects.mjs";
import { initialLibraryState, reduceLibrary } from "../library/state.mjs";
import { renderLibrary } from "../library/view.mjs";
import { renderExports } from "../exports/view.mjs";

let activeWorkspaceTab = "upload";
let viewerLibraryState = initialLibraryState("viewer");
let viewerLibraryEffects = null;
let viewerLibraryDataSource = null;
let viewerLibraryScopeGeneration = null;
let viewerContext = null;
const WORKSPACE_TABS = Object.freeze([
  ["upload", "workspace.tab.upload"],
  ["library", "workspace.tab.library"],
  ["exports", "workspace.tab.exports"],
]);

const ANALYSIS_LABEL_KEYS = Object.freeze({
  sales_ads: "public.analysis.salesAds",
  inventory_risk: "public.analysis.inventoryRisk",
  fifo_cost_aging: "public.analysis.fifoCostAging",
  operating_profit: "public.analysis.operatingProfit",
  replenishment: "public.analysis.replenishment",
});

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function validPeriod(value) {
  return Array.isArray(value)
    && value.length === 2
    && value.every((item) => typeof item === "string" && item.length > 0);
}

function readableToken(value) {
  return String(value).replaceAll("_", " ");
}

export function toPublicDataEvidenceModel(release, language = "en") {
  const complete = release
    && typeof release.currency === "string"
    && release.currency.length > 0
    && validPeriod(release.reporting_period);
  if (!complete) {
    return {
      status: "error",
      code: "PUBLIC_RELEASE_METADATA_INCOMPLETE",
      title: t(language, "public.releaseMetadataIncomplete"),
    };
  }

  return {
    status: "ready",
    language,
    currency: release.currency,
    periodStart: release.reporting_period[0],
    periodEnd: release.reporting_period[1],
    sourceRoles: Array.isArray(release.source_roles)
      ? release.source_roles.map(readableToken)
      : [],
    analyses: Array.isArray(release.precomputed_analyses)
      ? release.precomputed_analyses.map((kind) => ({
        kind,
        label: ANALYSIS_LABEL_KEYS[kind]
          ? t(language, ANALYSIS_LABEL_KEYS[kind])
          : readableToken(kind),
      }))
      : [],
    evidenceStates: Array.isArray(release.evidence_states)
      ? release.evidence_states.map(readableToken)
      : [],
  };
}

function releaseSummary(model) {
  const section = element("section", "release-controls");
  section.append(
    element("p", "eyebrow", t(model.language, "public.dataReady")),
    element("h2", "", `${model.periodStart} — ${model.periodEnd}`),
    element(
      "p",
      "import-description",
      `${model.currency} · ${t(model.language, "public.sharedPreparedData")}`,
    ),
  );
  return section;
}

function sourceCoverage(model) {
  const section = element("section", "release-controls");
  section.append(
    element("p", "eyebrow", t(model.language, "public.canonicalSources")),
    element("h2", "", t(model.language, "public.loadedSourceCoverage")),
  );
  const list = element("ul", "release-version-list");
  for (const role of model.sourceRoles) {
    list.append(element("li", "release-version-card", role));
  }
  section.append(list);
  return section;
}

function analysisCoverage(model, onOpenEvidence) {
  const section = element("section", "release-controls");
  section.append(
    element("p", "eyebrow", t(model.language, "public.readyAnalyses")),
    element("h2", "", t(model.language, "public.precomputedCoverage")),
  );
  const list = element("ul", "release-version-list");
  for (const analysis of model.analyses) {
    const item = element("li", "release-version-card");
    item.append(
      element("p", "release-version-title", analysis.label),
      element("p", "status-note", t(model.language, "public.precomputedEvidence")),
    );
    if (typeof onOpenEvidence === "function") {
      const button = element(
        "button",
        "evidence-button",
        t(model.language, "public.openAnalysisEvidence"),
      );
      button.type = "button";
      button.addEventListener("click", () => onOpenEvidence(analysis.kind));
      item.append(button);
    }
    list.append(item);
  }
  section.append(list);
  return section;
}

function evidenceAccess(model) {
  const section = element("section", "release-controls");
  section.append(
    element("p", "eyebrow", t(model.language, "public.evidenceContract")),
    element("h2", "", t(model.language, "public.evidenceStatesPreserved")),
  );
  const list = element("ul", "evidence-list");
  for (const state of model.evidenceStates) {
    list.append(element("li", "", state));
  }
  section.append(list);
  return section;
}

function viewerImportWorkspace(language, onImportDemoData) {
  const shell = element("article", "public-data-evidence viewer-import-workspace");
  const heading = element("section", "report-heading");
  heading.append(
    element("p", "eyebrow", t(language, "viewer.workspaceEyebrow")),
    element("h2", "", t(language, "viewer.workspaceTitle")),
    element("p", "report-summary", t(language, "viewer.workspaceSummary")),
  );

  const actions = element("div", "viewer-import-actions");
  const personal = element("section", "release-controls viewer-import-card");
  personal.append(
    element("p", "eyebrow", t(language, "workspace.import")),
    element("h3", "", t(language, "viewer.personalUploadTitle")),
    element("p", "status-note", t(language, "viewer.personalUploadBody")),
  );
  const input = element("input", "visually-hidden");
  input.type = "file";
  input.multiple = true;
  input.setAttribute("accept", ".csv,.xls,.xlsx");
  input.setAttribute("tabindex", "-1");
  const zone = element("div", "file-drop-zone");
  zone.setAttribute("role", "button");
  zone.setAttribute("tabindex", "0");
  zone.append(
    element("strong", "", t(language, "viewer.dropFiles")),
    element("span", "status-note", t(language, "viewer.acceptedFiles")),
  );
  const personalStatus = element("p", "form-error");
  personalStatus.setAttribute("role", "status");
  bindFileDropZone({
    zone,
    input,
    onFiles() {
      personalStatus.textContent = t(language, "viewer.uploadUnavailable");
    },
    onState(state) {
      zone.dataset.dragging = state === "dragging" ? "true" : "false";
    },
  });
  personal.append(input, zone, personalStatus);

  const prepared = element("section", "release-controls viewer-import-card");
  prepared.append(
    element("p", "eyebrow", t(language, "workspace.demoImport")),
    element("h3", "", t(language, "viewer.demoDataTitle")),
    element("p", "status-note", t(language, "viewer.demoDataBody")),
  );
  const importButton = element(
    "button",
    "primary-action",
    t(language, "workspace.demoImport"),
  );
  importButton.type = "button";
  const importStatus = element("p", "status-note");
  importStatus.setAttribute("role", "status");
  importButton.addEventListener("click", async () => {
    if (typeof onImportDemoData !== "function") return;
    importButton.disabled = true;
    importStatus.textContent = t(language, "viewer.preparingWorkspace");
    try {
      await onImportDemoData();
    } catch (error) {
      importButton.disabled = false;
      importStatus.textContent = t(language, "viewer.importFailed", {
        code: error?.code ?? "REQUEST_FAILED",
      });
    }
  });
  prepared.append(importButton, importStatus);
  actions.append(personal, prepared);
  shell.append(heading, actions);
  return shell;
}

function renderTabs(root, language, rerender) {
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
      rerender();
    });
    tabs.append(button);
  }
  root.append(tabs);
}

function ensureViewerLibraryEffects(dataSource, getScope = () => null) {
  const scopeGeneration = getScope()?.generation ?? null;
  if (
    viewerLibraryEffects
    && viewerLibraryDataSource === dataSource
    && viewerLibraryScopeGeneration === scopeGeneration
  ) return viewerLibraryEffects;
  viewerLibraryEffects?.invalidate?.();
  viewerLibraryState = initialLibraryState("viewer");
  viewerLibraryDataSource = dataSource;
  viewerLibraryScopeGeneration = scopeGeneration;
  viewerLibraryEffects = createLibraryEffects({
    dataSource,
    mode: "viewer",
    getScope,
    dispatch(action) {
      viewerLibraryState = reduceLibrary(viewerLibraryState, action);
      if (viewerContext && activeWorkspaceTab === "library") {
        renderPublicDataEvidence(
          viewerContext.root,
          viewerContext.release,
          viewerContext.options,
        );
      }
    },
  });
  return viewerLibraryEffects;
}

export function renderPublicDataEvidence(root, release, options = {}) {
  const language = options.language ?? "en";
  viewerContext = { root, release, options };
  const model = release === null
    ? { status: "awaiting-demo-data" }
    : toPublicDataEvidenceModel(release, language);
  if (release !== null && model.status === "error") {
    const error = element("article", "empty-state-card");
    error.setAttribute("role", "alert");
    error.append(
      element("h2", "", model.title),
      element("p", "", model.code),
    );
    root.replaceChildren(error);
    return model;
  }

  root.replaceChildren();
  renderTabs(root, language, () => renderPublicDataEvidence(root, release, options));
  if (activeWorkspaceTab === "library") {
    if (release === null || !options.dataSource) {
      const unavailable = element("article", "empty-state-card");
      unavailable.append(
        element("h2", "", t(language, "library.title")),
        element("p", "", t(language, "library.activateFirst")),
      );
      root.append(unavailable);
      return model;
    }
    const effects = ensureViewerLibraryEffects(options.dataSource, options.getScope);
    renderLibrary(root, viewerLibraryState, effects, { language });
    if (viewerLibraryState.status === "idle") void effects.load();
    return model;
  }
  if (activeWorkspaceTab === "exports") {
    renderExports(root, { mode: "viewer", language });
    return model;
  }
  const shell = viewerImportWorkspace(language, options.onImportDemoData);
  root.append(shell);
  return model;
}
