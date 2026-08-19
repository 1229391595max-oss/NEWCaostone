export function createProfitLoader(dataSource, dispatch, getScope = () => null) {
  let generation = 0;
  return async function load() {
    const current = ++generation;
    dispatch({ type: "request/started", generation: current });
    const [analysis, bridge] = await Promise.allSettled([
      dataSource.loadAnalysis("operating_profit", getScope()),
      dataSource.loadProfitBridge(getScope()),
    ]);
    if (analysis.status === "rejected") {
      const error = analysis.reason;
      dispatch({
        type: "request/failed",
        generation: current,
        error: error?.code ?? error?.message ?? "ANALYSIS_UNAVAILABLE",
      });
      return;
    }
    dispatch({
      type: "request/completed",
      generation: current,
      payload: analysis.value,
      bridge: bridge.status === "fulfilled" ? bridge.value : null,
      bridgeError:
        bridge.status === "rejected"
          ? bridge.reason?.code ??
            bridge.reason?.message ??
            "PROFIT_BRIDGE_UNAVAILABLE"
          : null,
    });
  };
}
