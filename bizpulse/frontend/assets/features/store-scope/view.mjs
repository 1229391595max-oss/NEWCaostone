import { t } from "../../i18n/catalog.mjs";
import { storeScopeLabel } from "./state.mjs";

function optionLabel(option, language) {
  const label = storeScopeLabel(option, language);
  return option.labelKey ? t(language, label) : label;
}

export function renderStoreScope(root, state, {
  language = "en",
  onSelect,
} = {}) {
  root.replaceChildren();
  const label = document.createElement("label");
  label.className = "store-scope-control";
  const text = document.createElement("span");
  text.className = "store-scope-label";
  text.textContent = t(language, "storeScope.label");
  const select = document.createElement("select");
  select.dataset.storeScopeSelector = "";
  select.setAttribute("aria-label", t(language, "storeScope.accessibleLabel"));
  select.disabled = state.options.length <= 1;
  for (const item of state.options) {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = optionLabel(item, language);
    option.selected = item.id === state.selectedId;
    select.append(option);
  }
  select.addEventListener("change", () => onSelect?.(select.value));
  label.append(text, select);
  root.append(label);
  return select;
}
