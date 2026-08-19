import { spawn } from "node:child_process";
import { mkdtemp, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromeEnvironment } from "./browser_process_env.mjs";
import { t } from "../frontend/assets/i18n/catalog.mjs";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const OPERATOR_IMPORT = join(
  PROJECT_ROOT,
  "tests/fixtures/synthetic/v1/operator_import.xlsx",
);
const baseUrl = new URL(process.argv[2]);
const scenario = process.argv[3] ?? "full";
const operatorPassword = process.env.BIZPULSE_BROWSER_OPERATOR_PASSWORD;
const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));
const CHROME_START_TIMEOUT_MS = 30_000;
const CDP_CONNECT_TIMEOUT_MS = 30_000;
const CDP_COMMAND_TIMEOUT_MS = 30_000;
const ui = Object.freeze({
  overview: t("en", "overview.title"),
  sales: t("en", "sales.title"),
  inventory: t("en", "inventory.title"),
  profit: t("en", "profit.title"),
  settings: t("en", "settings.title"),
  decisionCenter: t("en", "ai.title"),
  actions: t("en", "decision.actions"),
  actionsEmpty: t("en", "actions.empty"),
  review: t("en", "actions.review"),
  exportAction: t("en", "actions.export"),
  downloadAction: t("en", "actions.download"),
  resultLines: t("en", "actions.resultLines"),
  recordOutcome: t("en", "actions.recordOutcome"),
  operatorWorkspace: t("en", "workspace.title"),
  viewerWorkspace: t("en", "nav.viewerWorkspace"),
  importDemoData: t("en", "workspace.demoImport"),
  uploadUnavailable: t("en", "viewer.uploadUnavailable"),
  dataReady: t("en", "shell.dataReady"),
  currentData: t("en", "workspace.currentData"),
  forecast: t("en", "decision.forecast"),
  monthlySales: t("en", "preset.monthlySales"),
  replaceDraft: t("en", "ask.replace"),
  aiDisabled: t("en", "ask.disabled"),
  zhOverview: t("zh", "overview.title"),
  enTheaterOverview: t("en", "theater.overviewTitle"),
  zhTheaterOverview: t("zh", "theater.overviewTitle"),
});

async function waitForChildClose(child, timeout) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    if (child.exitCode !== null || child.signalCode !== null) return true;
    await sleep(25);
  }
  return child.exitCode !== null || child.signalCode !== null;
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

class BrowserPage {
  constructor(process, profile, websocket, stderr) {
    this.process = process;
    this.profile = profile;
    this.websocket = websocket;
    this.stderr = stderr;
    this.nextId = 1;
    this.pending = new Map();
    this.consoleErrors = [];
    this.requests = [];
    this.requestEvents = [];
    this.inFlightRequests = new Map();
    this.errorResponses = [];
    this.preparationResponses = [];
    this.chatResponses = [];
    this.chatResponseRequests = new Map();
    this.chatRequestAudits = new Map();
  }

  static async launch(initialUrl, { reducedMotion = false } = {}) {
    const profile = await mkdtemp(join(tmpdir(), "newcaostone-chrome-"));
    const stderr = [];
    const chrome = spawn(
      CHROME,
      [
        "--headless=new",
        "--remote-debugging-port=0",
        "--remote-allow-origins=*",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-sync",
        "--metrics-recording-only",
        "--no-first-run",
        "--password-store=basic",
        `--user-data-dir=${profile}`,
        "about:blank",
      ],
      {
        detached: true,
        env: chromeEnvironment(),
        stdio: ["ignore", "ignore", "pipe"],
      },
    );
    chrome.stderr.setEncoding("utf8");
    chrome.stderr.on("data", (chunk) => stderr.push(chunk));

    const portFile = join(profile, "DevToolsActivePort");
    let port;
    const deadline = Date.now() + CHROME_START_TIMEOUT_MS;
    while (Date.now() < deadline) {
      if (chrome.exitCode !== null) {
        throw new Error(`chrome_start_failed:${stderr.join("").slice(-1000)}`);
      }
      try {
        [port] = (await readFile(portFile, "utf8")).trim().split("\n");
        if (port) break;
      } catch {}
      await sleep(50);
    }
    assert(port, "chrome_debug_port_timeout");

    let target;
    while (Date.now() < deadline) {
      try {
        const response = await fetch(`http://127.0.0.1:${port}/json/list`);
        const targets = await response.json();
        target = targets.find((item) => item.type === "page");
        if (target?.webSocketDebuggerUrl) break;
      } catch {}
      await sleep(50);
    }
    assert(target?.webSocketDebuggerUrl, "chrome_page_target_timeout");

    const websocket = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error("cdp_connect_timeout")),
        CDP_CONNECT_TIMEOUT_MS,
      );
      websocket.addEventListener("open", () => {
        clearTimeout(timer);
        resolve();
      }, { once: true });
      websocket.addEventListener("error", () => {
        clearTimeout(timer);
        reject(new Error("cdp_connect_failed"));
      }, { once: true });
    });
    const page = new BrowserPage(chrome, profile, websocket, stderr);
    websocket.addEventListener("message", (event) => page.onMessage(event));
    await page.send("Page.enable");
    await page.send("Runtime.enable");
    await page.send("Network.enable");
    await page.send("Log.enable");
    await page.send("Emulation.setEmulatedMedia", {
      features: [{
        name: "prefers-reduced-motion",
        value: reducedMotion ? "reduce" : "no-preference",
      }],
    });
    await page.navigate(initialUrl);
    return page;
  }

  onMessage(event) {
    const message = JSON.parse(String(event.data));
    if (message.id) {
      const authority = this.pending.get(message.id);
      if (!authority) return;
      this.pending.delete(message.id);
      clearTimeout(authority.timer);
      if (message.error) {
        authority.reject(new Error(
          `cdp_command_failed:${authority.method}:${message.error.message}`,
        ));
      }
      else authority.resolve(message.result ?? {});
      return;
    }
    if (message.method === "Network.requestWillBeSent") {
      this.requests.push(message.params.request.url);
      this.requestEvents.push({
        method: message.params.request.method,
        url: message.params.request.url,
      });
      this.inFlightRequests.set(message.params.requestId, message.params.request.url);
      let pathname = "";
      try { pathname = new URL(message.params.request.url).pathname; } catch {}
      if (
        message.params.request.method === "POST"
        && pathname === "/api/v1/ai-chat/turns"
      ) {
        const headers = Object.fromEntries(
          Object.entries(message.params.request.headers ?? {})
            .map(([name, value]) => [name.toLowerCase(), value]),
        );
        this.chatRequestAudits.set(message.params.requestId, {
          csrfHeaderPresent: typeof headers["x-csrf-token"] === "string"
            && headers["x-csrf-token"].length > 0,
        });
      }
    }
    if (
      message.method === "Network.loadingFinished"
      || message.method === "Network.loadingFailed"
    ) {
      this.inFlightRequests.delete(message.params.requestId);
      const chatRecord = this.chatResponseRequests.get(message.params.requestId);
      if (chatRecord) {
        this.chatResponseRequests.delete(message.params.requestId);
        if (message.method === "Network.loadingFailed") chatRecord.ready = true;
        else void this.send("Network.getResponseBody", {
          requestId: message.params.requestId,
        }).then((body) => {
          const parsed = JSON.parse(String(body.body ?? "{}"));
          chatRecord.providerAudit = parsed.provider_audit ?? null;
          chatRecord.presetAuditComplete = Boolean(
            parsed.recommended_question_id
            && parsed.prompt_locale
            && parsed.prompt_template_version
            && parsed.prompt_template_sha256,
          );
          chatRecord.storeScopeCount = Array.isArray(parsed.answer?.scope?.store_ids)
            ? parsed.answer.scope.store_ids.length
            : null;
          chatRecord.ready = true;
        }).catch(() => { chatRecord.ready = true; });
      }
    }
    if (
      message.method === "Network.responseReceived"
      && message.params.response.status >= 400
    ) {
      const record = {
        status: message.params.response.status,
        url: message.params.response.url,
      };
      this.errorResponses.push(record);
      void this.send("Network.getResponseBody", {
        requestId: message.params.requestId,
      }).then((body) => { record.body = body.body; }).catch(() => {});
    }
    if (message.method === "Network.responseReceived") {
      let pathname = "";
      try { pathname = new URL(message.params.response.url).pathname; } catch {}
      if (pathname === "/api/v1/ai-chat/turns") {
        const record = {
          csrfHeaderPresent: this.chatRequestAudits.get(
            message.params.requestId,
          )?.csrfHeaderPresent === true,
          presetAuditComplete: false,
          providerAudit: null,
          ready: false,
          status: message.params.response.status,
          storeScopeCount: null,
        };
        this.chatRequestAudits.delete(message.params.requestId);
        this.chatResponses.push(record);
        this.chatResponseRequests.set(message.params.requestId, record);
      }
      if (pathname.endsWith("/prepare")) {
        const record = {
          status: message.params.response.status,
          url: pathname,
        };
        this.preparationResponses.push(record);
        void this.send("Network.getResponseBody", {
          requestId: message.params.requestId,
        }).then((body) => {
          record.body = String(body.body ?? "").slice(0, 4000);
        }).catch(() => {});
      }
    }
    if (message.method === "Runtime.exceptionThrown") {
      this.consoleErrors.push(message.params.exceptionDetails.text ?? "runtime_exception");
    }
    if (
      message.method === "Runtime.consoleAPICalled"
      && message.params.type === "error"
    ) {
      this.consoleErrors.push("console_error");
    }
    if (
      message.method === "Log.entryAdded"
      && message.params.entry.level === "error"
    ) {
      const entry = message.params.entry;
      this.consoleErrors.push(
        `${entry.text ?? "log_error"}${entry.url ? ` @ ${entry.url}` : ""}`,
      );
    }
  }

  send(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`cdp_command_timeout:${method}`));
      }, CDP_COMMAND_TIMEOUT_MS);
      this.pending.set(id, { method, resolve, reject, timer });
      this.websocket.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const response = await this.send("Runtime.evaluate", {
      expression,
      awaitPromise: true,
      returnByValue: true,
    });
    if (response.exceptionDetails) {
      throw new Error(`browser_evaluation_failed:${response.exceptionDetails.text}`);
    }
    return response.result?.value;
  }

  async waitForNetworkIdle(idleMilliseconds = 250, timeoutMilliseconds = 30_000) {
    const deadline = Date.now() + timeoutMilliseconds;
    let idleSince = null;
    while (Date.now() < deadline) {
      if (this.inFlightRequests.size === 0) {
        idleSince ??= Date.now();
        if (Date.now() - idleSince >= idleMilliseconds) return;
      } else idleSince = null;
      await sleep(25);
    }
    throw new Error(
      `browser_network_idle_timeout:${JSON.stringify([...this.inFlightRequests.values()])}`,
    );
  }

  async waitFor(expression, label, timeout = 20_000) {
    const deadline = Date.now() + timeout;
    let lastError;
    while (Date.now() < deadline) {
      try {
        if (await this.evaluate(`Boolean(${expression})`)) return;
      } catch (error) {
        lastError = error;
      }
      await sleep(100);
    }
    const body = await this.evaluate("document.body?.innerText?.slice(0, 2000) ?? ''");
    throw new Error(`browser_wait_timeout:${label}:${lastError ?? ""}:${body}`);
  }

  async navigate(url) {
    await this.send("Page.navigate", { url });
    await this.waitFor(
      `document.readyState === "complete" && location.href === ${JSON.stringify(url)}`,
      `navigation:${url}`,
    );
  }

  async clickSelector(selector) {
    const clicked = await this.evaluate(`(() => {
      const node = document.querySelector(${JSON.stringify(selector)});
      if (!node) return false;
      node.click();
      return true;
    })()`);
    assert(clicked, `browser_selector_missing:${selector}`);
  }

  async clickSelectorForNavigation(selector) {
    try {
      await this.clickSelector(selector);
    } catch (error) {
      if (
        error.message !== "cdp_command_failed:Runtime.evaluate:Inspected target navigated or closed"
      ) throw error;
    }
  }

  async clickText(text) {
    const clicked = await this.evaluate(`(() => {
      const wanted = ${JSON.stringify(text)};
      const node = [...document.querySelectorAll("button, a")]
        .find((item) => item.textContent.includes(wanted));
      if (!node) return false;
      node.click();
      return true;
    })()`);
    assert(clicked, `browser_text_missing:${text}`);
  }

  async clickTextForNavigation(text) {
    try {
      await this.clickText(text);
    } catch (error) {
      if (
        error.message !== "cdp_command_failed:Runtime.evaluate:Inspected target navigated or closed"
      ) throw error;
    }
  }

  async setValue(selector, value) {
    const updated = await this.evaluate(`(() => {
      const node = document.querySelector(${JSON.stringify(selector)});
      if (!node) return false;
      node.value = ${JSON.stringify(value)};
      node.dispatchEvent(new Event("input", { bubbles: true }));
      node.dispatchEvent(new Event("change", { bubbles: true }));
      return true;
    })()`);
    assert(updated, `browser_input_missing:${selector}`);
  }

  async setFile(selector, path) {
    await this.send("DOM.enable");
    const document = await this.send("DOM.getDocument", { depth: 1 });
    const selected = await this.send("DOM.querySelector", {
      nodeId: document.root.nodeId,
      selector,
    });
    assert(selected.nodeId, `browser_file_input_missing:${selector}`);
    await this.send("DOM.setFileInputFiles", {
      files: [path],
      nodeId: selected.nodeId,
    });
  }

  async reload() {
    try {
      await this.send("Page.reload", { ignoreCache: true });
    } catch (error) {
      if (
        error.message !== "cdp_command_failed:Page.reload:Inspected target navigated or closed"
      ) throw error;
    }
    await this.waitFor("document.readyState === 'complete'", "page-reload");
  }

  async close() {
    try { this.websocket.close(); } catch {}
    if (this.process.exitCode === null) {
      try { globalThis.process.kill(-this.process.pid, "SIGTERM"); } catch {}
      if (!(await waitForChildClose(this.process, 3_000))) {
        try { globalThis.process.kill(-this.process.pid, "SIGKILL"); } catch {}
        assert(
          await waitForChildClose(this.process, 3_000),
          "chrome_process_cleanup_failed",
        );
      }
    }
    this.process.stderr?.destroy();
    await rm(this.profile, { recursive: true, force: true });
  }
}

