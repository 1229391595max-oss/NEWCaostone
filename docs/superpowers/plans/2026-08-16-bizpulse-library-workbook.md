# BizPulse BP Library Workbook Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the BP Library card wall with a bilingual, scalable workbook that labels the active data as the current dataset, pages through complete tables, and opens full row details without weakening Viewer/Operator boundaries.

**Architecture:** Keep immutable dataset versions and normalized artifacts authoritative. Add bounded, version-exact table-page projections to the existing library service, expose separate read-only Operator and activated-Viewer routes, and drive a single-table frontend workspace through reducer/effect state. The browser renders horizontally scrollable tabs and one paged table; row details stay client-side because the selected page already contains the full safe row.

**Tech Stack:** Python 3.13, FastAPI, Pydantic, SQLAlchemy/PostgreSQL, vanilla ES modules, Node test runner, CSS, Playwright-backed real-browser gate.

## Global Constraints

- Implementation baseline for this batch is `BATCH_BASE_SHA=bdfe660`; do not use an old deployed SHA as the changed-path baseline.
- CAPTSONE remains read-only; every change stays under `/Users/maxli/Desktop/NEWCaostone`.
- Normal UI must say `Current dataset / 当前数据集`, not `Version 1 / 版本 1`.
- Viewer may only read the activated shared dataset; Operator reads an explicitly authorized version and retains exact-version export.
- Page sizes are exactly `25`, `50`, or `100`, default `50`; no unbounded client download or free-form query.
- UI rounding does not change source values, API precision, calculations, or exports.
- No Azure, registry, Keychain, secret, DNS, real/paid AI, push, PR, CI, or deployment mutation.
- Every task follows RED -> minimal GREEN -> focused regression -> local commit; final verification uses `scripts/verify_changed.py --base bdfe660 --no-reuse`.

---

## File Structure

- `bizpulse/src/services/library_service.py`: validate and return a safe page from one exact normalized table.
- `bizpulse/api/v1/schemas/library.py`: serialize the bounded table-page contract.
- `bizpulse/api/v1/routers/library.py`: authenticated Operator table-page route.
- `bizpulse/api/routers/demo_library.py`: activated Viewer table-page route pinned to the session dataset.
- `bizpulse/frontend/assets/data-sources/operator.mjs`: call the exact-version Operator page route.
- `bizpulse/frontend/assets/data-sources/public.mjs`: call the activated current Viewer page route.
- `bizpulse/frontend/assets/features/library/state.mjs`: own selected table, page, page size, page error, and open row state.
- `bizpulse/frontend/assets/features/library/effects.mjs`: load table pages without replacing the dataset summary.
- `bizpulse/frontend/assets/features/library/view-model.mjs`: produce friendly dataset/history/table labels without technical identity.
- `bizpulse/frontend/assets/features/library/workbook-view.mjs`: render tabs, one detailed table, pagination, and the row drawer.
- `bizpulse/frontend/assets/features/library/view.mjs`: compose current-dataset summary, optional Operator history, workbook, provenance, and exports.
- `bizpulse/frontend/assets/i18n/catalog.mjs`: English/Chinese workbook controls, empty/error states, and canonical table names.
- `bizpulse/frontend/assets/styles.css`: contain tab/table overflow and style the responsive drawer.
- `bizpulse/tests/services/test_library_service.py`: service page boundaries and safe-row tests.
- `bizpulse/tests/api/v1/test_library.py`: Operator auth, exact version, and page contract.
- `bizpulse/tests/api/test_demo_library.py`: Viewer activation and shared-version pinning.
- `bizpulse/tests/frontend/library.test.mjs`: reducer, effects, labels, data-source URL, and markup contract.
- `bizpulse/tests/browser/test_real_chrome_gate.py`: visible workbook behavior and no page-level overflow.

### Task 1: Add bounded exact-table pagination

**Files:**
- Modify: `bizpulse/src/services/library_service.py`
- Modify: `bizpulse/api/v1/schemas/library.py`
- Modify: `bizpulse/api/v1/routers/library.py`
- Modify: `bizpulse/api/routers/demo_library.py`
- Test: `bizpulse/tests/services/test_library_service.py`
- Test: `bizpulse/tests/api/v1/test_library.py`
- Test: `bizpulse/tests/api/test_demo_library.py`
- Test: `bizpulse/tests/security/test_viewer_operator_boundaries.py`

**Interfaces:**
- Consumes: `LibraryService._load_tables(version_id)` and the existing Operator/Viewer dependencies.
- Produces: `LibraryService.get_table_page(version_id, role, *, page=1, page_size=50) -> LibraryTablePage`; `GET /api/v1/library/{version_id}/tables/{role}`; `GET /api/demo/library/current/tables/{role}`.

