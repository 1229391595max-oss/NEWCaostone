import { mutationHeaders } from "../core/auth-session.mjs";
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

export const OPERATOR_DATA_CAPABILITIES = Object.freeze([
  "release",
  "analysis",
  "forecast",
  "profit_bridge",
  "action",
  "chat",
  "import",
  "mapping",
  "commit",
  "publish",
  "prepare",
  "runProfitBridge",
  "createForecast",
  "exportAction",
  "recordActionOutcome",
  "library",
  "exportDataset",
]);

export class OperatorDataSource {
  constructor(apiClient, expectedVersionId) {
    this.apiClient = apiClient;
    this.expectedVersionId = expectedVersionId;
    this.capabilities = OPERATOR_DATA_CAPABILITIES;
  }

  forVersion(versionId) {
    if (typeof versionId !== "string" || !versionId) {
      throw new Error("DATASET_VERSION_REQUIRED");
    }
    return new OperatorDataSource(this.apiClient, versionId);
  }

  async loadRelease() {
    try {
      return await this.apiClient.request("/api/v1/datasets/public-release", {
        cache: "no-store",
      });
    } catch (error) {
      if (error?.status === 404 && error?.code === "PUBLIC_RELEASE_NOT_FOUND") {
        return null;
      }
      throw error;
    }
  }

  async loadAnalysis(kind, scope = null) {
    if (!allowedKinds.has(kind)) throw new Error("ANALYSIS_KIND_INVALID");
    if (this.expectedVersionId === null) {
      throw new Error("PUBLIC_RELEASE_NOT_FOUND");
    }
    const payload = await this.apiClient.request(
      scopedPath(
        `/api/v1/analyses/versions/${encodeURIComponent(this.expectedVersionId)}/${kind}`,
        scope,
      ),
      { cache: "no-store" },
    );
    if (payload?.run?.dataset_version_id !== this.expectedVersionId) {
      throw new Error("ANALYSIS_RELEASE_MISMATCH");
    }
    return payload;
  }

  listVersions() {
    return this.apiClient.request("/api/v1/datasets/versions", {
      cache: "no-store",
    });
  }

  listLibraryVersions() {
    return this.apiClient.request("/api/v1/library", { cache: "no-store" });
  }

  loadLibraryVersion(versionId, scope = null) {
    if (typeof versionId !== "string" || !versionId) {
      throw new Error("DATASET_VERSION_REQUIRED");
    }
    return this.apiClient.request(
      scopedPath(`/api/v1/library/${encodeURIComponent(versionId)}`, scope),
      { cache: "no-store" },
    );
  }

