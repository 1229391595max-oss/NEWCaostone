import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const frontendRoot = new URL("../../frontend/", import.meta.url);

async function read(relativePath) {
  return readFile(new URL(relativePath, frontendRoot), "utf8");
}

test("application shell exposes the approved six fully named primary regions", async () => {
  const html = await read("index.html");
  const routes = [...html.matchAll(/data-primary-route="([^"]+)"/g)].map(
    (match) => match[1],
  );

  assert.deepEqual(routes, [
    "workspace",
    "overview",
    "sales",
    "inventory",
    "profit",
    "briefing",
  ]);
  assert.match(html, /data-i18n="nav\.workspace"[^>]*>Data Workspace</);
  assert.match(html, /data-i18n="nav\.overview"[^>]*>Today Overview</);
  assert.match(html, /data-i18n="nav\.sales"[^>]*>Sales &amp; Advertising</);
  assert.match(html, /data-i18n="nav\.inventory"[^>]*>Inventory &amp; Replenishment</);
  assert.match(html, /data-i18n="nav\.profit"[^>]*>Profit &amp; Cost</);
  assert.match(html, /data-i18n="nav\.briefing"[^>]*>AI Decision Center</);
  assert.doesNotMatch(html, /data-primary-route="ask-bizpulse"/);
  assert.match(html, /data-settings-route="settings"/);
  assert.doesNotMatch(html, /Synthetic Demo Data|纯合成演示/);
});

test("compact navigation preserves localized tooltip and accessible names", async () => {
  const [html, app, css] = await Promise.all([
    read("index.html"),
    read("assets/app.mjs"),
    read("assets/styles.css"),
  ]);

  assert.match(html, /aria-label="Data Workspace"[^>]*data-primary-route="workspace"/);
  assert.match(app, /button\.dataset\.tooltip = button\.textContent/);
  assert.match(app, /button\.setAttribute\("aria-label", button\.textContent\)/);
  assert.match(css, /content:\s*attr\(data-tooltip\)/);
  assert.match(css, /@media \(max-width: 1024px\)/);
});

test("in-app language control remains visible and rerenders the current route", async () => {
  const [html, app] = await Promise.all([
    read("index.html"),
    read("assets/app.mjs"),
  ]);

  assert.match(html, /data-language-toggle/);
  assert.match(html, />English \/ 中文</);
  assert.match(app, /renderLanguage\(\);\s*renderReleaseLabels\(\);\s*renderScopeControl\(\);\s*activate\(getState\(\)\.activeRoute\);/);
});

test("all checked-in shells use local assets and bilingual catalog hooks", async () => {
  for (const filename of ["welcome.html", "login.html", "index.html", "admin.html"]) {
    const html = await read(filename);
    assert.doesNotMatch(html, /(?:src|href)="https?:\/\//i);
    assert.match(html, /data-i18n=/);
    assert.match(html, /Non-Production/);
  }

  assert.match(await read("welcome.html"), /href="\/assets\/welcome\.css"/);
  assert.doesNotMatch(await read("login.html"), /Synthetic Demo Data/);
  assert.ok((await read("assets/welcome.css")).length > 0);
});

test("operator workspace exposes the administrator entry without adding it to primary navigation", async () => {
  const [html, app] = await Promise.all([read("index.html"), read("assets/app.mjs")]);

  assert.match(
    html,
    /<a class="text-button" href="\/admin" data-admin-entry data-i18n="nav\.admin" aria-label="Administrator Console" title="Administrator Console" hidden>Administrator Console<\/a>/,
  );
  assert.doesNotMatch(html, /data-primary-route="admin"/);
  assert.match(app, /adminEntry\.hidden\s*=\s*mode\s*!==\s*"operator"/);
});

test("workspace administrator entry localizes its text and accessible name", async () => {
  const [html, app, catalog] = await Promise.all([
    read("index.html"),
    read("assets/app.mjs"),
    read("assets/i18n/catalog.mjs"),
  ]);

  assert.match(
    html,
    /data-admin-entry[^>]*data-i18n="nav\.admin"[^>]*aria-label="Administrator Console"[^>]*title="Administrator Console"/,
  );
  assert.match(app, /navigationButtons\s*=\s*\[\.\.\.routeButtons, settingsButton, adminEntry\]/);
  assert.match(catalog, /"nav\.admin": "Administrator Console"/);
  assert.match(catalog, /"nav\.admin": "管理控制台"/);
});

test("admin shell provides route navigation and a return to the protected workspace", async () => {
  const html = await read("admin.html");
  const routes = [...html.matchAll(/data-admin-route="([^"]+)"/g)].map(
    (match) => match[1],
  );

  assert.deepEqual(routes, ["overview", "data", "status", "ai"]);
  assert.match(html, /href="\/app"[^>]*>Return to workspace<\/a>/);
  assert.match(html, /aria-label="Administrator navigation"/);
  assert.doesNotMatch(html, /api[ _-]?key/i);
  assert.doesNotMatch(html, /gpt-/i);
});

