import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { safeNext } from "../../frontend/assets/login.mjs";

const frontendRoot = new URL("../../frontend/", import.meta.url);

async function read(relativePath) {
  return readFile(new URL(relativePath, frontendRoot), "utf8");
}

test("login shell uses the local single-operator endpoint", async () => {
  const html = await read("login.html");
  const source = await read("assets/login.mjs");

  assert.match(html, /autocomplete="current-password"/);
  assert.match(source, /fetch\("\/api\/operator\/login"/);
  assert.match(source, /credentials:\s*"same-origin"/);
  assert.match(source, /sessionStorage\.setItem\("bp_csrf_token"/);
  assert.match(html, /<label for="operator-login"[^>]*>Account<\/label>/);
  assert.match(html, /data-i18n="login\.submit">Sign in<\/button>/);
  assert.match(html, /class="login-layout"/);
  assert.doesNotMatch(`${html}\n${source}`, /register|sign[ -]?up/i);
  assert.doesNotMatch(html, /Operator sign in/i);
  assert.doesNotMatch(`${html}\n${source}`, /(?:src|href)="https?:\/\//i);
});

test("login form remains a single fixed column beside the shared theater", async () => {
  const html = await read("login.html");

  assert.equal((html.match(/data-login-form/g) ?? []).length, 1);
  assert.ok(html.indexOf("data-product-theater") < html.indexOf("data-login-form"));
  assert.equal((html.match(/data-product-slide=/g) ?? []).length, 4);
});

test("login source never persists or prints the password", async () => {
  const source = await read("assets/login.mjs");

  assert.doesNotMatch(source, /localStorage/);
  assert.doesNotMatch(source, /console\./);
  assert.match(source, /passwordInput\.value\s*=\s*""/);
});

test("login returns only to allowlisted same-origin workspace paths", () => {
  assert.equal(safeNext("?next=/app"), "/app");
  assert.equal(safeNext("?next=/admin"), "/admin");
  assert.equal(safeNext("?next=/admin/data"), "/admin/data");
  assert.equal(safeNext("?next=/admin/status"), "/admin/status");
  assert.equal(safeNext("?next=/admin/ai"), "/admin/ai");
  assert.equal(safeNext("?next=https://attacker.test"), "/app");
  assert.equal(safeNext("?next=//attacker.test"), "/app");
  assert.equal(safeNext("?next=https%3A%2F%2Fattacker.test"), "/app");
  assert.equal(safeNext("?next=/unapproved"), "/app");
});
