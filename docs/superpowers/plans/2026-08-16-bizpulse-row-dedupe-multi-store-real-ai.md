# BizPulse Row Dedupe, Multi-Store Scope, and Real AI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` for inline execution or `superpowers:subagent-driven-development` only when the user explicitly requests delegated execution. Follow every task in order and stop at the explicit external-state gates.

**Goal:** Add deterministic row-level deduplication, a version-bound global store scope with a low-traffic second Demo store, and a final fail-closed real OpenAI path without weakening Operator capabilities, Viewer limits, immutable dataset versions, deterministic calculations, or current release controls.

**Architecture:** Standardized uploads and the current immutable dataset are assembled into one deterministic canonical bundle before commit. Business-key comparison removes exact duplicates and blocks conflicts atomically. Every dataset version exposes a bounded store catalog; one shared `StoreScope` contract drives precomputed analyses, Library, Action, Forecast, Profit, and Chat. The synthetic generator creates a stable second store and three scopes are prepared before publication. Real AI remains server-only, fixed to the approved nano snapshot, fake-provider tested locally, and enabled only in a separately approved Azure revision after an AI-disabled hosted verification.

**Tech Stack:** Python 3.12; FastAPI 0.138.2; SQLAlchemy Core 2.0.51; Alembic 1.18.5; PostgreSQL 17; Azure Blob; OpenAI Python SDK 2.52.0 Responses API; native HTML/CSS/ES modules; Node 24 test runner; pytest 9.1.1; Ruff 0.15.20; Bicep/Azure Container Apps release tooling.

**Authority:** Approved design: `docs/superpowers/specs/2026-08-16-bizpulse-row-dedupe-multi-store-real-ai-design.md`. Implementation batch baseline: `BATCH_BASE_SHA=d4ed425e8f9c5c2e271ef7e53a2276674500d4c3`. Never use `DEPLOYED_RELEASE_SHA` as a changed-path baseline.

## Global constraints

- Run every implementation task RED -> smallest implementation -> GREEN -> `python scripts/verify_changed.py --base d4ed425e8f9c5c2e271ef7e53a2276674500d4c3 --no-reuse` -> one local commit.
- Work only in `/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift`; preserve and route around unexpected user changes.
- `/Users/maxli/Desktop/CAPTSONE` and the Desktop demo workbooks are read-only references. Runtime and tests must use repository fixtures and the deterministic generator.
- Operator retains upload, mapping, standardization, commit, calculation, publication, export, Action, and Chat. Viewer keeps the existing shared Demo import and light Action sandbox, but cannot upload a personal file or trigger large calculations.
- A failed conflict check must leave workflow revision, current dataset version, public release, analysis rows, and permanent Blob objects unchanged.
- Keep `canonical.import.v1` readable for backward compatibility. Add bounded top-level metadata (`row_provenance`, `store_catalog`) that existing analysis readers ignore safely.
- Store scope is version-bound. `all` is resolved by the server from that version's store catalog; the browser never supplies an authoritative catalog.
- Viewer scope changes read already prepared artifacts only. They must not create dataset versions, analysis runs, forecasts, profit bridges, or public releases.
- Shared rows remain visible in single-store Library views. Unallocated shared costs enter only the all-store profit scope and must be marked excluded in single-store responses.
- AI model is exactly `gpt-5.4-nano-2026-03-17`, reasoning effort `low`; no automatic fallback.
- AI limits are exactly: 120 provider attempts/day, 150000 total tokens/month, 3 attempts/session/minute, 20 attempts/global/minute, 15 concurrent turns, and 2800 max output tokens.
- No API Key in Git, chat, browser, Settings, command arguments, `.env`, parameter files, logs, snapshots, or evidence. Local tests use a fake provider.
- Tasks 1-11 are ordinary local development. Task 12 may generate a local value-complete release package but performs no cloud mutation. Task 13 requires a fresh, exact package-hash approval before Azure/registry/paid-provider mutation; plan or design approval is not that approval.
- Hosted, Azure accepted, deployed, and Production ready remain false until their respective gates produce fresh evidence.

## Shared contracts

Add these contracts before feature-specific integration so later tasks do not invent parallel meanings.

```python
@dataclass(frozen=True, slots=True)
class RowOrigin:
    source_kind: Literal["base", "upload"]
    source_name: str
    sheet_name: str | None
    row_number: int | None

@dataclass(frozen=True, slots=True)
class DedupeConflict:
    role: str
    business_key: tuple[tuple[str, str], ...]
    fields: tuple[str, ...]
    existing: RowOrigin
    incoming: RowOrigin

@dataclass(frozen=True, slots=True)
class DedupeSummary:
    rows_read: int
    rows_retained: int
    duplicates_removed: int
    conflicts: int
    per_role: dict[str, dict[str, int]]

@dataclass(frozen=True, slots=True)
class StoreDescriptor:
    store_id: str
    display_name_en: str
    display_name_zh: str
    currency: str
    opened_on: date | None
    lifecycle: Literal["established", "new"]
    has_data: bool

@dataclass(frozen=True, slots=True)
class StoreScope:
    kind: Literal["all", "single"]
    store_ids: tuple[str, ...]
```

