# BizPulse Viewer / Operator Experience Corrections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Correct the approved local BizPulse experience so Viewer activation is a real lightweight demo action, Operator import and calculation remain fully functional, and both modes receive the approved bilingual shell, BP Library, richer analytics, P-priority inventory, collapsible Evidence, and permission-aware Settings without changing any hosted environment.

**Architecture:** Keep one immutable data-version pipeline and make the mode boundary explicit. Viewer sessions gain an idempotent activation marker that points at the existing shared precomputed release; Operator continues through multi-file import, standardization, immutable version creation, explicit preparation, publication, export, and outcome. A version-aware BP Library read model becomes the common navigation layer, while frontend view models consume deterministic analyses and never recompute authority in the browser. All corrections are additive from the approved design commit and stay inside the current isolated worktree.

**Tech Stack:** Python 3.12; FastAPI 0.138.2; SQLAlchemy Core 2.0.51; Alembic 1.18.5; PostgreSQL 17; native browser ES modules; Node 24 built-in test runner; pytest 9.1.1; Ruff 0.15.20; existing deterministic analysis, export, AI, release, and browser-acceptance infrastructure.

---

## Global Constraints

- `CORRECTION_START_SHA=61323ea54d678e8660be24d39247fe42e9f032e6` is the only changed-path base for this corrective implementation. Record `git rev-parse HEAD` at the start of every task; never use `DEPLOYED_RELEASE_SHA=537effe3036f77f83225beef12589bd447205a8b` as a development base.
- Work only in `/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift` on `codex/integrated-viewer-ai-anti-drift`. Preserve unrelated or unexpected edits and stop only for an actual overlap or authority change.
- The approved source of truth is `docs/superpowers/specs/2026-08-15-bizpulse-integrated-viewer-ai-experience-design.md` at design commit `61323ea`.
- This plan extends completed Tasks 1-13 from the earlier integrated plan. Do not rewrite or replay them, and do not alter their release anchors or claim their local evidence is hosted evidence.
- Every implementation task follows RED -> minimal GREEN -> focused regression -> `verify_changed` -> one small local commit. A task may use more than one RED test file only when the same interface crosses backend and frontend.
- Before adding each migration, run `cd bizpulse && .venv/bin/alembic heads`; if the expected head has drifted, rebase the new revision's `down_revision` onto the observed single local head rather than inventing a parallel head.
- Migrations are additive. Existing `source_confirmed_synthetic` and prior release/session fields remain readable for rollback compatibility; new behavior is selected by new fields and service logic.
- Viewer personal upload attempts must not read file bytes, construct `FormData`, or call any Operator import route. Viewer `Import demo data` may update only session activation metadata.
- Operator upload accepts supported authorized operational CSV/XLS/XLSX data without any synthetic or authorization checkbox. Security validation still rejects formulas, credentials, secrets, PII-shaped fields, external URLs, unsafe workbook structures, size/count violations, and unsupported schemas.
- Browser code never receives an AI key. Settings may expose only a server-computed availability state and bounded quota state. Do not inspect, create, log, or transmit secrets and do not make a real or paid AI call.
- No Azure, ACR/registry, Keychain, secret, DNS, push, PR, CI, deployment, slot, or production mutation is authorized. Local implementation, local PostgreSQL, temporary local services, browser validation, docs, and local commits are authorized.
- `Pinned`, hashes, schema identifiers, digests, raw UUIDs, and uncontextual `v1` remain available to logs/API internals where needed but do not appear in ordinary UI.
- All ordinary UI decimals use the shared two-decimal formatter. Raw data, calculation precision, API values, hashes, and exports are unchanged.
- `Product Opportunities` and network product search remain out of scope. Operator password discovery/reset/account creation remain out of scope.
- After each task run:

  ```bash
  cd /Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift/bizpulse
  .venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
  ```

  Use `--no-reuse` only in the final local acceptance task. If the selector requests a prohibited hosted/release action, stop and report the mismatch instead of performing that action.

## Batch Map

- **Batch A - entry and permission boundary:** Tasks 1-3 deliver the bilingual shell, custom upload affordance, real Viewer demo activation, compact Evidence, and removal of technical UI leakage.
- **Batch B - Operator data closure:** Tasks 4-6 deliver authorized multi-file import, exact-version preparation, and the BP Library/Exports workflow shared by both modes.
- **Batch C - analytical product depth:** Tasks 7-10 deliver the richer Overview, P-priority inventory, Settings, and concentrated browser/capacity acceptance.

## Task 1: Correct the application shell, language contract, upload primitive, and Evidence disclosure

**Files:**

- Modify: `bizpulse/frontend/index.html`
- Modify: `bizpulse/frontend/assets/styles.css`
- Modify: `bizpulse/frontend/assets/app.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/frontend/assets/features/analysis/view.mjs`
- Modify: `bizpulse/frontend/assets/core/evidence-drawer.mjs`
- Create: `bizpulse/frontend/assets/core/file-drop-zone.mjs`
- Create: `bizpulse/frontend/assets/core/disclosure.mjs`
- Modify: `bizpulse/tests/frontend/shell.test.mjs`
- Modify: `bizpulse/tests/frontend/i18n.test.mjs`
- Modify: `bizpulse/tests/frontend/copy-contract.test.mjs`
- Modify: `bizpulse/tests/frontend/analytics.test.mjs`
- Modify: `bizpulse/tests/frontend/evidence-drawer.test.mjs`
- Create: `bizpulse/tests/frontend/file-drop-zone.test.mjs`
- Create: `bizpulse/tests/frontend/disclosure.test.mjs`

### Step 1: Write failing shell, localization, upload, and disclosure tests

- [ ] Assert the desktop navigation renders localized full labels for the approved six primary regions: Data Workspace, Today Overview, Sales & Advertising, Inventory & Replenishment, Profit & Cost, and AI Decision Center. Settings is added as a separate utility destination in Task 9.
- [ ] Assert compact navigation retains a localized `aria-label` and tooltip string on hover/focus.
- [ ] Assert an always-visible in-app language selector calls the current view renderer after `setLocale` for Viewer and Operator.
- [ ] Assert upload UI renders only custom catalog text and the native `<input type="file">` is visually hidden, has `multiple`, and is activated only through the custom control.
- [ ] Assert `createFileDropZone` reports selected `File` objects without calling `arrayBuffer`, `text`, `stream`, or any network adapter.
- [ ] Assert Evidence returns exactly four visible rows when collapsed, all rows when expanded, and four again after collapse without losing its source collection.
- [ ] Assert ordinary rendered source does not include `Operator sign in`, `Course Demo`, `Synthetic Demo Data`, `纯合成演示`, `Pinned`, `schema`, `digest`, a hex hash label, or bilingual text joined with `/`.
- [ ] Assert `.chart-text-summary` is screen-reader-only and not repeated as visible body copy.

Use contract-focused tests such as:

```js
test("evidence disclosure defaults to four items without truncating the model", () => {
  const disclosure = createDisclosure({ itemCount: 7, collapsedCount: 4 });
  assert.deepEqual(disclosure.visibleIndexes(), [0, 1, 2, 3]);
  disclosure.expand();
  assert.deepEqual(disclosure.visibleIndexes(), [0, 1, 2, 3, 4, 5, 6]);
  disclosure.collapse();
  assert.equal(disclosure.totalCount, 7);
});

test("file drop selection does not inspect payload bytes", () => {
  const file = { name: "sales.csv", size: 10, type: "text/csv", text: fail };
  const result = normalizeSelectedFiles([file]);
  assert.deepEqual(result.map((item) => item.name), ["sales.csv"]);
});
```

Run RED:

```bash
cd bizpulse
node --test tests/frontend/shell.test.mjs tests/frontend/i18n.test.mjs tests/frontend/copy-contract.test.mjs tests/frontend/analytics.test.mjs tests/frontend/evidence-drawer.test.mjs tests/frontend/file-drop-zone.test.mjs tests/frontend/disclosure.test.mjs
```

Expected: failures for missing full-label navigation, file-drop/disclosure modules, and compact Evidence behavior.

### Step 2: Implement the minimal reusable UI primitives

- [ ] Add `createFileDropZone`/`normalizeSelectedFiles` as selection-only helpers. The component must accept click, Enter/Space, dragenter/dragleave/drop, validation messages, and locale text, but must never upload by itself.
- [ ] Add `createDisclosure({itemCount, collapsedCount: 4})` with deterministic expand/collapse state and `aria-expanded` metadata.
- [ ] Convert the application rail to full localized labels on desktop; preserve the compact icon treatment only under the existing responsive breakpoint and attach localized tooltip/focus text.
- [ ] Keep language selection reachable in every application page and rerender the current route on change.
- [ ] Render only the first four Evidence buttons initially with localized Show all/Show less controls and a count.
- [ ] Keep one visually hidden chart summary for assistive technology; remove the duplicate visible summary sentence.
- [ ] Delete technical normal-UI fragments, including the bottom `Pinned <hash>` text. Version/history context will return later only inside Library.

The disclosure contract should stay presentation-only:

```js
export function visibleEvidence(evidence, expanded, collapsedCount = 4) {
  const all = Array.isArray(evidence) ? evidence : [];
  return expanded ? all : all.slice(0, collapsedCount);
}
```

### Step 3: Run focused GREEN and static regressions

```bash
cd bizpulse
node --test tests/frontend/shell.test.mjs tests/frontend/i18n.test.mjs tests/frontend/copy-contract.test.mjs tests/frontend/analytics.test.mjs tests/frontend/evidence-drawer.test.mjs tests/frontend/file-drop-zone.test.mjs tests/frontend/disclosure.test.mjs tests/frontend/formatters.test.mjs tests/frontend/charts.test.mjs
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 4: Commit

```bash
git add frontend/index.html frontend/assets/styles.css frontend/assets/app.mjs frontend/assets/i18n/catalog.mjs frontend/assets/features/analysis/view.mjs frontend/assets/core/evidence-drawer.mjs frontend/assets/core/file-drop-zone.mjs frontend/assets/core/disclosure.mjs tests/frontend/shell.test.mjs tests/frontend/i18n.test.mjs tests/frontend/copy-contract.test.mjs tests/frontend/analytics.test.mjs tests/frontend/evidence-drawer.test.mjs tests/frontend/file-drop-zone.test.mjs tests/frontend/disclosure.test.mjs
git commit -m "feat: correct bilingual app shell and evidence disclosure"
```

## Task 2: Add real idempotent Viewer demo-data activation

**Files:**

- Create: `bizpulse/alembic/versions/0010_demo_data_activation.py`
- Modify: `bizpulse/src/db/schema.py`
- Modify: `bizpulse/src/repositories/sessions.py`
- Modify: `bizpulse/src/services/demo_session_service.py`
- Modify: `bizpulse/api/routers/demo_sessions.py`
- Modify: `bizpulse/api/routers/public_release.py`
- Modify: `bizpulse/api/dependencies/session.py`
- Modify: `bizpulse/api/v1/routers/actions.py`
- Modify: `bizpulse/api/v1/routers/ai_chat.py`
- Modify: `bizpulse/api/main.py`
- Modify: `bizpulse/frontend/assets/core/api-client.mjs`
- Modify: `bizpulse/frontend/assets/core/runtime-session.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/public-view.mjs`
- Modify: `bizpulse/frontend/assets/app.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/tests/postgres/test_migration_chain.py`
- Modify: `bizpulse/tests/services/test_demo_session_service.py`
- Modify: `bizpulse/tests/api/test_demo_sessions.py`
- Modify: `bizpulse/tests/api/test_public_release.py`
- Modify: `bizpulse/tests/api/v1/test_actions.py`
- Modify: `bizpulse/tests/api/v1/test_ai_chat.py`
- Create: `bizpulse/tests/security/test_viewer_operator_boundaries.py`
- Modify: `bizpulse/tests/frontend/runtime-session.test.mjs`
- Modify: `bizpulse/tests/frontend/workspace.test.mjs`
- Modify: `bizpulse/tests/frontend/api-client.test.mjs`

### Step 1: Write failing activation and isolation tests

- [ ] Assert a newly created Viewer session has `demo_data_imported=false` and remains pinned to one release internally without exposing that ID in UI.
- [ ] Assert `POST /api/demo/sessions/current/import-demo-data` requires the Viewer session and Demo CSRF contract.
- [ ] Assert the first activation sets `demo_data_imported_at`; a second activation returns the same timestamp and release association.
- [ ] Count `dataset_versions`, canonical/import rows, analysis runs/snapshots, and stored source objects before and after activation; assert all counts are unchanged.
- [ ] Assert release, analysis, Library, Ask BizPulse, and Action reads fail closed with `DEMO_DATA_NOT_IMPORTED` before activation and work after activation.
- [ ] Assert Viewer upload click/drop displays the localized unavailable state while spies prove no file-read method, `FormData`, or `/api/v1/imports` call occurs.
- [ ] Assert runtime startup can render Data Workspace before a release is activated, then refreshes capabilities and navigates to Overview after activation.

Service test shape:

```python
first = service.activate_demo_data(connection, principal)
counts_after_first = count_authoritative_rows(connection)
second = service.activate_demo_data(connection, principal)
assert second.demo_data_imported_at == first.demo_data_imported_at
assert count_authoritative_rows(connection) == counts_after_first == counts_before
```

Run RED:

```bash
cd bizpulse
.venv/bin/pytest tests/postgres/test_migration_chain.py tests/services/test_demo_session_service.py tests/api/test_demo_sessions.py tests/api/test_public_release.py tests/api/v1/test_actions.py tests/api/v1/test_ai_chat.py tests/security/test_viewer_operator_boundaries.py -q
node --test tests/frontend/runtime-session.test.mjs tests/frontend/workspace.test.mjs tests/frontend/api-client.test.mjs
```

Expected: missing migration field, endpoint, pre-activation gate, and frontend activation command.

### Step 2: Add the activation marker and idempotent service

- [ ] Add nullable `demo_data_imported_at` to `demo_sessions` in migration `0010`; existing sessions remain inactive until explicitly activated.
- [ ] Extend `DemoSessionProjection`, principal/session schemas, and repository mapping without changing existing session IDs or expiry behavior.
- [ ] Implement an atomic compare-and-set repository method. It updates only `demo_data_imported_at` and `last_seen_at`; it never calls the generator, importer, analysis service, Blob service, or public-release preparation.
- [ ] Add the CSRF-protected route and stable error code `DEMO_DATA_NOT_IMPORTED`.
- [ ] Centralize `require_demo_data_imported` so every Viewer authority read uses the same check.

The service boundary is intentionally small:

```python
def activate_demo_data(self, connection, principal: DemoPrincipal) -> DemoSessionProjection:
    session = self.sessions.get_active(connection, principal.session_id)
    if session.demo_data_imported_at is None:
        session = self.sessions.mark_demo_data_imported(
            connection,
            session.session_id,
            imported_at=self.clock.now(),
        )
    return session
