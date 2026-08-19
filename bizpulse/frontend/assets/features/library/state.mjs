export function initialLibraryState(mode) {
  return {
    mode,
    status: "idle",
    versions: [],
    selectedVersionId: null,
    detail: null,
    error: null,
    exportStatus: "idle",
    table: {
      status: "idle",
      role: null,
      columns: [],
      rows: [],
      page: 1,
      pageSize: 50,
      totalRows: 0,
      totalPages: 1,
      requestPage: 1,
      requestPageSize: 50,
      error: null,
    },
    rowDetail: null,
  };
}

export function reduceLibrary(state, action) {
  switch (action.type) {
    case "library/loading":
      return { ...state, status: "loading", error: null };
    case "library/loaded":
      return {
        ...state,
        status: "ready",
        versions: action.versions ?? [],
        error: null,
      };
    case "library/selecting":
      return {
        ...state,
        status: "loading-detail",
        selectedVersionId: action.versionId,
        detail: null,
        error: null,
        exportStatus: "idle",
        table: initialLibraryState(state.mode).table,
        rowDetail: null,
      };
    case "library/detail-loaded":
      return {
        ...state,
        status: "ready",
        selectedVersionId: action.detail?.dataset_version_id ?? state.selectedVersionId,
        detail: action.detail ?? null,
        error: null,
      };
    case "library/table-loading": {
      const sameRole = state.table.role === action.role;
      return {
        ...state,
        table: {
          ...(sameRole ? state.table : initialLibraryState(state.mode).table),
          status: "loading",
          role: action.role,
          requestPage: action.page ?? 1,
          requestPageSize: action.pageSize ?? 50,
          error: null,
        },
        rowDetail: null,
      };
    }
    case "library/table-loaded":
      return {
        ...state,
        table: {
          status: "ready",
          role: action.page.role,
          columns: action.page.columns ?? [],
          rows: action.page.rows ?? [],
          page: action.page.page,
          pageSize: action.page.page_size,
          totalRows: action.page.total_rows,
          totalPages: action.page.total_pages,
          requestPage: action.page.page,
          requestPageSize: action.page.page_size,
          error: null,
        },
        rowDetail: null,
      };
    case "library/table-failed":
      return {
        ...state,
        table: {
          ...state.table,
          status: "error",
          error: action.code ?? "LIBRARY_TABLE_UNAVAILABLE",
        },
      };
    case "library/row-opened":
      return { ...state, rowDetail: action.row ?? null };
    case "library/row-closed":
      return { ...state, rowDetail: null };
    case "library/failed":
      return {
        ...state,
        status: "error",
        error: action.code ?? "LIBRARY_UNAVAILABLE",
      };
    case "export/started":
      return { ...state, exportStatus: "generating", error: null };
    case "export/completed":
      return { ...state, exportStatus: "available", error: null };
    case "export/failed":
      return {
        ...state,
        exportStatus: "failed",
        error: action.code ?? "DATASET_EXPORT_UNAVAILABLE",
      };
    default:
      return state;
  }
}