`StoreScopeResolver.resolve(dataset_version_id, requested_store_ids) -> StoreScope` must reject unknown IDs, sort IDs by the version catalog, and use all catalog stores when no store is requested.

---

## Task 1: Bind every import workflow to an immutable base dataset version

**Files:**

- Create: `bizpulse/alembic/versions/0014_import_base_lineage.py`
- Modify: `bizpulse/src/db/schema.py`
- Modify: `bizpulse/src/repositories/imports.py`
- Modify: `bizpulse/src/repositories/datasets.py`
- Modify: `bizpulse/src/services/import_service.py`
- Modify: `bizpulse/tests/postgres/test_migration_chain.py`
- Create: `bizpulse/tests/postgres/test_0014_import_base_lineage.py`
- Modify: `bizpulse/tests/repositories/test_import_version_repositories.py`
- Modify: `bizpulse/tests/services/test_import_service.py`

**Contract:**

- `import_workflows.base_dataset_version_id` is a nullable FK to `dataset_versions.id` captured when the workflow is created.
- `dataset_versions.base_version_id` is a nullable self-FK recording lineage of the successful committed version.
- `upload_records.assigned_store_id` is nullable and records an explicit Operator choice for a single-store file whose mapped canonical table lacks `store_id`; it is never inferred from a default.
- A workflow created with no current series version stays based on `None`, even if another import commits before it.
- Commit checks that the current series head still equals the captured base; otherwise return `IMPORT_BASE_VERSION_CHANGED` and require a fresh workflow.

- [ ] Write migration and repository tests first:

```python
def test_workflow_captures_current_version_once(database):
    first = complete_version(database)
    workflow = import_service(database).create_workflow(idempotency_key="w1").workflow
    complete_version(database, base_version_id=first.id)
    assert import_repository(database).get_workflow(workflow.id).base_dataset_version_id == first.id

def test_commit_rejects_when_series_head_changed(import_fixture):
    workflow = import_fixture.ready_workflow()
    import_fixture.advance_series_head()
    with pytest.raises(WorkflowNotReady, match="IMPORT_BASE_VERSION_CHANGED"):
        import_fixture.service.commit(
            workflow.id,
            expected_revision=workflow.revision,
            idempotency_key="commit-1",
        )
```

- [ ] Run RED tests:

```bash
cd bizpulse
.venv/bin/pytest tests/postgres/test_0014_import_base_lineage.py tests/repositories/test_import_version_repositories.py tests/services/test_import_service.py -q
```

- [ ] Add the two nullable FKs, indexes, projections, serialization fields, and repository parameters. Resolve the current `synthetic-main` head inside workflow creation's transaction and never refresh it later.
- [ ] Run the same tests plus `tests/postgres/test_migration_chain.py` GREEN.
- [ ] Run changed-path verification.
- [ ] Commit: `feat: bind imports to dataset lineage`.

## Task 2: Preserve safe row provenance and define the business-key registry

**Files:**

- Create: `bizpulse/src/services/canonical_contracts.py`
- Create: `bizpulse/src/services/business_keys.py`
- Modify: `bizpulse/src/adapters/protocol.py`
- Modify: `bizpulse/src/adapters/upseller_excel.py`
- Modify: `bizpulse/src/adapters/shopee_advertising_csv.py`
- Create: `bizpulse/tests/unit/test_business_keys.py`
- Modify: `bizpulse/tests/services/test_import_service.py`
- Modify: `bizpulse/tests/security/test_synthetic_source_boundary.py`

**Contract:**

- Add `row_provenance` parallel to `tables`, keyed by role and zero-based canonical row index. Each entry contains only safe filename, sheet name, and one-based source row number.
- Business-key definitions exactly match section 5.2 of the approved design:

| Role | Exact business key |
|---|---|
| `daily_sales` | `store_id + order_id + sku_id` |
| `shopee_advertising` | `store_id + date + sku_id` |
| `product_inventory_sales` | `store_id + date + sku_id` |
| `inventory_movement` | `store_id + movement_id` |
| `inventory_receipt_lot` | `store_id + lot_id` |
| `outbound_event` | `store_id + outbound_id` |
| `refund` | `store_id + refund_id` |
| `settlement` | `store_id + fee_id` or `store_id + settlement_id` |
| `fulfillment_cost` | `store_id + fulfillment_id` |
| `operating_expense` | `store_id + expense_id`, or `expense_id` only for explicit shared scope |
| `fx_effect` | `store_id + fx_effect_id` |
| `other_variable_cost` | `store_id + cost_id` |
| `product_catalog` | `sku_id` |
| `replenishment_policy` | `store_id + sku_id` |
| `fx_assumption` | `currency + period_start + period_end` |
| `new_product_benchmark` | `forecast_id` |
| `new_product_backtest_window` | `window_id` |

