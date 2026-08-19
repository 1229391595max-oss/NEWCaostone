export function initialAskBizPulseState(release, mode, scope = null) {
  return {
    release,
    mode,
    scope,
    status: "idle",
    turns: [],
    savedTurns: [],
    recommendedQuestions: [],
    availability: "available",
    unavailableCode: null,
    generation: 0,
    submitting: false,
    sessionEnding: false,
    draftText: "",
    selectedPreset: null,
    pendingReplacement: null,
    composerFocused: false,
    draftTurnId: null,
    savingTurnId: null,
    context: null,
    error: null,
  };
}

function sameGeneration(state, action) {
  return action.generation === state.generation;
}

function upsertTurn(turns, incoming) {
    const next = turns.filter((item) => item.id !== incoming.id);
    next.push(incoming);
    return next.sort((left, right) =>
    Number(left.turn_sequence ?? 0) - Number(right.turn_sequence ?? 0)
  );
}

export function reduceAskBizPulse(state, action) {
  if (action.type === "chat/preset-fill-requested") {
    if (!action.preset?.id || typeof action.preset?.template !== "string") return state;
    if (state.draftText.trim()) {
      return {
        ...state,
        pendingReplacement: action.preset,
        composerFocused: false,
      };
    }
    return {
      ...state,
      draftText: action.preset.template,
      selectedPreset: action.preset,
      pendingReplacement: null,
      composerFocused: true,
    };
  }
  if (action.type === "chat/preset-replacement-confirmed") {
    if (!state.pendingReplacement) return state;
    return {
      ...state,
      draftText: state.pendingReplacement.template,
      selectedPreset: state.pendingReplacement,
      pendingReplacement: null,
      composerFocused: true,
    };
  }
  if (action.type === "chat/preset-replacement-kept") {
    return {
      ...state,
      pendingReplacement: null,
      composerFocused: true,
    };
  }
  if (action.type === "chat/draft-changed") {
    const draftText = String(action.value ?? "");
    return {
      ...state,
      draftText,
      selectedPreset: state.selectedPreset?.template === draftText
        ? state.selectedPreset
        : null,
      pendingReplacement: null,
    };
  }
  if (action.type === "chat/composer-focus-consumed") {
    return { ...state, composerFocused: false };
  }
  if (action.type === "chat/loading") {
    return {
      ...state,
      status: "loading",
      generation: action.generation,
      error: null,
    };
  }
  if (action.type === "chat/loaded") {
    if (!sameGeneration(state, action)) return state;
    return {
      ...state,
      status: "ready",
      turns: [...(action.payload?.items ?? [])],
      savedTurns: [...(action.payload?.saved_items ?? [])],
      recommendedQuestions: [...(action.payload?.recommended_questions ?? [])],
      availability: action.payload?.availability === "unavailable"
        ? "unavailable"
        : "available",
      unavailableCode: action.payload?.unavailable_code === "AI_CHAT_UNAVAILABLE"
        ? "AI_CHAT_UNAVAILABLE"
        : null,
      error: null,
    };
  }
  if (action.type === "chat/load-failed") {
    if (!sameGeneration(state, action)) return state;
    return {
      ...state,
      status: "error",
      turns: [],
      savedTurns: [],
      error: action.error ?? "AI_CHAT_UNAVAILABLE",
    };
  }
  if (action.type === "chat/submitting") {
    if (!sameGeneration(state, action)) return state;
    return { ...state, submitting: true, error: null };
  }
  if (action.type === "chat/submitted") {
    if (!sameGeneration(state, action)) return state;
    return {
      ...state,
      status: "ready",
      submitting: false,
      draftText: "",
      selectedPreset: null,
      pendingReplacement: null,
      composerFocused: false,
      turns: upsertTurn(state.turns, action.payload),
      error: null,
    };
  }
  if (action.type === "chat/submit-failed") {
    if (!sameGeneration(state, action)) return state;
    return { ...state, submitting: false, error: action.error ?? "AI_CHAT_UNAVAILABLE" };
  }
  if (action.type === "chat/drafting") {
    if (!sameGeneration(state, action)) return state;
    return { ...state, draftTurnId: action.turnId, error: null };
  }
  if (action.type === "chat/drafted") {
    if (!sameGeneration(state, action)) return state;
    return {
      ...state,
      draftTurnId: null,
      turns: upsertTurn(state.turns, action.payload),
      error: null,
    };
  }
  if (action.type === "chat/draft-failed") {
    if (!sameGeneration(state, action)) return state;
    return { ...state, draftTurnId: null, error: action.error ?? "AI_CHAT_UNAVAILABLE" };
  }
  if (action.type === "chat/saving") {
    if (!sameGeneration(state, action)) return state;
    return { ...state, savingTurnId: action.turnId, error: null };
  }
  if (action.type === "chat/saved") {
    if (!sameGeneration(state, action)) return state;
    return {
      ...state,
      savingTurnId: null,
      turns: upsertTurn(state.turns, action.payload),
      error: null,
    };
  }
  if (action.type === "chat/save-failed") {
    if (!sameGeneration(state, action)) return state;
    return { ...state, savingTurnId: null, error: action.error ?? "AI_CHAT_UNAVAILABLE" };
  }
  if (action.type === "chat/context-selected") {
    return {
      ...state,
      status: state.status === "loading" ? "idle" : state.status,
      generation: action.generation ?? state.generation + 1,
      submitting: false,
      context: action.context ?? null,
      selectedPreset: null,
      pendingReplacement: null,
      error: null,
    };
  }
  if (action.type === "chat/session-ending") {
    return {
      ...state,
      generation: action.generation,
      submitting: false,
      sessionEnding: true,
      draftTurnId: null,
      savingTurnId: null,
      pendingReplacement: null,
      error: null,
    };
  }
  if (action.type === "chat/session-end-failed") {
    if (!sameGeneration(state, action)) return state;
    return {
      ...state,
      sessionEnding: false,
      error: action.error ?? "AI_CHAT_UNAVAILABLE",
    };
  }
  if (action.type === "chat/session-ended") {
    return {
      ...state,
      status: "ready",
      turns: [],
      savedTurns: [],
      generation: action.generation ?? state.generation + 1,
      submitting: false,
      sessionEnding: false,
      draftText: "",
      selectedPreset: null,
      pendingReplacement: null,
      composerFocused: false,
      draftTurnId: null,
      savingTurnId: null,
      context: null,
      error: null,
    };
  }
  return state;
}
