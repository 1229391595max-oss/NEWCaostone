export function createLibraryEffects({
  dataSource,
  mode,
  dispatch,
  getScope = () => null,
}) {
  let detailGeneration = 0;
  let tableGeneration = 0;

  async function loadTable({ versionId, role, page = 1, pageSize = 50 }) {
    if (!role) return;
    const generation = ++tableGeneration;
    dispatch({ type: "library/table-loading", role, page, pageSize });
    try {
      const result = mode === "operator"
        ? await dataSource.loadLibraryTable(
          versionId,
          role,
          { page, pageSize },
          getScope(),
        )
        : await dataSource.loadLibraryTable(role, { page, pageSize }, getScope());
      if (generation === tableGeneration) {
        dispatch({ type: "library/table-loaded", page: result });
      }
    } catch (error) {
      if (generation === tableGeneration) {
        dispatch({
          type: "library/table-failed",
          code: error?.code ?? error?.message ?? "LIBRARY_TABLE_UNAVAILABLE",
        });
      }
    }
  }

  async function loadDetail(detail, { generation, openTable = true } = {}) {
    if (generation !== undefined && generation !== detailGeneration) return;
    dispatch({ type: "library/detail-loaded", detail });
    if (!openTable) return;
    const tables = detail?.tables ?? [];
    const selected = tables.find((item) => item.row_count > 0) ?? tables[0];
    if (selected) {
      await loadTable({
        versionId: detail.dataset_version_id,
        role: selected.role,
      });
    }
  }

  async function select(versionId) {
    if (mode !== "operator") return;
    const generation = ++detailGeneration;
    tableGeneration += 1;
    dispatch({ type: "library/selecting", versionId });
    try {
      const detail = await dataSource.loadLibraryVersion(versionId, getScope());
      if (generation !== detailGeneration) return;
      await loadDetail(detail, { generation });
    } catch (error) {
      if (generation === detailGeneration) {
        dispatch({
          type: "library/failed",
          code: error?.code ?? error?.message ?? "LIBRARY_UNAVAILABLE",
        });
      }
    }
  }

  return {
    async load() {
      const generation = ++detailGeneration;
      tableGeneration += 1;
      dispatch({ type: "library/loading" });
      try {
        if (mode === "viewer") {
          const detail = await dataSource.loadLibrary(getScope());
          if (generation !== detailGeneration) return;
          dispatch({ type: "library/loaded", versions: [detail] });
          await loadDetail(detail, { generation });
          return;
        }
        const payload = await dataSource.listLibraryVersions();
        if (generation !== detailGeneration) return;
        const versions = payload?.versions ?? [];
        dispatch({ type: "library/loaded", versions });
        if (versions[0]) await select(versions[0].dataset_version_id);
      } catch (error) {
        if (generation !== detailGeneration) return;
        dispatch({
          type: "library/failed",
          code: error?.code ?? error?.message ?? "LIBRARY_UNAVAILABLE",
        });
      }
    },
    select,
    loadTable,
    invalidate() {
      detailGeneration += 1;
      tableGeneration += 1;
    },
    openRow(row) {
      dispatch({ type: "library/row-opened", row });
    },
    closeRow() {
      dispatch({ type: "library/row-closed" });
    },
    async generateExport(versionId) {
      if (mode !== "operator") return;
      const generation = detailGeneration;
      dispatch({ type: "export/started" });
      try {
        await dataSource.generateDatasetExport(
          versionId,
          `dataset-export-${globalThis.crypto.randomUUID()}`,
        );
        if (generation !== detailGeneration) return;
        const detail = await dataSource.loadLibraryVersion(versionId, getScope());
        if (generation !== detailGeneration) return;
        await loadDetail(detail, { generation, openTable: false });
        dispatch({ type: "export/completed" });
      } catch (error) {
        if (generation === detailGeneration) {
          dispatch({
            type: "export/failed",
            code: error?.code ?? error?.message ?? "DATASET_EXPORT_UNAVAILABLE",
          });
        }
      }
    },
    downloadUrl(versionId, exportId) {
      return mode === "operator"
        ? dataSource.datasetExportDownloadUrl(versionId, exportId)
        : null;
    },
  };
}