- `business_key(role, row)` canonicalizes values to strings only after adapter normalization.
- Missing required components raise `BusinessKeyIncomplete(role, fields)`; no whole-row-hash fallback.
- `operating_expense` uses `(store_id, expense_id)` when store is present and `(expense_id,)` only when `scope == "shared"` is explicit.
- `settlement` accepts exactly one of `fee_id` or `settlement_id`; ambiguous/missing identifiers fail closed.

- [ ] Write table-driven failing tests for every supported role, numeric/date equality after adapter normalization, missing keys, explicit shared expense, and provenance redaction.

```python
@pytest.mark.parametrize(
    ("role", "row", "expected"),
    [
        ("daily_sales", sales_row(), (("store_id", "S1"), ("order_id", "O1"), ("sku_id", "K1"))),
        ("product_catalog", {"sku_id": "K1"}, (("sku_id", "K1"),)),
        ("fx_assumption", fx_row(), (("currency", "USD"), ("period_start", "2026-07-01"), ("period_end", "2026-07-31"))),
    ],
)
def test_business_keys_are_explicit(role, row, expected):
    assert business_key(role, row) == expected
```

- [ ] Implement immutable contracts and the exhaustive registry. Add adapter provenance without adding Blob keys, digests, temp paths, or credentials.
- [ ] Run:

```bash
.venv/bin/pytest tests/unit/test_business_keys.py tests/services/test_import_service.py tests/security/test_synthetic_source_boundary.py -q
.venv/bin/ruff check src/services/canonical_contracts.py src/services/business_keys.py src/adapters tests/unit/test_business_keys.py
```

- [ ] Run changed-path verification and commit: `feat: define canonical row provenance and keys`.

## Task 3: Build the deterministic canonical dataset assembler

**Files:**

- Create: `bizpulse/src/services/canonical_dataset_assembler.py`
- Create: `bizpulse/tests/services/test_canonical_dataset_assembler.py`
- Create: `bizpulse/tests/property/test_canonical_dataset_assembler.py`

**Interface:**

```python
@dataclass(frozen=True, slots=True)
class CanonicalSource:
    source_kind: Literal["base", "upload"]
    source_name: str
    tables: Mapping[str, Sequence[Mapping[str, object]]]
    row_provenance: Mapping[str, Sequence[Mapping[str, object]]]
    store_catalog: tuple[StoreDescriptor, ...] = ()

@dataclass(frozen=True, slots=True)
class AssemblyResult:
    content: bytes
    sha256: str
    summary: DedupeSummary
    conflicts: tuple[DedupeConflict, ...]

class CanonicalDatasetAssembler:
    def assemble(self, *, base: CanonicalSource | None, uploads: tuple[CanonicalSource, ...]) -> AssemblyResult: ...
```

**Rules:** base rows precede uploads; uploads are sorted by creation timestamp, safe filename, sheet order, and source row; exact same key/value retains the earlier row; same key/different business value records a conflict; output role, row, and JSON key order are stable; any conflict produces no committable content; internal ingestion metadata is excluded from value comparison.

- [ ] Write failing tests for same-file, cross-sheet, cross-file, base-vs-upload duplicates; conflicts; stable ordering; stable SHA; key-incomplete; idempotence; and `5`/`5.0`/`5.00` equivalence after adapter normalization.

```python
def test_assembly_is_idempotent_and_prefers_base_origin():
    first = assembler.assemble(base=base_source(), uploads=(duplicate_upload(),))
    second = assembler.assemble(base=source_from(first.content), uploads=())
    assert first.content == second.content
    assert first.sha256 == second.sha256
    assert first.summary.duplicates_removed == 1
    assert json.loads(first.content)["row_provenance"]["daily_sales"][0]["source_kind"] == "base"
```

- [ ] Implement a single-pass per-role index using the explicit business keys. Serialize compact UTF-8 JSON with `sort_keys=True`, stable role order, `schema_version="canonical.import.v1"`, and bounded provenance.
- [ ] Run:

```bash
.venv/bin/pytest tests/services/test_canonical_dataset_assembler.py tests/property/test_canonical_dataset_assembler.py -q
.venv/bin/ruff check src/services/canonical_dataset_assembler.py tests/services/test_canonical_dataset_assembler.py tests/property/test_canonical_dataset_assembler.py
```

- [ ] Run changed-path verification and commit: `feat: assemble deduplicated canonical datasets`.

## Task 4: Integrate dedupe planning, conflict CSV, and atomic merged commit

**Files:**

- Modify: `bizpulse/src/services/import_service.py`
- Modify: `bizpulse/src/repositories/storage_objects.py`
- Modify: `bizpulse/src/repositories/datasets.py`
- Modify: `bizpulse/api/v1/schemas/imports.py`
- Modify: `bizpulse/api/v1/routers/imports.py`
- Modify: `bizpulse/tests/services/test_import_service.py`
- Modify: `bizpulse/tests/integration/test_atomic_import_version.py`
- Modify: `bizpulse/tests/api/v1/test_imports.py`
- Create: `bizpulse/tests/security/test_import_conflict_export.py`

**API additions:**

