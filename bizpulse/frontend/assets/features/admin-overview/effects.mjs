const REFRESH_INTERVAL_MS = 30_000;

export function createAdminOverviewEffects({
  dataSource,
  dispatch,
  setInterval = globalThis.setInterval,
  clearInterval = globalThis.clearInterval,
}) {
  let timer = null;
  let pending = null;

  async function load() {
    dispatch({ type: "load/started" });
    try {
      const payload = await dataSource.loadSummary();
      dispatch({ type: "load/succeeded", payload });
    } catch (error) {
      dispatch({
        type: "load/failed",
        code: error?.code ?? "ADMIN_SUMMARY_UNAVAILABLE",
      });
    } finally {
      pending = null;
    }
  }

  function refresh() {
    if (pending === null) pending = load();
    return pending;
  }

  function start() {
    if (timer === null) {
      timer = setInterval(() => void refresh(), REFRESH_INTERVAL_MS);
    }
    return refresh();
  }

  function stop() {
    if (timer !== null) clearInterval(timer);
    timer = null;
  }

  return { refresh, start, stop };
}
