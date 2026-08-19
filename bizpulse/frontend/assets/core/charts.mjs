import { formatBrl } from "./formatters.mjs";
import { t } from "../i18n/catalog.mjs";

function escapeText(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function metadata(spec) {
  const language = spec.language ?? "en";
  for (const field of ["title", "summary", "period", "definition", "version"]) {
    if (typeof spec[field] !== "string" || !spec[field]) {
      throw new Error("CHART_DATA_INVALID");
    }
  }
  return `<title>${escapeText(spec.title)}</title><desc>${escapeText(
    `${spec.summary} ${t(language, "chart.period")}: ${spec.period}. ${t(language, "chart.definition")}: ${spec.definition}. ${t(language, "chart.version")}: ${spec.version}.`,
  )}</desc>`;
}

function values(items) {
  if (
    !Array.isArray(items) ||
    items.length === 0 ||
    items.some(
      (item) =>
        !item ||
        typeof item.label !== "string" ||
        typeof item.value !== "number" ||
        !Number.isFinite(item.value) ||
        item.value < 0,
    )
  ) {
    throw new Error("CHART_DATA_INVALID");
  }
  return items;
}

function frame(spec, body) {
  const language = spec.language ?? "en";
  return `<svg viewBox="0 0 640 260" role="img" xmlns="http://www.w3.org/2000/svg">${metadata(spec)}${body}<text x="16" y="246" class="chart-meta">${escapeText(
    `${t(language, "chart.period")}: ${spec.period} · ${spec.definition} · ${spec.version}`,
  )}</text></svg>`;
}

export function lineChartSvg(spec) {
  const points = values(spec.points);
  const max = Math.max(...points.map((point) => point.value), 1);
  const step = points.length === 1 ? 0 : 580 / (points.length - 1);
  const coordinates = points
    .map((point, index) => `${30 + step * index},${210 - (point.value / max) * 170}`)
    .join(" ");
  const labels = axisLabelIndexes(points.length)
    .map(
      (index) =>
        `<text x="${30 + step * index}" y="226" text-anchor="middle">${escapeText(points[index].label)}</text>`,
    )
    .join("");
  return frame(
    spec,
    `<polyline class="chart-line" points="${coordinates}" fill="none"/>${labels}`,
  );
}

function axisLabelIndexes(length) {
  if (length <= 6) return Array.from({ length }, (_, index) => index);
  return [...new Set(
    Array.from({ length: 6 }, (_, index) =>
      Math.round((index * (length - 1)) / 5),
    ),
  )];
}

export function barChartSvg(spec) {
  const bars = [...values(spec.bars)].sort((left, right) => right.value - left.value);
  const max = Math.max(...bars.map((bar) => bar.value), 1);
  const body = bars
    .slice(0, 6)
    .map((bar, index) => {
      const y = 24 + index * 31;
      const width = (bar.value / max) * 360;
      return `<text x="16" y="${y + 16}">${escapeText(bar.label)}</text><rect class="chart-bar" x="220" y="${y}" width="${width}" height="20"/><text x="${228 + width}" y="${y + 16}">${escapeText(bar.value)}</text>`;
    })
    .join("");
  return frame(spec, body);
}

export function segmentedBarSvg(spec) {
  const segments = values(spec.segments);
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  if (total <= 0) throw new Error("CHART_DATA_INVALID");
  let offset = 16;
  const bars = segments
    .map((segment, index) => {
      const width = (segment.value / total) * 608;
      const current = offset;
      offset += width;
      return `<rect class="chart-segment chart-segment-${index + 1}" x="${current}" y="80" width="${width}" height="64"><title>${escapeText(segment.label)}: ${escapeText(segment.value)}</title></rect>`;
    })
    .join("");
  const legend = segments
    .map((segment, index) => {
      const x = 16 + (index % 2) * 300;
      const y = 174 + Math.floor(index / 2) * 24;
      return `<text x="${x}" y="${y}" class="chart-legend">${escapeText(segment.label)}: ${escapeText(segment.value)}</text>`;
    })
    .join("");
  return frame(
    {
      ...spec,
      summary: `${spec.summary} ${t(spec.language ?? "en", "chart.values")}: ${segments
        .map((segment) => `${segment.label}: ${segment.value}`)
        .join(", ")}`,
    },
    bars + legend,
  );
}

export function waterfallChartSvg(spec) {
  const language = spec.language ?? "en";
  if (
    typeof spec.baseline !== "number" ||
    !Number.isFinite(spec.baseline) ||
    typeof spec.current !== "number" ||
    !Number.isFinite(spec.current) ||
    !Array.isArray(spec.items) ||
    spec.items.length === 0 ||
    spec.items.some(
      (item) =>
        !item ||
        typeof item.label !== "string" ||
        !item.label ||
        (item.value !== null &&
          (typeof item.value !== "number" || !Number.isFinite(item.value))) ||
        !["measured", "derived", "assumed", "unknown"].includes(
          item.evidenceState,
        ),
    )
  ) {
    throw new Error("CHART_DATA_INVALID");
  }
  let running = spec.baseline;
  const steps = spec.items.map((item) => {
    const start = running;
    if (item.value !== null) running += item.value;
    return { ...item, start, end: running };
  });
  const valuesForScale = [
    0,
    spec.baseline,
    spec.current,
    ...steps.flatMap((item) => [item.start, item.end]),
  ];
  const low = Math.min(...valuesForScale);
  const high = Math.max(...valuesForScale);
  const padding = Math.max((high - low) * 0.12, 1);
  const scaleLow = low - padding;
  const scaleHigh = high + padding;
  const y = (value) => 210 - ((value - scaleLow) / (scaleHigh - scaleLow)) * 170;
  const columnWidth = 900 / (steps.length + 2);
  const totalBar = (value, index, label, className) => {
    const zeroY = y(0);
    const valueY = y(value);
    const x = 24 + index * columnWidth;
    return `<g><title>${escapeText(label)}: ${escapeText(signedBrl(value, language))}</title><rect class="${className}" x="${x}" y="${Math.min(zeroY, valueY)}" width="${Math.max(columnWidth - 16, 12)}" height="${Math.max(Math.abs(zeroY - valueY), 2)}"/><text x="${x + (columnWidth - 16) / 2}" y="238" text-anchor="middle">${escapeText(label)}</text><text x="${x + (columnWidth - 16) / 2}" y="252" text-anchor="middle">${escapeText(signedBrl(value, language))}</text></g>`;
  };
  const baseline = totalBar(
    spec.baseline,
    0,
    t(spec.language ?? "en", "chart.baseline"),
    "waterfall-total",
  );
  const drivers = steps
    .map((item, index) => {
      const x = 24 + (index + 1) * columnWidth;
      const center = x + (columnWidth - 16) / 2;
      if (item.value === null) {
        return `<g><title>${escapeText(item.label)}: ${escapeText(t(spec.language ?? "en", "common.unavailable"))}</title><rect class="waterfall-unknown" x="${x}" y="82" width="${Math.max(columnWidth - 16, 12)}" height="78"/><text x="${center}" y="300" text-anchor="end" transform="rotate(-48 ${center} 300)">${escapeText(item.label)}</text><text x="${center}" y="326" text-anchor="middle">${escapeText(t(spec.language ?? "en", "chart.unknown"))}</text></g>`;
      }
      const startY = y(item.start);
      const endY = y(item.end);
      const className = item.value >= 0 ? "waterfall-positive" : "waterfall-negative";
      return `<g><title>${escapeText(item.label)}: ${escapeText(signedBrl(item.value, language))}; ${escapeText(item.evidenceState)}</title><rect class="${className}" x="${x}" y="${Math.min(startY, endY)}" width="${Math.max(columnWidth - 16, 12)}" height="${Math.max(Math.abs(startY - endY), 2)}"/><text x="${center}" y="300" text-anchor="end" transform="rotate(-48 ${center} 300)">${escapeText(item.label)}</text><text x="${center}" y="326" text-anchor="middle">${escapeText(signedBrl(item.value, language))}</text></g>`;
    })
    .join("");
  const current = totalBar(
    spec.current,
    steps.length + 1,
    t(spec.language ?? "en", "chart.current"),
    "waterfall-total",
  );
  const describedItems = steps
    .map((item) => `${item.label}: ${item.value === null ? t(spec.language ?? "en", "common.unavailable") : signedBrl(item.value, spec.language ?? "en")} (${item.evidenceState})`)
    .join(", ");
  return `<svg viewBox="0 0 960 340" role="img" xmlns="http://www.w3.org/2000/svg">${metadata({
    ...spec,
    summary: `${spec.summary} ${t(language, "chart.baseline")}: ${signedBrl(spec.baseline, language)}. ${t(language, "chart.values")}: ${describedItems}. ${t(language, "chart.current")}: ${signedBrl(spec.current, language)}.`,
  })}<line class="waterfall-zero" x1="16" x2="944" y1="${y(0)}" y2="${y(0)}"/>${baseline}${drivers}${current}</svg>`;
}

function signedBrl(value, language = "en") {
  const prefix = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${prefix}${formatBrl(Math.abs(value), language)}`;
}