```json
{
  "ready": false,
  "dedupe": {
    "rows_read": 100,
    "rows_retained": 98,
    "duplicates_removed": 2,
    "conflicts": 1,
    "per_role": {"daily_sales": {"rows_read": 20, "rows_retained": 18, "duplicates_removed": 2, "conflicts": 1}}
  },
  "conflicts": [],
  "conflicts_truncated": false,
  "conflict_download_url": "/api/v1/imports/workflows/{id}/conflicts.csv"
}
```

- `GET /api/v1/imports/workflows/{id}/commit-plan` recomputes/loads the exact assembly against the captured base version and returns at most 50 conflicts.
- `GET /api/v1/imports/workflows/{id}/conflicts.csv` is Operator-authenticated, `private, no-store`, spreadsheet-injection escaped, and contains only role, business-key fields, conflicting fields, safe source names, sheet names, row numbers, and base/upload labels.
- Mapping/standardization accepts an optional `assigned_store_id` only when all store-scoped rows in that upload lack `store_id` and the selected ID belongs to the captured version/incoming explicit store catalog. A multi-store file must map its own store field. Explicit shared expenses use their `scope="shared"` data value; a blank store is never silently treated as shared.
- Successful commit promotes exactly one merged canonical artifact; candidate artifacts stay temporary and are deleted/scheduled after the database transaction. The new dataset version records `base_version_id`.
- The idempotency request hash includes captured base ID and merged content SHA.

- [ ] Write failing API and integration tests proving conflict response shape, 50-row cap, complete CSV, no internal paths/digests, exact-duplicate successful commit, one canonical artifact, and no state/object mutation on conflict.
- [ ] Implement a private `_assembly_for(workflow_id)` that opens the captured base artifact plus all verified candidates, then delegates all comparison to the assembler. Do not duplicate comparison logic in the router.
- [ ] Stage the merged bytes as a new storage object, promote once, commit database state atomically, and clean up candidates only after a known outcome. Preserve the existing outcome-unknown safeguards.
- [ ] Run:

```bash
.venv/bin/pytest tests/services/test_import_service.py tests/integration/test_atomic_import_version.py tests/api/v1/test_imports.py tests/security/test_import_conflict_export.py -q
.venv/bin/ruff check src/services/import_service.py api/v1/schemas/imports.py api/v1/routers/imports.py tests/api/v1/test_imports.py
```

- [ ] Run changed-path verification and commit: `feat: commit row-deduplicated dataset versions`.

## Task 5: Add bilingual Operator import quality and conflict UI

**Files:**

- Modify: `bizpulse/frontend/assets/features/workspace/state.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/workspace/view.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/frontend/assets/styles.css`
- Modify: `bizpulse/tests/frontend/workspace.test.mjs`
- Modify: `bizpulse/tests/frontend/operator-data-source.test.mjs`
- Modify: `bizpulse/tests/frontend/i18n.test.mjs`

**Behavior:** replace the raw commit-plan JSON block with totals and a per-table summary; exact duplicates require no checkbox; conflicts disable Commit, show the first 50 rows in a keyboard-readable table, and offer one real CSV download link. Viewer UI remains unchanged and cannot reach these controls.

- [ ] Write failing state/view/data-source tests for dedupe summary, conflict ordering, disabled Commit, CSV link, EN/ZH text, and absence from Viewer mode.
- [ ] Add `conflictDownloadUrl(workflowId)` to `OperatorDataSource`; store structured `dedupe`/`conflicts` in workspace state rather than preformatted text.
- [ ] Implement compact, responsive UI. Format counts as integers and monetary preview values with existing two-decimal formatters.
- [ ] Run:

```bash
npm test -- --test-name-pattern='workspace|operator data source|i18n'
```

- [ ] Run changed-path verification and commit: `feat: show import dedupe quality and conflicts`.

## Task 6: Generate and seed the stable low-traffic second store

**Files:**

- Modify: `bizpulse/src/synthetic/contracts.py`
- Modify: `bizpulse/src/synthetic/release_profile.py`
- Modify: `bizpulse/src/synthetic/generator.py`
- Modify: `bizpulse/src/synthetic/seed.py`
- Modify: `bizpulse/tests/unit/test_synthetic_generator.py`
- Modify: `bizpulse/tests/integration/test_synthetic_seed.py`
- Regenerate: `bizpulse/tests/fixtures/synthetic/v1/*`

**Fixture contract:**

- Main: `SYNTH-STORE-01`, established.
- Launch: `SYNTH-STORE-02`, `Brazil Launch Store` / `巴西新店`, opens `2026-07-08`, lifecycle `new`.
- Launch store uses only `SYNTH-SKU-001`, `SYNTH-SKU-003`, `SYNTH-SKU-006`.
- Launch impressions/traffic across the overlapping period are between 10% and 20% of main-store traffic for those SKUs; at least one open day has zero orders.
- Every store-scoped ID is stable and collision-free. Shared product catalog is not duplicated.