function chatSubmitRequestCount(page) {
  return page.requestEvents.filter((event) => {
    try {
      return event.method === "POST"
        && new URL(event.url).pathname === "/api/v1/ai-chat/turns";
    } catch {
      return false;
    }
  }).length;
}

async function assertProductTheater(page, { reducedMotion = false } = {}) {
  await page.waitFor(
    "document.querySelector('[data-product-theater]')?.dataset.productTheaterIndex !== undefined",
    "product-theater-ready",
  );
  await page.waitFor(
    "[...document.querySelectorAll('[data-product-slide] img')].every((image) => image.complete && image.naturalWidth > 0)",
    "product-theater-images",
  );
  const projection = await page.evaluate(`(() => {
    const root = document.querySelector("[data-product-theater]");
    const slides = [...root.querySelectorAll("[data-product-slide]")];
    return {
      index: Number(root.dataset.productTheaterIndex),
      localImages: slides.every((slide) => {
        const image = slide.querySelector("img");
        return image && new URL(image.src).origin === location.origin;
      }),
      order: slides.map((slide) => slide.dataset.productSlide),
      slides: slides.length,
    };
  })()`);
  assert(projection?.slides === 4, "product_theater_slide_count_invalid");
  assert(projection?.localImages, "product_theater_remote_image_present");
  assert(
    projection?.order?.join(",") === "overview,profit_bridge,inventory_forecast,ask_bizpulse",
    "product_theater_order_invalid",
  );

  await page.clickSelector("[data-product-next]");
  await page.waitFor(
    "document.querySelector('[data-product-theater]')?.dataset.productTheaterIndex === '1'",
    "product-theater-next",
  );
  await page.clickSelector("[data-product-previous]");
  await page.waitFor(
    "document.querySelector('[data-product-theater]')?.dataset.productTheaterIndex === '0'",
    "product-theater-previous",
  );
  await page.clickSelector("[data-product-dot='ask_bizpulse']");
  await page.waitFor(
    "document.querySelector('[data-product-theater]')?.dataset.productTheaterSlide === 'ask_bizpulse'",
    "product-theater-dot",
  );
  await page.clickSelector("[data-product-dot='overview']");
  await page.evaluate("document.activeElement?.blur()");

  if (reducedMotion) {
    assert(
      await page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches"),
      "product_theater_reduced_motion_media_missing",
    );
    await sleep(6_300);
    assert(
      await page.evaluate("document.querySelector('[data-product-theater]')?.dataset.productTheaterIndex === '0'"),
      "product_theater_reduced_motion_autoplayed",
    );
  } else {
    await page.waitFor(
      "document.querySelector('[data-product-theater]')?.dataset.productTheaterIndex === '1'",
      "product-theater-autoplay",
      8_000,
    );
  }
  return { autoplay: !reducedMotion, manual: true, slides: projection.slides };
}

async function assertWelcomeLanguages(page) {
  assert(
    await page.evaluate(`document.documentElement.lang === "en"
      && document.querySelector('[data-product-slide="overview"] h2')?.textContent === ${JSON.stringify(ui.enTheaterOverview)}`),
    "welcome_english_catalog_invalid",
  );
  await page.clickSelector("[data-language-toggle]");
  await page.waitFor(
    `document.documentElement.lang === "zh-CN"
      && document.querySelector('[data-product-slide="overview"] h2')?.textContent === ${JSON.stringify(ui.zhTheaterOverview)}`,
    "welcome-chinese-catalog",
  );
  await page.clickSelector("[data-language-toggle]");
  await page.waitFor(
    `document.documentElement.lang === "en"
      && document.querySelector('[data-product-slide="overview"] h2')?.textContent === ${JSON.stringify(ui.enTheaterOverview)}`,
    "welcome-english-catalog-restored",
  );
}

async function assertAppLanguages(page) {
  await page.clickSelector("[data-language-toggle]");
  await page.waitFor(
    `document.documentElement.lang === "zh-CN"
      && document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.zhOverview)}`,
    "app-chinese-catalog",
  );
  await page.clickSelector("[data-language-toggle]");
  await page.waitFor(
    `document.documentElement.lang === "en"
      && document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.overview)}`,
    "app-english-catalog-restored",
  );
  return ["en", "zh"];
}

async function startDemo(page) {
  await page.waitFor("document.querySelector('[data-demo-start]')", "demo-entry");
  await page.clickSelectorForNavigation("[data-demo-start]");
  await page.waitFor(
    `location.pathname === '/demo' && document.querySelector('[data-primary-route="workspace"][aria-current="page"]') && document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.viewerWorkspace)}`,
    "demo-workspace-runtime",
    30_000,
  );
  const operatorImportRequestsBefore = page.requestEvents.filter((event) => {
    try { return new URL(event.url).pathname.startsWith("/api/v1/imports"); }
    catch { return false; }
  }).length;
  await page.setFile("input[type='file']", OPERATOR_IMPORT);
  await page.waitFor(
    `document.querySelector('[data-view-root]')?.innerText.includes(${JSON.stringify(ui.uploadUnavailable)})`,
    "viewer-personal-upload-unavailable",
  );
  const operatorImportRequestsAfter = page.requestEvents.filter((event) => {
    try { return new URL(event.url).pathname.startsWith("/api/v1/imports"); }
    catch { return false; }
  }).length;
  assert(
    operatorImportRequestsAfter === operatorImportRequestsBefore,
    "viewer_personal_file_reached_operator_import_api",
  );
  await page.clickTextForNavigation(ui.importDemoData);
  await page.waitFor(
    `location.pathname === '/demo' && document.querySelector('[data-primary-route="overview"][aria-current="page"]') && document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.overview)}`,
    "demo-activated-runtime",
    30_000,
  );
  const boundary = await viewerDatasetAuthority(page);
  const chrome = await page.evaluate(`(() => ({
    freshness: document.querySelector('[data-release-freshness]')?.textContent,
    text: document.body.innerText,
  }))()`);
  assert(chrome?.freshness === ui.dataReady, "viewer_data_ready_status_missing");
  assert(
    !chrome?.text.includes("Pinned")
      && !chrome?.text.includes(boundary.releaseDatasetVersionId),
    "viewer_release_internal_visible",
  );
  assert(
    boundary.sessionDatasetVersionId === boundary.releaseDatasetVersionId,
    "viewer_release_authority_mismatch",
  );
  return boundary;
}

