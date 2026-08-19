function errorCode(error) {
  return error?.code ?? error?.message ?? "FORECAST_UNAVAILABLE";
}

export function createForecastLoader(dataSource, dispatch, getScope = () => null) {
  let generation = 0;
  return async function loadForecast() {
    const current = ++generation;
    dispatch({ type: "forecast/loading", generation: current });
    try {
      const payload = await dataSource.loadForecast(getScope());
      dispatch({ type: "forecast/loaded", generation: current, payload });
    } catch (error) {
      if (error?.status === 404 && error?.code === "FORECAST_NOT_FOUND") {
        dispatch({ type: "forecast/loaded", generation: current, payload: null });
        return;
      }
      dispatch({ type: "forecast/failed", generation: current, error: errorCode(error) });
    }
  };
}

export async function createForecast(dataSource, dispatch, payload, idempotencyKey) {
  dispatch({ type: "forecast/loading" });
  try {
    const forecast = await dataSource.createForecast(payload, idempotencyKey);
    dispatch({ type: "forecast/created", payload: forecast });
  } catch (error) {
    dispatch({ type: "forecast/failed", error: errorCode(error) });
  }
}

export async function confirmForecast(dataSource, dispatch, forecastId, skuIds) {
  try {
    const forecast = await dataSource.confirmForecast(forecastId, skuIds);
    dispatch({ type: "forecast/confirmed", payload: forecast });
  } catch (error) {
    dispatch({ type: "forecast/failed", error: errorCode(error) });
  }
}

export async function runForecast(dataSource, dispatch, forecastId) {
  try {
    const forecast = await dataSource.runForecast(forecastId);
    dispatch({ type: "forecast/completed", payload: forecast });
  } catch (error) {
    dispatch({ type: "forecast/failed", error: errorCode(error) });
  }
}
