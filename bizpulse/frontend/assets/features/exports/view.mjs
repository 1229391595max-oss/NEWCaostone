import { t } from "../../i18n/catalog.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function renderExports(
  root,
  { mode, language = "en", libraryState = null, effects = null },
) {
  const shell = element("article", "exports-workspace");
  shell.append(
    element("p", "eyebrow", t(language, "exports.eyebrow")),
    element("h2", "", t(language, "exports.title")),
    element(
      "p",
      "report-summary",
      t(language, mode === "viewer" ? "exports.viewerBody" : "exports.operatorBody"),
    ),
  );
  if (mode === "operator" && libraryState?.detail && effects) {
    const detail = libraryState.detail;
    const controls = element("section", "library-detail");
    controls.append(
      element("h3", "", t(language, "library.version", {
        number: detail.version_number,
      })),
    );
    const generate = element(
      "button",
      "primary-button",
      libraryState.exportStatus === "generating"
        ? t(language, "exports.generating")
        : t(language, "exports.generate"),
    );
    generate.type = "button";
    generate.disabled = libraryState.exportStatus === "generating";
    generate.addEventListener("click", () =>
      effects.generateExport(detail.dataset_version_id));
    controls.append(generate);
    for (const item of detail.exports ?? []) {
      const link = element("a", "secondary-button", t(language, "exports.download"));
      link.href = effects.downloadUrl(detail.dataset_version_id, item.id);
      link.setAttribute("download", "BizPulse-data.xlsx");
      controls.append(link);
    }
    shell.append(controls);
  }
  root.append(shell);
}
