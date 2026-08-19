import {
  initialAdminOverviewState,
  reduceAdminOverview,
} from "../admin-overview/state.mjs";

export function initialAdminStatusState() {
  return initialAdminOverviewState();
}

export function reduceAdminStatus(state, action) {
  return reduceAdminOverview(state, action);
}
