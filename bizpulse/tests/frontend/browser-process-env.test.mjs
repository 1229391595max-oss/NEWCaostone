import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { chromeEnvironment } from "../../scripts/browser_process_env.mjs";

test("Chrome receives no deployment or browser credential", () => {
  assert.deepEqual(
    chromeEnvironment({
      BIZPULSE_BROWSER_OPERATOR_PASSWORD: "operator-secret",
      BIZPULSE_DEPLOY_POSTGRES_PASSWORD: "database-secret",
      HOME: "/tmp/home",
      OPENAI_API_KEY: "provider-secret",
      PATH: "/usr/bin",
    }),
    { HOME: "/tmp/home", PATH: "/usr/bin" },
  );
});

test("admin AI browser sources have no server environment or persisted secret path", async () => {
  const files = [
    "../../frontend/assets/admin.mjs",
    "../../frontend/assets/data-sources/admin.mjs",
    "../../frontend/assets/features/admin-ai/state.mjs",
    "../../frontend/assets/features/admin-ai/effects.mjs",
    "../../frontend/assets/features/admin-ai/view.mjs",
  ];
  const source = (await Promise.all(
    files.map((file) => readFile(new URL(file, import.meta.url), "utf8")),
  )).join("\n");

  assert.doesNotMatch(source, /process\.env|import\.meta\.env/);
  assert.doesNotMatch(source, /(?:localStorage|sessionStorage).*?(?:password|candidate|api.?key)/i);
  assert.doesNotMatch(source, /vault\.azure\.net|\/subscriptions\/|resourceGroups|key.?vault.?id/i);
  assert.doesNotMatch(source, /sk-[A-Za-z0-9_-]{12,}/);
});