```

### Step 3: Implement the Viewer workspace interaction

- [ ] Let runtime load the Viewer session even when `demo_data_imported=false`; do not request the public release until activation.
- [ ] Start Viewer on Data Workspace and render two adjacent actions: the disabled-personal-upload affordance and `Import demo data`.
- [ ] Use the Task 1 custom drop zone in Viewer mode with a selection callback that discards file references immediately after setting the localized unavailable message.
- [ ] On demo import, show only truthful `Preparing demo workspace`; call the activation endpoint once; refresh the session/release/data source; navigate to Overview on success.
- [ ] Make repeat activation return the already prepared workspace without generating a new visible version or a fake calculation progress state.

Frontend command shape:

```js
async importDemoData() {
  await this.api.activateDemoData();
  const [session, release] = await Promise.all([
    this.api.getCurrentDemoSession(),
    this.api.getCurrentPublicRelease(),
  ]);
  return { session, release };
}
```

### Step 4: Run GREEN, migration, and boundary regressions

```bash
cd bizpulse
.venv/bin/alembic upgrade head
.venv/bin/pytest tests/postgres/test_migration_chain.py tests/services/test_demo_session_service.py tests/api/test_demo_sessions.py tests/api/test_public_release.py tests/api/v1/test_actions.py tests/api/v1/test_ai_chat.py tests/security/test_viewer_operator_boundaries.py tests/security/test_cross_session_isolation.py -q
node --test tests/frontend/runtime-session.test.mjs tests/frontend/workspace.test.mjs tests/frontend/api-client.test.mjs tests/frontend/shell.test.mjs
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 5: Commit

```bash
git add alembic/versions/0010_demo_data_activation.py src/db/schema.py src/repositories/sessions.py src/services/demo_session_service.py api/routers/demo_sessions.py api/routers/public_release.py api/dependencies/session.py api/v1/routers/actions.py api/v1/routers/ai_chat.py api/main.py frontend/assets/core/api-client.mjs frontend/assets/core/runtime-session.mjs frontend/assets/data-sources/public.mjs frontend/assets/features/workspace/public-view.mjs frontend/assets/app.mjs frontend/assets/i18n/catalog.mjs tests/postgres/test_migration_chain.py tests/services/test_demo_session_service.py tests/api/test_demo_sessions.py tests/api/test_public_release.py tests/api/v1/test_actions.py tests/api/v1/test_ai_chat.py tests/security/test_viewer_operator_boundaries.py tests/frontend/runtime-session.test.mjs tests/frontend/workspace.test.mjs tests/frontend/api-client.test.mjs
git commit -m "feat: activate shared viewer demo data without recomputation"
```

## Task 3: Restore safe Operator multi-file import without confirmation checkboxes

**Files:**

- Create: `bizpulse/alembic/versions/0011_operator_source_kind.py`
- Modify: `bizpulse/src/db/schema.py`
- Modify: `bizpulse/src/repositories/imports.py`
- Modify: `bizpulse/src/repositories/datasets.py`
- Modify: `bizpulse/src/services/import_service.py`
- Modify: `bizpulse/src/synthetic/boundary.py`
- Modify: `bizpulse/src/adapters/upseller_excel.py`
- Modify: `bizpulse/src/adapters/shopee_advertising_csv.py`
- Modify: `bizpulse/api/v1/schemas/imports.py`
- Modify: `bizpulse/api/v1/routers/imports.py`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/state.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/view.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/tests/postgres/test_migration_chain.py`
- Modify: `bizpulse/tests/services/test_import_service.py`
- Modify: `bizpulse/tests/security/test_synthetic_source_boundary.py`
- Modify: `bizpulse/tests/unit/adapters/test_declared_sources.py`
- Modify: `bizpulse/tests/api/v1/test_imports.py`
- Modify: `bizpulse/tests/security/test_upload_boundary.py`
- Modify: `bizpulse/tests/frontend/workspace.test.mjs`

### Step 1: Write failing Operator import tests

- [ ] Assert `POST /api/v1/imports/workflows` accepts an empty JSON object for an authenticated Operator and records `source_kind=operator_upload`.
- [ ] Assert legacy rows keep `source_kind=legacy_synthetic` and remain releasable/readable.
- [ ] Assert ordinary store/SKU/order IDs without `SYNTH-` are accepted in Operator mode when the supported source schema is valid.
- [ ] Assert secrets, credential-like columns, email/phone/address PII, formulas, external URLs, unsupported workbook structures, and upload limits remain rejected.
- [ ] Assert the frontend queues multiple CSV/XLS/XLSX selections, deduplicates by stable local key, validates type/size before upload, supports remove/retry, and does not upload until the explicit Upload action.
- [ ] Assert queue upload creates one workflow, uploads sources in order, records per-file progress/failure, and does not discard successful entries when another entry fails.
- [ ] Assert no synthetic/data-rights authorization checkbox or related payload field exists in the rendered Operator flow.

Queue reducer test shape:

```js
const queue = addFiles(emptyUploadQueue(), [sales, inventory, costs]);
assert.deepEqual(queue.items.map((item) => item.status), ["ready", "ready", "ready"]);
assert.equal(uploadSpy.callCount, 0);
const next = await uploadQueue(queue, operatorDataSource);
assert.deepEqual(next.items.map((item) => item.status), ["uploaded", "uploaded", "uploaded"]);
```

Run RED:

```bash
cd bizpulse
.venv/bin/pytest tests/postgres/test_migration_chain.py tests/services/test_import_service.py tests/security/test_synthetic_source_boundary.py tests/unit/adapters/test_declared_sources.py tests/api/v1/test_imports.py tests/security/test_upload_boundary.py -q
node --test tests/frontend/workspace.test.mjs tests/frontend/file-drop-zone.test.mjs
```

Expected: current synthetic-only workflow rejects Operator data and current frontend holds only one file behind a synthetic confirmation.

### Step 2: Add an additive source-kind boundary

- [ ] Add non-null `source_kind` with an explicit legacy backfill and constrained values `legacy_synthetic`/`operator_upload`. Keep `source_confirmed_synthetic` present for old-code rollback reads.
- [ ] Create new workflows as `operator_upload` and `source_confirmed_synthetic=false`; do not accept either field from the browser.
- [ ] Split validation into `validate_safe_import_records` and the stricter existing `validate_synthetic_records`. Operator upload uses the safe boundary; fixture generation and legacy synthetic paths keep the strict boundary.
- [ ] Make adapters report normalized records without silently injecting `pure_synthetic` or rewriting business IDs when `source_kind=operator_upload`.
- [ ] Update release eligibility to require committed workflow, canonical version, quality artifacts, and an allowed source kind; remove the blanket requirement that all new Operator data claim to be synthetic.

Schema/service contract:

```python
class CreateWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

workflow = imports.create_workflow(
    connection,
    source_kind="operator_upload",
    source_confirmed_synthetic=False,
    idempotency_key=idempotency_key,
)
```

### Step 3: Replace the single-file state with an explicit queue

- [ ] Store no `File` object outside the active page lifecycle; remove it on success, remove, navigation teardown, or logout.
- [ ] Render localized file name, size, detected type, status, progress, validation error, Remove, and Retry.
- [ ] Let click and drop add one or many items; selection alone must not start upload.
- [ ] On Upload, create one workflow and process the ready queue deterministically; retain existing inspect, map, standardize, commit, and quality transitions.
- [ ] Keep commit/publish/export/outcome actions Operator-only and present; do not collapse the workflow into a frozen preview.

### Step 4: Run GREEN and compatibility regressions

```bash
cd bizpulse
.venv/bin/alembic upgrade head
.venv/bin/pytest tests/postgres/test_migration_chain.py tests/services/test_import_service.py tests/security/test_synthetic_source_boundary.py tests/unit/adapters/test_declared_sources.py tests/api/v1/test_imports.py tests/security/test_upload_boundary.py tests/services/test_public_release_service.py -q
node --test tests/frontend/workspace.test.mjs tests/frontend/file-drop-zone.test.mjs tests/frontend/i18n.test.mjs tests/frontend/copy-contract.test.mjs
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 5: Commit

