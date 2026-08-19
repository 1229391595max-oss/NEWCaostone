import { formatBrl, formatDecimal } from "../../core/formatters.mjs";
import { t } from "../../i18n/catalog.mjs";

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function token(value) {
  return String(value).replaceAll(/[^A-Za-z0-9_-]/g, "-");
}

export function libraryRoleLabel(role, language) {
  try {
    return t(language, `library.table.${role}`);
  } catch (error) {
    if (error?.message !== "I18N_KEY_MISSING") throw error;
    const words = String(role).replaceAll("_", " ");
    return words ? `${words[0].toUpperCase()}${words.slice(1)}` : "—";
  }
}

function columnLabel(column, language) {
  try {
    return t(language, `library.column.${column}`);
  } catch (error) {
    if (error?.message !== "I18N_KEY_MISSING") throw error;
    return String(column) || "—";
  }
}

function cellValue(column, value, language) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "object") return JSON.stringify(value);
  const name = String(column).toLowerCase();
  if (name.endsWith("_brl")) return formatBrl(value, language);
  const numeric = typeof value === "number"
    || (typeof value === "string" && /^-?\d+(?:\.\d+)?$/.test(value));
  if (numeric && !name.endsWith("_id")) return formatDecimal(value, language);
  return String(value);
}

function loadPage(effects, versionId, role, page, pageSize) {
  return effects.loadTable({ versionId, role, page, pageSize });
}

function restoreTabFocus(role) {
  queueMicrotask(() => {
    [...document.querySelectorAll(".library-table-tab")]
      .find((tab) => tab.dataset.libraryRole === role)
      ?.focus();
  });
}

function activateTab(role, activate) {
  Promise.resolve(activate(role)).finally(() => restoreTabFocus(role));
}

function tabKeydown(event, tabs, activate) {
  const current = tabs.indexOf(event.currentTarget);
  let target = null;
  if (event.key === "ArrowRight") target = (current + 1) % tabs.length;
  if (event.key === "ArrowLeft") target = (current - 1 + tabs.length) % tabs.length;
  if (event.key === "Home") target = 0;
  if (event.key === "End") target = tabs.length - 1;
  if (target === null) return;
  event.preventDefault();
  tabs[target].focus();
  activateTab(tabs[target].dataset.libraryRole, activate);
}

function renderTabs(container, tables, activeRole, language, activate) {
  const tablist = element("div", "library-table-tabs");
  tablist.setAttribute("role", "tablist");
  tablist.setAttribute("aria-label", t(language, "library.tables"));
  for (const table of tables) {
    const label = libraryRoleLabel(table.role, language);
    const tab = element("button", "library-table-tab");
    const selected = table.role === activeRole;
    tab.type = "button";
    tab.dataset.libraryRole = table.role;
    tab.id = `library-tab-${token(table.role)}`;
    tab.setAttribute("role", "tab");
    tab.setAttribute("aria-selected", String(selected));
    tab.setAttribute("aria-controls", `library-panel-${token(table.role)}`);
    tab.setAttribute("aria-label", t(language, "library.tableLabel", {
      name: label,
      count: table.rowCount,
    }));
    tab.tabIndex = selected ? 0 : -1;
    tab.append(
      element("span", "", label),
      element(
        "span",
        `library-scope-badge scope-${table.scopeKind}`,
        t(language, table.scopeKind === "shared" ? "storeScope.shared" : "storeScope.store"),
      ),
      element("span", "library-table-count", String(table.rowCount)),
    );
    tab.addEventListener("click", () => activateTab(table.role, activate));
    tablist.append(tab);
  }
  const tabs = [...tablist.querySelectorAll('[role="tab"]')];
  for (const tab of tabs) {
    tab.addEventListener("keydown", (event) => tabKeydown(event, tabs, activate));
  }
  container.append(tablist);
}

function renderPagination(container, page, activeRole, language, effects, versionId) {
  const controls = element("div", "library-pagination");
  const sizeLabel = element("label", "library-page-size-label");
  sizeLabel.append(element("span", "", t(language, "library.rowsPerPage")));
  const size = element("select", "library-page-size");
  size.setAttribute("aria-label", t(language, "library.rowsPerPage"));
  for (const value of [25, 50, 100]) {
    const option = element("option", "", String(value));
    option.value = String(value);
    option.selected = value === page.pageSize;
    size.append(option);
  }
  size.disabled = page.status === "loading";
  size.addEventListener("change", () =>
    loadPage(effects, versionId, activeRole, 1, Number(size.value)));
  sizeLabel.append(size);

  const status = element("span", "library-page-status", t(language, "library.page", {
    page: page.page,
    total: page.totalPages,
  }));
  status.setAttribute("aria-live", "polite");

  const buttons = element("div", "library-page-buttons");
  const previous = element("button", "secondary-button compact-button", t(language, "library.previousPage"));
  previous.type = "button";
  previous.dataset.libraryPage = "previous";
  previous.disabled = page.status === "loading" || page.page <= 1;
  previous.addEventListener("click", () =>
    loadPage(effects, versionId, activeRole, page.page - 1, page.pageSize));
  const next = element("button", "secondary-button compact-button", t(language, "library.nextPage"));
  next.type = "button";
  next.dataset.libraryPage = "next";
  next.disabled = page.status === "loading" || page.page >= page.totalPages;
  next.addEventListener("click", () =>
    loadPage(effects, versionId, activeRole, page.page + 1, page.pageSize));
  buttons.append(previous, next);
  controls.append(sizeLabel, status, buttons);
  container.append(controls);
}

