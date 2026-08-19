import { t } from "../i18n/catalog.mjs";

const evidenceStates = new Set(["measured", "derived", "assumed", "unknown"]);

export function toEvidenceDrawerModel(item) {
  if (
    !item ||
    typeof item.evidence_id !== "string" ||
    typeof item.alias !== "string" ||
    !evidenceStates.has(item.evidence_state) ||
    typeof item.formula !== "string" ||
    !Array.isArray(item.source_refs) ||
    item.source_refs.some((source) => typeof source !== "string")
  ) {
    throw new Error("EVIDENCE_INVALID");
  }
  return {
    id: item.evidence_id,
    alias: item.alias,
    state: item.evidence_state,
    formula: item.formula,
    sources: [...item.source_refs],
  };
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function openEvidenceDrawer(item) {
  const model = toEvidenceDrawerModel(item);
  const trigger = document.activeElement;
  const language = document.documentElement?.lang?.startsWith("zh") ? "zh" : "en";
  let drawer = document.querySelector("[data-evidence-drawer]");
  drawer?.remove();
  drawer = element("aside", "evidence-drawer");
  drawer.dataset.evidenceDrawer = "";
  drawer.setAttribute("role", "dialog");
  drawer.setAttribute("aria-modal", "true");
  document.body.append(drawer);
  const closeDrawer = () => {
    drawer.remove();
    trigger?.focus?.();
  };
  const close = element("button", "text-button", t(language, "evidence.close"));
  close.type = "button";
  close.addEventListener("click", closeDrawer);
  drawer.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
    } else if (event.key === "Tab") {
      event.preventDefault();
      close.focus();
    }
  });
  const sources = element("ul", "evidence-sources");
  for (const source of model.sources) sources.append(element("li", "", source));
  drawer.append(
    close,
    element("p", "eyebrow", model.state),
    element("h2", "", model.alias),
    element("p", "evidence-formula", model.formula),
    element("h3", "", t(language, "evidence.sourceRoles")),
    sources,
  );
  close.focus();
}