```bash
git add alembic/versions/0011_operator_source_kind.py src/db/schema.py src/repositories/imports.py src/repositories/datasets.py src/services/import_service.py src/synthetic/boundary.py src/adapters/upseller_excel.py src/adapters/shopee_advertising_csv.py api/v1/schemas/imports.py api/v1/routers/imports.py frontend/assets/data-sources/operator.mjs frontend/assets/features/workspace/state.mjs frontend/assets/features/workspace/effects.mjs frontend/assets/features/workspace/view-model.mjs frontend/assets/features/workspace/view.mjs frontend/assets/i18n/catalog.mjs tests/postgres/test_migration_chain.py tests/services/test_import_service.py tests/security/test_synthetic_source_boundary.py tests/unit/adapters/test_declared_sources.py tests/api/v1/test_imports.py tests/security/test_upload_boundary.py tests/frontend/workspace.test.mjs
git commit -m "feat: restore safe operator multi-file import"
```

## Task 4: Add exact-version calculation preparation for Operator

**Files:**

- Create: `bizpulse/src/services/dataset_preparation_service.py`
- Modify: `bizpulse/src/services/public_release_service.py`
- Modify: `bizpulse/src/services/analysis_service.py`
- Modify: `bizpulse/src/services/forecast_service.py`
- Modify: `bizpulse/src/services/profit_bridge_service.py`
- Modify: `bizpulse/src/services/action_service.py`
- Modify: `bizpulse/api/v1/schemas/datasets.py`
- Modify: `bizpulse/api/v1/routers/datasets.py`
- Modify: `bizpulse/api/container.py`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/view.mjs`
- Modify: `bizpulse/frontend/assets/views.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Create: `bizpulse/tests/services/test_dataset_preparation_service.py`
- Modify: `bizpulse/tests/services/test_public_release_service.py`
- Create: `bizpulse/tests/api/v1/test_datasets.py`
- Modify: `bizpulse/tests/frontend/workspace.test.mjs`
- Create: `bizpulse/tests/frontend/operator-data-source.test.mjs`

### Step 1: Write failing exact-version calculation tests

- [ ] Create and commit an Operator dataset version that is not the current public release; assert preparation runs against that exact version and never reads the old public version.
- [ ] Assert `POST /api/v1/datasets/versions/{version_id}/prepare` is Operator-only, idempotent by version and algorithm versions, and returns separate readiness for Sales/Advertising, Inventory/P priority, Profit/Profit Bridge, Forecast, Actions, and Evidence.
- [ ] Assert failure in one domain reports that domain and leaves successful immutable snapshots readable; retry only executes missing/stale domains.
- [ ] Assert publish no longer hides calculation work: it verifies the same readiness contract and switches the public pointer only after all required domains are complete.
- [ ] Assert `OperatorDataSource.forVersion(versionId)` sends the selected version on every analysis/forecast/profit/action request and cannot silently fall back to `expectedVersionId` from page load.
- [ ] Assert UI exposes explicit Calculate/Retry calculations, progress by domain, then Publish, Export, and Outcome controls.

Run RED:

```bash
cd bizpulse
.venv/bin/pytest tests/services/test_dataset_preparation_service.py tests/services/test_public_release_service.py tests/api/v1/test_datasets.py -q
node --test tests/frontend/operator-data-source.test.mjs tests/frontend/workspace.test.mjs
```

Expected: no preparation service/endpoint and Operator page remains tied to the public release loaded at startup.

### Step 2: Extract a reusable preparation orchestrator

- [ ] Move preparation logic currently private to public publication into `DatasetPreparationService`; keep public publication as verification plus pointer switch.
- [ ] Use the existing deterministic services and algorithm-version identities. Do not add a browser-side calculator and do not use AI for any result.
- [ ] Return one bounded status document rather than streaming unbounded logs.
- [ ] Keep calls idempotent and transaction boundaries explicit; do not overwrite completed immutable snapshots.

Response shape:

```python
class DatasetPreparationResponse(BaseModel):
    dataset_version_id: UUID
    status: Literal["ready", "partial", "failed"]
    domains: list[PreparationDomain]

class PreparationDomain(BaseModel):
    name: Literal["sales_ads", "inventory", "profit", "forecast", "actions"]
    status: Literal["ready", "running", "failed", "unavailable"]
    limitation_code: str | None = None
```

### Step 3: Make the Operator frontend version-explicit

- [ ] Add `OperatorDataSource.forVersion(versionId)` or equivalent immutable binding; never mutate one shared expected-version field behind active views.
- [ ] After commit, select the new version and show data coverage/quality plus Calculate.
- [ ] Render per-domain progress and localized failures. Enable Publish only at `status=ready`; keep Export/outcome controls linked to that exact version.
- [ ] When publication completes, refresh Viewer-facing current-release metadata without changing the Operator-selected version unexpectedly.

### Step 4: Run GREEN and deterministic-analysis regressions

```bash
cd bizpulse
.venv/bin/pytest tests/services/test_dataset_preparation_service.py tests/services/test_public_release_service.py tests/api/v1/test_datasets.py tests/integration/test_analysis_vertical.py tests/unit/analysis/test_replenishment.py tests/services/test_profit_bridge_service.py tests/services/test_forecast_service.py tests/services/test_action_service.py -q
node --test tests/frontend/operator-data-source.test.mjs tests/frontend/workspace.test.mjs tests/frontend/analytics.test.mjs
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 5: Commit

```bash
git add src/services/dataset_preparation_service.py src/services/public_release_service.py src/services/analysis_service.py src/services/forecast_service.py src/services/profit_bridge_service.py src/services/action_service.py api/v1/schemas/datasets.py api/v1/routers/datasets.py api/container.py frontend/assets/data-sources/operator.mjs frontend/assets/features/workspace/effects.mjs frontend/assets/features/workspace/view-model.mjs frontend/assets/features/workspace/view.mjs frontend/assets/views.mjs frontend/assets/i18n/catalog.mjs tests/services/test_dataset_preparation_service.py tests/services/test_public_release_service.py tests/api/v1/test_datasets.py tests/frontend/workspace.test.mjs tests/frontend/operator-data-source.test.mjs
git commit -m "feat: prepare exact operator dataset versions"
```

## Task 5: Build the BP Library read model and Data Workspace tabs

**Files:**

- Create: `bizpulse/src/repositories/library.py`
- Create: `bizpulse/src/services/library_service.py`
- Create: `bizpulse/api/v1/schemas/library.py`
- Create: `bizpulse/api/v1/routers/library.py`
- Create: `bizpulse/api/routers/demo_library.py`
- Modify: `bizpulse/api/container.py`
- Modify: `bizpulse/api/v1/router.py`
- Modify: `bizpulse/api/main.py`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Create: `bizpulse/frontend/assets/features/library/state.mjs`
- Create: `bizpulse/frontend/assets/features/library/effects.mjs`
- Create: `bizpulse/frontend/assets/features/library/view-model.mjs`
- Create: `bizpulse/frontend/assets/features/library/view.mjs`
- Create: `bizpulse/frontend/assets/features/exports/view.mjs`
- Modify: `bizpulse/frontend/assets/views.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/frontend/assets/styles.css`
- Create: `bizpulse/tests/services/test_library_service.py`
- Create: `bizpulse/tests/api/v1/test_library.py`
- Create: `bizpulse/tests/api/test_demo_library.py`
- Create: `bizpulse/tests/frontend/library.test.mjs`
- Modify: `bizpulse/tests/frontend/workspace.test.mjs`
- Modify: `bizpulse/tests/security/test_viewer_operator_boundaries.py`

### Step 1: Write failing Library contracts

- [ ] Assert the Operator Library lists immutable versions from existing datasets/imports/artifacts, ordered newest first, with friendly version number/status, period, stores, SKUs, source-role coverage, row counts, quality/missing roles, analysis readiness, provenance, preview availability, and export availability.
- [ ] Assert one detail call reads a bounded preview and provenance for a selected version without returning source file bytes.
- [ ] Assert Viewer Library returns only the activated session's pinned shared release and is read-only.
- [ ] Assert Viewer cannot list Operator history, unpublished versions, source object locations, import workflow mutations, publish/export generation, or outcome routes.
- [ ] Assert Data Workspace has reachable Upload, Library, and Exports tabs; Viewer Upload contains only personal-unavailable plus Import demo data, Viewer Library is read-only, and Viewer Exports explains formal exports are Operator-only.
- [ ] Assert the ordinary Library UI hides UUID/hash/schema/digest fields while presenting a friendly `Version 3`/`版本 3` in history context.

Run RED:

```bash
cd bizpulse
.venv/bin/pytest tests/services/test_library_service.py tests/api/v1/test_library.py tests/api/test_demo_library.py tests/security/test_viewer_operator_boundaries.py -q
node --test tests/frontend/library.test.mjs tests/frontend/workspace.test.mjs
```

Expected: Library service/routes/features do not exist.

### Step 2: Implement a read model over existing authoritative tables

- [ ] Query existing dataset versions, import workflows/upload records, standardized artifacts, completed analyses, forecasts, profit bridges, exports, and publication pointer. Do not create a second source of truth or copy raw files.
- [ ] Calculate coverage and quality metadata with bounded aggregate queries; use explicit limits for version list, preview rows, source records, and provenance edges.
- [ ] Return internal IDs only where the client needs opaque selection; mark them non-display fields and never build labels from them.
- [ ] Require `require_demo_data_imported` for Viewer Library and pin it to the principal's release.

Read-model outline:

```python
@dataclass(frozen=True, slots=True)
class LibraryVersion:
    dataset_version_id: UUID          # opaque routing field
    version_number: int               # display field
    lifecycle: str
    period_start: date | None
    period_end: date | None
    stores: int
    skus: int
    source_roles: tuple[str, ...]
    row_count: int
    quality: QualitySummary
    preparation: PreparationSummary
