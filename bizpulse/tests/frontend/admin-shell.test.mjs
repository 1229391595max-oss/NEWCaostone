import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import { AdminDataSource } from "../../frontend/assets/data-sources/admin.mjs";
import { t } from "../../frontend/assets/i18n/catalog.mjs";

const frontendRoot = new URL("../../frontend/", import.meta.url);

async function read(relativePath) {
  return readFile(new URL(relativePath, frontendRoot), "utf8");
}

test("admin shell exposes selected cockpit navigation", async () => {
  const html = await read("admin.html");
  assert.deepEqual(
    [...html.matchAll(/data-admin-route="([^"]+)"/g)].map((match) => match[1]),
    ["overview", "data", "status", "ai"],
  );
  assert.match(html, /href="\/app"[^>]*>Return to workspace<\/a>/);
  assert.match(html, /<script type="module" src="\/assets\/admin\.mjs"><\/script>/);
});

test("admin data source reads only same-origin no-store projections", async () => {
  const calls = [];
  const api = {
    async request(path, options) {
      calls.push([path, options]);
      return { path };
    },
  };
  const dataSource = new AdminDataSource(api);

  await dataSource.loadSummary();
  await dataSource.loadAI();

  assert.deepEqual(calls, [
    ["/api/v1/admin/summary", { cache: "no-store" }],
    ["/api/v1/admin/ai", { cache: "no-store" }],
  ]);
});

test("admin entry reuses the operator workspace without copying upload authority", async () => {
  const source = await read("assets/admin.mjs");

  assert.match(source, /import \{ renderWorkspace \} from "\.\/features\/workspace\/view\.mjs"/);
  assert.match(source, /renderWorkspace\(root, operatorDataSource,/);
  assert.doesNotMatch(source, /createWorkflow|uploadFile|commitWorkflow|confirmMapping/);
  assert.doesNotMatch(source, /model[ _-]?(?:selector|picker|choice)|gpt-/i);
});

test("data management fails closed to reauthentication without tab-local CSRF", async () => {
  const source = await read("assets/admin.mjs");

  assert.match(source, /import \{ csrfToken \} from "\.\/core\/auth-session\.mjs"/);
  assert.match(source, /if \(!csrfToken\(\)\) \{\s*renderDataReauthentication\(\);\s*return;/);
  assert.match(source, /href = "\/login\?next=\/admin\/data"/);
});

test("admin anchors receive full navigation geometry and localized chrome", async () => {
  const [html, source, css] = await Promise.all([
    read("admin.html"),
    read("assets/admin.mjs"),
    read("assets/styles.css"),
  ]);

  assert.match(css, /\.primary-nav button, \.primary-nav a \{[^}]*display: flex;[^}]*padding: 9px 12px;/s);
  assert.match(html, /data-admin-navigation/);
  assert.match(source, /const returnLink = document\.querySelector\("\.sidebar-footer a\[href='\/app'\]"\)/);
  assert.match(source, /navigation\.setAttribute\("aria-label", t\(language, "admin\.nav\.label"\)\)/);
  assert.match(source, /returnLink\.textContent = t\(language, "admin\.nav\.return"\)/);
  assert.match(source, /languageButton\.dataset\.short = language === "en" \? "中" : "EN"/);
});

test("admin catalog carries the approved AI handoff and safe outcome labels", () => {
  assert.equal(t("en", "admin.ai.operator"), "Ordinary Login AI");
  assert.equal(t("zh", "admin.ai.demo"), "公开 Demo AI");
  assert.equal(t("en", "admin.ai.rotate"), "Validate and safely replace");
  assert.match(t("en", "admin.ai.validating"), /Validating/);
  assert.match(t("zh", "admin.ai.rollback"), /原凭据/);
  assert.equal(
    t("en", "admin.ai.failed", { code: "ADMIN_AI_SECRET_UNAVAILABLE" }),
    "AI management request failed: ADMIN_AI_SECRET_UNAVAILABLE",
  );
});

test("admin AI rerenders retain the initiating action for keyboard focus return", async () => {
  const source = await read("assets/admin.mjs");

  assert.match(source, /lastAIAction/);
  assert.match(source, /data-admin-ai-action/);
  assert.match(source, /viewHandle\.focusAction\(lastAIAction\)/);
});
