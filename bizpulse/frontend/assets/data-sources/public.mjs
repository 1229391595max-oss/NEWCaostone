import { demoMutationHeaders } from "../core/auth-session.mjs";
import { scopeQuery } from "../features/store-scope/state.mjs";

function scopedPath(path, scope, initial = null) {
  const query = initial instanceof URLSearchParams
    ? new URLSearchParams(initial)
    : new URLSearchParams(initial ?? undefined);
  if (scope) {
    for (const [name, value] of scopeQuery(scope)) query.append(name, value);
  }
  const encoded = query.toString();
  return encoded ? `${path}?${encoded}` : path;
}

const allowedKinds = new Set([
  "sales_ads",
  "inventory_risk",
  "fifo_cost_aging",
  "operating_profit",
  "replenishment",
]);

export const PUBLIC_DATA_CAPABILITIES = Object.freeze([
  "release",
  "analysis",
  "forecast",
  "profit_bridge",
  "action_overlay",
  "chat",
  "library",
]);

export class PublicDataSource {
  constructor(apiClient, expectedVersionId) {
    this.apiClient = apiClient;
    this.expectedVersionId = expectedVersionId;
    this.capabilities = PUBLIC_DATA_CAPABILITIES;
  }

  loadRelease() {
    return this.apiClient.request("/api/demo/release/current", {
      cache: "no-store",
    });
  }

  importDemoData() {
    return this.apiClient.request(
      "/api/demo/sessions/current/import-demo-data",
      {
        method: "POST",
        headers: demoMutationHeaders(),
      },
    );
  }

  loadLibrary(scope = null) {
    return this.apiClient.request(scopedPath("/api/demo/library/current", scope), {
      cache: "no-store",
    });
  }

  loadLibraryTable(role, { page = 1, pageSize = 50 } = {}, scope = null) {
    if (typeof role !== "string" || !role) {
      throw new Error("LIBRARY_TABLE_REQUIRED");
    }
    const query = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    return this.apiClient.request(
      scopedPath(
        `/api/demo/library/current/tables/${encodeURIComponent(role)}`,
        scope,
        query,
      ),
      { cache: "no-store" },
    );
  }

  loadSettings() {
    return this.apiClient.request("/api/demo/preferences", {
      cache: "no-store",
    });
  }

  async loadAnalysis(kind, scope = null) {
    if (!allowedKinds.has(kind)) throw new Error("ANALYSIS_KIND_INVALID");
    const payload = await this.apiClient.request(
      scopedPath(`/api/demo/release/analyses/${kind}`, scope),
      { cache: "no-store" },
    );
    if (payload?.run?.dataset_version_id !== this.expectedVersionId) {
      throw new Error("ANALYSIS_RELEASE_MISMATCH");
    }
    return payload;
  }

  async loadForecast(scope = null) {
    const payload = await this.apiClient.request(
      scopedPath("/api/demo/release/forecasts/latest", scope),
      { cache: "no-store" },
    );
    if (payload?.dataset_version_id !== this.expectedVersionId) {
      throw new Error("FORECAST_RELEASE_MISMATCH");
    }
    return payload;
  }

  async loadProfitBridge(scope = null) {
    const payload = await this.apiClient.request(
      scopedPath("/api/demo/release/profit-bridge/current", scope),
      { cache: "no-store" },
    );
    if (payload?.dataset_version_id !== this.expectedVersionId) {
      throw new Error("PROFIT_BRIDGE_RELEASE_MISMATCH");
    }
    return payload;
  }

  async loadActions(scope = null) {
    const payload = await this.apiClient.request(
      scopedPath("/api/demo/release/actions", scope),
      { cache: "no-store" },
    );
    const items = await Promise.all((payload?.items ?? []).map(async (item) => {
      if (item.dataset_version_id !== this.expectedVersionId) {
        throw new Error("ACTION_RELEASE_MISMATCH");
      }
      const overlays = await this.apiClient.request(
        scopedPath(`/api/demo/actions/${encodeURIComponent(item.id)}/overlays`, scope),
        { cache: "no-store" },
      );
      return { ...item, viewer_overlays: overlays?.items ?? [] };
    }));
    return { items };
  }

  commandAction(actionId, payload, idempotencyKey) {
    return this.apiClient.request(
      `/api/demo/actions/${encodeURIComponent(actionId)}/commands`,
      {
        method: "POST",
        headers: demoMutationHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        }),
        body: JSON.stringify(payload),
      },
    );
  }

  resetActionSandbox(scope = null) {
    return this.apiClient.request(scopedPath("/api/demo/action-sandbox", scope), {
      method: "DELETE",
      headers: demoMutationHeaders(),
    });
  }

  listChatTurns() {
    return this.apiClient.request("/api/v1/ai-chat/turns", { cache: "no-store" });
  }

  submitChatTurn(payload, idempotencyKey) {
    return this.apiClient.request("/api/v1/ai-chat/turns", {
      method: "POST",
      headers: demoMutationHeaders({
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      }),
      body: JSON.stringify(payload),
    });
  }

  createChatActionDraft(turnId, idempotencyKey) {
    return this.apiClient.request(
      `/api/v1/ai-chat/turns/${encodeURIComponent(turnId)}/action-card-drafts`,
      {
        method: "POST",
        headers: demoMutationHeaders({ "Idempotency-Key": idempotencyKey }),
      },
    );
  }

  deleteChatSession() {
    return this.apiClient.request("/api/v1/ai-chat/session", {
      method: "DELETE",
      headers: demoMutationHeaders(),
    });
  }
}