  loadLibraryTable(versionId, role, { page = 1, pageSize = 50 } = {}, scope = null) {
    if (typeof versionId !== "string" || !versionId) {
      throw new Error("DATASET_VERSION_REQUIRED");
    }
    if (typeof role !== "string" || !role) {
      throw new Error("LIBRARY_TABLE_REQUIRED");
    }
    const query = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    });
    return this.apiClient.request(
      scopedPath(
        `/api/v1/library/${encodeURIComponent(versionId)}/tables/${encodeURIComponent(role)}`,
        scope,
        query,
      ),
      { cache: "no-store" },
    );
  }

  loadSettings() {
    return this.apiClient.request("/api/v1/preferences", { cache: "no-store" });
  }

  saveSettings(payload) {
    return this.apiClient.request("/api/v1/preferences", {
      method: "PUT",
      headers: mutationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
  }

  createSavedView(payload) {
    return this.apiClient.request("/api/v1/preferences/saved-views", {
      method: "POST",
      headers: mutationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
  }

  updateSavedView(viewId, payload) {
    return this.apiClient.request(
      `/api/v1/preferences/saved-views/${encodeURIComponent(viewId)}`,
      {
        method: "PUT",
        headers: mutationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(payload),
      },
    );
  }

  deleteSavedView(viewId, revision) {
    return this.apiClient.request(
      `/api/v1/preferences/saved-views/${encodeURIComponent(viewId)}?expected_revision=${encodeURIComponent(revision)}`,
      { method: "DELETE", headers: mutationHeaders() },
    );
  }

  createTarget(payload) {
    return this.apiClient.request("/api/v1/preferences/targets", {
      method: "POST",
      headers: mutationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
  }

  setTargetStatus(targetId, payload) {
    return this.apiClient.request(
      `/api/v1/preferences/targets/${encodeURIComponent(targetId)}`,
      {
        method: "PATCH",
        headers: mutationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify(payload),
      },
    );
  }

  generateDatasetExport(versionId, idempotencyKey) {
    return this.apiClient.request(
      `/api/v1/datasets/versions/${encodeURIComponent(versionId)}/exports`,
      {
        method: "POST",
        headers: mutationHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        }),
        body: JSON.stringify({ format: "xlsx" }),
      },
    );
  }

  datasetExportDownloadUrl(versionId, exportId) {
    return `/api/v1/datasets/versions/${encodeURIComponent(versionId)}/exports/${encodeURIComponent(exportId)}/download`;
  }

  conflictDownloadUrl(workflowId) {
    return `/api/v1/import-workflows/${encodeURIComponent(workflowId)}/conflicts.csv`;
  }

  prepare() {
    if (this.expectedVersionId === null) {
      throw new Error("DATASET_VERSION_REQUIRED");
    }
    return this.apiClient.request(
      `/api/v1/datasets/versions/${encodeURIComponent(this.expectedVersionId)}/prepare`,
      { method: "POST", headers: mutationHeaders() },
    );
  }

  publish(datasetVersionId, expectedCurrentId, idempotencyKey) {
    return this.apiClient.request(
      `/api/v1/datasets/versions/${encodeURIComponent(datasetVersionId)}/publish`,
      {
        method: "POST",
        headers: mutationHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        }),
        body: JSON.stringify({ expected_current_id: expectedCurrentId }),
      },
    );
  }

  async loadForecast(scope = null) {
    if (this.expectedVersionId === null) return null;
    const payload = await this.apiClient.request(
      scopedPath("/api/v1/forecasts/latest", scope, {
        dataset_version_id: this.expectedVersionId,
      }),
      { cache: "no-store" },
    );
    if (payload?.dataset_version_id !== this.expectedVersionId) {
      throw new Error("FORECAST_RELEASE_MISMATCH");
    }
    return payload;
  }

  async loadProfitBridge(scope = null) {
    if (this.expectedVersionId === null) return null;
    const payload = await this.apiClient.request(
      scopedPath("/api/v1/profit-bridges/default", scope, {
        dataset_version_id: this.expectedVersionId,
      }),
      { cache: "no-store" },
    );
    if (payload?.dataset_version_id !== this.expectedVersionId) {
      throw new Error("PROFIT_BRIDGE_RELEASE_MISMATCH");
    }
    return payload;
  }

  runProfitBridge(payload) {
    if (payload?.dataset_version_id !== this.expectedVersionId) {
      throw new Error("PROFIT_BRIDGE_RELEASE_MISMATCH");
    }
    return this.apiClient.request("/api/v1/profit-bridges", {
      method: "POST",
      headers: mutationHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
  }

  createForecast(payload, idempotencyKey) {
    if (payload?.dataset_version_id !== this.expectedVersionId) {
      throw new Error("FORECAST_RELEASE_MISMATCH");
    }
    return this.apiClient.request("/api/v1/forecasts", {
      method: "POST",
      headers: mutationHeaders({
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      }),
      body: JSON.stringify(payload),
    });
  }

  confirmForecast(forecastId, skuIds) {
    return this.apiClient.request(
      `/api/v1/forecasts/${encodeURIComponent(forecastId)}/analogs/confirm`,
      {
        method: "POST",
        headers: mutationHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ sku_ids: skuIds }),
      },
    );
  }

  runForecast(forecastId) {
    return this.apiClient.request(
      `/api/v1/forecasts/${encodeURIComponent(forecastId)}/run`,
      { method: "POST", headers: mutationHeaders() },
    );
  }

  async loadActions(scope = null) {
    if (this.expectedVersionId === null) return { items: [] };
    const payload = await this.apiClient.request(
      scopedPath("/api/v1/actions", scope, {
        dataset_version_id: this.expectedVersionId,
      }),
      { cache: "no-store" },
    );
    if ((payload?.items ?? []).some((item) => item.dataset_version_id !== this.expectedVersionId)) {
      throw new Error("ACTION_RELEASE_MISMATCH");
    }
    return payload;
  }

  commandAction(actionId, payload, idempotencyKey) {
    return this.apiClient.request(
      `/api/v1/actions/${encodeURIComponent(actionId)}/commands`,
      {
        method: "POST",
        headers: mutationHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        }),
        body: JSON.stringify({ ...payload, dataset_version_id: this.expectedVersionId }),
      },
    );
  }

  exportAction(actionId, payload, idempotencyKey) {
    return this.apiClient.request(
      `/api/v1/actions/${encodeURIComponent(actionId)}/exports`,
      {
        method: "POST",
        headers: mutationHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        }),
        body: JSON.stringify({ ...payload, dataset_version_id: this.expectedVersionId }),
      },
    );
  }

  recordActionOutcome(actionId, payload, idempotencyKey) {
    return this.apiClient.request(
      `/api/v1/actions/${encodeURIComponent(actionId)}/outcomes`,
      {
        method: "POST",
        headers: mutationHeaders({
          "Content-Type": "application/json",
          "Idempotency-Key": idempotencyKey,
        }),
        body: JSON.stringify({ ...payload, dataset_version_id: this.expectedVersionId }),
      },
    );
  }

  actionExportDownloadUrl(actionId, exportId) {
    return `/api/v1/actions/${encodeURIComponent(actionId)}/exports/${encodeURIComponent(exportId)}/download`;
  }

  listChatTurns() {
    return this.apiClient.request("/api/v1/ai-chat/turns", { cache: "no-store" });
  }

  submitChatTurn(payload, idempotencyKey) {
    return this.apiClient.request("/api/v1/ai-chat/turns", {
      method: "POST",
      headers: mutationHeaders({
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
        headers: mutationHeaders({ "Idempotency-Key": idempotencyKey }),
      },
    );
  }

  saveChatTurn(turnId) {
    return this.apiClient.request(
      `/api/v1/ai-chat/turns/${encodeURIComponent(turnId)}/save`,
      {
        method: "POST",
        headers: mutationHeaders(),
      },
    );
  }
}
