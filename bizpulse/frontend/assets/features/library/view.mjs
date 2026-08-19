import { t } from "../../i18n/catalog.mjs";
import { toLibraryViewModel } from "./view-model.mjs";
import { libraryRoleLabel, renderLibraryWorkbook } from "./workbook-view.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function metric(label, value) {
  const item = element("li", "library-metric");
  item.append(element("span", "status-note", label), element("strong", "", String(value)));
  return item;
}

function metrics(item, language) {
  const list = element("ul", "library-metrics");
  list.append(
    metric(t(language, "library.stores"), item.stores),
    metric(t(language, "library.skus"), item.skus),
    metric(t(language, "library.rows"), item.rowCount),
  );
  return list;
}

function historyCard(item, language, onSelect, selected) {
  const card = element("li", "library-version-card");
  if (selected) card.dataset.selected = "true";
  card.append(
    element("p", "eyebrow", item.lifecycle),
    element("h3", "", item.historyLabel),
    element("p", "status-note", item.period),
    metrics(item, language),
  );
  const button = element("button", "secondary-button", t(language, "library.open"));
  button.type = "button";
  button.addEventListener("click", onSelect);
  card.append(button);
  return card;
}

function renderHistory(container, state, model, effects, language) {
  if (state.mode !== "operator" || model.versions.length <= 1) return;
  const history = element("details", "library-history");
  history.append(element("summary", "", t(language, "library.history", {
    count: model.versions.length,
  })));
  const list = element("ul", "library-version-grid");
  for (const [index, item] of model.versions.entries()) {
    const raw = state.versions[index];
    list.append(historyCard(
      item,
      language,
      () => effects.select(raw.dataset_version_id),
      raw.dataset_version_id === state.selectedVersionId,
    ));
  }
  history.append(list);
  container.append(history);
}

function renderProvenance(container, detail, language) {
  const provenance = element("details", "library-provenance");
  provenance.append(element("summary", "", t(language, "library.provenance")));
  const list = element("ul", "evidence-list");
  for (const item of detail.provenance) {
    list.append(element(
      "li",
      "",
      `${item.sourceName} · ${libraryRoleLabel(item.sourceRole, language)} · ${item.rowCount ?? "—"}`,
    ));
  }
  provenance.append(list);
  container.append(provenance);
}

function renderExports(container, rawDetail, effects, mode, language, exportStatus) {
  const exports = element("section", "library-exports");
  exports.append(element("h3", "", t(language, "exports.title")));
  if (mode === "operator") {
    const generate = element(
      "button",
      "primary-button",
      exportStatus === "generating"
        ? t(language, "exports.generating")
        : t(language, "exports.generate"),
    );
    generate.type = "button";
    generate.disabled = exportStatus === "generating";
    generate.addEventListener("click", () =>
      effects.generateExport(rawDetail.dataset_version_id));
    exports.append(generate);
    for (const item of rawDetail.exports ?? []) {
      const link = element("a", "secondary-button", t(language, "exports.download"));
      link.href = effects.downloadUrl(rawDetail.dataset_version_id, item.id);
      link.setAttribute("download", "BizPulse-data.xlsx");
      exports.append(link);
    }
  } else {
    exports.append(element("p", "status-note", t(language, "exports.viewerBody")));
  }
  container.append(exports);
}

function renderDetail(container, detail, language, rawDetail, effects, mode, exportStatus) {
  const section = element("section", "library-detail");
  const heading = element("header", "library-dataset-heading");
  heading.append(
    element("p", "eyebrow", t(language, "library.combinedData")),
    element("h2", "", detail.version.label),
    element("p", "status-note", detail.version.period),
    element("p", "report-summary", t(language, "library.combinedDataBody")),
    metrics(detail.version, language),
  );
  section.append(heading);
  if (detail.version.missingRoles.length) {
    section.append(element("p", "form-error", t(language, "library.missingInputs", {
      count: detail.version.missingRoles.length,
    })));
  }
  renderLibraryWorkbook(section, detail, effects, {
    language,
    versionId: rawDetail.dataset_version_id,
  });
  renderProvenance(section, detail, language);
  renderExports(section, rawDetail, effects, mode, language, exportStatus);
  container.append(section);
}

export function renderLibrary(root, state, effects, { language = "en" } = {}) {
  const model = toLibraryViewModel(state, language);
  const shell = element("article", "library-workspace");
  shell.append(
    element("p", "eyebrow", t(language, "library.eyebrow")),
    element("h2", "", t(language, "library.title")),
    element("p", "report-summary", t(language, "library.summary")),
  );
  if (["idle", "loading"].includes(model.status)) {
    shell.setAttribute("aria-busy", "true");
    shell.append(element("p", "status-note", t(language, "library.loading")));
  }
  renderHistory(shell, state, model, effects, language);
  if (model.detail) {
    renderDetail(
      shell,
      model.detail,
      language,
      state.detail,
      effects,
      state.mode,
      model.exportStatus,
    );
  }
  if (model.error) {
    const error = element("p", "form-error", t(language, "library.failed", { code: model.error }));
    error.setAttribute("role", "alert");
    shell.append(error);
  }
  root.append(shell);
  return model;
}
