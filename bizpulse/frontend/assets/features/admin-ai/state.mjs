const SAFE_ERROR_CODES = new Set([
  "ADMIN_AI_STATE_CONFLICT",
  "ADMIN_AI_OPERATION_BUSY",
  "ADMIN_AI_KEY_REJECTED",
  "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN",
  "ADMIN_AI_SECRET_UNAVAILABLE",
  "ADMIN_REAUTHENTICATION_FAILED",
  "RATE_LIMITED",
]);
const FINGERPRINT_PREFIX = /^[a-f0-9]{8,16}$/i;

function projectCredential(value) {
  if (!value || typeof value.configured !== "boolean") return null;
  const configured = value.configured;
  const fingerprint = value.fingerprint;
  const verifiedAt = value.verified_at;
  if (
    configured &&
    (
      typeof fingerprint !== "string" ||
      !FINGERPRINT_PREFIX.test(fingerprint) ||
      typeof verifiedAt !== "string" ||
      !Number.isFinite(new Date(verifiedAt).getTime())
    )
  ) {
    return null;
  }
  if (!configured && (fingerprint !== null || verifiedAt !== null)) return null;
  return {
    configured,
    fingerprint: configured ? fingerprint.toLowerCase() : null,
    verified_at: configured ? verifiedAt : null,
  };
}

export function projectAdminAIControl(value) {
  if (
    !value ||
    !Number.isSafeInteger(value.revision) ||
    value.revision < 0 ||
    typeof value.operator_enabled !== "boolean" ||
    typeof value.demo_enabled !== "boolean" ||
    !value.credential
  ) {
    return null;
  }
  const credential = projectCredential(value.credential);
  if (!credential) return null;

  return {
    revision: value.revision,
    operator_enabled: value.operator_enabled,
    demo_enabled: value.demo_enabled,
    credential,
  };
}

export function projectAdminAIRotation(value) {
  if (!value || !Number.isSafeInteger(value.revision) || value.revision < 0) return null;
  const credential = projectCredential(value.credential);
  return credential ? { revision: value.revision, credential } : null;
}

function safeError(code) {
  return SAFE_ERROR_CODES.has(code) ? code : "ADMIN_AI_SECRET_UNAVAILABLE";
}

function noticeFor(code) {
  if (code === "ADMIN_AI_STATE_CONFLICT") return "conflict";
  if (code === "ADMIN_AI_OPERATION_BUSY") return "busy";
  if (code === "ADMIN_AI_KEY_REJECTED") return "rejected";
  if (code === "ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN") return "unknown";
  if (code === "ADMIN_REAUTHENTICATION_FAILED") return "reauthentication";
  if (code === "RATE_LIMITED") return "rate-limited";
  return "rollback";
}

export function initialAdminAIState() {
  return {
    status: "idle",
    payload: null,
    operation: null,
    notice: null,
    error: null,
    refreshError: null,
  };
}

export function reduceAdminAI(state, action) {
  if (action.type === "load/started") {
    return {
      ...state,
      status: state.payload ? "refreshing" : "loading",
      refreshError: null,
    };
  }
  if (action.type === "load/succeeded") {
    const payload = projectAdminAIControl(action.payload);
    if (!payload) {
      return {
        ...state,
        status: state.payload ? "stale" : "failed",
        operation: null,
        error: "ADMIN_AI_SECRET_UNAVAILABLE",
        notice: "rollback",
      };
    }
    return {
      status: "ready",
      payload,
      operation: null,
      notice: state.notice,
      error: state.error,
      refreshError: null,
    };
  }
  if (action.type === "load/failed") {
    const error = safeError(action.code);
    if (action.preserveOutcome && state.payload) {
      return {
        ...state,
        status: "stale",
        operation: null,
        refreshError: error,
      };
    }
    return {
      ...state,
      status: state.payload ? "stale" : "failed",
      operation: null,
      error,
      notice: noticeFor(error),
      refreshError: null,
    };
  }
  if (action.type === "channels/started" || action.type === "rotation/started") {
    return {
      ...state,
      operation: action.type.startsWith("channels") ? "channels" : "rotation",
      notice: null,
      error: null,
      refreshError: null,
    };
  }
  if (action.type === "channels/succeeded" || action.type === "rotation/succeeded") {
    const payload = action.type.startsWith("channels")
      ? projectAdminAIControl(action.payload)
      : projectAdminAIRotation(action.payload);
    if (!payload) {
      return {
        ...state,
        operation: null,
        notice: "rollback",
        error: "ADMIN_AI_SECRET_UNAVAILABLE",
        refreshError: null,
      };
    }
    return {
      ...state,
      payload: action.type.startsWith("channels")
        ? payload
        : {
          ...state.payload,
          revision: payload.revision,
          credential: payload.credential,
        },
      operation: null,
      notice: action.type.startsWith("channels") ? "channels-saved" : "rotated",
      error: null,
      refreshError: null,
    };
  }
  if (action.type === "channels/failed" || action.type === "rotation/failed") {
    const error = safeError(action.code);
    return {
      ...state,
      operation: null,
      error,
      notice: noticeFor(error),
      refreshError: null,
    };
  }
  return state;
}