```

### Step 3: Build Data Workspace navigation and mode-specific commands

- [ ] Add internal tabs with real routes/state, keyboard focus, localized names, and URL/hash restoration if the current router supports it.
- [ ] Render source roles, coverage, quality, missing inputs, preview, provenance, associated analyses/Evidence, and exports in scannable cards/tables.
- [ ] Operator history allows Select version, Calculate/Retry, Publish, and Generate/Download export only when the backend capability permits it.
- [ ] Viewer renders the same information density but no mutation buttons.

### Step 4: Run GREEN and authorization regressions

```bash
cd bizpulse
.venv/bin/pytest tests/services/test_library_service.py tests/api/v1/test_library.py tests/api/test_demo_library.py tests/security/test_viewer_operator_boundaries.py tests/security/test_cross_session_isolation.py -q
node --test tests/frontend/library.test.mjs tests/frontend/workspace.test.mjs tests/frontend/shell.test.mjs tests/frontend/i18n.test.mjs
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 5: Commit

```bash
git add src/repositories/library.py src/services/library_service.py api/v1/schemas/library.py api/v1/routers/library.py api/routers/demo_library.py api/container.py api/v1/router.py api/main.py frontend/assets/data-sources/public.mjs frontend/assets/data-sources/operator.mjs frontend/assets/features/library/state.mjs frontend/assets/features/library/effects.mjs frontend/assets/features/library/view-model.mjs frontend/assets/features/library/view.mjs frontend/assets/features/exports/view.mjs frontend/assets/views.mjs frontend/assets/i18n/catalog.mjs frontend/assets/styles.css tests/services/test_library_service.py tests/api/v1/test_library.py tests/api/test_demo_library.py tests/frontend/library.test.mjs tests/frontend/workspace.test.mjs tests/security/test_viewer_operator_boundaries.py
git commit -m "feat: add version-aware BP data library"
```

## Task 6: Close the Operator publish, export, and outcome workflow in the UI

**Files:**

- Create: `bizpulse/alembic/versions/0012_dataset_exports.py`
- Modify: `bizpulse/src/db/schema.py`
- Create: `bizpulse/src/repositories/dataset_exports.py`
- Create: `bizpulse/src/services/dataset_export_service.py`
- Create: `bizpulse/src/exports/__init__.py`
- Create: `bizpulse/src/exports/dataset_workbook.py`
- Modify: `bizpulse/src/repositories/library.py`
- Modify: `bizpulse/src/services/library_service.py`
- Modify: `bizpulse/api/v1/schemas/datasets.py`
- Modify: `bizpulse/api/v1/routers/datasets.py`
- Modify: `bizpulse/api/container.py`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/features/library/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/library/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/library/view.mjs`
- Modify: `bizpulse/frontend/assets/features/exports/view.mjs`
- Modify: `bizpulse/frontend/assets/features/action-inbox/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/action-inbox/view.mjs`
- Modify: `bizpulse/frontend/assets/core/api-client.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/tests/postgres/test_migration_chain.py`
- Create: `bizpulse/tests/services/test_dataset_export_service.py`
- Create: `bizpulse/tests/api/v1/test_dataset_exports.py`
- Modify: `bizpulse/tests/frontend/library.test.mjs`
- Modify: `bizpulse/tests/frontend/action-inbox.test.mjs`
- Create: `bizpulse/tests/frontend/operator-workflow.test.mjs`
- Modify: `bizpulse/tests/api/v1/test_actions.py`

### Step 1: Write one failing end-to-end frontend-state contract

- [ ] Model the Operator state sequence `queued -> uploaded -> inspected -> mapped -> standardized -> committed -> selected -> prepared -> published -> exported -> outcome recorded`.
- [ ] Assert every transition is reached by a visible localized control with an enabled/disabled reason; there are no dead buttons or implicit jumps.
- [ ] Assert dataset export generation/download uses the selected prepared version, exports normalized tables plus a manifest/quality sheet, and action outcome recording uses the selected Action Card/version.
- [ ] Assert export generation is Operator-only, idempotent, bounded, stored through the existing storage authority, and never returns an object key.
- [ ] Assert the Library/Exports read model lists available dataset export records for the exact version.
- [ ] Assert Viewer capabilities cannot construct any of the mutation commands even if DOM events are forged.
- [ ] Assert errors preserve the last successful state and expose a safe retry at only the failed transition.

Run RED:

```bash
cd bizpulse
node --test tests/frontend/operator-workflow.test.mjs tests/frontend/library.test.mjs tests/frontend/action-inbox.test.mjs
.venv/bin/pytest tests/postgres/test_migration_chain.py tests/services/test_dataset_export_service.py tests/api/v1/test_dataset_exports.py tests/api/v1/test_actions.py -q
```

Expected: dataset export authority does not exist and the complete version-aware UI sequence is not reachable.

### Step 2: Add an immutable dataset export authority

- [ ] Add `dataset_exports` with dataset version, requested format, lifecycle, storage object, content SHA-256, byte count, idempotency digest, timestamps, and failure code. Do not place source bytes or object locations in the row/API.
- [ ] Build one XLSX from the selected normalized version with a manifest, source-role/quality summary, and bounded worksheets for the canonical tables needed for an Operator handoff. Escape formula-leading cells and enforce workbook/row/byte limits.
- [ ] Stage, verify, and promote the workbook with the same recoverable storage pattern as Action exports; make a replay return the prior immutable record.
- [ ] Add `POST /api/v1/datasets/versions/{version_id}/exports` and `GET /api/v1/datasets/versions/{version_id}/exports/{export_id}/download`, both Operator-only and exact-version checked.
- [ ] Extend the Library read model with export availability after the export record commits.

API shape:

```python
class DatasetExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: Literal["xlsx"] = "xlsx"