async function route(page, name, title, content) {
  await page.clickSelector(`[data-primary-route="${name}"]`);
  await page.waitFor(
    `document.querySelector('[data-view-title]')?.textContent.includes(${JSON.stringify(title)})`,
    `route:${name}`,
  );
  if (content) {
    await page.waitFor(
      `document.querySelector('[data-view-root]')?.innerText.toLowerCase().includes(${JSON.stringify(content.toLowerCase())})`,
      `route-content:${name}`,
    );
  }
}

async function assertViewerDataEvidence(page) {
  await route(page, "workspace", ui.viewerWorkspace);
  await page.clickText(t("en", "workspace.tab.library"));
  await page.waitFor(
    `document.querySelector('.library-workspace')?.innerText.includes(${JSON.stringify(t("en", "library.provenance"))})`,
    "viewer-library-ready",
    30_000,
  );
  const projection = await page.evaluate(`(() => {
    const root = document.querySelector('[data-view-root]');
    const text = root?.innerText ?? "";
    return {
      hasCoverage: text.includes("2026-07-31")
        && text.includes("2026-05-01")
        && text.includes(${JSON.stringify(t("en", "library.table.daily_sales"))})
        && text.includes("Source provenance"),
      hasFileInput: Boolean(root?.querySelector('input[type="file"]')),
      hasOperatorControl: [...(root?.querySelectorAll("button") ?? [])]
        .some((node) => /upload selected|import demo data|publish prepared/i.test(node.textContent ?? "")),
    };
  })()`);
  assert(projection?.hasCoverage, "viewer_data_evidence_incomplete");
  assert(!projection?.hasFileInput, "viewer_file_input_present");
  assert(!projection?.hasOperatorControl, "viewer_operator_control_present");
}

