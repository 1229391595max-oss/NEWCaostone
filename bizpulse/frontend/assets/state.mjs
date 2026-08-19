const initialState = Object.freeze({
  activeRoute: "workspace",
  language: "en",
  decisionContext: null,
});

let state = { ...initialState };

export function getState() {
  return {
    ...state,
    decisionContext: state.decisionContext
      ? { ...state.decisionContext }
      : null,
  };
}

export function setActiveRoute(activeRoute, decisionContext = null) {
  state = {
    ...state,
    activeRoute,
    decisionContext: activeRoute === "briefing"
      ? safeDecisionContext(decisionContext)
      : null,
  };
  return getState();
}

export function toggleLanguage() {
  state = { ...state, language: state.language === "en" ? "zh" : "en" };
  return getState();
}

function safeDecisionContext(value) {
  if (value === null) return null;
  const allowedKinds = new Set([
    "inventory_analysis",
    "profit_bridge",
    "forecast",
    "action_cards",
  ]);
  const expectedReferences = {
    inventory_analysis: "inventory_analysis:pinned",
    profit_bridge: "profit_bridge:pinned",
    forecast: "forecast:pinned",
    action_cards: "action_cards:pinned",
  };
  if (
    !value ||
    typeof value !== "object" ||
    !allowedKinds.has(value.kind) ||
    typeof value.reference !== "string" ||
    value.reference !== expectedReferences[value.kind]
  ) {
    throw new Error("DECISION_CONTEXT_INVALID");
  }
  return { kind: value.kind, reference: value.reference };
}