class DatasetExportResponse(BaseModel):
    id: UUID
    dataset_version_id: UUID
    status: Literal["available", "failed"]
    format: Literal["xlsx"]
    byte_count: int | None
    created_at: datetime
```

### Step 3: Wire publish, dataset export, action export, and outcome into one explicit workflow

- [ ] Use the Library-selected immutable version as the command context for preparation, publication, export generation/download, and action outcome.
- [ ] Do not add placeholder controls. Each visible button must call an existing or Task 4/5 endpoint, or be absent with an explanatory status.
- [ ] Preserve idempotency keys and CSRF on mutations. Disable only while the exact request is in flight.
- [ ] Refresh Library/version readiness after each successful mutation and retain focus on the triggering workflow region.
- [ ] Keep dataset exports and Action execution exports visibly distinct and localized; both must expose a real download only after `available`.

### Step 4: Run GREEN and mode-boundary regressions

```bash
cd bizpulse
node --test tests/frontend/operator-workflow.test.mjs tests/frontend/library.test.mjs tests/frontend/action-inbox.test.mjs tests/frontend/workspace.test.mjs
.venv/bin/pytest tests/postgres/test_migration_chain.py tests/services/test_dataset_export_service.py tests/api/v1/test_dataset_exports.py tests/api/v1/test_actions.py tests/security/test_viewer_operator_boundaries.py tests/security/test_action_export.py -q
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 5: Commit

```bash
git add alembic/versions/0012_dataset_exports.py src/db/schema.py src/repositories/dataset_exports.py src/services/dataset_export_service.py src/exports/__init__.py src/exports/dataset_workbook.py src/repositories/library.py src/services/library_service.py api/v1/schemas/datasets.py api/v1/routers/datasets.py api/container.py frontend/assets/data-sources/operator.mjs frontend/assets/features/library/effects.mjs frontend/assets/features/library/view-model.mjs frontend/assets/features/library/view.mjs frontend/assets/features/exports/view.mjs frontend/assets/features/action-inbox/effects.mjs frontend/assets/features/action-inbox/view.mjs frontend/assets/core/api-client.mjs frontend/assets/i18n/catalog.mjs tests/postgres/test_migration_chain.py tests/services/test_dataset_export_service.py tests/api/v1/test_dataset_exports.py tests/frontend/library.test.mjs tests/frontend/action-inbox.test.mjs tests/frontend/operator-workflow.test.mjs tests/api/v1/test_actions.py
git commit -m "feat: close operator data workflow in app"
```

## Task 7: Restore a decision-dense Overview with meaningful charts

**Files:**

- Modify: `bizpulse/frontend/assets/features/overview/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/overview/view.mjs`
- Modify: `bizpulse/frontend/assets/features/analysis/view-model.mjs`
- Modify: `bizpulse/frontend/assets/core/charts.mjs`
- Modify: `bizpulse/frontend/assets/views.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/frontend/assets/styles.css`
- Create: `bizpulse/tests/frontend/overview.test.mjs`
- Modify: `bizpulse/tests/frontend/charts.test.mjs`
- Modify: `bizpulse/tests/frontend/analytics.test.mjs`
- Modify: `bizpulse/tests/frontend/formatters.test.mjs`

### Step 1: Write failing information-density and formatter tests

- [ ] Assert Overview exposes scope/period, sales, orders, AOV or units, ad spend, ROAS or available efficiency, operating profit/margin, stockout count, and forecast direction when those deterministic facts exist.
- [ ] Assert it renders at least one non-empty sales/advertising trend chart and one profit/inventory/forecast chart from analysis snapshots.
- [ ] Assert coverage/quality, top four P-priority items, active anomalies, recommended actions, and Ask BizPulse entry are reachable.
- [ ] Assert absent metrics show localized unavailable state rather than `0` or fabricated precision.
- [ ] Assert currency, decimals, ratios, percentages, days, negatives, null, NaN, and high-precision inputs display at most two decimal places without mutating source values.
- [ ] Assert the Overview cannot pass with `metrics.length === 4 && charts.length === 0`.

View-model contract:

```js
assert.ok(model.metrics.length >= 8);
assert.ok(model.charts.filter((chart) => chart.series.some((s) => s.points.length)).length >= 2);
assert.equal(model.priorities.length, 4);
assert.deepEqual(rawSnapshot, structuredClone(rawSnapshot));
```

Run RED:

```bash
cd bizpulse
node --test tests/frontend/overview.test.mjs tests/frontend/charts.test.mjs tests/frontend/analytics.test.mjs tests/frontend/formatters.test.mjs
```

Expected: current Overview has four metrics and no charts.

### Step 2: Compose the Overview strictly from deterministic snapshots

- [ ] Build one view model from Sales/Ads, Inventory, Replenishment, Operating Profit, Forecast, Actions, and Library coverage already returned by the data source.
- [ ] Reuse chart primitives; do not fetch decorative images or create client-side analytical results.
- [ ] Keep provenance/evidence references on every KPI/chart/action but put detailed records behind the Evidence drawer.
- [ ] Use a responsive KPI grid: four columns desktop, two below 820px, one below 560px.
- [ ] Use the shared two-decimal formatters for visible labels and accessible summaries only.

### Step 3: Run GREEN and all analytical frontend regressions

