import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

const featureRoot = new URL(
  "../../frontend/assets/features/workspace/",
  import.meta.url,
);

class ViewerElement {
  constructor(tag = "div") {
    this.tag = tag;
    this.children = [];
    this.dataset = {};
    this.attributes = new Map();
    this._textContent = "";
    this.type = "";
    this.listeners = new Map();
    this.files = [];
    this.value = "";
    this.hidden = false;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  addEventListener(name, callback) {
    this.listeners.set(name, callback);
  }

  removeEventListener(name) {
    this.listeners.delete(name);
  }

  click() {
    this.listeners.get("click")?.({ preventDefault() {} });
  }

  set textContent(value) {
    this._textContent = String(value);
  }

  get textContent() {
    return [
      this._textContent,
      ...this.children.map((child) =>
        typeof child === "string" ? child : child?.textContent ?? ""
      ),
    ].join(" ");
  }
}

function publicReleaseFixture(overrides = {}) {
  return {
    dataset_version_id: "version-1",
    version_number: 7,
    schema_version: "synthetic.v1",
    content_sha256: "a".repeat(64),
    reporting_period: ["2026-05-01", "2026-07-31"],
    current_period: ["2026-07-01", "2026-07-31"],
    comparison_period: ["2026-06-01", "2026-06-30"],
    currency: "BRL",
    source_roles: ["daily_sales", "shopee_advertising", "inventory_receipt_lot"],
    precomputed_analyses: ["sales_ads", "inventory_risk", "operating_profit"],
    evidence_states: ["measured", "derived", "assumed", "unknown"],
    ...overrides,
  };
}

test("workspace reducer stores projections but never browser File objects", async () => {
  const { initialWorkspaceState, reduceWorkspace } = await import(
    new URL("state.mjs", featureRoot)
  );
  const state = reduceWorkspace(initialWorkspaceState(), {
    type: "upload/selected",
    fileName: "operator_import.xlsx",
    sizeBytes: 22007,
  });

  assert.equal(state.upload.fileName, "operator_import.xlsx");
  assert.equal(state.upload.sizeBytes, 22007);
  assert.equal("file" in state.upload, false);
});

test("operator upload queue deduplicates multiple selections without uploading", async () => {
  const { initialWorkspaceState, reduceWorkspace } = await import(
    new URL("state.mjs", featureRoot)
  );
  const descriptors = [
    { localKey: "0:sales.csv:10", name: "sales.csv", size: 10, mediaType: "text/csv", accepted: true },
    { localKey: "1:inventory.xlsx:20", name: "inventory.xlsx", size: 20, mediaType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", accepted: true },
  ];
  let state = reduceWorkspace(initialWorkspaceState(), {
    type: "queue/added",
    items: descriptors,
  });
  state = reduceWorkspace(state, {
    type: "queue/added",
    items: [descriptors[0]],
  });

  assert.deepEqual(
    state.queue.map((item) => [item.name, item.status]),
    [["sales.csv", "ready"], ["inventory.xlsx", "ready"]],
  );
  assert.equal("file" in state.queue[0], false);
  assert.equal(state.workflow, null);
});

test("operator queue retains successful uploads when a later item fails", async () => {
  const { initialWorkspaceState, reduceWorkspace } = await import(
    new URL("state.mjs", featureRoot)
  );
  let state = reduceWorkspace(initialWorkspaceState(), {
    type: "queue/added",
    items: [
      { localKey: "sales", name: "sales.csv", size: 10, accepted: true },
      { localKey: "cost", name: "cost.xlsx", size: 20, accepted: true },
    ],
  });
  state = reduceWorkspace(state, {
    type: "queue/item-uploaded",
    localKey: "sales",
    workflow: { id: "workflow-1", revision: 1 },
    upload: { id: "upload-1", source_filename: "sales.csv" },
  });
  state = reduceWorkspace(state, {
    type: "queue/item-failed",
    localKey: "cost",
    code: "SOURCE_SHAPE_INVALID",
  });

  assert.deepEqual(state.queue.map((item) => item.status), ["uploaded", "failed"]);
  assert.equal(state.queue[0].upload.id, "upload-1");
  assert.equal(state.queue[1].error, "SOURCE_SHAPE_INVALID");
});

test("workspace reducer preserves a workflow and queues multiple source projections", async () => {
  const { initialWorkspaceState, reduceWorkspace } = await import(
    new URL("state.mjs", featureRoot)
  );
  const workflow = { id: "workflow-1", revision: 1 };
  let state = reduceWorkspace(initialWorkspaceState(), {
    type: "upload/selected",
    fileName: "sales.csv",
    sizeBytes: 10,
  });
  state = reduceWorkspace(state, {
    type: "source/uploaded",
    workflow,
    upload: { id: "upload-1", source_filename: "sales.csv" },
  });
  state = reduceWorkspace(state, { type: "source/add" });
  state = reduceWorkspace(state, {
    type: "upload/selected",
    fileName: "advertising.csv",
    sizeBytes: 20,
  });
  state = reduceWorkspace(state, {
    type: "source/uploaded",
    workflow: { ...workflow, revision: 2 },
    upload: { id: "upload-2", source_filename: "advertising.csv" },
  });

  assert.equal(state.workflow.id, "workflow-1");
  assert.deepEqual(
    state.uploads.map((upload) => upload.id),
    ["upload-1", "upload-2"],
  );
  assert.equal(state.upload.id, "upload-2");
});

test("workspace reducer stores the direct preview API projection", async () => {
  const { initialWorkspaceState, reduceWorkspace } = await import(
    new URL("state.mjs", featureRoot)
  );
  const state = reduceWorkspace(initialWorkspaceState(), {
    type: "preview/completed",
    workflow_id: "workflow-1",
    upload_id: "upload-1",
    candidate_sha256: "a".repeat(64),
    records: [{ sku_id: "SYNTH-SKU-001" }],
  });

  assert.deepEqual(state.preview.records, [{ sku_id: "SYNTH-SKU-001" }]);
  assert.equal(state.preview.workflow_id, "workflow-1");
});

test("workspace reducer stores direct commit plan and result projections", async () => {
  const { initialWorkspaceState, reduceWorkspace } = await import(
    new URL("state.mjs", featureRoot)
  );
  let state = reduceWorkspace(initialWorkspaceState(), {
    type: "commit/planned",
    workflow_id: "workflow-1",
    expected_revision: 4,
    ready: true,
    candidate_sha256s: ["a".repeat(64)],
    content_sha256: "b".repeat(64),
  });

  assert.equal(state.commitPlan.ready, true);
  state = reduceWorkspace(state, {
    type: "commit/completed",
    workflow_id: "workflow-1",
    dataset_version_id: "version-2",
    version_number: 2,
    content_sha256: "b".repeat(64),
    created: true,
  });
  assert.equal(state.committed.dataset_version_id, "version-2");
});

test("workspace keeps structured dedupe totals and stable conflict order", async () => {
  const { initialWorkspaceState, reduceWorkspace } = await import(
    new URL("state.mjs", featureRoot)
  );
  const conflicts = [
    {
      role: "daily_sales",
      business_key: [["store_id", "STORE-02"], ["order_id", "ORDER-2"]],
      fields: ["gross_sales_brl"],
      existing: { source_name: "base", sheet_name: null, row_number: 8 },
      incoming: { source_name: "sales.csv", sheet_name: null, row_number: 4 },
    },
    {
      role: "inventory_snapshot",
      business_key: [["store_id", "STORE-01"], ["sku_id", "SKU-1"]],
      fields: ["on_hand_units"],
      existing: { source_name: "base", sheet_name: null, row_number: 3 },
      incoming: { source_name: "stock.xlsx", sheet_name: "Sheet1", row_number: 9 },
    },
  ];
  const dedupe = {
    rows_read: 25,
    rows_retained: 20,
    duplicates_removed: 3,
    conflicts: 2,
    per_role: {
      daily_sales: {
        rows_read: 20,
        rows_retained: 16,
        duplicates_removed: 3,
        conflicts: 1,
      },
    },
  };

  const state = reduceWorkspace(initialWorkspaceState(), {
    type: "commit/planned",
    plan: {
      workflow_id: "workflow-1",
      ready: false,
      dedupe,
      conflicts,
      conflicts_truncated: false,
      conflict_download_url: "/api/v1/import-workflows/workflow-1/conflicts.csv",
    },
  });

  assert.deepEqual(state.dedupe, dedupe);
  assert.deepEqual(state.conflicts, conflicts);
  assert.equal(state.commitPlan.ready, false);
});

test("operator commit view summarizes dedupe, blocks conflicts, and links CSV only there", async () => {
  const operatorSource = await readFile(new URL("view.mjs", featureRoot), "utf8");
  const viewerSource = await readFile(new URL("public-view.mjs", featureRoot), "utf8");

  assert.match(operatorSource, /import-dedupe-summary/);
  assert.match(operatorSource, /import-dedupe-role-table/);
  assert.match(operatorSource, /import-conflict-table/);
  assert.match(operatorSource, /state\.conflicts\.length > 0/);
  assert.match(operatorSource, /conflictDownloadUrl/);
  assert.match(operatorSource, /workspace\.downloadConflicts/);
  assert.match(operatorSource, /formatBrl/);
  assert.match(operatorSource, /import-preview-table/);
  assert.doesNotMatch(operatorSource, /dedupe.*checkbox|checkbox.*dedupe/i);
  assert.doesNotMatch(viewerSource, /import-dedupe-summary|import-conflict-table|conflictDownloadUrl/);
});

test("workspace effects keep File in the effect boundary and send CSRF", async () => {
  const source = await readFile(new URL("effects.mjs", featureRoot), "utf8");

  assert.match(source, /fetch\(`/);
  assert.match(source, /X-CSRF-Token/);
  assert.match(source, /credentials:\s*"same-origin"/);
  assert.doesNotMatch(source, /localStorage/);
  assert.doesNotMatch(source, /state\.file/);
  assert.match(source, /existingWorkflow \?\?/);
  assert.match(source, /JSON\.stringify\(\{\}\)/);
});

test("workspace exposes explicit exact-version calculation before publish", async () => {
  const source = await readFile(new URL("view.mjs", featureRoot), "utf8");

  assert.match(source, /workspace\.calculate/);
  assert.match(source, /workspace\.retryCalculations/);
  assert.match(source, /preparation\.domains/);
  assert.match(source, /dataSource\.forVersion/);
  assert.match(source, /\.prepare\(\)/);
});

test("workspace view model exposes the explicit import stages", async () => {
  const { toWorkspaceViewModel } = await import(
    new URL("view-model.mjs", featureRoot)
  );
  const model = toWorkspaceViewModel({
    phase: "mapping",
    workflow: { revision: 3 },
    upload: { fileName: "advertising.csv", recognition: { sourceRole: "advertising" } },
    error: null,
  });

  assert.equal(model.phase, "mapping");
  assert.match(model.summary, /advertising\.csv/);
  assert.deepEqual(model.stages, [
    "source",
    "recognition",
    "mapping",
    "quality",
    "preview",
    "commit",
  ]);
});

test("release controls allow current-version readiness repair", async () => {
  const { toReleaseControlsModel } = await import(
    new URL("view-model.mjs", featureRoot)
  );
  const model = toReleaseControlsModel({
    status: "ready",
    current: { dataset_version_id: "version-2", version_number: 2 },
    versions: [
      { id: "version-1", version_number: 1, status: "complete" },
      { id: "version-2", version_number: 2, status: "complete" },
      { id: "version-3", version_number: 3, status: "failed" },
    ],
    preparations: {
      "version-1": { status: "ready", domains: [] },
    },
  });

  assert.equal(model.currentVersion, 2);
  assert.equal(model.versions[0].publishable, true);
  assert.equal(model.versions[1].isCurrent, true);
  assert.equal(model.versions[1].publishable, true);
  assert.equal(model.versions[2].publishable, false);
});

test("workspace renders operator release list and CAS publish controls", async () => {
  const source = await readFile(new URL("view.mjs", featureRoot), "utf8");

  assert.match(source, /dataSource\.listVersions\(\)/);
  assert.match(source, /dataSource\.publish\(/);
  assert.match(source, /expectedCurrentId/);
  assert.match(source, /workspace\.publishData/);
  assert.match(source, /dataset\.versionId = version\.id/);
  assert.doesNotMatch(source, /Publish v|Current v|release-digest/);
  assert.doesNotMatch(source, /synthetic-confirmation|pure synthetic data only/i);
  assert.match(source, /bindFileDropZone/);
  const initialLoad = source.slice(
    source.indexOf("async function loadReleaseControls"),
    source.indexOf("async function publishVersion"),
  );
  const publish = source.slice(
    source.indexOf("async function publishVersion"),
    source.indexOf("function renderReleaseControls"),
  );
  assert.doesNotMatch(initialLoad, /location\?\.reload/);
  assert.match(publish, /location\?\.reload/);
  assert.doesNotMatch(
    publish,
    /if \(workspaceIsActive\(\)\) globalThis\.location\?\.reload/,
  );
});

test("workspace release completion cannot overwrite a later route", async () => {
  class FakeElement {
    constructor(tag = "div") {
      this.tag = tag;
      this.children = [];
      this.dataset = {};
      this.attributes = new Map();
      this.textContent = "";
    }

    append(...children) {
      this.children.push(...children);
    }

    replaceChildren(...children) {
      this.children = [...children];
    }

    setAttribute(name, value) {
      this.attributes.set(name, String(value));
    }

    addEventListener() {}
  }

  let resolveVersions;
  let resolveRelease;
  const versions = new Promise((resolve) => {
    resolveVersions = resolve;
  });
  const release = new Promise((resolve) => {
    resolveRelease = resolve;
  });
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new FakeElement(tag);
    },
  };
  try {
    const { createViewRenderer } = await import(
      new URL("../../frontend/assets/views.mjs?workspace-fence-test", import.meta.url)
    );
    const root = new FakeElement("main");
    const title = new FakeElement("h1");
    const dataSource = {
      listVersions: () => versions,
      loadRelease: () => release,
      async loadAnalysis() {
        throw new Error("ANALYSIS_NOT_FOUND");
      },
    };
    const renderer = createViewRenderer({
      root,
      title,
      dataSource,
      release: null,
      mode: "operator",
    });

    renderer.render("workspace");
    renderer.render("overview");
    resolveVersions({ versions: [] });
    resolveRelease(null);
    await Promise.all([versions, release]);
    await new Promise((resolve) => setImmediate(resolve));

    assert.equal(title.textContent, "Business overview");
    assert.equal(root.children[0].className, "report-heading");
    assert.equal(
      root.children.some((child) => child.className === "import-workspace"),
      false,
    );
  } finally {
    globalThis.document = originalDocument;
  }
});

test("viewer workspace offers safe personal selection beside demo-data activation", async () => {
  const originalDocument = globalThis.document;
  globalThis.document = {
    createElement(tag) {
      return new ViewerElement(tag);
    },
  };
  try {
    const { renderPublicDataEvidence } = await import(
      new URL("public-view.mjs", featureRoot)
    );
    const root = new ViewerElement("main");
    let imports = 0;
    renderPublicDataEvidence(root, null, {
      language: "en",
      async onImportDemoData() { imports += 1; },
    });

    assert.match(root.textContent, /Import files/i);
    assert.match(root.textContent, /drag/i);
    assert.match(root.textContent, /Import demo data/i);
    assert.doesNotMatch(root.textContent, /synthetic|confirm|v1|pinned/i);

    const allNodes = [];
    const visit = (node) => {
      allNodes.push(node);
      for (const child of node.children ?? []) visit(child);
    };
    visit(root);
    const fileInput = allNodes.find((node) => node.tag === "input");
    const demoButton = allNodes.find(
      (node) => node.tag === "button" && /Import demo data/i.test(node.textContent),
    );
    assert.equal(fileInput.type, "file");
    assert.equal(fileInput.attributes.get("accept"), ".csv,.xls,.xlsx");
    fileInput.files = [{ name: "private.xlsx", size: 12 }];
    fileInput.listeners.get("change")();
    assert.match(root.textContent, /unavailable/i);
    await demoButton.listeners.get("click")();
    assert.equal(imports, 1);

    const chineseRoot = new ViewerElement("main");
    renderPublicDataEvidence(chineseRoot, null, {
      language: "zh",
      async onImportDemoData() {},
    });
    assert.match(chineseRoot.textContent, /导入文件/);
    assert.match(chineseRoot.textContent, /拖放/);
    assert.match(chineseRoot.textContent, /导入演示数据/);
  } finally {
    globalThis.document = originalDocument;
  }
});

test("viewer workspace fails closed on incomplete release metadata", async () => {
  const { toPublicDataEvidenceModel } = await import(
    new URL("public-view.mjs", featureRoot)
  );
  const model = toPublicDataEvidenceModel(
    publicReleaseFixture({ reporting_period: null }),
    "en",
  );

  assert.equal(model.status, "error");
  assert.equal(model.code, "PUBLIC_RELEASE_METADATA_INCOMPLETE");
  assert.doesNotMatch(JSON.stringify(model), /Period unavailable/i);
});
