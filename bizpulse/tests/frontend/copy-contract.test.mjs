import assert from "node:assert/strict";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const frontendRoot = fileURLToPath(new URL("../../frontend/", import.meta.url));
const assetsRoot = path.join(frontendRoot, "assets");

async function filesBelow(root, suffixes) {
  const entries = await readdir(root, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    const target = path.join(root, entry.name);
    if (entry.isDirectory()) return filesBelow(target, suffixes);
    return suffixes.some((suffix) => entry.name.endsWith(suffix)) ? [target] : [];
  }));
  return nested.flat();
}

async function joined(files) {
  return (await Promise.all(files.map((file) => readFile(file, "utf8")))).join("\n");
}

test("visible frontend sources contain no retired demo copy", async () => {
  const files = await filesBelow(frontendRoot, [".html", ".mjs"]);
  const visible = await joined(files);
  for (const retired of [
    /Operator sign in/i,
    /Course Demo/i,
    /Synthetic Demo Data/i,
    /纯合成演示/,
    /Period unavailable/i,
  ]) {
    assert.doesNotMatch(visible, retired);
  }
  const entryShells = (await joined([
    path.join(frontendRoot, "index.html"),
    path.join(frontendRoot, "login.html"),
    path.join(frontendRoot, "welcome.html"),
  ])).replaceAll("English / 中文", "");
  assert.doesNotMatch(entryShells, /\s\/\s[^<"']*[\u3400-\u9fff]/);
});

test("there are no nonfunctional decision-center entries", async () => {
  const source = await readFile(
    path.join(assetsRoot, "features/ask-bizpulse/view.mjs"),
    "utf8",
  );
  assert.doesNotMatch(source, /Product Opportunities|Favorites|Operating Advice/);
  assert.doesNotMatch(source, /handler \? "button" : "span"/);
});

test("feature views use the central formatter and one selected language", async () => {
  const featureNames = [
    "overview",
    "analysis",
    "inventory",
    "profit",
    "forecast",
    "action-inbox",
    "ask-bizpulse",
  ];
  const files = (await Promise.all(featureNames.map((name) => (
    filesBelow(path.join(assetsRoot, "features", name), [".mjs"])
  )))).flat().filter((file) => /view(?:-model)?\.mjs$/.test(file));
  const sources = await joined(files);
  assert.doesNotMatch(sources, /\.toFixed\(/);
  assert.doesNotMatch(sources, /new Intl\.NumberFormat/);
  assert.doesNotMatch(sources, /\s\/\s[^"'`]*[\u3400-\u9fff]/);
  assert.match(sources, /formatBrl|formatDecimal|formatInteger|formatPercentRatio/);
});

test("application tokens match the selected warm Product Theater language", async () => {
  const css = await readFile(path.join(assetsRoot, "styles.css"), "utf8");
  for (const token of ["#f6f5f1", "#efeee8", "#534ab7", "#eeedfe", "56px"]) {
    assert.match(css, new RegExp(token.replace("#", "\\#"), "i"));
  }
});

test("ordinary workspace views hide technical release labels and bilingual joins", async () => {
  const sources = await joined([
    path.join(frontendRoot, "index.html"),
    path.join(assetsRoot, "app.mjs"),
    path.join(assetsRoot, "features/workspace/public-view.mjs"),
    path.join(assetsRoot, "features/workspace/view.mjs"),
  ]);

  assert.doesNotMatch(sources, /Pinned|contentHash|schemaVersion|release-digest/);
  assert.doesNotMatch(sources, /Current v\$\{|Verify v\$\{|Publish v\$\{/);
  assert.doesNotMatch(
    sources.replaceAll("English / 中文", ""),
    /\s\/\s[^<"'`]*[\u3400-\u9fff]/,
  );
});

test("business pages replace uncontextual version and implementation labels with current data copy", async () => {
  const sources = await joined([
    path.join(assetsRoot, "features/analysis/view-model.mjs"),
    path.join(assetsRoot, "features/action-inbox/view-model.mjs"),
    path.join(assetsRoot, "features/forecast/view-model.mjs"),
    path.join(assetsRoot, "features/forecast/view.mjs"),
    path.join(assetsRoot, "features/ask-bizpulse/view-model.mjs"),
    path.join(assetsRoot, "features/profit/view-model.mjs"),
  ]);

  assert.doesNotMatch(sources, /`v\$\{state\.release\.version_number\}/);
  assert.doesNotMatch(sources, /context\.versionLabel} · \$\{payload\.formula_version/);
  assert.doesNotMatch(sources, /forecast\.datasetVersion|forecast\.algorithm/);
  assert.match(sources, /common\.currentDataset/);

  const catalog = await readFile(path.join(assetsRoot, "i18n/catalog.mjs"), "utf8");
  assert.doesNotMatch(catalog, /\bpinned\b|固定版本|固定的示例数据版本/i);
});