```bash
cd bizpulse
node --test tests/frontend/overview.test.mjs tests/frontend/charts.test.mjs tests/frontend/analytics.test.mjs tests/frontend/formatters.test.mjs tests/frontend/action-inbox.test.mjs tests/frontend/ask-bizpulse-view.test.mjs
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 4: Commit

```bash
git add frontend/assets/features/overview/view-model.mjs frontend/assets/features/overview/view.mjs frontend/assets/features/analysis/view-model.mjs frontend/assets/core/charts.mjs frontend/assets/views.mjs frontend/assets/i18n/catalog.mjs frontend/assets/styles.css tests/frontend/overview.test.mjs tests/frontend/charts.test.mjs tests/frontend/analytics.test.mjs tests/frontend/formatters.test.mjs
git commit -m "feat: restore decision-dense business overview"
```

## Task 8: Replace the low-information inventory chart with a deterministic P-priority list

**Files:**

- Create: `bizpulse/frontend/assets/features/inventory/priority.mjs`
- Modify: `bizpulse/frontend/assets/features/inventory/view-model.mjs`
- Modify: `bizpulse/frontend/assets/features/inventory/view.mjs`
- Modify: `bizpulse/frontend/assets/features/overview/view-model.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/frontend/assets/styles.css`
- Create: `bizpulse/tests/frontend/inventory-priority.test.mjs`
- Modify: `bizpulse/tests/frontend/analytics.test.mjs`
- Modify: `bizpulse/tests/frontend/overview.test.mjs`
- Modify: `bizpulse/tests/unit/analysis/test_replenishment.py`

### Step 1: Write failing priority mapping and rendering tests

- [ ] Preserve existing replenishment calculation semantics: map `urgent -> P0`, `soon -> P1`, `planned with recommended quantity > 0 -> P2`, `recommended quantity == 0 -> Monitor`, and incomplete/unknown evidence -> Unavailable.
- [ ] Sort stably by P0, P1, P2, Monitor, Unavailable, then latest order date, then SKU.
- [ ] Assert rows show SKU, priority, stock state/on hand if present, velocity, days of cover, recommended quantity, order-by date, cash required, confidence/evidence state, and action affordance.
- [ ] Assert the six-stockout fixture renders six P rows and does not render a one-segment red distribution bar.
- [ ] Assert a genuinely mixed distribution may keep a compact secondary chart, but the list remains the primary view.
- [ ] Assert Overview receives only the first four sorted urgent rows.

Priority function:

```js
export function displayPriority(item) {
  if (!item || item.evidence_state === "unknown" || item.recommended_quantity == null) return "unavailable";
  if (item.recommended_quantity === 0) return "monitor";
  return { urgent: "p0", soon: "p1", planned: "p2" }[item.priority] ?? "unavailable";
}
```

Run RED:

```bash
cd bizpulse
node --test tests/frontend/inventory-priority.test.mjs tests/frontend/analytics.test.mjs tests/frontend/overview.test.mjs
.venv/bin/pytest tests/unit/analysis/test_replenishment.py -q
```

Expected: priority module/list is missing and current UI favors the one-color stockout bar.

### Step 2: Implement the P-priority presentation layer

- [ ] Keep authoritative calculator output unchanged; implement P labels only in a named frontend presentation adapter so existing API/AI/action contracts remain compatible.
- [ ] Build a responsive horizontal-scroll table with correct headers and focusable row actions.
- [ ] Suppress the distribution chart when fewer than two non-zero bands exist.
- [ ] Link each row to Evidence and the session-safe Action Sandbox; Viewer actions remain overlays and Operator actions keep their existing authority path.

### Step 3: Run GREEN and inventory/action regressions

```bash
cd bizpulse
node --test tests/frontend/inventory-priority.test.mjs tests/frontend/analytics.test.mjs tests/frontend/overview.test.mjs tests/frontend/action-inbox.test.mjs tests/frontend/formatters.test.mjs
.venv/bin/pytest tests/unit/analysis/test_replenishment.py tests/services/test_action_service.py -q
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 4: Commit

```bash
git add frontend/assets/features/inventory/priority.mjs frontend/assets/features/inventory/view-model.mjs frontend/assets/features/inventory/view.mjs frontend/assets/features/overview/view-model.mjs frontend/assets/i18n/catalog.mjs frontend/assets/styles.css tests/frontend/inventory-priority.test.mjs tests/frontend/analytics.test.mjs tests/frontend/overview.test.mjs tests/unit/analysis/test_replenishment.py
git commit -m "feat: present inventory as P-priority worklist"
```

## Task 9: Add permission-aware Settings, saved views, targets, and AI status

**Files:**

- Create: `bizpulse/alembic/versions/0013_workspace_preferences.py`
- Modify: `bizpulse/src/db/schema.py`
- Create: `bizpulse/src/repositories/preferences.py`
- Create: `bizpulse/src/services/preferences_service.py`
- Create: `bizpulse/api/v1/schemas/preferences.py`
- Create: `bizpulse/api/v1/routers/preferences.py`
- Create: `bizpulse/api/routers/demo_preferences.py`
- Modify: `bizpulse/api/container.py`
- Modify: `bizpulse/api/v1/router.py`
- Modify: `bizpulse/api/main.py`
- Modify: `bizpulse/src/config.py`
- Create: `bizpulse/frontend/assets/features/settings/state.mjs`
- Create: `bizpulse/frontend/assets/features/settings/effects.mjs`
- Create: `bizpulse/frontend/assets/features/settings/view-model.mjs`
- Create: `bizpulse/frontend/assets/features/settings/view.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/views.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/tests/postgres/test_migration_chain.py`
- Create: `bizpulse/tests/services/test_preferences_service.py`
- Create: `bizpulse/tests/api/v1/test_preferences.py`
- Create: `bizpulse/tests/api/test_demo_preferences.py`
- Create: `bizpulse/tests/security/test_preferences_boundary.py`
- Create: `bizpulse/tests/frontend/settings.test.mjs`
- Modify: `bizpulse/tests/frontend/shell.test.mjs`

### Step 1: Write failing settings and secret-boundary tests

- [ ] Assert Operator preferences persist locale, sidebar density, default scope, KPI order, and saved views with revision/optimistic concurrency.
- [ ] Assert Operator targets persist by period/scope with revision and basic numeric/date validation.
- [ ] Assert Viewer locale/sidebar/default scope/KPI/saved-view changes stay in session-local storage and do not write Operator tables.
- [ ] Assert Viewer target/currency/timezone fields are read-only demo values; Operator can edit only fields allowed by the settings schema.
- [ ] Assert AI status response is one of `available`, `disabled`, `unavailable` plus bounded quota state and never contains key names, values, prefixes, provider headers, or config dumps.
- [ ] Assert no endpoint accepts an AI key field and extra secret-like fields fail with 422.
- [ ] Assert two-decimal presentation is fixed and is not exposed as a preference.
- [ ] Assert Settings is reachable from full/compact navigation in both modes and every visible control either saves or is explicitly read-only.

Run RED:

```bash
cd bizpulse
.venv/bin/pytest tests/postgres/test_migration_chain.py tests/services/test_preferences_service.py tests/api/v1/test_preferences.py tests/api/test_demo_preferences.py tests/security/test_preferences_boundary.py -q
node --test tests/frontend/settings.test.mjs tests/frontend/shell.test.mjs
```

Expected: settings persistence/read models/routes and frontend page do not exist.

### Step 2: Add minimal additive preference storage

- [ ] Add `workspace_preferences`, `saved_views`, and `workspace_targets` with UUID primary keys, singleton Operator workspace scope, revision, timestamps, constrained document size, and no secret columns.
- [ ] Use validated schemas instead of arbitrary unbounded JSON. Keep saved-view filters limited to supported scope/period/metric keys.
- [ ] Apply compare-and-set revision on update and return `PREFERENCE_REVISION_CONFLICT` rather than last-write-wins.
- [ ] Compute AI status server-side from the existing provider/config capability without reading or serializing the secret value.

Status boundary:

```python
class AiConnectionStatus(BaseModel):
    status: Literal["available", "disabled", "unavailable"]
    minute_remaining: int | None = None
    daily_remaining: int | None = None
    limitation_code: str | None = None
```

### Step 3: Build Settings with mode-specific persistence

- [ ] Reuse the shared language control and formatters; do not duplicate catalog state.
- [ ] Viewer writes only namespaced `sessionStorage` for session-local preferences and saved views.
- [ ] Operator loads/saves the API-backed preference document, saved views, and targets with visible save/error/revision-conflict states.
- [ ] Show currency, timezone, targets, and AI state with localized permission explanations. Never render an API-key input.

### Step 4: Run GREEN, migration, and security regressions

```bash
cd bizpulse
.venv/bin/alembic upgrade head
.venv/bin/pytest tests/postgres/test_migration_chain.py tests/services/test_preferences_service.py tests/api/v1/test_preferences.py tests/api/test_demo_preferences.py tests/security/test_preferences_boundary.py tests/security/test_viewer_operator_boundaries.py tests/unit/test_config.py tests/services/test_ai_chat_container.py -q
node --test tests/frontend/settings.test.mjs tests/frontend/shell.test.mjs tests/frontend/i18n.test.mjs tests/frontend/formatters.test.mjs
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6
```

### Step 5: Commit

