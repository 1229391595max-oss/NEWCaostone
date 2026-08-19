const localeByLanguage = Object.freeze({ en: "en-US", zh: "zh-CN" });
const invalidDisplay = "—";

function locale(language) {
  const selected = localeByLanguage[language];
  if (!selected) throw new Error("LANGUAGE_INVALID");
  return selected;
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function displayNumber(value, language, options) {
  const selectedLocale = locale(language);
  const number = finiteNumber(value);
  if (number === null) return invalidDisplay;
  return new Intl.NumberFormat(selectedLocale, options)
    .format(number)
    .replaceAll("\u00a0", "")
    .replaceAll("\u202f", "");
}

export function formatBrl(value, language) {
  return displayNumber(value, language, {
    style: "currency",
    currency: "BRL",
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatDecimal(value, language) {
  return displayNumber(value, language, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  });
}

export function formatDays(value, language) {
  const formatted = formatDecimal(value, language);
  if (formatted === invalidDisplay) return formatted;
  return `${formatted} ${language === "zh" ? "天" : "days"}`;
}

export function formatScore(value, language) {
  return formatDecimal(value, language);
}

export function formatInteger(value, language) {
  return displayNumber(value, language, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

export function formatPercentRatio(value, language) {
  const selectedLocale = locale(language);
  const number = finiteNumber(value);
  if (number === null) return invalidDisplay;
  return new Intl.NumberFormat(selectedLocale, {
    style: "percent",
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  })
    .format(number)
    .replaceAll("\u00a0", "")
    .replaceAll("\u202f", "");
}
