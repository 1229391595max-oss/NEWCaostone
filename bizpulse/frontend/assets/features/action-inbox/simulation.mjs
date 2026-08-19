const unavailable = "unavailable";
const MAX_QUANTITY = 1_000_000n;
const MAX_BUDGET_CENTS = 100_000_000_000n;

function parseQuantity(value) {
  const text = typeof value === "string" ? value : "";
  if (!/^(?:0|[1-9]\d*)$/.test(text) || text.length > 7) return null;
  const quantity = BigInt(text);
  return quantity <= MAX_QUANTITY ? quantity : null;
}

function parseCents(value) {
  const text = typeof value === "string" ? value : "";
  const match = /^(0|[1-9]\d*)(?:\.(\d{1,2}))?$/.exec(text);
  if (!match || match[1].length > 10) return null;
  const cents = BigInt(match[1]) * 100n
    + BigInt((match[2] ?? "").padEnd(2, "0") || "0");
  return cents <= MAX_BUDGET_CENTS ? cents : null;
}

function parsePositiveDecimal(value) {
  const text = typeof value === "string" ? value : "";
  const match = /^(0|[1-9]\d*)(?:\.(\d{1,6}))?$/.exec(text);
  if (!match || match[1].length > 10) return null;
  const fraction = match[2] ?? "";
  const scale = 10n ** BigInt(fraction.length);
  const numerator = BigInt(match[1]) * scale + BigInt(fraction || "0");
  return numerator > 0n ? { numerator, scale } : null;
}

function formatCents(cents) {
  const negative = cents < 0n;
  const absolute = negative ? -cents : cents;
  return `${negative ? "-" : ""}${absolute / 100n}.${String(absolute % 100n).padStart(2, "0")}`;
}

function formatRatio(numerator, denominator) {
  const hundredths = (numerator * 100n + denominator / 2n) / denominator;
  const whole = hundredths / 100n;
  const fraction = String(hundredths % 100n).padStart(2, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : String(whole);
}

export function normalizeSimulationAdjustment({ quantity, budgetBrl }) {
  const parsedQuantity = quantity === "" ? null : parseQuantity(quantity);
  const parsedBudget = budgetBrl === "" ? null : parseCents(budgetBrl);
  if ((quantity !== "" && parsedQuantity === null) || (budgetBrl !== "" && parsedBudget === null)) {
    throw new Error("ACTION_SIMULATION_INPUT_INVALID");
  }
  const adjustment = {};
  if (parsedQuantity !== null) adjustment.quantity = String(parsedQuantity);
  if (parsedBudget !== null) adjustment.budget_brl = formatCents(parsedBudget);
  if (!Object.keys(adjustment).length) throw new Error("ACTION_SIMULATION_INPUT_INVALID");
  return adjustment;
}

export function estimateSimulation(input) {
  const quantity = parseQuantity(input?.quantity);
  const unitCost = parseCents(input?.unitCostBrl);
  const simulatedBudget = parseCents(input?.simulatedBudgetBrl);
  const baselineBudget = parseCents(input?.baselineBudgetBrl);
  const velocity = parsePositiveDecimal(input?.precomputedDailyVelocity);

  return {
    purchaseCashBrl: quantity !== null && unitCost !== null
      ? formatCents(quantity * unitCost)
      : unavailable,
    budgetDeltaBrl: simulatedBudget !== null && baselineBudget !== null
      ? formatCents(simulatedBudget - baselineBudget)
      : unavailable,
    additionalCoverDays: quantity !== null && velocity !== null
      ? formatRatio(quantity * velocity.scale, velocity.numerator)
      : unavailable,
  };
}