- [ ] **Step 1: Write failing service and API tests**

Add tests proving that a 552-row `daily_sales` table returns page 1 with 50 safe rows, page 12 with 2 rows, exact totals, stable columns, and no `object_key`/digest fields. Add a missing-role 404 test, a disallowed `page_size=30` validation test, an unauthenticated Operator test, and a Viewer test that is 409 before activation and bound to the activated release after activation.

```python
page = service.get_table_page(seeded.dataset_version_id, "daily_sales", page=12, page_size=50)
assert page.page == 12
assert page.page_size == 50
assert page.total_rows == 552
assert page.total_pages == 12
assert len(page.rows) == 2
assert all("object_key" not in row for row in page.rows)

response = client.get(
    f"/api/v1/library/{seeded.dataset_version_id}/tables/daily_sales?page=1&page_size=50"
)
assert response.status_code == 200
assert response.json()["total_rows"] == 552
assert client.get(
    f"/api/v1/library/{seeded.dataset_version_id}/tables/daily_sales?page_size=30"
).status_code == 422
```

- [ ] **Step 2: Run the focused tests and confirm RED**

Run:

```bash
cd bizpulse
.venv/bin/pytest tests/services/test_library_service.py tests/api/v1/test_library.py tests/api/test_demo_library.py tests/security/test_viewer_operator_boundaries.py -q
```

Expected: new tests fail because `get_table_page` and both routes do not exist.

- [ ] **Step 3: Implement the bounded service contract**

Add the following public contract and validate exact page sizes and table identity before slicing sanitized rows:

```python
ALLOWED_LIBRARY_PAGE_SIZES = (25, 50, 100)

class LibraryTableNotFound(RuntimeError):
    code = "LIBRARY_TABLE_NOT_FOUND"

class LibraryPageInvalid(RuntimeError):
    code = "LIBRARY_PAGE_INVALID"

@dataclass(frozen=True, slots=True)
class LibraryTablePage:
    role: str
    columns: tuple[str, ...]
    rows: tuple[dict[str, object], ...]
    page: int
    page_size: int
    total_rows: int
    total_pages: int

def get_table_page(self, version_id: UUID, role: str, *, page: int = 1, page_size: int = 50) -> LibraryTablePage:
    if type(page) is not int or page < 1 or page_size not in ALLOWED_LIBRARY_PAGE_SIZES:
        raise LibraryPageInvalid
    tables = self._load_tables(version_id)
    if role not in tables:
        raise LibraryTableNotFound
    safe_rows = tuple(_safe_row(row) for row in tables[role])
    total_rows = len(safe_rows)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    if page > total_pages:
        raise LibraryPageInvalid
    start = (page - 1) * page_size
    return LibraryTablePage(
        role=role,
        columns=tuple(sorted({key for row in safe_rows for key in row})[:40]),
        rows=safe_rows[start:start + page_size],
        page=page,
        page_size=page_size,
        total_rows=total_rows,
        total_pages=total_pages,
    )
```

- [ ] **Step 4: Expose separate Operator and Viewer routes**

Add `LibraryTablePageResponse` with the same fields, use `Literal[25, 50, 100]` for `page_size`, return 404 for `LibraryTableNotFound`, 400 for `LibraryPageInvalid`, and 503 for `LibraryUnavailable`. Operator passes the URL version UUID; Viewer passes only `principal.dataset_version_id` from `require_demo_data_imported`. Apply the existing private no-store headers to successful responses.

- [ ] **Step 5: Run focused tests and commit**

Run the Step 2 command and expect all selected tests to pass. Then:

```bash
git add bizpulse/src/services/library_service.py bizpulse/api/v1/schemas/library.py bizpulse/api/v1/routers/library.py bizpulse/api/routers/demo_library.py bizpulse/tests/services/test_library_service.py bizpulse/tests/api/v1/test_library.py bizpulse/tests/api/test_demo_library.py bizpulse/tests/security/test_viewer_operator_boundaries.py
git commit -m "feat: add bounded library table pages"
```

### Task 2: Add workbook state and data loading

