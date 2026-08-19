export function createOverviewLoader(dataSource, dispatch, getScope = () => null) {
  let generation = 0;
  return async function load() {
    const current = ++generation;
    dispatch({ type: "request/started", generation: current });
    try {
      const [sales, inventory, profit, replenishment, actions] =
        await Promise.allSettled([
          () => dataSource.loadAnalysis("sales_ads", getScope()),
          () => dataSource.loadAnalysis("inventory_risk", getScope()),
          () => dataSource.loadAnalysis("operating_profit", getScope()),
          () => dataSource.loadAnalysis("replenishment", getScope()),
          () => dataSource.loadActions(getScope()),
        ].map((operation) => Promise.resolve().then(operation)));
      const core = [sales, inventory, profit];
      const failed = core.find((item) => item.status === "rejected");
      if (failed) throw failed.reason;
      dispatch({
        type: "request/completed",
        generation: current,
        payload: {
          sales: sales.value,
          inventory: inventory.value,
          profit: profit.value,
          replenishment: settledValue(replenishment),
          actions: settledValue(actions),
        },
      });
    } catch (error) {
      dispatch({
        type: "request/failed",
        generation: current,
        error: error.code ?? error.message ?? "OVERVIEW_UNAVAILABLE",
      });
    }
  };
}

function settledValue(result) {
  return result.status === "fulfilled" ? result.value : null;
}