function renderTable(container, page, activeRole, language, effects) {
  if (page.status === "loading" && page.rows.length === 0) {
    container.append(element("p", "library-table-message", t(language, "library.loadingTable")));
    return;
  }
  if (page.status === "error" && page.rows.length === 0) return;
  if (page.rows.length === 0) {
    container.append(element("p", "library-table-message", t(language, "library.emptyTable")));
    return;
  }

  const scroll = element("div", "library-table-scroll");
  const table = element("table", "library-data-table");
  const caption = element("caption", "visually-hidden", libraryRoleLabel(activeRole, language));
  const head = element("thead", "");
  const headRow = element("tr", "");
  for (const column of page.columns) {
    headRow.append(element("th", "", columnLabel(column, language)));
  }
  head.append(headRow);
  const body = element("tbody", "");
  for (const [index, row] of page.rows.entries()) {
    const tableRow = element("tr", "library-data-row");
    const absoluteRow = (page.page - 1) * page.pageSize + index + 1;
    tableRow.tabIndex = 0;
    tableRow.dataset.libraryRowIndex = String(index);
    tableRow.setAttribute("aria-label", t(language, "library.openRow", { number: absoluteRow }));
    const open = () => {
      effects.openRow(row);
      queueMicrotask(() => document.querySelector(".library-row-detail-close")?.focus());
    };
    tableRow.addEventListener("click", open);
    tableRow.addEventListener("keydown", (event) => {
      if (!["Enter", " "].includes(event.key)) return;
      event.preventDefault();
      open();
    });
    for (const column of page.columns) {
      tableRow.append(element("td", "", cellValue(column, row[column], language)));
    }
    body.append(tableRow);
  }
  table.append(caption, head, body);
  scroll.append(table);
  container.append(scroll);
}

function renderError(container, page, activeRole, language, effects, versionId) {
  if (!page.error) return;
  const error = element("div", "library-table-error");
  error.setAttribute("role", "alert");
  error.append(element("span", "", t(language, "library.tableFailed", { code: page.error })));
  const retry = element("button", "secondary-button compact-button", t(language, "library.retry"));
  retry.type = "button";
  retry.addEventListener("click", () =>
    loadPage(
      effects,
      versionId,
      activeRole,
      page.requestPage,
      page.requestPageSize,
    ));
  error.append(retry);
  container.append(error);
}

function renderRowDrawer(container, detail, language, effects) {
  if (!detail.rowDetail) return;
  const index = detail.tablePage.rows.indexOf(detail.rowDetail);
  const close = () => {
    effects.closeRow();
    queueMicrotask(() => {
      document.querySelector(`[data-library-row-index="${index}"]`)?.focus();
    });
  };
  const drawer = element("dialog", "library-row-drawer");
  drawer.setAttribute("role", "dialog");
  drawer.setAttribute("aria-modal", "true");
  drawer.setAttribute("aria-labelledby", "library-row-detail-title");
  drawer.addEventListener("cancel", (event) => {
    event.preventDefault();
    close();
  });
  drawer.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const focusable = [...drawer.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
    )];
    if (focusable.length === 0) {
      event.preventDefault();
      drawer.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable.at(-1);
    if (
      (event.shiftKey && document.activeElement === first)
      || (!event.shiftKey && document.activeElement === last)
    ) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  });
  const closeButton = element("button", "text-button library-row-detail-close", t(language, "library.closeRow"));
  closeButton.type = "button";
  closeButton.addEventListener("click", close);
  const title = element("h2", "", t(language, "library.rowDetails"));
  title.id = "library-row-detail-title";
  const fields = element("dl", "library-row-fields");
  for (const column of detail.tablePage.columns) {
    fields.append(
      element("dt", "", columnLabel(column, language)),
      element("dd", "", cellValue(column, detail.rowDetail[column], language)),
    );
  }
  drawer.append(closeButton, title, fields);
  container.append(drawer);
  queueMicrotask(() => {
    if (drawer.isConnected && !drawer.open) drawer.showModal();
  });
}

export function renderLibraryWorkbook(
  container,
  detail,
  effects,
  { language = "en", versionId } = {},
) {
  const workbook = element("section", "library-workbook");
  const activeRole = detail.tablePage.role
    ?? detail.tables.find((table) => table.rowCount > 0)?.role
    ?? detail.tables[0]?.role
    ?? null;
  if (!activeRole) {
    workbook.append(element("p", "library-table-message", t(language, "library.noTables")));
    container.append(workbook);
    return workbook;
  }

  renderTabs(workbook, detail.tables, activeRole, language, (role) => {
    if (role !== activeRole) return loadPage(effects, versionId, role, 1, 50);
    return Promise.resolve();
  });
  const panel = element("div", "library-table-panel");
  panel.id = `library-panel-${token(activeRole)}`;
  panel.setAttribute("role", "tabpanel");
  panel.setAttribute("aria-labelledby", `library-tab-${token(activeRole)}`);
  panel.setAttribute("aria-busy", String(detail.tablePage.status === "loading"));
  const heading = element("div", "library-table-heading");
  heading.append(
    element("h3", "", libraryRoleLabel(activeRole, language)),
    element("span", "status-note", t(language, "library.tableRows", {
      count: detail.tablePage.totalRows,
    })),
  );
  panel.append(heading);
  renderTable(panel, detail.tablePage, activeRole, language, effects);
  renderError(panel, detail.tablePage, activeRole, language, effects, versionId);
  renderPagination(panel, detail.tablePage, activeRole, language, effects, versionId);
  workbook.append(panel);
  renderRowDrawer(workbook, detail, language, effects);
  container.append(workbook);
  return workbook;
}