- [ ] Write the invariants as failing tests before changing the generator. Add byte-for-byte regeneration and aggregate conservation assertions.
- [ ] Extend the fixed-seed generator with an independent deterministic launch-store process, not a copied fixed multiplier. Create independent orders, lots, movements, snapshots, outbound, refunds, fees, fulfillment, advertising, policies, and store-scoped costs.
- [ ] Regenerate fixtures with the checked-in generator command already used by `test_synthetic_generator.py`; inspect the manifest diff and reject any non-approved source/classification change.
- [ ] Run:

```bash
.venv/bin/pytest tests/unit/test_synthetic_generator.py tests/integration/test_synthetic_seed.py tests/security/test_synthetic_source_boundary.py -q
```

- [ ] Run changed-path verification and commit: `feat: add deterministic launch store data`.

## Task 7: Add version-bound store catalogs and scope resolution

**Files:**

- Create: `bizpulse/src/services/store_scope.py`
- Modify: `bizpulse/src/services/analysis_service.py`
- Modify: `bizpulse/src/services/library_service.py`
- Modify: `bizpulse/api/v1/schemas/library.py`
- Modify: `bizpulse/api/v1/routers/library.py`
- Modify: `bizpulse/api/routers/demo_library.py`
- Modify: `bizpulse/tests/services/test_library_service.py`
- Modify: `bizpulse/tests/api/v1/test_library.py`
- Modify: `bizpulse/tests/api/test_demo_library.py`
- Create: `bizpulse/tests/services/test_store_scope.py`

**Contract:**

- Derive catalog from explicit `store_catalog`, falling back to exact `stores` rows. Unknown requested IDs raise `STORE_SCOPE_INVALID`.
- API query form is repeated `store_id`, e.g. `?store_id=SYNTH-STORE-02`; absence means all stores. Never accept a client-provided display name or catalog.
- Library filters store-scoped rows to the scope, keeps shared tables, and returns `scope_kind: "store" | "shared"` per table.
- Version/library detail returns the bounded store catalog and resolved scope.

- [ ] Write failing tests for default-all, one valid store, unknown store, deterministic catalog order, single-store Library rows, shared tables, and Demo/Operator parity.
- [ ] Implement `StoreScopeResolver` and route all scope validation through it. Remove prefix-only `SYNTH-` validation from general scope code; synthetic-source enforcement remains at the source boundary.
- [ ] Run:

```bash
.venv/bin/pytest tests/services/test_store_scope.py tests/services/test_library_service.py tests/api/v1/test_library.py tests/api/test_demo_library.py -q
```

- [ ] Run changed-path verification and commit: `feat: resolve version-bound store scopes`.

## Task 8: Precompute and serve all, main, and launch analysis scopes

**Files:**

- Modify: `bizpulse/src/services/dataset_preparation_service.py`
- Modify: `bizpulse/src/services/public_release_service.py`
- Modify: `bizpulse/src/services/demo_action_authority.py`
- Modify: `bizpulse/src/services/profit_bridge_service.py`
- Modify: `bizpulse/src/services/forecast_service.py`
- Modify: `bizpulse/api/v1/routers/analyses.py`
- Modify: `bizpulse/api/v1/routers/forecasts.py`
- Modify: `bizpulse/api/v1/routers/profit_bridge.py`
- Modify: `bizpulse/api/v1/routers/actions.py`
- Modify: `bizpulse/api/routers/public_release.py`
- Modify: `bizpulse/api/v1/schemas/analyses.py`
- Modify: `bizpulse/api/v1/schemas/forecasts.py`
- Modify: `bizpulse/api/v1/schemas/profit_bridge.py`
- Modify: `bizpulse/api/v1/schemas/actions.py`
- Modify: `bizpulse/tests/services/test_dataset_preparation_service.py`
- Modify: `bizpulse/tests/services/test_public_release_service.py`
- Modify: `bizpulse/tests/integration/test_analysis_vertical.py`
- Modify: `bizpulse/tests/api/test_public_release.py`

**Rules:**

- `DatasetPreparationService.prepare()` resolves and prepares exactly three scopes for the two-store synthetic release: all, main, launch.
- Preparation status is ready only when every required domain/scope exists. Scope is part of analysis, forecast, bridge, and action identity/input hash. `ForecastService.latest(dataset_version_id, scope)`, `ProfitBridgeService.default(dataset_version_id, scope)`, and `ActionService.list(dataset_version_id, scope)` must return only exact-scope records.
- Read routes accept the validated store query and call `get_exact_completed` only; Viewer reads cannot call `run`.
- All-store ratio KPIs are recomputed from combined numerators/denominators. Tests must reject averaging store-level ROAS, margin, conversion, refund rate, or cover days.
- Launch-store periods before opening return a structured `not_opened_yet` state.
- Single-store profit excludes unallocated shared cost and returns `shared_costs_unallocated=true`.

- [ ] Write failing service/API tests for all three exact scopes, read-only Viewer switching, aggregate conservation, weighted/recomputed ratios, shared-cost flag, and pre-opening semantics.
- [ ] Replace `PUBLIC_ANALYSIS_SCOPE` fixed-store reads with `StoreScopeResolver` while retaining the same fixed period/currency authority.
- [ ] Run:

```bash
.venv/bin/pytest tests/services/test_dataset_preparation_service.py tests/services/test_public_release_service.py tests/integration/test_analysis_vertical.py tests/api/test_public_release.py -q
```

- [ ] Run changed-path verification and commit: `feat: prepare and serve three store scopes`.

## Task 9: Add one global store selector and propagate scope across every page

**Files:**

- Create: `bizpulse/frontend/assets/features/store-scope/state.mjs`
- Create: `bizpulse/frontend/assets/features/store-scope/view.mjs`
- Modify: `bizpulse/frontend/index.html`
- Modify: `bizpulse/frontend/assets/app.mjs`
- Modify: `bizpulse/frontend/assets/views.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/frontend/assets/features/settings/state.mjs`
- Modify: `bizpulse/frontend/assets/features/library/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/library/view.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/frontend/assets/styles.css`
- Create: `bizpulse/tests/frontend/store-scope.test.mjs`
- Modify: `bizpulse/tests/frontend/operator-data-source.test.mjs`
- Modify: `bizpulse/tests/frontend/library.test.mjs`
- Modify: `bizpulse/tests/frontend/shell.test.mjs`

**Frontend contract:**

```javascript
initialStoreScope(release, defaultStore)
reduceStoreScope(state, { type: "scope/selected", storeId })
scopeQuery(scope) // returns URLSearchParams with repeated store_id
```

- Selector order: All stores, Brazil Main Store, Brazil Launch Store.
- Current scope is visible in the workspace header, localized, keyboard accessible, and screen-reader labeled.
- Operator initializes from persisted `default_store`; Viewer persists only in `sessionStorage` for that Demo session.
- Every data-source read accepts a scope and appends validated query parameters.
- Scope change increments a generation token. Old responses may remain visible during loading but cannot commit after a later generation.
- Scope change invalidates Overview, Sales, Inventory, Profit, Forecast, Action, Library, and new Chat turns; it clears unsaved Action inputs and shows one lightweight notice.

- [ ] Write failing reducer, stale-response, URL, persistence, selector, Library shared-label, EN/ZH, and narrow-screen contract tests.
- [ ] Implement the selector once in `app.mjs`; do not duplicate selectors inside individual pages. Pass a `getScope()` dependency into loaders/effects.
- [ ] Run:

```bash
npm test -- --test-name-pattern='store scope|operator data source|library|shell'
```

- [ ] Run changed-path verification and commit: `feat: add global store scope selector`.

## Task 10: Bind Action and Ask BizPulse turns to the selected scope

**Files:**

- Modify: `bizpulse/api/v1/schemas/ai_chat.py`
- Modify: `bizpulse/api/v1/routers/ai_chat.py`
- Modify: `bizpulse/src/ai/contracts.py`
- Modify: `bizpulse/src/services/ai_chat_service.py`
- Modify: `bizpulse/src/services/action_service.py`
- Modify: `bizpulse/src/services/demo_action_authority.py`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/state.mjs`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/effects.mjs`
- Modify: `bizpulse/frontend/assets/features/ask-bizpulse/view.mjs`
- Modify: `bizpulse/frontend/assets/features/action-inbox/state.mjs`
- Modify: `bizpulse/frontend/assets/features/action-inbox/effects.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/operator.mjs`
- Modify: `bizpulse/frontend/assets/data-sources/public.mjs`
- Modify: `bizpulse/tests/api/v1/test_ai_chat.py`
- Modify: `bizpulse/tests/services/test_ai_chat_service.py`
- Modify: `bizpulse/tests/integration/test_ai_chat_tools.py`
- Modify: `bizpulse/tests/frontend/ask-bizpulse-effects.test.mjs`
- Modify: `bizpulse/tests/frontend/action-inbox.test.mjs`
- Modify: `bizpulse/tests/security/test_ai_chat_boundary.py`

**Behavior:**

- `ChatTurnRequest` includes repeated/array `store_ids`; the server resolves them against the principal's exact dataset catalog and records the resolved tuple with the turn.
- Existing turns retain and display their original dataset/store/period/currency label after a selector change. Only new turns use the new scope.
- All-store AI may compare stores only using bounded deterministic tools. Single-store answers cannot contain evidence from another store.
- AI performs no internet search, new-product opportunity search, raw-table discovery, arbitrary SQL, upload, publication, or calculation trigger.
- Preset click still only fills the draft. Send performs the provider workflow.
- Action simulations and overlays are scope-bound; stale or cross-scope commands return `ACTION_SCOPE_CONFLICT`.

- [ ] Write failing tests for unknown/cross-version stores, scope persistence on turns, single-store evidence isolation, all-store comparison, Action reset, and no provider attempt on preset click.
- [ ] Resolve scope in the router/service from server authority, not from a prefix. Include scope in idempotency hashes, audit metadata, tool query inputs, and UI evidence labels.
- [ ] Run:

```bash
.venv/bin/pytest tests/api/v1/test_ai_chat.py tests/services/test_ai_chat_service.py tests/integration/test_ai_chat_tools.py tests/security/test_ai_chat_boundary.py -q
npm test -- --test-name-pattern='ask bizpulse|action inbox'
```

- [ ] Run changed-path verification and commit: `feat: bind AI and actions to store scope`.

## Task 11: Lock the nano provider, approved budgets, and real-model qualification harness

**Files:**

- Modify: `bizpulse/src/config.py`
- Modify: `bizpulse/src/ai/openai_gateway.py`
- Modify: `bizpulse/src/services/ai_chat_service.py`
- Modify: `bizpulse/api/container.py`
- Modify: `bizpulse/infra/main.bicep`
- Modify: `bizpulse/tests/infra/test_bicep_contract.py`
- Modify: `bizpulse/tests/services/test_ai_chat_container.py`
- Modify: `bizpulse/tests/services/test_ai_chat_service.py`
- Modify: `bizpulse/tests/security/test_ai_chat_boundary.py`
- Create: `bizpulse/scripts/qualify_openai_model.py`
- Create: `bizpulse/tests/unit/ai/test_model_qualification.py`
- Modify: `bizpulse/docs/runbooks/DEPLOY.md`

**Exact configuration:**

```text
model = gpt-5.4-nano-2026-03-17
reasoning_effort = low
daily_provider_attempts = 120
monthly_total_tokens = 150000
session_attempts_per_minute = 3
global_attempts_per_minute = 20
max_concurrent_turns = 15
max_output_tokens = 2800
```

- Gateway makes no automatic retry after timeout or outcome-unknown, validates the complete response schema before display, and never falls back to another model.
- Qualification matrix is exactly EN/ZH x all/main/launch x monthly-sales-report/inventory-risk = 12 calls. It verifies scope, numerical citations, evidence refs, language, schema, and token limit.
- The qualification script is inert unless `--execute-paid-qualification` and `OPENAI_API_KEY` are both present. Unit tests inject a fake client and perform zero network calls.
- Receipt contains model snapshot, case IDs, pass/fail, token counts, and hashes, but no secret or raw customer prompt/response.

- [ ] Write failing exact-config, retry, fallback, incomplete-response, 12-case, fake-provider, and secret-absence tests.
- [ ] Update application/Bicep defaults and hosted verifier expectations together. Keep `infra/environments/demo.bicepparam` AI-disabled and secret-free.
- [ ] Implement the qualification script with dependency injection and an explicit paid flag.
- [ ] Run:

```bash
.venv/bin/pytest tests/unit/ai/test_model_qualification.py tests/services/test_ai_chat_container.py tests/services/test_ai_chat_service.py tests/infra/test_bicep_contract.py tests/security/test_ai_chat_boundary.py -q
.venv/bin/ruff check src/config.py src/ai/openai_gateway.py scripts/qualify_openai_model.py tests/unit/ai/test_model_qualification.py
```

- [ ] Scan tracked/browser content for secret names/values and prohibited mutable model aliases.
- [ ] Run changed-path verification and commit: `feat: lock bounded nano AI configuration`.

## Task 12: Run local acceptance and create a two-stage release package

**Files:**

- Modify: `bizpulse/tests/acceptance/test_browser_smoke.py`
- Modify: `bizpulse/tests/acceptance/test_exact_15_sessions.py`
- Modify: `bizpulse/tests/acceptance/test_restart_readback.py`
- Modify: `bizpulse/tests/acceptance/test_rollback_compatibility.py`
- Modify: `bizpulse/tests/hosted/verify_azure_demo.py`
- Modify: `bizpulse/tests/hosted/test_verify_azure_demo.py`
- Modify: `bizpulse/scripts/create_release_manifest.py`
- Modify: `bizpulse/scripts/verify_release.py`
- Modify: `bizpulse/release/local-release-manifest.json`
- Modify: `CURRENT_STATUS.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`

**Local acceptance:**

- Fresh PostgreSQL migration to head `0014`, restart/readback, row-dedupe atomicity, three-scope preparation, all Operator functions, Viewer restrictions, 15 concurrent Viewer sessions, bilingual UI, keyboard/narrow-screen selector, Library paging, Action reset, AI fake states, and secret scan.
- Browser acceptance must prove Viewer scope switches create no canonical/analysis/forecast/bridge/release rows.
- Run the full non-reusable release gate on the exact candidate SHA; changed-path evidence is not release evidence.

**Release package:** create two bound stages for one immutable candidate image digest:

1. `data_scope_revision`: AI disabled, no OpenAI secret, full non-AI hosted checks.
2. `ai_revision`: same candidate digest and data authority, AI enabled only after stage 1 receipt plus model qualification receipt; one hosted monthly-report smoke; exact stage-1 revision is rollback.

The package contains exact subscription/tenant/resource group/app/environment/registry/image digest, migration, seed manifest, commands, retry limits, stop conditions, expected secret-presence booleans, cost cap, and expiry. It never contains the Key.

- [ ] Write/extend failing release-package tests before changing scripts.
- [ ] Run focused acceptance, then:

```bash
cd bizpulse
.venv/bin/python scripts/verify_changed.py --base d4ed425e8f9c5c2e271ef7e53a2276674500d4c3 --no-reuse
.venv/bin/python scripts/verify_release.py
```

- [ ] Commit the implementation candidate and create the immutable local release manifest/attestation using the existing two-commit protocol.
- [ ] Report exact candidate SHA, image digest, package SHA256, expiry, stage order, cost cap, remaining external actions, and that Azure/paid AI have not executed.
- [ ] **STOP.** Obtain explicit approval of the newly generated exact package hash. Do not interpret the approval of this plan as approval of Task 13.

## Task 13: Execute the separately approved Azure stages and inject the Key safely

This task is an external-state gate, not ordinary local development. Start only after the user approves the exact Task 12 package hash and all existing release-control preflights pass without drift.

**Key handling:** the user keeps the Key in the OpenAI project until this point. Ask them to paste it once into a hidden interactive terminal prompt:

```zsh
read -s "BIZPULSE_DEPLOY_OPENAI_API_KEY?OpenAI API Key: "
export BIZPULSE_DEPLOY_OPENAI_API_KEY
echo
```

The release runner must read that process environment variable, pass it through a Bicep secure parameter to Container Apps secret `openai-api-key`, and expose it only as server env secretRef `OPENAI_API_KEY`. Never print, echo, inspect, persist, or include it in evidence. Immediately after the AI revision command returns:

```zsh
unset BIZPULSE_DEPLOY_OPENAI_API_KEY
```

**Execution order:**

- [ ] Run the exact read-only authority/preflight from the approved package once; stop on target, digest, migration, cost, identity, secret-presence, writer, or rollback drift.
- [ ] Run the 12-case real nano qualification within the package's paid-call cap. If any case fails, disable/stop and ask the user; do not fall back.
- [ ] Deploy the exact AI-disabled data/scope revision and run full hosted non-AI acceptance for Operator, Viewer, three scopes, Library, Action, health, capacity, restart, and rollback compatibility.
- [ ] Capture the exact healthy AI-disabled revision as rollback authority.
- [ ] Prompt for the Key through hidden terminal input and deploy the bound AI-enabled revision.
- [ ] Run exactly one hosted monthly-report smoke. Verify dataset/store/period/currency/evidence, response completeness, token ledger, rate/concurrency state, and OpenAI project usage delta.
- [ ] On AI failure, deploy/route to the exact verified AI-disabled revision. Revoke the OpenAI Key as well if exposure or unexplained usage is suspected.
- [ ] Record sanitized hosted evidence, exact revision/image identities, rollback target, and separate state claims. Do not label the result Production ready unless the distinct Production gate is satisfied.

---

## Final verification matrix

| Requirement | Primary tasks | Required evidence |
|---|---:|---|
| Exact duplicate rows removed | 2-4 | assembler/property/API/integration tests |
| Same-key conflicts block atomically | 3-5 | no-state-change integration + UI/CSV tests |
| Operator functions remain live | 4-5, 12 | Operator API/browser acceptance |
| Viewer cannot upload or recompute | 8-10, 12 | auth + row-count/browser acceptance |
| Second store is low-traffic and stable | 6 | deterministic fixture invariants |
| One global scope controls seven surfaces | 7-10 | service/API/frontend generation-fence tests |
| Shared catalog/cost semantics | 7-8 | Library/profit scope tests |
| AI scope/evidence isolation | 10-11 | tool/security tests |
| Fixed nano and six hard limits | 11 | config/Bicep/container tests |
| Key never reaches client or source | 11-13 | static/security/release readback evidence |
| AI-disabled rollback remains healthy | 12-13 | hosted receipt and exact revision identity |

## Plan self-review

- **Spec coverage:** Tasks 1-5 cover sections 5 and 11.1; Tasks 6-10 cover sections 6-8 and 11.2; Tasks 11-13 cover sections 9-10, 11.3, and all release/rollback gates; Task 12 covers section 13 acceptance.
- **Type consistency:** dataset IDs remain UUIDs, store IDs remain bounded strings from a version catalog, dates remain ISO dates, currency remains `BRL`, money/ratios retain backend precision, and UI-only formatting stays at two decimals.
- **Authority consistency:** the captured base version prevents commit-plan drift; scope is resolved server-side; AI and Action identities include exact version/scope; release artifacts bind exact SHA/digest/revision.
- **Security consistency:** no client Key path, no free SQL/raw table AI access, no model fallback, no retry after unknown outcome, no conflict-export internals, no Viewer write escalation.
- **Rollback consistency:** database versions remain immutable, conflict failures create no version, data/scope goes live AI-disabled first, and that exact revision is the AI rollback target.
- **Placeholder scan:** no `TODO`, `TBD`, `fill later`, guessed Azure target, dummy secret, mutable model alias, or unbounded “run all” step is permitted in execution artifacts.

Plan complete. Begin with Task 1 only after the user selects an execution mode. Do not request or accept an AI Key until Task 13's exact approved external-state gate.
