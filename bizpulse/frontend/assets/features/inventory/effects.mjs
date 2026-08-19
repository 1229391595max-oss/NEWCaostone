export function createInventoryLoader(dataSource, dispatch, getScope = () => null) {
  let generation = 0;
  return async function load() {
    const current = ++generation;
    dispatch({ type: "request/started", generation: current });
    const [inventory, replenishment] = await Promise.allSettled([
      () => dataSource.loadAnalysis("inventory_risk", getScope()),
      () => dataSource.loadAnalysis("replenishment", getScope()),
    ].map((operation) => Promise.resolve().then(operation)));
    if (inventory.status === "rejected") {
      const error = inventory.reason;
      dispatch({
        type: "request/failed",
        generation: current,
        error: error?.code ?? error?.message ?? "INVENTORY_UNAVAILABLE",
      });
      return;
    }
    dispatch({
      type: "request/completed",
      generation: current,
      payload: {
        inventory: inventory.value,
        replenishment: replenishment.status === "fulfilled"
          ? replenishment.value
          : null,
      },
    });
  };
}
