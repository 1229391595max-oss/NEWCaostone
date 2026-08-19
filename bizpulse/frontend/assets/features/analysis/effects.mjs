export function createAnalysisLoader(dataSource, kind, dispatch, getScope = () => null) {
  let generation = 0;
  return async function load() {
    const current = ++generation;
    dispatch({ type: "request/started", generation: current });
    try {
      const payload = await dataSource.loadAnalysis(kind, getScope());
      dispatch({ type: "request/completed", generation: current, payload });
    } catch (error) {
      dispatch({
        type: "request/failed",
        generation: current,
        error: error.code ?? error.message ?? "ANALYSIS_UNAVAILABLE",
      });
    }
  };
}