async function assertLibraryWorkbook(page, mode) {
  await route(
    page,
    "workspace",
    mode === "viewer" ? ui.viewerWorkspace : ui.operatorWorkspace,
  );
  await page.clickText(t("en", "workspace.tab.library"));
  await page.waitFor(
    `document.querySelector('.library-workbook .library-data-table')
      && document.querySelector('.library-table-panel')?.getAttribute('aria-busy') === 'false'`,
    `${mode}-library-workbook-ready`,
    30_000,
  );
  const projection = await page.evaluate(`(() => {
    const root = document.querySelector('[data-view-root]');
    return {
      cardWall: Boolean(root?.querySelector('.library-table-card, .library-table-grid')),
      currentDataset: root?.innerText.includes(${JSON.stringify(t("en", "library.currentDataset"))}),
      detailedTables: root?.querySelectorAll('.library-data-table').length,
      horizontalOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      tabs: root?.querySelectorAll('.library-table-tab').length,
      versionOne: /version\s*1/i.test(root?.innerText ?? ''),
    };
  })()`);
  assert(!projection?.cardWall, `${mode}_library_card_wall_present`);
  assert(projection?.currentDataset, `${mode}_library_current_dataset_missing`);
  assert(projection?.detailedTables === 1, `${mode}_library_detailed_table_count_invalid`);
  assert(projection?.tabs > 1, `${mode}_library_tabs_missing`);
  assert(!projection?.versionOne, `${mode}_library_version_one_visible`);
  assert(projection?.horizontalOverflow <= 1, `${mode}_library_horizontal_overflow`);

  const nextRole = await page.evaluate(`(() => {
    const tabs = [...document.querySelectorAll('.library-table-tab')];
    const current = tabs.findIndex((tab) => tab.getAttribute('aria-selected') === 'true');
    return tabs[(current + 1) % tabs.length]?.dataset.libraryRole;
  })()`);
  assert(nextRole, `${mode}_library_alternate_tab_missing`);
  await page.evaluate("document.querySelector('.library-table-tab[aria-selected=\"true\"]')?.focus()");
  for (const type of ["keyDown", "keyUp"]) {
    await page.send("Input.dispatchKeyEvent", {
      type,
      key: "ArrowRight",
      code: "ArrowRight",
      windowsVirtualKeyCode: 39,
    });
  }
  await page.waitFor(
    `document.querySelector('[data-library-role=${JSON.stringify(nextRole)}]')?.getAttribute('aria-selected') === 'true'
      && document.querySelector('.library-table-panel')?.getAttribute('aria-busy') === 'false'`,
    `${mode}-library-tab-switch`,
  );
  assert(
    await page.evaluate(`document.querySelectorAll('.library-data-table').length === 1
      && document.activeElement?.dataset.libraryRole === ${JSON.stringify(nextRole)}`),
    `${mode}_library_tab_switch_failed:library_tab_keyboard_failed`,
  );

  await page.clickSelector('[data-library-role="daily_sales"]');
  await page.waitFor(
    `document.querySelector('[data-library-role="daily_sales"]')?.getAttribute('aria-selected') === 'true'
      && document.querySelector('.library-table-panel')?.getAttribute('aria-busy') === 'false'
      && document.querySelector('.library-data-row')`,
    `${mode}-library-sales-table`,
  );
  const dailySalesRowCount = await page.evaluate(
    "Number(document.querySelector('[data-library-role=\"daily_sales\"] .library-table-count')?.textContent)",
  );
  assert(
    Number.isInteger(dailySalesRowCount) && dailySalesRowCount > 25,
    `${mode}_library_sales_row_count_invalid`,
  );
  const dailySalesPagesAt25 = Math.ceil(dailySalesRowCount / 25);
  const formatProjection = await page.evaluate(`(() => {
    const headers = [...document.querySelectorAll('.library-data-table th')]
      .map((cell) => cell.textContent.trim());
    const grossIndex = headers.indexOf(${JSON.stringify(t("en", "library.column.gross_sales_brl"))});
    const gross = grossIndex >= 0
      ? document.querySelector('.library-data-row')?.cells[grossIndex]?.textContent.trim()
      : null;
    return {
      decimal: /^R\\$[\\d,]+\\.\\d{2}$/.test(gross ?? ""),
      syntheticMarker: document.querySelector('.library-table-panel')?.innerText.includes('pure_synthetic'),
    };
  })()`);
  assert(formatProjection?.decimal, `${mode}_library_decimal_format_invalid`);
  assert(!formatProjection?.syntheticMarker, `${mode}_library_synthetic_marker_visible`);

  await page.clickSelector("[data-language-toggle]");
  await page.waitFor(
    `[...document.querySelectorAll('.library-data-table th')]
      .some((cell) => cell.textContent.trim() === ${JSON.stringify(t("zh", "library.column.date"))})`,
    `${mode}-library-chinese-column`,
  );
  assert(
    await page.evaluate(`document.querySelector('.library-table-panel')?.innerText.includes(${JSON.stringify(t("zh", "library.table.daily_sales"))})`),
    `${mode}_library_chinese_column_missing`,
  );
  await page.clickSelector("[data-language-toggle]");
  await page.waitFor(
    `[...document.querySelectorAll('.library-data-table th')]
      .some((cell) => cell.textContent.trim() === ${JSON.stringify(t("en", "library.column.date"))})`,
    `${mode}-library-english-column-restored`,
  );

  await page.setValue(".library-page-size", "25");
  await page.waitFor(
    `document.querySelectorAll('.library-data-row').length === 25
      && document.querySelector('.library-page-status')?.textContent.includes(${JSON.stringify(t("en", "library.page", { page: 1, total: dailySalesPagesAt25 }))})
      && document.querySelector('.library-table-panel')?.getAttribute('aria-busy') === 'false'`,
    `${mode}-library-page-size`,
  );
  assert(
    await page.evaluate("document.querySelector('.library-page-size')?.value === '25'"),
    `${mode}_library_page_size_change_failed`,
  );

  await page.clickSelector(".library-data-row");
  await page.waitFor(
    "document.querySelector('.library-row-drawer[role=\"dialog\"]')",
    `${mode}-library-row-drawer`,
  );
  assert(
    await page.evaluate("document.activeElement?.classList.contains('library-row-detail-close')"),
    `${mode}_library_row_drawer_missing`,
  );
  for (const modifiers of [0, 8]) {
    for (const type of ["keyDown", "keyUp"]) {
      await page.send("Input.dispatchKeyEvent", {
        type,
        key: "Tab",
        code: "Tab",
        windowsVirtualKeyCode: 9,
        modifiers,
      });
    }
    assert(
      await page.evaluate("document.querySelector('.library-row-drawer')?.contains(document.activeElement)"),
      `${mode}_library_modal_focus_escape`,
    );
  }
  await page.send("Input.dispatchKeyEvent", {
    type: "keyDown",
    key: "Escape",
    code: "Escape",
    windowsVirtualKeyCode: 27,
  });
  await page.send("Input.dispatchKeyEvent", {
    type: "keyUp",
    key: "Escape",
    code: "Escape",
    windowsVirtualKeyCode: 27,
  });
  await page.waitFor(
    "!document.querySelector('.library-row-drawer')",
    `${mode}-library-row-drawer-close`,
  );
  assert(
    await page.evaluate("document.activeElement?.classList.contains('library-data-row')"),
    `${mode}_library_row_drawer_escape_failed`,
  );

  await page.clickSelector('[data-library-page="next"]');
  await page.waitFor(
    `document.querySelector('.library-page-status')?.textContent.includes(${JSON.stringify(t("en", "library.page", { page: 2, total: dailySalesPagesAt25 }))})
      && document.querySelector('.library-table-panel')?.getAttribute('aria-busy') === 'false'`,
    `${mode}-library-next-page`,
  );
  assert(
    await page.evaluate("document.querySelectorAll('.library-data-table').length === 1"),
    `${mode}_library_pagination_replaced_table`,
  );
  for (const width of [820, 390]) {
    await page.send("Emulation.setDeviceMetricsOverride", {
      width,
      height: width === 390 ? 844 : 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await sleep(100);
    assert(
      await page.evaluate(`document.documentElement.scrollWidth <= window.innerWidth + 1
        && document.querySelector('.library-table-scroll')?.scrollWidth >= document.querySelector('.library-table-scroll')?.clientWidth`),
      `${mode}_library_workbook_overflow:${width}`,
    );
  }
  await page.send("Emulation.clearDeviceMetricsOverride");
  await page.clickText(t("en", "workspace.tab.upload"));
  await page.waitFor(
    `[...document.querySelectorAll('.workspace-tab')].some((tab) =>
      tab.textContent.includes(${JSON.stringify(t("en", "workspace.tab.upload"))})
      && tab.getAttribute('aria-selected') === 'true'
    )`,
    `${mode}-library-upload-tab-restored`,
  );
}

async function askAdvertisingPerformance(page, expectedCount) {
  await page.waitFor(
    "[...document.querySelectorAll('button')].some((node) => node.textContent.includes('Summarize advertising performance'))",
    "recommended-question",
  );
  await page.clickText("Summarize advertising performance");
  await page.waitFor(
    "document.querySelector('.chat-question')?.value.toLowerCase().includes('advertising')",
    "recommended-question-draft",
  );
  const beforeSend = await page.evaluate(
    "document.querySelectorAll('.chat-answer-card').length",
  );
  assert(beforeSend === expectedCount - 1, "preset_click_submitted_without_send");
  await page.clickSelector(".chat-form button[type='submit']");
  await page.waitFor(
    `document.querySelectorAll('.chat-answer-card').length === ${expectedCount}`,
    `chat-answer:${expectedCount}`,
    30_000,
  );
}

async function askMonthlyReportAfterExplicitSend(page, expectedCount) {
  await page.waitFor(
    "document.querySelectorAll('.chat-recommended-grid button').length === 6",
    "six-prompt-presets",
  );
  await page.setValue(".chat-question", "Keep this draft until replacement is confirmed.");
  const requestsBeforePreset = chatSubmitRequestCount(page);
  const answersBeforePreset = await page.evaluate(
    "document.querySelectorAll('.chat-answer-card').length",
  );
  await page.clickText(ui.monthlySales);
  await page.waitFor(
    "document.querySelector('.chat-replacement-dialog[role=\"alertdialog\"]')",
    "monthly-preset-replacement-confirmation",
  );
  assert(
    await page.evaluate("document.querySelector('.chat-question')?.value === 'Keep this draft until replacement is confirmed.'"),
    "monthly_preset_replaced_without_confirmation",
  );
  assert(
    chatSubmitRequestCount(page) === requestsBeforePreset,
    "monthly_preset_requested_provider_before_confirmation",
  );
  await page.clickText(ui.replaceDraft);
  await page.waitFor(
    "document.querySelector('.chat-question')?.value.includes('month covered by the current data release')",
    "monthly-preset-draft",
  );
  assert(
    await page.evaluate("document.querySelectorAll('.chat-answer-card').length") === answersBeforePreset,
    "monthly_preset_click_submitted_without_send",
  );
  assert(
    chatSubmitRequestCount(page) === requestsBeforePreset,
    "monthly_preset_called_provider_without_send",
  );
  await page.clickSelector(".chat-form button[type='submit']");
  await page.waitFor(
    `document.querySelectorAll('.chat-answer-card').length === ${expectedCount}`,
    `monthly-report-answer:${expectedCount}`,
    30_000,
  );
  assert(
    chatSubmitRequestCount(page) === requestsBeforePreset + 1,
    "monthly_report_request_count_invalid",
  );
  assert(
    await page.evaluate(`document.querySelector('.chat-answer-card')?.innerText.includes('2026-07-01')
      && document.querySelector('.chat-answer-card')?.innerText.includes('2026-07-31')`),
    "monthly_report_release_period_missing",
  );
}

async function askEditedAdvertisingPerformance(page, expectedCount) {
  await page.clickText("Summarize advertising performance");
  await page.waitFor(
    "document.querySelector('.chat-question')?.value.toLowerCase().includes('advertising')",
    "edited-preset-draft",
  );
  const original = await page.evaluate("document.querySelector('.chat-question')?.value");
  const edited = `${original} Focus on the most decision-relevant evidence.`;
  await page.setValue(".chat-question", edited);
  const beforeSend = chatSubmitRequestCount(page);
  await page.clickSelector(".chat-form button[type='submit']");
  await page.waitFor(
    `document.querySelectorAll('.chat-answer-card').length === ${expectedCount}`,
    `edited-preset-answer:${expectedCount}`,
    30_000,
  );
  assert(
    chatSubmitRequestCount(page) === beforeSend + 1,
    "edited_preset_request_count_invalid",
  );
  assert(
    await page.evaluate(`document.querySelector('.chat-answer-card h3')?.textContent === ${JSON.stringify(edited)}`),
    "edited_preset_text_not_preserved",
  );
}

async function assertViewports(page) {
  const widths = [1280, 820, 390];
  for (const width of widths) {
    await page.send("Emulation.setDeviceMetricsOverride", {
      width,
      height: width === 390 ? 844 : 900,
      deviceScaleFactor: 1,
      mobile: false,
    });
    await sleep(100);
    const fits = await page.evaluate(
      "document.documentElement.scrollWidth <= window.innerWidth + 1",
    );
    if (!fits) {
      const diagnostic = await page.evaluate(`(() => ({
        innerWidth: window.innerWidth,
        scrollWidth: document.documentElement.scrollWidth,
        offenders: [...document.querySelectorAll("body, body *")]
          .map((node) => ({
            className: typeof node.className === "string" ? node.className : "",
            clientWidth: node.clientWidth,
            left: Math.round(node.getBoundingClientRect().left),
            right: Math.round(node.getBoundingClientRect().right),
            scrollWidth: node.scrollWidth,
            tag: node.tagName,
            text: (node.textContent ?? "").trim().slice(0, 80),
            width: Math.round(node.getBoundingClientRect().width),
          }))
          .sort((left, right) => Math.max(
            right.right - window.innerWidth,
            right.scrollWidth - right.clientWidth,
          ) - Math.max(
            left.right - window.innerWidth,
            left.scrollWidth - left.clientWidth,
          ))
          .slice(0, 15),
      }))()`);
      throw new Error(`horizontal_overflow:${width}:${JSON.stringify(diagnostic)}`);
    }
  }
  await page.send("Emulation.clearDeviceMetricsOverride");
  return widths.sort((left, right) => left - right);
}

async function assertCorrectedBusinessExperience(page, mode) {
  const navigation = await page.evaluate(`(() => {
    const primary = [...document.querySelectorAll("[data-primary-route]")];
    const settings = document.querySelector("[data-settings-route]");
    return {
      languageVisible: Boolean(document.querySelector("[data-language-toggle]")),
      primaryCount: primary.length,
      settingsVisible: Boolean(settings),
      titlesMatch: [...primary, settings].filter(Boolean).every((button) =>
        button.title === button.textContent.trim()
        && button.getAttribute("aria-label") === button.textContent.trim()
        && button.dataset.tooltip === button.textContent.trim()
      ),
    };
  })()`);
  assert(navigation?.primaryCount === 6, `${mode}_navigation_count_invalid`);
  assert(navigation?.settingsVisible, `${mode}_settings_navigation_missing`);
  assert(navigation?.languageVisible, `${mode}_language_control_missing`);
  assert(navigation?.titlesMatch, `${mode}_navigation_full_name_missing`);

  await route(page, "overview", ui.overview, "Net sales");
  const collapsedEvidence = await page.evaluate(
    "document.querySelectorAll('.evidence-list [data-evidence-item]').length",
  );
  const hasEvidenceToggle = await page.evaluate(
    `Boolean(document.querySelector('.evidence-disclosure[aria-expanded="false"]'))`,
  );
  assert(collapsedEvidence === 4, `${mode}_evidence_not_collapsed_to_four`);
  assert(hasEvidenceToggle, `${mode}_evidence_disclosure_missing`);
  await page.clickText(t("en", "evidence.showAll"));
  const expandedEvidence = await page.evaluate(
    "document.querySelectorAll('.evidence-list [data-evidence-item]').length",
  );
  assert(expandedEvidence > 4, `${mode}_evidence_did_not_expand`);
  await page.clickText(t("en", "evidence.showLess"));
  assert(
    await page.evaluate("document.querySelectorAll('.evidence-list [data-evidence-item]').length") === 4,
    `${mode}_evidence_did_not_collapse`,
  );

  await route(page, "inventory", ui.inventory, "P0");
  const inventory = await page.evaluate(`(() => ({
    alignedRows: [...document.querySelectorAll(".inventory-priority-table tbody tr")]
      .every((row) => {
        const cells = [...row.cells];
        const bottoms = cells.map((cell) => cell.getBoundingClientRect().bottom);
        return cells.every((cell) => getComputedStyle(cell).display === "table-cell")
          && Math.max(...bottoms) - Math.min(...bottoms) < 0.5;
      }),
    hasPriorityList: Boolean(document.querySelector(".inventory-priority-table")),
    hasRiskChart: Boolean(document.querySelector(".analytics-grid svg")),
    priorities: ["P0", "P1", "P2", "Monitor"].every((label) =>
      document.querySelector("[data-view-root]")?.innerText.includes(label)
    ),
  }))()`);
  assert(inventory?.hasPriorityList, `${mode}_inventory_priority_list_missing`);
  assert(inventory?.alignedRows, `${mode}_inventory_row_dividers_misaligned`);
  assert(inventory?.priorities, `${mode}_inventory_priority_labels_missing`);
  assert(!inventory?.hasRiskChart, `${mode}_inventory_risk_chart_not_removed`);

  await page.clickSelector("[data-settings-route]");
  await page.waitFor(
    `document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.settings)} && document.querySelector('[data-page="settings"]')`,
    `${mode}-settings-route`,
  );
  const settings = await page.evaluate(`(() => {
    const root = document.querySelector("[data-view-root]");
    const text = root?.innerText ?? "";
    const normalizedPageText = document.body.innerText.toLowerCase();
    return {
      hasApiKeyField: [...(root?.querySelectorAll("input") ?? [])]
        .some((input) => /api.?key/i.test(input.name || input.id || input.placeholder || "")),
      hasAiStatus: text.includes(${JSON.stringify(t("en", "settings.aiStatus"))}),
      hasTargetEditor: Boolean(root?.querySelector('[data-settings-action="create-target"]')),
      reportingDisabled: [...(root?.querySelectorAll('[data-settings-field="reporting_currency"], [data-settings-field="timezone"]') ?? [])]
        .every((control) => control.disabled),
      technicalLabel: ["pinned", "schema", "digest", " v1"]
        .some((label) => normalizedPageText.includes(label)),
    };
  })()`);
  assert(settings?.hasAiStatus, `${mode}_ai_status_missing`);
  assert(!settings?.hasApiKeyField, `${mode}_browser_api_key_field_present`);
  assert(!settings?.technicalLabel, `${mode}_technical_label_visible`);
  assert(
    mode === "viewer"
      ? settings?.reportingDisabled && !settings?.hasTargetEditor
      : !settings?.reportingDisabled && settings?.hasTargetEditor,
    `${mode}_settings_permission_boundary_invalid`,
  );

  await page.setValue('[data-settings-field="sidebar_mode"]', "compact");
  await page.clickSelector('[data-settings-action="save"]');
  await page.waitFor(
    "document.body.classList.contains('sidebar-compact')",
    `${mode}-compact-navigation`,
  );
  assert(
    await page.evaluate(`(() => {
      const button = document.querySelector('[data-primary-route="inventory"]');
      return button?.title === ${JSON.stringify(t("en", "nav.inventory"))}
        && button?.getAttribute("aria-label") === ${JSON.stringify(t("en", "nav.inventory"))};
    })()`),
    `${mode}_compact_navigation_full_name_missing`,
  );
  await page.setValue('[data-settings-field="sidebar_mode"]', "full");
  await page.clickSelector('[data-settings-action="save"]');
  await page.waitFor(
    "!document.body.classList.contains('sidebar-compact')",
    `${mode}-full-navigation-restored`,
  );
  await assertLibraryWorkbook(page, mode);
}

async function assertSixViewerAreas(page) {
  const areaCount = await page.evaluate(
    "document.querySelectorAll('[data-primary-route]').length",
  );
  assert(areaCount === 6, "viewer_area_count_invalid");
  await route(page, "overview", ui.overview, "Net sales");
  await route(page, "sales", ui.sales, "Net sales");
  await route(page, "inventory", ui.inventory, "Stockout");
  await route(page, "profit", ui.profit, "Contribution");
  await assertViewerDataEvidence(page);
  assert(
    await page.evaluate(`document.querySelector('[data-view-root]')?.innerText.includes('Source provenance')
      && !document.querySelector('[data-view-root]')?.innerText.includes('数据来源')`),
    "viewer_evidence_english_catalog_mixed",
  );
  await page.clickSelector("[data-language-toggle]");
  await page.waitFor(
    "document.querySelector('[data-view-root]')?.innerText.includes('数据来源') && !document.querySelector('[data-view-root]')?.innerText.includes('Source provenance')",
    "viewer-evidence-chinese-catalog",
  );
  await page.clickSelector("[data-language-toggle]");
  await page.waitFor(
    "document.querySelector('[data-view-root]')?.innerText.includes('Source provenance')",
    "viewer-evidence-english-restored",
  );
  await route(page, "briefing", ui.decisionCenter, "Ask BizPulse");
  await page.clickText(ui.forecast);
  await page.waitFor(
    `document.querySelector('[data-view-root]')?.innerText.includes(${JSON.stringify(t("en", "forecast.title"))})`,
    "viewer-forecast-area",
  );
  await page.clickText(t("en", "decision.ask"));
  await page.waitFor(
    "document.querySelector('.chat-recommended-grid')",
    "viewer-ask-area-restored",
  );
  await page.clickText(t("en", "ask.returnGeneral"));
  await page.waitFor(
    "document.querySelectorAll('.chat-recommended-grid button').length === 6",
    "viewer-general-ask-restored",
  );
  return areaCount;
}

async function operatorDatasetAuthority(page) {
  return page.evaluate(`(async () => {
    const [versionsResponse, releaseResponse] = await Promise.all([
      fetch("/api/v1/datasets/versions", { credentials: "same-origin", cache: "no-store" }),
      fetch("/api/v1/datasets/public-release", { credentials: "same-origin", cache: "no-store" }),
    ]);
    if (!versionsResponse.ok || !releaseResponse.ok) {
      throw new Error("operator_dataset_authority_unavailable");
    }
    return {
      versions: (await versionsResponse.json()).versions,
      current: await releaseResponse.json(),
    };
  })()`);
}

async function viewerDatasetAuthority(page) {
  return page.evaluate(`(async () => {
    const [sessionResponse, releaseResponse] = await Promise.all([
      fetch("/api/demo/sessions/current", { credentials: "same-origin", cache: "no-store" }),
      fetch("/api/demo/release/current", { credentials: "same-origin", cache: "no-store" }),
    ]);
    if (!sessionResponse.ok || !releaseResponse.ok) {
      throw new Error("viewer_dataset_authority_unavailable");
    }
    const session = (await sessionResponse.json()).session;
    const release = await releaseResponse.json();
    return {
      sessionDatasetVersionId: session.dataset_version_id,
      releaseDatasetVersionId: release.dataset_version_id,
    };
  })()`);
}

async function importAndPublishSyntheticWorkbook(page) {
  await route(page, "workspace", ui.operatorWorkspace, "Choose files or drag them here");
  const initialAuthority = await operatorDatasetAuthority(page);
  await page.setFile("input[type='file']", OPERATOR_IMPORT);
  await page.waitFor(
    "document.querySelector('[data-view-root]')?.innerText.includes('operator_import.xlsx')",
    "operator-file-selected",
  );
  await page.waitFor(
    "[...document.querySelectorAll('button')].some((node) => node.textContent.includes('Upload selected files') && !node.disabled)",
    "operator-upload-enabled",
  );
  await page.clickText("Upload selected files");
  await page.waitFor(
    "[...document.querySelectorAll('button')].some((node) => node.textContent.includes('Recognize source'))",
    "operator-source-uploaded",
    30_000,
  );
  await page.clickText("Recognize source");
  await page.waitFor(
    "[...document.querySelectorAll('button')].some((node) => node.textContent.includes('Confirm suggested mapping'))",
    "operator-source-recognized",
    30_000,
  );
  await page.clickText("Confirm suggested mapping");
  await page.waitFor(
    "[...document.querySelectorAll('button')].some((node) => node.textContent.includes('Load exact preview'))",
    "operator-source-standardized",
    45_000,
  );
  await page.clickText("Load exact preview");
  await page.waitFor(
    "[...document.querySelectorAll('button')].some((node) => node.textContent.includes('Prepare commit plan'))",
    "operator-preview-loaded",
    30_000,
  );
  await page.clickText("Prepare commit plan");
  await page.waitFor(
    "[...document.querySelectorAll('button')].some((node) => node.textContent.includes('Commit immutable dataset version') && !node.disabled)",
    "operator-commit-ready",
    30_000,
  );
  const qualityVisible = await page.evaluate(`(() => {
    const summary = document.querySelector(".import-dedupe-summary");
    const table = document.querySelector(".import-dedupe-role-table");
    const conflicts = document.querySelector(".import-conflict-table");
    return Boolean(summary && table && !conflicts);
  })()`);
  assert(qualityVisible, "operator_commit_quality_summary_missing");
  const planAuthority = await page.evaluate(`(async () => {
    const entry = performance.getEntriesByType("resource").toReversed().find((item) => {
      const path = new URL(item.name).pathname;
      return path.startsWith("/api/v1/import-workflows/") && path.endsWith("/commit-plan");
    });
    if (!entry) return null;
    const response = await fetch(new URL(entry.name).pathname, {
      credentials: "same-origin",
      cache: "no-store",
    });
    return response.ok ? response.json() : null;
  })()`);
  assert(
    /^[0-9a-f]{64}$/.test(planAuthority?.content_sha256 ?? ""),
    "operator_commit_plan_authority_missing",
  );
  let committedAuthority = await operatorDatasetAuthority(page);
  let target = committedAuthority.versions.find(
    (version) => version.content_sha256 === planAuthority.content_sha256,
  );
  if (!target) {
    await page.clickText("Commit immutable dataset version");
    await page.waitFor(
      "document.body.innerText.includes('Import another source') || document.querySelector('.import-card .import-error')",
      "operator-version-resolved",
      45_000,
    );
    const committed = await page.evaluate(`(() => {
      for (const node of document.querySelectorAll(".import-detail")) {
        try {
          const value = JSON.parse(node.textContent);
          if (typeof value?.dataset_version_id === "string") return value;
        } catch {}
      }
      return null;
    })()`);
    assert(committed?.dataset_version_id, "operator_commit_result_authority_missing");
    committedAuthority = await operatorDatasetAuthority(page);
    target = committedAuthority.versions.find(
      (version) => version.id === committed.dataset_version_id,
    );
    assert(
      target?.content_sha256 === planAuthority.content_sha256,
      "operator_commit_result_authority_mismatch",
    );
  }
  assert(
    target?.status === "complete",
    `operator_exact_version_unavailable:${planAuthority.content_sha256}:${JSON.stringify(committedAuthority)}`,
  );
  if (committedAuthority.current.dataset_version_id !== target.id) {
    await page.clickSelector(`[data-version-id="${target.id}"] button`);
    try {
      await page.waitFor(
        `(() => {
          const card = document.querySelector('[data-version-id="${target.id}"]');
          const buttons = [...(card?.querySelectorAll('button') ?? [])];
          const publish = buttons.find((button) => button.textContent.includes('Publish prepared data'));
          const calculate = buttons[0];
          return Boolean(
            (publish && !publish.disabled)
            || (calculate?.textContent.includes('Retry calculations') && !calculate.disabled)
          );
        })()`,
        "operator-calculation-resolution",
        90_000,
      );
      let publishReady = await page.evaluate(`(() => {
        const card = document.querySelector('[data-version-id="${target.id}"]');
        return [...(card?.querySelectorAll('button') ?? [])]
          .some((button) => button.textContent.includes('Publish prepared data') && !button.disabled);
      })()`);
      if (!publishReady) {
        await page.clickSelector(
          `[data-version-id="${target.id}"] button:first-of-type`,
        );
        await page.waitFor(
          `(() => {
            const card = document.querySelector('[data-version-id="${target.id}"]');
            return [...(card?.querySelectorAll('button') ?? [])]
              .some((button) => button.textContent.includes('Publish prepared data') && !button.disabled);
          })()`,
          "operator-calculations-retry-ready",
          90_000,
        );
        publishReady = true;
      }
      assert(publishReady, "operator_calculations_not_publishable");
    } catch (error) {
      throw new Error(
        `${error.message};preparation_responses:${JSON.stringify(page.preparationResponses)}`,
      );
    }
    await page.clickSelector(
      `[data-version-id="${target.id}"] > button:last-of-type`,
    );
    const deadline = Date.now() + 90_000;
    while (Date.now() < deadline) {
      await sleep(100);
      const authority = await operatorDatasetAuthority(page).catch(() => null);
      if (authority?.current?.dataset_version_id === target.id) break;
    }
  }
  const publishedAuthority = await operatorDatasetAuthority(page);
  assert(
    publishedAuthority.current.dataset_version_id === target.id,
    "operator_exact_release_not_current",
  );
  return {
    releaseChanged: initialAuthority.current.dataset_version_id !== target.id,
    versionId: target.id,
    versionNumber: target.version_number,
  };
}

async function verifyOperatorActionExportAndOutcome(page) {
  await route(page, "briefing", ui.decisionCenter, "Ask BizPulse");
  await page.clickText(ui.actions);
  await page.waitFor(
    `document.querySelector('.action-card') || document.body.innerText.includes(${JSON.stringify(ui.actionsEmpty)})`,
    "operator-export-authority",
  );
  const hasDownload = await page.evaluate(
    `[...document.querySelectorAll('a')].some((node) => node.textContent.includes(${JSON.stringify(ui.downloadAction)}))`,
  );
  const hasCurrentAction = await page.evaluate("Boolean(document.querySelector('.action-card'))");
  if (!hasCurrentAction) {
    const historicalAuthority = await page.evaluate(`(async () => {
      const versionsResponse = await fetch("/api/v1/datasets/versions", {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!versionsResponse.ok) return null;
      const versions = (await versionsResponse.json()).versions ?? [];
      for (const version of versions) {
        const actionsResponse = await fetch(
          "/api/v1/actions?dataset_version_id=" + encodeURIComponent(version.id),
          { credentials: "same-origin", cache: "no-store" },
        );
        if (!actionsResponse.ok) return null;
        const actions = (await actionsResponse.json()).items ?? [];
        const action = actions.find((item) =>
          item.exports?.length
          && item.outcomes?.some((outcome) =>
            outcome.synthetic_result?.browser_release_gate === "verified_synthetic"
          )
        );
        if (!action) continue;
        const exported = action.exports.at(-1);
        const response = await fetch(
          "/api/v1/actions/" + encodeURIComponent(action.id)
            + "/exports/" + encodeURIComponent(exported.id) + "/download",
          { credentials: "same-origin", cache: "no-store" },
        );
        const bytes = new Uint8Array(await response.arrayBuffer());
        return {
          disposition: response.headers.get("content-disposition"),
          size: bytes.length,
          signature: [...bytes.slice(0, 2)],
          status: response.status,
        };
      }
      return null;
    })()`);
    assert(
      historicalAuthority?.status === 200
        && historicalAuthority.size > 100
        && historicalAuthority.signature?.join(",") === "80,75"
        && historicalAuthority.disposition?.includes("SYNTH-ACTION-"),
      "operator_historical_action_authority_invalid",
    );
    return;
  }
  if (!hasDownload) {
    await page.clickText(ui.exportAction);
    await page.waitFor(
      `[...document.querySelectorAll('a')].some((node) => node.textContent.includes(${JSON.stringify(ui.downloadAction)}))`,
      "operator-export-completed",
      30_000,
    );
  }
  const exportAuthority = await page.evaluate(`(async () => {
    const link = [...document.querySelectorAll("a")]
      .find((node) => node.textContent.includes(${JSON.stringify(ui.downloadAction)}));
    if (!link || new URL(link.href).origin !== location.origin) return null;
    const response = await fetch(link.href, { credentials: "same-origin", cache: "no-store" });
    const bytes = new Uint8Array(await response.arrayBuffer());
    return {
      disposition: response.headers.get("content-disposition"),
      size: bytes.length,
      signature: [...bytes.slice(0, 2)],
      status: response.status,
    };
  })()`);
  assert(
    exportAuthority?.status === 200
      && exportAuthority.size > 100
      && exportAuthority.signature?.join(",") === "80,75"
      && exportAuthority.disposition?.includes("SYNTH-ACTION-"),
    "operator_export_blob_authority_invalid",
  );
  const outcomeRecorded = await page.evaluate(
    "document.body.innerText.includes('browser_release_gate: verified_synthetic')",
  );
  if (!outcomeRecorded) {
    await page.setValue(
      `textarea[aria-label^=${JSON.stringify(ui.resultLines)}]`,
      "browser_release_gate=verified_synthetic",
    );
    await page.clickText(ui.recordOutcome);
    await page.waitFor(
      "document.body.innerText.includes('browser_release_gate: verified_synthetic')",
      "operator-outcome-recorded",
      30_000,
    );
  }
}

async function endDemoSession(page) {
  const cookieProjection = await page.send("Network.getCookies", {
    urls: [`${baseUrl.origin}/`],
  });
  const cookieHeader = (cookieProjection.cookies ?? [])
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");
  assert(cookieHeader.includes("bp_demo_session="), "demo_session_cookie_missing");
  const result = await page.evaluate(`(async () => {
    const csrf = sessionStorage.getItem("bp_demo_csrf_token") ?? "";
    const ended = await fetch("/api/demo/sessions", {
      method: "DELETE",
      credentials: "same-origin",
      headers: { "Origin": location.origin, "X-CSRF-Token": csrf },
    });
    return { ended: ended.status };
  })()`);
  const current = await fetch(`${baseUrl.origin}/api/demo/sessions/current`, {
    cache: "no-store",
    headers: { Cookie: cookieHeader },
    redirect: "manual",
  });
  assert(
    result?.ended === 204 && current.status === 401,
    "demo_session_end_not_enforced",
  );
}

async function fullGate() {
  assert(operatorPassword, "browser_operator_password_missing");
  const pages = [];
  try {
    const viewer = await BrowserPage.launch(`${baseUrl.origin}/`);
    pages.push(viewer);
    const theater = await assertProductTheater(viewer);
    await assertWelcomeLanguages(viewer);
    const reducedMotionViewer = await BrowserPage.launch(
      `${baseUrl.origin}/`,
      { reducedMotion: true },
    );
    pages.push(reducedMotionViewer);
    const reducedTheater = await assertProductTheater(
      reducedMotionViewer,
      { reducedMotion: true },
    );
    const pinnedViewerAuthority = await startDemo(viewer);
    const languages = await assertAppLanguages(viewer);
    const viewports = await assertViewports(viewer);
    await assertCorrectedBusinessExperience(viewer, "viewer");
    const viewerAreas = await assertSixViewerAreas(viewer);
    await askMonthlyReportAfterExplicitSend(viewer, 1);
    await askEditedAdvertisingPerformance(viewer, 2);
    await assertViewports(viewer);
    assert(
      await viewer.evaluate("document.querySelector('.chat-answer-card')?.innerText.includes('Authoritative facts')"),
      "chat_authority_missing",
    );
    await viewer.setValue(".chat-question", "Prepare one synthetic stockout action");
    await viewer.clickSelector(".chat-form button[type='submit']");
    await viewer.waitFor(
      "document.querySelectorAll('.chat-answer-card').length === 3",
      "planned-inventory-chat-answer",
      30_000,
    );
    const canDraft = await viewer.evaluate(
      "[...document.querySelectorAll('button')].some((node) => node.textContent.includes('Create Action draft'))",
    );
    assert(canDraft, "chat_action_draft_unavailable");
    await viewer.clickText("Create Action draft");
    await viewer.waitFor(
      "document.body.innerText.includes('Action draft created')",
      "action-draft-created",
    );
    await viewer.clickText(ui.actions);
    await viewer.waitFor(
      "document.querySelector('.action-card') && document.querySelector('[data-view-root]')?.innerText.includes('Action Inbox')",
      "action-inbox",
    );
    const viewerEstimates = await viewer.evaluate(
      "document.querySelectorAll('.action-simulation-estimates .action-detail').length",
    );
    assert(viewerEstimates === 3, "viewer_action_estimate_count_invalid");
    await viewer.clickText(ui.review);
    await viewer.waitFor(
      "document.querySelector('.action-card')?.innerText.includes('reviewed')",
      "viewer-action-simulation",
    );
    await assertViewports(viewer);
    const operator = await BrowserPage.launch(`${baseUrl.origin}/login`);
    pages.push(operator);
    const loginSignIn = await operator.evaluate(`(() => {
      const heading = document.querySelector("h1")?.textContent?.trim();
      const submit = document.querySelector("[data-login-form] button[type='submit']")?.textContent?.trim();
      return heading === "Sign in" && submit === "Sign in"
        && !document.body.innerText.includes("Operator sign in");
    })()`);
    assert(loginSignIn, "stable_sign_in_copy_invalid");
    await operator.setValue("#operator-login", "operator");
    await operator.setValue("#operator-password", operatorPassword);
    await operator.clickSelectorForNavigation("[data-login-form] button[type='submit']");
    await operator.waitFor(
      `location.pathname === '/app' && document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.operatorWorkspace)} && document.body.innerText.includes(${JSON.stringify(ui.currentData)})`,
      "operator-runtime",
      30_000,
    );
    await assertCorrectedBusinessExperience(operator, "operator");
    await verifyOperatorActionExportAndOutcome(operator);
    const published = await importAndPublishSyntheticWorkbook(operator);

    await viewer.reload();
    await viewer.waitFor(
      `location.pathname === '/demo' && document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.overview)}`,
      "existing-viewer-remains-pinned",
      30_000,
    );
    const reloadedViewerAuthority = await viewerDatasetAuthority(viewer);
    assert(
      reloadedViewerAuthority.releaseDatasetVersionId
        === pinnedViewerAuthority.releaseDatasetVersionId,
      "existing_viewer_release_drifted",
    );

    const second = await BrowserPage.launch(`${baseUrl.origin}/`);
    pages.push(second);
    const secondViewerAuthority = await startDemo(second);
    assert(
      secondViewerAuthority.releaseDatasetVersionId === published.versionId,
      "new-viewer_release_not_updated",
    );
    if (published.releaseChanged) {
      assert(
        secondViewerAuthority.releaseDatasetVersionId
          !== pinnedViewerAuthority.releaseDatasetVersionId,
        "new_viewer_not_advanced",
      );
    } else {
      assert(
        secondViewerAuthority.releaseDatasetVersionId
          === pinnedViewerAuthority.releaseDatasetVersionId,
        "replayed_release_drifted",
      );
    }
    await route(second, "briefing", ui.decisionCenter, "Ask BizPulse");
    assert(
      await second.evaluate("document.querySelectorAll('.chat-answer-card').length === 0"),
      "viewer_session_leak",
    );
    await askAdvertisingPerformance(second, 1);

    await route(operator, "workspace", ui.operatorWorkspace, ui.currentData);
    await assertViewports(operator);
    await route(operator, "briefing", ui.decisionCenter, "Ask BizPulse");
    await askAdvertisingPerformance(operator, 1);
    await assertViewports(operator);
    await operator.clickText("Save Q&A");
    await operator.waitFor("document.body.innerText.includes('Saved Q&A')", "saved-qa");
    await operator.clickText(ui.actions);
    await operator.waitFor(
      "document.querySelector('[data-view-root]')?.innerText.includes('Action Inbox')",
      "operator-action-inbox",
    );

    await route(viewer, "briefing", ui.decisionCenter, "Ask BizPulse");
    await viewer.waitFor(
      "document.querySelector('[data-chat-session-state=\"active\"]') && document.querySelectorAll('.chat-answer-card').length === 3 && ![...document.querySelectorAll('button')].find((node) => node.textContent.includes('End Chat Session'))?.disabled",
      "return-to-chat",
      30_000,
    );
    await viewer.clickText("End Chat Session");
    await viewer.waitFor(
      "location.pathname === '/demo' && document.querySelector('[data-chat-session-state=\"empty\"]') && document.querySelectorAll('.chat-answer-card').length === 0",
      "chat-session-cleared",
      30_000,
    );
    await endDemoSession(viewer);
    await endDemoSession(second);

    const allConsoleErrors = pages.flatMap((page) => page.consoleErrors);
    const chatSessionRequests = pages.flatMap((page) => page.requestEvents).filter(
      (event) => new URL(event.url).pathname === "/api/v1/ai-chat/session",
    );
    const errorResponses = pages.flatMap((page) => page.errorResponses);
    const externalRequests = pages.flatMap((page) => page.requests).filter((raw) => {
      try {
        const url = new URL(raw);
        return ["http:", "https:"].includes(url.protocol) && url.origin !== baseUrl.origin;
      } catch {
        return false;
      }
    });
    assert(
      allConsoleErrors.length === 0,
      `browser_console_errors:${allConsoleErrors};chat_session_requests:${JSON.stringify(chatSessionRequests)};error_responses:${JSON.stringify(errorResponses)}`,
    );
    assert(externalRequests.length === 0, `external_requests:${externalRequests}`);
    return {
      consoleErrors: allConsoleErrors.length,
      editedPrompt: true,
      externalRequests: externalRequests.length,
      languages,
      loginSignIn,
      monthlyPreset: true,
      operator: true,
      operatorExport: true,
      operatorImport: true,
      operatorOutcome: true,
      operatorPublish: true,
      pinnedRefresh: true,
      productTheater: {
        autoplay: theater.autoplay,
        manual: theater.manual && reducedTheater.manual,
        reducedMotion: !reducedTheater.autoplay,
        slides: theater.slides,
      },
      scenario: "full",
      sessionsEnded: 2,
      sixPresets: true,
      viewerAreas,
      viewerEstimates,
      viewers: 2,
      viewports,
    };
  } finally {
    await Promise.all(pages.map((page) => page.close()));
  }
}

async function coreGate() {
  assert(operatorPassword, "browser_operator_password_missing");
  const pages = [];
  try {
    const viewer = await BrowserPage.launch(`${baseUrl.origin}/`);
    pages.push(viewer);
    const pinnedViewerAuthority = await startDemo(viewer);
    const viewports = await assertViewports(viewer);
    await route(viewer, "sales", ui.sales, "Net sales");
    await route(viewer, "inventory", ui.inventory, "Stockout");
    await route(viewer, "profit", ui.profit, "Contribution");
    await assertViewerDataEvidence(viewer);
    const operator = await BrowserPage.launch(`${baseUrl.origin}/login`);
    pages.push(operator);
    await operator.setValue("#operator-login", "operator");
    await operator.setValue("#operator-password", operatorPassword);
    await operator.clickSelectorForNavigation("[data-login-form] button[type='submit']");
    await operator.waitFor(
      `location.pathname === '/app' && document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.operatorWorkspace)} && document.body.innerText.includes(${JSON.stringify(ui.currentData)})`,
      "operator-runtime",
      30_000,
    );
    await verifyOperatorActionExportAndOutcome(operator);
    const published = await importAndPublishSyntheticWorkbook(operator);

    await viewer.reload();
    await viewer.waitFor(
      `location.pathname === '/demo' && document.querySelector('[data-view-title]')?.textContent === ${JSON.stringify(ui.overview)}`,
      "existing-viewer-remains-pinned",
      30_000,
    );
    const reloadedViewerAuthority = await viewerDatasetAuthority(viewer);
    assert(
      reloadedViewerAuthority.releaseDatasetVersionId
        === pinnedViewerAuthority.releaseDatasetVersionId,
      "existing_viewer_release_drifted",
    );
    const second = await BrowserPage.launch(`${baseUrl.origin}/`);
    pages.push(second);
    const secondViewerAuthority = await startDemo(second);
    assert(
      secondViewerAuthority.releaseDatasetVersionId === published.versionId,
      "new-viewer_release_not_updated",
    );
    if (published.releaseChanged) {
      assert(
        secondViewerAuthority.releaseDatasetVersionId
          !== pinnedViewerAuthority.releaseDatasetVersionId,
        "new_viewer_not_advanced",
      );
    } else {
      assert(
        secondViewerAuthority.releaseDatasetVersionId
          === pinnedViewerAuthority.releaseDatasetVersionId,
        "replayed_release_drifted",
      );
    }
    await route(operator, "workspace", ui.operatorWorkspace, ui.currentData);
    await assertViewports(operator);
    await endDemoSession(viewer);
    await endDemoSession(second);

    const allConsoleErrors = pages.flatMap((page) => page.consoleErrors);
    const externalRequests = pages.flatMap((page) => page.requests).filter((raw) => {
      try {
        const url = new URL(raw);
        return ["http:", "https:"].includes(url.protocol) && url.origin !== baseUrl.origin;
      } catch {
        return false;
      }
    });
    assert(allConsoleErrors.length === 0, `browser_console_errors:${allConsoleErrors}`);
    assert(externalRequests.length === 0, `external_requests:${externalRequests}`);
    return {
      consoleErrors: allConsoleErrors.length,
      externalRequests: externalRequests.length,
      operator: true,
      operatorExport: true,
      operatorImport: true,
      operatorOutcome: true,
      operatorPublish: true,
      pinnedRefresh: true,
      scenario: "core",
      sessionsEnded: 2,
      viewers: 2,
      viewports,
    };
  } finally {
    await Promise.all(pages.map((page) => page.close()));
  }
}

async function terminalGate(expectedCode) {
  const page = await BrowserPage.launch(`${baseUrl.origin}/`);
  try {
    await startDemo(page);
    await route(page, "briefing", ui.decisionCenter, "Ask BizPulse");
    await askAdvertisingPerformance(page, 1);
    await page.waitFor(
      `document.querySelector('.chat-answer-card')?.innerText.includes(${JSON.stringify(expectedCode)})`,
      `terminal-state:${expectedCode}`,
      30_000,
    );
    await page.waitForNetworkIdle();
    const responseDeadline = Date.now() + 5_000;
    while (
      !page.chatResponses.some((item) => item.ready)
      && Date.now() < responseDeadline
    ) await sleep(25);
    const response = page.chatResponses.findLast((item) => item.ready);
    assert(response?.status === 201, "terminal_chat_response_missing");
    const audit = response.providerAudit;
    assert(audit !== null, "terminal_provider_audit_missing");
    const attempts = Array.isArray(audit.attempts) ? audit.attempts : [];
    const evidence = expectedCode === "AI_CHAT_BUDGET_EXHAUSTED"
      ? {
          ledgerAttemptCount: audit.ledger_attempt_count,
          ledgerReservedTokens: audit.ledger_reserved_tokens,
          providerAttemptCount: audit.attempt_count,
          providerReservedTokens: audit.reserved_tokens,
        }
      : {
          ledgerAttemptCount: audit.ledger_attempt_count,
          ledgerReservedTokens: audit.ledger_reserved_tokens,
          providerAttemptCount: audit.attempt_count,
          providerErrorCode: attempts[0]?.error_code,
          providerReservedTokens: audit.reserved_tokens,
          providerStatus: attempts[0]?.status,
        };
    if (expectedCode === "AI_CHAT_BUDGET_EXHAUSTED") {
      assert(evidence.providerAttemptCount === 0, "budget_provider_attempted");
      assert(evidence.ledgerAttemptCount === 0, "budget_ledger_charged");
      assert(evidence.providerReservedTokens === 0, "budget_tokens_reserved");
      assert(evidence.ledgerReservedTokens === 0, "budget_ledger_tokens_reserved");
    } else {
      assert(evidence.providerAttemptCount === 1, "provider_attempt_count_invalid");
      assert(evidence.ledgerAttemptCount === 1, "provider_ledger_count_invalid");
      assert(evidence.providerReservedTokens >= 16000, "provider_reservation_missing");
      assert(
        evidence.ledgerReservedTokens === evidence.providerReservedTokens,
        "provider_ledger_reservation_drift",
      );
      assert(evidence.providerStatus === "failed", "provider_attempt_status_invalid");
      assert(
        evidence.providerErrorCode === "provider_auth_rejected",
        "provider_key_vault_read_unproven",
      );
    }
    await route(page, "sales", ui.sales, "Net sales");
    const externalRequests = page.requests.filter((raw) => {
      try {
        const url = new URL(raw);
        return ["http:", "https:"].includes(url.protocol) && url.origin !== baseUrl.origin;
      } catch {
        return false;
      }
    });
    assert(page.consoleErrors.length === 0, `browser_console_errors:${page.consoleErrors}`);
    assert(externalRequests.length === 0, `external_requests:${externalRequests}`);
    return {
      consoleErrors: page.consoleErrors.length,
      externalRequests: externalRequests.length,
      scenario,
      state: expectedCode,
      ...evidence,
    };
  } finally {
    await page.close();
  }
}

async function scopeReadonlyGate() {
  const page = await BrowserPage.launch(`${baseUrl.origin}/`);
  try {
    await startDemo(page);
    await page.send("Emulation.setDeviceMetricsOverride", {
      width: 390,
      height: 844,
      deviceScaleFactor: 1,
      mobile: false,
    });
    const initial = await page.evaluate(`(() => {
      const select = document.querySelector("[data-store-scope-selector]");
      return {
        options: [...(select?.options ?? [])].map((option) => ({
          label: option.textContent.trim(),
          value: option.value,
        })),
        label: document.querySelector(".store-scope-label")?.textContent.trim(),
      };
    })()`);
    assert(initial?.options?.length === 3, "scope_option_count_invalid");
    assert(
      initial.options.every((option) => option.value && option.label),
      "scope_option_label_invalid",
    );
    assert(initial.label === t("en", "storeScope.label"), "scope_english_label_invalid");

    await page.evaluate("document.querySelector('[data-store-scope-selector]')?.focus()");
    const keyboard = await page.evaluate(
      "document.activeElement?.matches('[data-store-scope-selector]')",
    );
    assert(keyboard, "scope_keyboard_focus_invalid");

    const selectedIds = [];
    for (const option of [...initial.options.slice(1), initial.options[0]]) {
      await page.setValue("[data-store-scope-selector]", option.value);
      await page.waitFor(
        `document.querySelector('[data-store-scope-selector]')?.value === ${JSON.stringify(option.value)}
          && document.querySelector('[data-store-scope-notice]')?.hidden === false`,
        `scope-switch-${option.value}`,
      );
      selectedIds.push(option.value);
      if (selectedIds.length === 1) {
        await route(page, "sales", ui.sales, "Net sales");
        await route(page, "inventory", ui.inventory, "Stockout");
        await route(page, "profit", ui.profit, "Contribution");
        await route(page, "briefing", ui.decisionCenter, "Ask BizPulse");
        await page.clickText(ui.actions);
        await page.waitFor(
          `document.querySelector('.action-card') || document.body.innerText.includes(${JSON.stringify(ui.actionsEmpty)})`,
          "scope-action-loaded",
        );
        await route(page, "workspace", ui.viewerWorkspace, "Choose how to explore");
        await page.clickText(t("en", "workspace.tab.library"));
        await page.waitFor(
          "document.querySelector('.library-workbook .library-data-table')",
          "scope-library-read",
        );
        await route(page, "overview", ui.overview, "Net sales");
      }
    }

    await page.clickSelector("[data-language-toggle]");
    await page.waitFor(
      `document.querySelector('.store-scope-label')?.textContent.trim() === ${JSON.stringify(t("zh", "storeScope.label"))}`,
      "scope-chinese-label",
    );
    const bilingual = await page.evaluate(`(() => {
      const select = document.querySelector("[data-store-scope-selector]");
      return document.querySelector(".store-scope-label")?.textContent.trim()
        === ${JSON.stringify(t("zh", "storeScope.label"))}
        && [...(select?.options ?? [])].every((option) => option.textContent.trim());
    })()`);
    assert(bilingual, "scope_bilingual_selector_invalid");
    await page.clickSelector("[data-language-toggle]");

    const scopedIds = new Set(
      page.requests.flatMap((raw) => {
        try {
          const url = new URL(raw);
          return url.origin === baseUrl.origin && url.searchParams.has("store_id")
            ? [url.searchParams.get("store_id")]
            : [];
        } catch {
          return [];
        }
      }),
    );
    assert(
      initial.options.slice(1).every((option) => scopedIds.has(option.value)),
      `scope_request_authority_missing:${JSON.stringify([...scopedIds])}`,
    );
    await page.waitForNetworkIdle();
    await endDemoSession(page);
    await sleep(100); // Drain ordered CDP diagnostics.
    const externalRequests = page.requests.filter((raw) => {
      try {
        const url = new URL(raw);
        return ["http:", "https:"].includes(url.protocol) && url.origin !== baseUrl.origin;
      } catch {
        return false;
      }
    });
    assert(page.consoleErrors.length === 0, `browser_console_errors:${page.consoleErrors}`);
    assert(externalRequests.length === 0, `external_requests:${externalRequests}`);
    return {
      bilingual: true,
      consoleErrors: page.consoleErrors.length,
      externalRequests: externalRequests.length,
      keyboard: true,
      narrow: true,
      options: initial.options.length,
      scenario: "scope-readonly",
      switches: selectedIds.length,
    };
  } finally {
    await page.close();
  }
}

async function paidAiGate() {
  const page = await BrowserPage.launch(`${baseUrl.origin}/`);
  try {
    await startDemo(page);
    await route(page, "briefing", ui.decisionCenter, "Ask BizPulse");
    await askMonthlyReportAfterExplicitSend(page, 1);
    assert(
      await page.evaluate(
        "document.querySelector('.chat-answer-card')?.innerText.includes('Authoritative facts')",
      ),
      "paid_ai_authority_missing",
    );
    await page.waitForNetworkIdle();
    const responseDeadline = Date.now() + 5_000;
    while (
      !page.chatResponses.some((item) => item.ready)
      && Date.now() < responseDeadline
    ) await sleep(25);
    const response = page.chatResponses.findLast((item) => item.ready);
    const audit = response?.providerAudit;
    assert(response?.status === 201 && audit !== null, "paid_provider_audit_missing");
    assert(audit.attempt_count === 1, "paid_provider_attempt_count_invalid");
    assert(audit.ledger_attempt_count === 1, "paid_provider_ledger_count_invalid");
    assert(response.csrfHeaderPresent, "paid_demo_csrf_missing");
    assert(response.presetAuditComplete, "paid_preset_audit_missing");
    assert(response.storeScopeCount >= 1, "paid_store_scope_missing");
    assert(
      await page.evaluate("location.pathname === '/demo'"),
      "paid_demo_viewer_missing",
    );
    const externalRequests = page.requests.filter((raw) => {
      try {
        const url = new URL(raw);
        return ["http:", "https:"].includes(url.protocol) && url.origin !== baseUrl.origin;
      } catch {
        return false;
      }
    });
    assert(page.consoleErrors.length === 0, `browser_console_errors:${page.consoleErrors}`);
    assert(externalRequests.length === 0, `external_requests:${externalRequests}`);
    return {
      consoleErrors: page.consoleErrors.length,
      externalRequests: externalRequests.length,
      providerTurns: audit.attempt_count,
      publicDemoViewer: true,
      csrfSessionScoped: true,
      presetAuditComplete: true,
      storeScopeCount: response.storeScopeCount,
      scenario: "paid-ai",
    };
  } finally {
    await page.close();
  }
}

async function aiDisabledGate() {
  const page = await BrowserPage.launch(`${baseUrl.origin}/`);
  try {
    await startDemo(page);
    await route(page, "briefing", ui.decisionCenter, "Ask BizPulse");
    await page.waitFor(
      "document.querySelectorAll('.chat-recommended-grid button').length === 6",
      "six-prompt-presets",
    );
    const chatRequestsBefore = chatSubmitRequestCount(page);
    assert(
      await page.evaluate(`document.body.innerText.includes(${JSON.stringify(ui.aiDisabled)})`),
      "ai_disabled_status_missing",
    );
    assert(
      await page.evaluate("document.querySelectorAll('.chat-recommended-grid button:disabled').length === 6"),
      "ai_disabled_presets_not_disabled",
    );
    await sleep(100);
    const chatRequestsAfter = chatSubmitRequestCount(page);
    assert(chatRequestsAfter === chatRequestsBefore, "ai_disabled_requested_provider");
    const externalRequests = page.requests.filter((raw) => {
      try {
        const url = new URL(raw);
        return ["http:", "https:"].includes(url.protocol) && url.origin !== baseUrl.origin;
      } catch {
        return false;
      }
    });
    assert(page.consoleErrors.length === 0, `browser_console_errors:${page.consoleErrors}`);
    assert(externalRequests.length === 0, `external_requests:${externalRequests}`);
    await endDemoSession(page);
    return {
      consoleErrors: page.consoleErrors.length,
      disabledPresets: 6,
      externalRequests: externalRequests.length,
      providerTurns: 0,
      scenario: "ai-disabled",
    };
  } finally {
    await page.close();
  }
}

let result;
if (scenario === "core") result = await coreGate();
else if (scenario === "full") result = await fullGate();
else if (scenario === "scope-readonly") result = await scopeReadonlyGate();
else if (scenario === "ai-disabled") result = await aiDisabledGate();
else if (scenario === "paid-ai") result = await paidAiGate();
else if (scenario === "provider-unavailable") {
  result = await terminalGate("AI_CHAT_UNAVAILABLE");
} else if (scenario === "budget") {
  result = await terminalGate("AI_CHAT_BUDGET_EXHAUSTED");
} else throw new Error(`browser_scenario_invalid:${scenario}`);

process.stdout.write(`${JSON.stringify(result)}\n`);
