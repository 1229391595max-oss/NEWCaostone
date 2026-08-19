import { t } from "../../i18n/catalog.mjs";

function period(item) {
  return item.period_start && item.period_end
    ? `${item.period_start} — ${item.period_end}`
    : t(item.language, "common.unavailable");
}

function importedLabel(item, language) {
  const parsed = new Date(item.created_at);
  if (!Number.isNaN(parsed.valueOf())) {
    const date = new Intl.DateTimeFormat(language === "zh" ? "zh-CN" : "en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    }).format(parsed);
    return t(language, "library.importedDataset", { date });
  }
  return t(language, "library.importNumber", { number: item.version_number });
}

function versionModel(item, language) {
  const localized = { ...item, language };
  const historyLabel = importedLabel(item, language);
  return {
    label: item.lifecycle === "current"
      ? t(language, "library.currentDataset")
      : historyLabel,
    historyLabel,
    lifecycle: t(language, `library.lifecycle.${item.lifecycle}`),
    period: period(localized),
    stores: item.stores ?? 0,
    skus: item.skus ?? 0,
    rowCount: item.row_count ?? 0,
    sourceRoles: item.source_roles ?? [],
    quality: item.quality?.status ?? "unknown",
    missingRoles: item.quality?.missing_roles ?? [],
    preparation: item.preparation?.status ?? "not_started",
    previewAvailable: item.preview_available === true,
    exportAvailable: item.export_available === true,
  };
}

export function toLibraryViewModel(state, language) {
  return {
    mode: state.mode,
    status: state.status,
    error: state.error,
    versions: state.versions.map((item) => versionModel(item, language)),
    detail: state.detail
      ? {
          version: versionModel(state.detail, language),
          tables: (state.detail.tables ?? []).map((table) => ({
            role: table.role,
            rowCount: table.row_count,
            columns: table.columns ?? [],
            preview: table.preview ?? [],
            scopeKind: table.scope_kind === "shared" ? "shared" : "store",
          })),
          provenance: (state.detail.provenance ?? []).map((item) => ({
            sourceName: item.source_name,
            sourceRole: item.source_role,
            status: item.status,
            adapter: item.adapter,
            rowCount: item.row_count,
          })),
          analyses: state.detail.analyses ?? [],
          exports: (state.detail.exports ?? []).map((item) => ({
            id: item.id,
            status: item.status,
            byteCount: item.byte_count,
            createdAt: item.created_at,
          })),
          tablePage: { ...state.table },
          rowDetail: state.rowDetail,
        }
      : null,
    exportStatus: state.exportStatus,
  };
}
