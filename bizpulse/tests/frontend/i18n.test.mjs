import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  LANGUAGE_STORAGE_KEY,
  applyCatalog,
  catalog,
  loadLanguagePreference,
  localizeCode,
  persistLanguagePreference,
  t,
} from "../../frontend/assets/i18n/catalog.mjs";

const frontendRoot = new URL("../../frontend/", import.meta.url);

test("English and Chinese catalogs have identical complete key sets", () => {
  assert.deepEqual(
    Object.keys(catalog.en).sort(),
    Object.keys(catalog.zh).sort(),
  );
  for (const locale of ["en", "zh"]) {
    for (const value of Object.values(catalog[locale])) {
      assert.ok(value.trim().length > 0);
    }
  }
});

test("all static catalog hooks resolve in both languages", async () => {
  const sources = await Promise.all(
    ["welcome.html", "login.html", "index.html"].map((path) =>
      readFile(new URL(path, frontendRoot), "utf8"),
    ),
  );
  const keys = sources.flatMap((source) =>
    [...source.matchAll(/data-i18n="([^"]+)"/g)].map((match) => match[1]),
  );

  for (const key of keys) {
    assert.equal(typeof t("en", key), "string");
    assert.equal(typeof t("zh", key), "string");
  }
});

test("strict lookup interpolates parameters and rejects missing keys", () => {
  assert.equal(
    t("en", "workspace.releaseFailed", { code: "PUBLICATION_FAILED" }),
    "Data request failed: PUBLICATION_FAILED",
  );
  assert.throws(() => t("en", "missing.key"), /I18N_KEY_MISSING/);
  assert.throws(() => t("pt", "nav.overview"), /LANGUAGE_INVALID/);
});

test("import dedupe and conflict controls are fully bilingual", () => {
  const keys = [
    "workspace.importQuality",
    "workspace.rowsRead",
    "workspace.rowsRetained",
    "workspace.duplicatesRemoved",
    "workspace.conflicts",
    "workspace.conflictFields",
    "workspace.downloadConflicts",
    "workspace.commitBlockedByConflicts",
  ];

  for (const key of keys) {
    assert.equal(typeof t("en", key), "string");
    assert.equal(typeof t("zh", key), "string");
    assert.notEqual(t("en", key), t("zh", key));
  }
});

test("the render boundary uses a localized safe fallback", () => {
  const node = { dataset: { i18n: "missing.key" }, textContent: "old" };
  const root = { querySelectorAll: () => [node] };

  applyCatalog("zh", root);

  assert.equal(node.textContent, "翻译暂不可用");
});

test("stable limitation codes are localized only at the render boundary", () => {
  assert.equal(localizeCode("en", "sample_data_only"), "Available sample data only.");
  assert.equal(localizeCode("zh", "sample_data_only"), "仅限当前示例数据。");
  assert.equal(localizeCode("en", "unmapped_code"), "unmapped_code");
});

test("only the language preference is written to local storage", () => {
  const writes = [];
  const storage = {
    getItem(key) {
      assert.equal(key, LANGUAGE_STORAGE_KEY);
      return "zh";
    },
    setItem(key, value) {
      writes.push([key, value]);
    },
  };

  assert.equal(loadLanguagePreference(storage), "zh");
  assert.equal(persistLanguagePreference("en", storage), "en");
  assert.deepEqual(writes, [["bp_language", "en"]]);
  assert.throws(
    () => persistLanguagePreference("pt", storage),
    /LANGUAGE_INVALID/,
  );
});
