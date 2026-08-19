export class ApiError extends Error {
  constructor(code, status) {
    super(code);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export class ApiClient {
  constructor(fetchImpl, origin = globalThis.location?.origin ?? "http://local.invalid") {
    const selected = fetchImpl === undefined ? globalThis.fetch : fetchImpl;
    if (typeof selected !== "function") throw new Error("FETCH_REQUIRED");
    const parsedOrigin = new URL(origin).origin;
    if (parsedOrigin !== origin) throw new Error("ORIGIN_INVALID");
    this.origin = parsedOrigin;
    this.fetchImpl =
      fetchImpl === undefined ? selected.bind(globalThis) : selected;
  }

  async request(path, options) {
    if (
      typeof path !== "string" ||
      !path.startsWith("/") ||
      path.includes("\\") ||
      new URL(path, this.origin).origin !== this.origin
    ) {
      throw new Error("SAME_ORIGIN_PATH_REQUIRED");
    }
    const response = await this.fetchImpl(path, {
      credentials: "same-origin",
      ...options,
    });
    const contentType = response.headers?.get?.("content-type") ?? "";
    const payload = contentType.includes("application/json")
      ? await response.json()
      : null;
    if (!response.ok) {
      throw new ApiError(payload?.code ?? "REQUEST_FAILED", response.status);
    }
    return payload;
  }
}
