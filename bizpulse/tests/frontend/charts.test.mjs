import assert from "node:assert/strict";
import { test } from "node:test";

import {
  barChartSvg,
  lineChartSvg,
  segmentedBarSvg,
} from "../../frontend/assets/core/charts.mjs";

test("local SVG line chart is accessible and includes metric context", () => {
  const svg = lineChartSvg({
    title: "Net sales trend",
    summary: "Net sales rose across the selected period.",
    period: "2026-07-01 — 2026-07-30",
    definition: "Sum of net sales in BRL.",
    version: "v3",
    points: [
      { label: "Jul 1", value: 10 },
      { label: "Jul 2", value: 20 },
    ],
  });

  assert.match(svg, /<svg/);
  assert.match(svg, /role="img"/);
  assert.match(svg, /<title>Net sales trend<\/title>/);
  assert.match(svg, /2026-07-01 — 2026-07-30/);
  assert.match(svg, /Sum of net sales in BRL/);
  assert.match(svg, /v3/);
  assert.doesNotMatch(svg, /NaN|Infinity/);
});

test("long line series draws every point but limits overlapping axis labels", () => {
  const svg = lineChartSvg({
    title: "Daily trend",
    summary: "Thirty daily observations.",
    period: "2026-07",
    definition: "Daily BRL",
    version: "v1",
    points: Array.from({ length: 30 }, (_, index) => ({
      label: `2026-07-${String(index + 1).padStart(2, "0")}`,
      value: index + 1,
    })),
  });

  assert.equal(svg.match(/<polyline/g)?.length, 1);
  assert.ok((svg.match(/text-anchor="middle"/g)?.length ?? 0) <= 6);
  assert.match(svg, /2026-07-01/);
  assert.match(svg, /2026-07-30/);
});

test("bars are sorted and labels are escaped", () => {
  const svg = barChartSvg({
    title: "SKU comparison",
    summary: "Sorted descending.",
    period: "Jul",
    definition: "Units",
    version: "v1",
    bars: [
      { label: "Low", value: 1 },
      { label: "<script>High</script>", value: 9 },
    ],
  });

  assert.ok(svg.indexOf("&lt;script&gt;High") < svg.indexOf("Low"));
  assert.doesNotMatch(svg, /<script>/);
});

test("segmented bar rejects negative or non-finite values", () => {
  assert.throws(
    () =>
      segmentedBarSvg({
        title: "Risk",
        summary: "Risk distribution.",
        period: "Jul",
        definition: "SKU count",
        version: "v1",
        segments: [{ label: "Risk", value: -1 }],
      }),
    /CHART_DATA_INVALID/,
  );
});

test("segmented risk chart exposes a visible text legend and values in description", () => {
  const svg = segmentedBarSvg({
    title: "Inventory risk",
    summary: "Risk distribution.",
    period: "Jul",
    definition: "SKU count",
    version: "v1",
    segments: [
      { label: "stockout", value: 2 },
      { label: "balanced", value: 4 },
    ],
  });

  assert.match(svg, /Risk distribution\. Values: stockout: 2, balanced: 4/);
  assert.match(svg, />stockout: 2<\/text>/);
  assert.match(svg, />balanced: 4<\/text>/);
});