**Files:**
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/frontend/assets/features/library/state.mjs`
- Modify: `bizpulse/frontend/assets/features/library/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/library/view-model.mjs`
- Test: `bizpulse/tests/frontend/library.test.mjs`

**Interfaces:**
- Consumes: Task 1 table-page routes.
- Produces: `loadLibraryTable(versionId, role, {page, pageSize})` for Operator, `loadLibraryTable(role, {page, pageSize})` for Viewer, reducer actions `library/table-loading|table-loaded|table-failed|row-opened|row-closed`, and view-model fields `currentDataset`, `history`, `tables`, `selectedTable`, `tablePage`, `rowDetail`.

- [ ] **Step 1: Write failing frontend tests**

Cover URL encoding and query parameters, automatic first non-empty table selection, page-state transitions, retaining the prior page on page-load failure, opening/closing a row, and friendly data labels:

```javascript
assert.equal(model.detail.version.label, "Current dataset");
assert.equal(model.detail.version.historyLabel, "Imported dataset · Aug 16, 2026");
assert.equal(JSON.stringify(model).includes("Version 1"), false);

state = reduceLibrary(state, { type: "library/table-loaded", page });
assert.equal(state.table.role, "daily_sales");
assert.equal(state.table.rows.length, 50);
state = reduceLibrary(state, { type: "library/table-failed", code: "NETWORK" });
assert.equal(state.table.rows.length, 50);
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
cd bizpulse
npm test -- --test-name-pattern='library'
```

Expected: new assertions fail because table-page methods, reducer state, and friendly labels are absent.

- [ ] **Step 3: Implement data-source methods and reducer state**

Build query strings with `URLSearchParams`, `encodeURIComponent` path segments, and `cache: "no-store"`. Initialize table state exactly as:

```javascript
table: {
  status: "idle",
  role: null,
  columns: [],
  rows: [],
  page: 1,
  pageSize: 50,
  totalRows: 0,
  totalPages: 1,
  error: null,
},
rowDetail: null,
```

`table-loading` changes only table status/error; `table-failed` keeps columns and rows; `table-loaded` replaces the full page; `row-opened` stores a row object; `row-closed` clears it.

- [ ] **Step 4: Implement effects and friendly view-model labels**

After Viewer detail load or Operator version selection, select the first table whose `row_count > 0` (otherwise the first table) and request page 1 at size 50. Table switching and page-size changes call the same `loadTable({versionId, role, page, pageSize})` effect. Format current detail as `Current dataset / 当前数据集`; format Operator history from `created_at` using a UTC `Intl.DateTimeFormat`, falling back to `Import {number} / 第 {number} 次导入`.

- [ ] **Step 5: Run focused tests and commit**

Run the Step 2 command and expect all library tests to pass. Then:

```bash
git add bizpulse/frontend/assets/data-sources/operator.mjs bizpulse/frontend/assets/data-sources/public.mjs bizpulse/frontend/assets/features/library/state.mjs bizpulse/frontend/assets/features/library/effects.mjs bizpulse/frontend/assets/features/library/view-model.mjs bizpulse/tests/frontend/library.test.mjs
git commit -m "feat: drive paged library workbook state"
```

### Task 3: Render the bilingual Excel-style workbook

**Files:**
- Create: `bizpulse/frontend/assets/features/library/workbook-view.mjs`
- Modify: `bizpulse/frontend/assets/features/library/view.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/frontend/assets/styles.css`
- Test: `bizpulse/tests/frontend/library.test.mjs`
- Test: `bizpulse/tests/browser/test_real_chrome_gate.py`

**Interfaces:**
- Consumes: Task 2 view model and effects.
- Produces: `renderLibraryWorkbook(container, model, effects, {language, versionId})` and visible accessible workbook behavior.

- [ ] **Step 1: Write failing markup and real-browser tests**

Add source/DOM contract assertions for `tablist`, `tab`, `tabpanel`, `aria-selected`, a page-size selector, Previous/Next buttons, row-detail dialog, and `Escape` handling. Extend the real Chrome gate to open the Library, assert only one detailed `<table>` is visible, click a different table tab, click a row and close its dialog, change page, and measure:

```python
overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
assert overflow <= 1
assert page.locator(".library-data-table").count() == 1
assert page.locator(".library-row-drawer[role=dialog]").is_visible()
```

- [ ] **Step 2: Run frontend tests and confirm RED**

Run:

```bash
cd bizpulse
npm test -- --test-name-pattern='library'
```

Expected: new workbook structure assertions fail.

- [ ] **Step 3: Render one selected table and accessible tabs**

Create `workbook-view.mjs`. Render a horizontally scrollable `role="tablist"`; each button includes the localized canonical role name and row count, owns its panel, and invokes `effects.loadTable(...)`. Implement ArrowLeft/ArrowRight/Home/End keyboard movement. Render exactly one `table.library-data-table`, all returned columns, and one button per row that dispatches `library/row-opened` without modifying data.

- [ ] **Step 4: Render pagination, empty/error states, and row drawer**

The page-size select exposes only 25, 50, and 100. Previous/Next are disabled at boundaries or while loading. Loading uses `aria-busy`; a page failure keeps old rows visible and adds a retry button. The dialog lists every `column -> value`, closes by button or Escape, restores focus to the invoking row, and never exposes blocked storage/digest fields because Task 1 sanitizes the page.

- [ ] **Step 5: Replace the card wall and add bilingual copy**

In `view.mjs`, remove `.library-table-grid` rendering. Show one current-dataset summary, render Operator history only when more than one version exists inside a collapsed `details`, then compose the workbook, collapsed provenance, and existing export controls. Add translations for the workbook controls plus canonical roles:

```javascript
"library.currentDataset": "Current dataset",
"library.history": "Import history",
"library.table.daily_sales": "Daily sales",
"library.table.inventory_receipt_lot": "Inventory receipt lots",
"library.previousPage": "Previous",
"library.nextPage": "Next",
"library.rowDetails": "Row details",
```

and equivalent Chinese values such as `当前数据集`, `导入历史`, `每日销售`, `库存收货批次`, `上一页`, `下一页`, and `行详情`. Cover every canonical role generated by `src/synthetic/generator.py`; unknown roles use a deterministic underscore-to-space fallback.

- [ ] **Step 6: Contain overflow and style the responsive drawer**

Make `.library-workspace`, `.library-detail`, `.library-workbook`, `.library-table-panel` and their grid parents use `min-width: 0`. Make only `.library-table-tabs` and `.library-table-scroll` horizontally scrollable. Use sticky table headers and a fixed right-side desktop drawer; below 720px, use an inset bottom sheet with bounded height. Respect existing colors, borders, focus indicators, and reduced-motion behavior.

- [ ] **Step 7: Run focused frontend and browser tests**

Run:

```bash
cd bizpulse
npm test -- --test-name-pattern='library'
.venv/bin/pytest tests/browser/test_real_chrome_gate.py -q
```

Expected: library tests pass; real browser shows one table, working tab/page/drawer controls, bilingual labels, and at most 1 px page overflow.

- [ ] **Step 8: Commit the workbook UI**

```bash
git add bizpulse/frontend/assets/features/library/workbook-view.mjs bizpulse/frontend/assets/features/library/view.mjs bizpulse/frontend/assets/i18n/catalog.mjs bizpulse/frontend/assets/styles.css bizpulse/tests/frontend/library.test.mjs bizpulse/tests/browser/test_real_chrome_gate.py
git commit -m "feat: replace library cards with workbook"
```

### Task 4: Run anti-drift verification and document exact local evidence

**Files:**
- Modify if required by test routing: `bizpulse/release/verification-policy.json`
- Test if routing changes: `bizpulse/tests/release/test_select_required_checks.py`
- Modify: `CURRENT_STATUS.md`

**Interfaces:**
- Consumes: all Tasks 1-3 commits and `BATCH_BASE_SHA=bdfe660`.
- Produces: exact local test evidence without Hosted/Azure/Production claims.

- [ ] **Step 1: Verify changed-path selection before the long run**

Run:

```bash
cd bizpulse
.venv/bin/python scripts/select_required_checks.py --base bdfe660
```

Expected: selection includes backend API/security tests, frontend tests, and the real-browser local gate. If a changed implementation path is unmapped, add the narrow glob/check mapping and a selector regression test before continuing.

- [ ] **Step 2: Run the uncached aggregate verification**

Run:

```bash
cd bizpulse
.venv/bin/python scripts/verify_changed.py --base bdfe660 --no-reuse
```

Expected: every selected local check exits 0. This is local evidence only.

- [ ] **Step 3: Perform final diff and UI checks**

Run:

```bash
git diff --check bdfe660..HEAD
git status --short
```

Use the already-running local preview or a temporary local service to verify English and Chinese current-dataset labels, one-table rendering, tab overflow containment, page-size changes, row drawer close/focus behavior, Viewer read-only boundaries, and Operator exact-version export presence.

- [ ] **Step 4: Record evidence and commit**

Update `CURRENT_STATUS.md` with exact commit SHAs, focused test counts, aggregate verification artifact/path if emitted, local URL used, and the explicit statement that Azure/Hosted/Production were not tested or changed. Then:

```bash
git add CURRENT_STATUS.md bizpulse/release/verification-policy.json bizpulse/tests/release/test_select_required_checks.py
git commit -m "docs: record library workbook verification"
```

Only add the policy/test files if Task 4 Step 1 required a routing repair.
