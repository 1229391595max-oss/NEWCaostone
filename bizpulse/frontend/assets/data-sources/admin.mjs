import { mutationHeaders } from "../core/auth-session.mjs";

export class AdminDataSource {
  constructor(apiClient) {
    this.api = apiClient;
  }

  loadSummary() {
    return this.api.request("/api/v1/admin/summary", { cache: "no-store" });
  }

  loadAI() {
    return this.api.request("/api/v1/admin/ai", { cache: "no-store" });
  }

  updateChannels({
    expectedRevision,
    operatorEnabled,
    demoEnabled,
    currentPassword,
  }, idempotencyKey) {
    return this.api.request("/api/v1/admin/ai/channels", {
      method: "PATCH",
      headers: mutationHeaders({
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      }),
      body: JSON.stringify({
        expected_revision: expectedRevision,
        operator_enabled: operatorEnabled,
        demo_enabled: demoEnabled,
        current_password: currentPassword,
      }),
    });
  }

  rotateKey({
    expectedRevision,
    candidateKey,
    currentPassword,
  }, idempotencyKey) {
    return this.api.request("/api/v1/admin/ai/key-rotations", {
      method: "POST",
      headers: mutationHeaders({
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      }),
      body: JSON.stringify({
        expected_revision: expectedRevision,
        candidate_key: candidateKey,
        current_password: currentPassword,
      }),
    });
  }
}