```bash
git add alembic/versions/0013_workspace_preferences.py src/db/schema.py src/repositories/preferences.py src/services/preferences_service.py api/v1/schemas/preferences.py api/v1/routers/preferences.py api/routers/demo_preferences.py api/container.py api/v1/router.py api/main.py src/config.py frontend/assets/features/settings/state.mjs frontend/assets/features/settings/effects.mjs frontend/assets/features/settings/view-model.mjs frontend/assets/features/settings/view.mjs frontend/assets/data-sources/public.mjs frontend/assets/data-sources/operator.mjs frontend/assets/views.mjs frontend/assets/i18n/catalog.mjs tests/postgres/test_migration_chain.py tests/services/test_preferences_service.py tests/api/v1/test_preferences.py tests/api/test_demo_preferences.py tests/security/test_preferences_boundary.py tests/frontend/settings.test.mjs tests/frontend/shell.test.mjs
git commit -m "feat: add permission-aware workspace settings"
```

## Task 10: Run local browser, capacity, anti-drift, and documentation acceptance

**Files:**

- Create: `bizpulse/tests/acceptance/test_viewer_demo_activation_capacity.py`
- Create: `bizpulse/tests/browser/test_corrected_viewer_operator_experience.py`
- Modify: `bizpulse/tests/frontend/copy-contract.test.mjs`
- Modify: `bizpulse/tests/security/test_cross_session_isolation.py`
- Modify: `bizpulse/tests/security/test_viewer_operator_boundaries.py`
- Modify: `bizpulse/tests/release/test_select_required_checks.py`
- Modify: `bizpulse/release/verification-policy.json`
- Modify: `CURRENT_STATUS.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`
- Modify: `NEXT_AI_HANDOFF.md`

### Step 1: Write the final failing acceptance cases

- [ ] Start a clean local PostgreSQL-backed application and create 15 Viewer sessions. Activate all 15 and assert one shared dataset version/analysis set/source-object set, no 15-fold canonical row growth, and no analysis-worker invocation from Action adjustments.
- [ ] Assert session expiry/deletion removes only that session's Chat/action overlays and leaves the public release/Operator records intact.
- [ ] In 1280px, 820px, and 390px browser sizes, cover welcome/login carousel, `Sign in`, language selection, Viewer activation, six analytical regions plus Library/Settings, Evidence four/all/four, Ask BizPulse presets, Action simulation, and responsive navigation.
- [ ] Cover Operator multi-file click and drag selection, queue, upload, inspection/mapping/standardization/commit, exact-version preparation, Library, publish, export, and outcome using local generated supported files only.
- [ ] Assert Viewer personal upload click/drop never reads/sends the file; forge mutation requests and verify 401/403 rather than relying only on hidden DOM.
- [ ] Assert no console error, external image request, dead visible button, blocking horizontal overflow, mixed-language control, technical label, uncontextual `v1`, repeated visible chart summary, or unnecessary value beyond two decimal places.
- [ ] Assert AI-unavailable mode keeps deterministic pages working and disables chat with an explicit reason; do not call a paid provider.
- [ ] Add all new backend/frontend paths to `verification-policy.json` domains so `verify_changed` selects migrations, API/security, frontend, and browser-local checks. It must not select hosted deployment checks for ordinary corrective source paths.

Browser assertion outline:

```python
expect(page.get_by_role("button", name="Import demo data")).to_be_visible()
expect(page.get_by_role("navigation")).to_contain_text("Data Workspace")
expect(page.locator("[data-evidence-item]:visible")).to_have_count(4)
expect(page.get_by_text(re.compile(r"Pinned|schema|digest|[a-f0-9]{12,}"))).to_have_count(0)
```

Run RED on the new cases before final corrections:

```bash
cd bizpulse
.venv/bin/pytest tests/acceptance/test_viewer_demo_activation_capacity.py tests/browser/test_corrected_viewer_operator_experience.py tests/security/test_cross_session_isolation.py tests/security/test_viewer_operator_boundaries.py tests/release/test_select_required_checks.py -q
node --test tests/frontend/copy-contract.test.mjs
```

### Step 2: Fix only acceptance-discovered defects

- [ ] Make the smallest implementation/test-policy corrections needed for these tests. Do not expand scope to hosted release work, Product Opportunities, account management, or deployment.
- [ ] Use the local generated Demo/operator fixture set including costs. Never use a real customer file or secret.
- [ ] If the browser test needs a server, use the repository's temporary local-service harness and stop it after the run.

### Step 3: Run concentrated local verification

First run the focused acceptance set:

```bash
cd bizpulse
.venv/bin/pytest tests/acceptance/test_viewer_demo_activation_capacity.py tests/browser/test_corrected_viewer_operator_experience.py tests/security/test_cross_session_isolation.py tests/security/test_viewer_operator_boundaries.py tests/release/test_select_required_checks.py -q
node --test tests/frontend/*.test.mjs
```

Then run full local verification from the corrective base without reuse:

```bash
cd bizpulse
.venv/bin/python scripts/verify_changed.py --base 61323ea54d678e8660be24d39247fe42e9f032e6 --no-reuse
```

If and only if `verify_changed` does not already include them, run the local full suites explicitly:

```bash
cd bizpulse
.venv/bin/pytest -q
node --test tests/frontend/*.test.mjs
```

Record exact commands, counts, exit status, migration head, browser viewport coverage, and known local limitations. Do not translate local success into Hosted verified, Azure accepted, Production ready, or deployed.

### Step 4: Update status and handoff documents

- [ ] Record the corrective start SHA, final implementation SHA, migration head, local commands/results, browser coverage, and remaining non-goals.
- [ ] State separately: local implementation status, local test status, Git commit status, deployment status, hosted verification status, and Production status.
- [ ] Keep the deployed anchor compare-only and explicitly state that no Azure/registry/secret/DNS/push/PR/CI/deploy action occurred.
- [ ] Update handoff instructions so any future deployment task starts from the final local implementation commit and must obtain new narrow release authorization.

### Step 5: Commit the acceptance closeout

```bash
git add tests/acceptance/test_viewer_demo_activation_capacity.py tests/browser/test_corrected_viewer_operator_experience.py tests/frontend/copy-contract.test.mjs tests/security/test_cross_session_isolation.py tests/security/test_viewer_operator_boundaries.py tests/release/test_select_required_checks.py release/verification-policy.json ../CURRENT_STATUS.md ../docs/handoffs/CURRENT_HANDOFF.md ../NEXT_AI_HANDOFF.md
git commit -m "test: close corrected viewer operator experience locally"
```

## Final Self-Review Checklist

- [ ] Search this plan for `TODO`, `TBD`, `placeholder`, `later`, and ellipses used as missing implementation; none may represent unfinished design.
- [ ] Confirm every approved design requirement in sections 7.5, 8, 11, 13-17, and 19 maps to at least one task/test above.
- [ ] Confirm every named endpoint/schema/module has a producer and consumer, and that Viewer and Operator use different authorization dependencies.
- [ ] Confirm `0010 -> 0011 -> 0012 -> 0013` is a single additive migration chain after the currently observed head; refresh revision IDs if local head drifted before implementation.
- [ ] Confirm legacy synthetic releases remain readable and old columns are not removed.
- [ ] Confirm Viewer activation writes only session metadata and capacity tests prove shared data is not copied.
- [ ] Confirm Operator can import ordinary supported operational identifiers while secrets/PII/formulas/URLs remain blocked.
- [ ] Confirm all visible Operator workflow buttons are backed by real local endpoints and all Viewer mutation paths fail server-side.
- [ ] Confirm Overview and Inventory use existing deterministic snapshots, not browser recomputation or AI.
- [ ] Confirm no AI key field/value crosses an API or appears in Settings/logs/tests.
- [ ] Confirm ordinary UI contains neither technical release labels nor bilingual concatenations and all decimals follow the two-place presentation contract.
- [ ] Confirm final evidence wording distinguishes local implementation, local verification, committed Git state, deployed state, hosted verification, and Production readiness.