test("admin navigation remains visible and named in the compact sidebar", async () => {
  const [html, css] = await Promise.all([
    read("admin.html"),
    read("assets/styles.css"),
  ]);
  const entries = [
    ["/admin", "overview", "概", "Overview · 概览"],
    ["/admin/data", "data", "数", "Data Management · 数据管理"],
    ["/admin/status", "status", "状", "System Status · 系统状态"],
    ["/admin/ai", "ai", "AI", "AI Management · AI 管理"],
    ["/app", "return", "返", "Return to workspace · 返回工作区"],
  ];

  for (const [href, route, short, label] of entries) {
    const routeAttribute = route === "return" ? "" : ` data-admin-route="${route}"`;
    const pattern = new RegExp(
      `<a class="text-button" href="${href}"${routeAttribute} data-short="${short}" data-tooltip="${label}" aria-label="${label}" title="${label}">`,
    );
    assert.match(html, pattern);
  }
  assert.match(css, /\.sidebar \.text-button \{ position: relative; text-align: center; font-size: 0; \}/);
  assert.match(css, /\.sidebar \.text-button::before \{ content: attr\(data-short\); font-size: 0\.78rem; \}/);
});

test("browser shell contains no model or API key control", async () => {
  const sources = await Promise.all([
    read("welcome.html"),
    read("login.html"),
    read("index.html"),
    read("assets/app.mjs"),
    read("assets/views.mjs"),
  ]);
  const combined = sources.join("\n");

  assert.doesNotMatch(combined, /api[ _-]?key/i);
  assert.doesNotMatch(combined, /model[ _-]?(?:selector|picker|choice)/i);
  assert.doesNotMatch(combined, /gpt-/i);
});

test("normal application chrome does not expose release internals", async () => {
  const html = await read("index.html");
  const app = await read("assets/app.mjs");

  assert.match(html, /data-dataset-label(?:\s|>)/);
  assert.match(html, /data-release-freshness(?:\s|>)/);
  assert.doesNotMatch(html, /data-dataset-label[^>]+data-i18n/);
  assert.doesNotMatch(html, /data-release-freshness[^>]+data-i18n/);
  assert.doesNotMatch(`${html}\n${app}`, /Pinned|\.slice\(0,\s*8\)|shell\.pinnedRelease/);
});

test("app bootstrap imports every state function it invokes", async () => {
  const source = await read("assets/app.mjs");

  assert.match(source, /import \{ getState, setActiveRoute \} from "\.\/state\.mjs"/);
  assert.match(source, /getState\(\)\.activeRoute/);
  assert.match(
    source,
    /renderReleaseLabels\(\);\s*renderScopeControl\(\);\s*activate\(getState\(\)\.activeRoute\);/,
  );
});

test("public shells keep the first theater slide useful without JavaScript", async () => {
  for (const filename of ["welcome.html", "login.html"]) {
    const html = await read(filename);
    const slides = [...html.matchAll(/<figure class="product-slide"[^>]*>/g)]
      .map((match) => match[0]);

    assert.equal(slides.length, 4);
    assert.doesNotMatch(slides[0], /\shidden/);
    assert.ok(slides.slice(1).every((slide) => /\shidden/.test(slide)));
  }

  const welcome = await read("welcome.html");
  assert.match(welcome, /data-demo-start/);
  assert.match(welcome, /href="\/login"/);
});
