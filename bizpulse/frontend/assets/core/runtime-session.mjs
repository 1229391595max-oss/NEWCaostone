export function runtimeModeForPath(pathname) {
  const normalized = pathname.replace(/\/+$/, "") || "/";
  if (normalized === "/demo") return "viewer";
  if (normalized === "/app") return "operator";
  throw new Error("RUNTIME_PATH_INVALID");
}

export class RuntimeSessionController {
  constructor(apiClient) {
    this.apiClient = apiClient;
    this.generation = 0;
    this.state = { status: "idle", mode: null, release: null, error: null };
  }

  async load(mode) {
    if (mode !== "viewer" && mode !== "operator") {
      throw new Error("RUNTIME_MODE_INVALID");
    }
    const generation = ++this.generation;
    this.state = { status: "loading", mode, release: null, error: null };
    try {
      let principal = null;
      let release;
      if (mode === "viewer") {
        principal = await this.apiClient.request("/api/demo/sessions/current", {
          cache: "no-store",
        });
        if (generation !== this.generation) return { stale: true };
        release = principal?.session?.demo_data_imported
          ? await this.apiClient.request("/api/demo/release/current", {
            cache: "no-store",
          })
          : null;
      } else {
        try {
          release = await this.apiClient.request(
            "/api/v1/datasets/public-release",
            { cache: "no-store" },
          );
        } catch (error) {
          if (error?.status === 404 && error?.code === "PUBLIC_RELEASE_NOT_FOUND") {
            release = null;
          } else {
            throw error;
          }
        }
      }
      if (generation !== this.generation) return { stale: true };
      if (
        mode === "viewer" &&
        principal?.session?.demo_data_imported &&
        principal?.session?.dataset_version_id !== release?.dataset_version_id
      ) {
        throw new Error("SESSION_RELEASE_MISMATCH");
      }
      this.state = {
        status: "ready",
        mode,
        principal,
        release,
        error: null,
      };
      return { ...this.state };
    } catch (error) {
      if (generation !== this.generation) return { stale: true };
      this.state = {
        status: "error",
        mode,
        release: null,
        error: error.code ?? error.message ?? "RUNTIME_UNAVAILABLE",
      };
      return { ...this.state };
    }
  }
}

export class ViewerExpiryGuard {
  constructor(
    apiClient,
    {
      onExpired,
      now = () => Date.now(),
      setTimer = (callback, delay) => globalThis.setTimeout(callback, delay),
      clearTimer = (timer) => globalThis.clearTimeout(timer),
    },
  ) {
    this.apiClient = apiClient;
    this.onExpired = onExpired;
    this.now = now;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.timer = null;
  }

  start(session) {
    this.stop();
    const idle = Date.parse(session?.idle_expires_at ?? "");
    const absolute = Date.parse(session?.absolute_expires_at ?? "");
    const expiresAt = Math.min(idle, absolute);
    if (!Number.isFinite(expiresAt)) {
      this.onExpired();
      return;
    }
    const delay = Math.max(0, Math.min(expiresAt - this.now(), 2_147_483_647));
    this.timer = this.setTimer(async () => {
      try {
        const payload = await this.apiClient.request("/api/demo/sessions/current", {
          cache: "no-store",
        });
        this.start(payload.session);
      } catch {
        this.stop();
        this.onExpired();
      }
    }, delay);
  }

  stop() {
    if (this.timer !== null) this.clearTimer(this.timer);
    this.timer = null;
  }
}
