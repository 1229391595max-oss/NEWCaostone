import assert from "node:assert/strict";
import { test } from "node:test";

import {
  formatBrl,
  formatDays,
  formatDecimal,
  formatInteger,
  formatPercentRatio,
  formatScore,
} from "../../frontend/assets/core/formatters.mjs";

test("display formatters round only at the UI boundary", () => {
  assert.equal(formatBrl("1234.567", "en"), "R$1,234.57");
  assert.equal(formatDecimal("8.500", "en"), "8.5");
  assert.equal(formatDays("12.345", "en"), "12.35 days");
  assert.equal(formatInteger("42.9", "en"), "43");
  assert.equal(formatPercentRatio("0.12345", "en"), "12.35%");
  assert.equal(formatScore("98.765", "en"), "98.77");
});

test("invalid display values use an em dash", () => {
  for (const value of [null, undefined, "", "not-a-number", Infinity, NaN]) {
    assert.equal(formatBrl(value, "en"), "—");
    assert.equal(formatDecimal(value, "zh"), "—");
  }
});

test("formatting never mutates the raw API value", () => {
  const raw = Object.freeze({ amount: "1234.567", ratio: "0.12345" });

  formatBrl(raw.amount, "en");
  formatPercentRatio(raw.ratio, "zh");

  assert.deepEqual(raw, { amount: "1234.567", ratio: "0.12345" });
});

test("formatters reject an unsupported language", () => {
  assert.throws(() => formatDecimal("1", "pt"), /LANGUAGE_INVALID/);
});
