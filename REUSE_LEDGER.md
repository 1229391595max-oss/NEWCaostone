# NEWCaostone Reuse Ledger

Status: Stage 0 source-authority audit complete; no source has been copied.

Authoritative product design: `docs/superpowers/specs/2026-08-13-newcaostone-demo-single-operator-design-v0.2.0.md` (`v0.2.0`, Approved)

Source repository (read-only): `/Users/maxli/Desktop/CAPTSONE`

Selected immutable inspection baseline: `3af1c6bc20e9b925b148d05b6da4f4301310c293`

Remote reference available locally: `bdbe53a3a74ac1a75849c044302cf32ad83ebbf1` (`refs/remotes/origin/master`)

Merge base: `f2fdd032cf5ba84d026e57dcf831ac86dcdb6374`

Observed divergence: local baseline is 275 commits ahead and 6 commits behind the locally stored remote reference. No fetch was performed. The source worktree also had pre-existing modified and untracked files, so neither worktree timestamps nor a moving branch name are accepted as authority.

## Decision vocabulary

- `Reuse candidate`: all five source gates have repository evidence at an immutable commit: formal entry, service/data chain, migration dependency, no later removal on the selected line, and executable tests. The code still must be copied selectively into NEWCaostone and pass the listed isolated tests before adoption.
- `Adapt candidate`: a proved source seam is useful, but NEWCaostone's approved scope requires a deliberate rewrite around it.
- `Pending verification`: one or more five-gate checks are incomplete or the exact baseline contains later overlays not covered by the strongest historical test evidence. Default to rebuild if the design time box expires.
- `Rebuild`: the approved capability does not exist as an effective source module or cannot safely inherit the old schema/behavior.
- `Reject`: deliberately excluded source; it must not be copied.

No item is marked `adopted` in Stage 0. Adoption happens only after implementation-plan approval, selective copy, target-path review, and isolated NEWCaostone verification.

## Reuse candidates

### R1. Deterministic sales and advertising analysis core

- Decision: `Reuse candidate`, selective copy and adaptation.
- Source baseline: `3af1c6bc20e9b925b148d05b6da4f4301310c293`.
- Source files: `bizpulse/src/analysis/sales_ads_calculator.py`, `bizpulse/src/services/workflow_analysis_service.py`, `bizpulse/api/v1/routers/analysis.py`, `bizpulse/src/repositories/analysis_runs.py`, `bizpulse/src/repositories/analysis_artifacts.py`.
- Last material source commits: calculator `c8e65b4d41046e5271ebdb97352815701d1cf2a0`; service PostgreSQL parity/review through `475d0b3a4f1666c512530f6addd3f3e0751c86c6`. Both are ancestors of the selected baseline.
- Formal reachability: `api.main:create_app()` -> `api/v1/router.py` -> `api/v1/routers/analysis.py` -> `ApiContainer.workflow_analysis_service` -> calculator/repositories -> immutable snapshot/evidence.
- Migration dependency: local migration 5 (`stage_2a3_sales_ads_analysis`); PostgreSQL objects are included in Alembic `0001_cloud_baseline`.
- Replacement check: the relevant analysis group is byte-identical between the selected baseline and the locally stored `origin/master`; no deletion of the listed service/calculator paths appears on the selected baseline history.
- Test evidence in the immutable tree: `tests/integration/test_stage_2a3_analysis_api.py`, `tests/services/test_workflow_analysis_service.py`, `tests/services/test_workflow_analysis_reuse.py`, `tests/repositories/test_stage_2a3_schema.py`, and the golden snapshot under `tests/fixtures/stage_2a3/`. `CURRENT_STATUS.md` records the exact feature run at 1,802 Python passes and 117 frontend passes at the Stage 2A-3 source state; that is historical local evidence, not a fresh run in this task.
- NEWCaostone target: `bizpulse/src/analysis/sales_ads_calculator.py` and the matching versioned service/repository boundary.
- Required adaptation: remove owner/multi-tenant assumptions not needed by the single-operator design while preserving server-derived workspace/session scope, PostgreSQL-only persistence, pure synthetic data, immutable evidence, and no silent zeroes.
- Revalidation: focused calculator tests, repository tests against PostgreSQL, API integration, deterministic snapshot hash, and frontend Sales/Ads tests.

### R2. Deterministic inventory, FIFO/cost-aging, operating-profit, and replenishment calculators

- Decision: `Reuse candidate` for the deterministic calculation kernels; services are `Adapt candidates`.
- Source files: `bizpulse/src/analysis/inventory_risk_*`, `fifo_cost_aging_*`, `operating_profit_*`, `replenishment_*`; matching `bizpulse/src/services/workflow_*_service.py`; `bizpulse/api/v1/routers/analysis.py`.
- Last material source commits: inventory service `4f6698cf4e7035dc2019efbf476268c9a1224245`; operating-profit and replenishment PostgreSQL publication `d0bf6f219ddeb9aee4dc260ff6cc8a0c437f050b`. Both are ancestors of the selected baseline.
- Formal reachability: versioned analysis router selects the matching workflow service; each service plans inputs, invokes a pure calculator, persists an immutable run/artifact/evidence record, and returns typed reads through the same router.
- Migration dependency: local migrations 7 (inventory), 8-10 (FIFO/workbook groups/scope), 11 (operating profit), and 12 (replenishment); PostgreSQL baseline objects are in Alembic `0001_cloud_baseline`.
- Replacement check: the calculator/service group is byte-identical between the selected baseline and stored `origin/master`; no deletion of the named paths appears on the selected history.
- Test evidence: `tests/services/test_workflow_inventory_analysis_service.py`, `test_workflow_fifo_cost_aging_service.py`, `test_workflow_operating_profit_service.py`, `test_workflow_replenishment_service.py`, their `*_reuse.py` files, Stage 4A/4B/4C/5A integration files, and corresponding repository tests. `CURRENT_STATUS.md` preserves exact historical feature verification and its limitations.
- NEWCaostone target: retain pure deterministic formulas and typed snapshot contracts; rebuild the PostgreSQL schema and public services around the approved single-workspace contract.
- Required adaptation: exclude private-sample paths, real-data assumptions, legacy SQLite migration code, annual old-product forecasting, and any external market-source behavior. Existing replenishment is not the approved new-product forecast.
- Revalidation: unit fixtures with Decimal/currency boundaries; PostgreSQL persistence/restart; evidence integrity/reuse signatures; missing-input behavior; API and frontend composites.

#### R1/R2 Task 7 time-box decision: `Adapt behavior, rebuild target contracts`

- Pinned source commit: `3af1c6bc20e9b925b148d05b6da4f4301310c293`; all five calculator blobs are byte-identical at stored `origin/master` `bdbe53a3a74ac1a75849c044302cf32ad83ebbf1`.
- Calculator blobs: sales/ads `8a5088a27a3ae623066724b818bbf03d9ebe4801`; inventory risk `a44456a523621a27f5d4d9572314bd5a074b765a`; FIFO/cost aging `7de866d49eb48f1bf89673b73457b91720871ba7`; operating profit `4854965988d4e87504c75d09e11224c8293c45d8`; replenishment `6b8d4cc6134f8fd6dc68fa275f29dbb817030aa7`.
- Characterization-test blobs: sales `754132b2db21e0efa12f735f2224b6d9d7a17b85`; inventory `a8e7b09e4874c72e8c8f27512f2806fbb3abdd87`; FIFO `06dddc5e816d802be777070ab1263cdb06178b21`; profit `b9d468820effb520e029aab7fe7a449a3747b8dd`; replenishment `2fb922cc573c9f150ef5b1f84da9edd810b34408`.
- Replacement/history proof: last selected material commits are `c8e65b4d41046e5271ebdb97352815701d1cf2a0`, `ffc39b7451f628b7a3707c6f00f8cf4fae2ad639`, `8da8b312ff501025ef4fe94a4917dee078b7a170`, `8e4e178f8341a31460554708de06c5b1397d052f`, and `7c5c7afd31c0f65b9eae0277cca18e7bc64e3ad0` respectively; each is an ancestor of the pinned baseline.
- Adaptation decision: the source calculators are 2,720/818/931/1,249/2,039 lines and depend on the old canonical-artifact, planning, mapping, signature, and snapshot graphs. Copying them would import the rejected multi-tenant/legacy migration boundary. NEWCaostone will preserve the characterized Decimal formulas, unknown-not-zero behavior, deterministic ordering, evidence states, and immutable input-signature semantics while rebuilding the smaller `synthetic.v1` contracts and PostgreSQL publication layer. No CAPTSONE file is copied.
- Target attestation: implemented by behavior-level adaptation and fresh target contracts in NEWCaostone commit `2defd71` (`feat: add deterministic analysis evidence`). No CAPTSONE file was copied. The target adds five scoped deterministic analyses, hash-verified immutable artifacts/evidence, safe reuse and recovery, and a formal pure-synthetic seed vertical. Ruff and the complete PostgreSQL-backed Python suite passed `154` tests with `3` controlled external-emulator skips; independent review found no Critical or Important issue before commit.

### R3. Azure Blob workflow-storage adapter and PostgreSQL advisory locks

- Decision: `Reuse candidate`, subject to isolated SDK/Azurite and PostgreSQL tests.
- Source files: `bizpulse/src/storage/azure_blob_workflow_storage.py`, `bizpulse/src/storage/postgres_entry_locks.py`, `bizpulse/src/storage/storage_keys.py`, and their container wiring.
- Last material Blob commit: `f8cfbba214a23f4c40f7b5fb2c9ea15e0b297576`, an ancestor of the selected baseline.
- Formal reachability: `api.main:create_app()` -> `build_api_container()` -> cloud storage/lock construction -> import and artifact services.
- Migration dependency: database object-reference and lock coordination tables are represented in Alembic `0001_cloud_baseline`; NEWCaostone will create a smaller fresh migration rather than copy the monolithic baseline.
- Replacement check: source and principal Blob test are byte-identical between the selected baseline and stored `origin/master`; no deletion appears in selected history.
- Test evidence: `tests/storage/test_azure_blob_workflow_storage.py`, `test_postgres_entry_locks.py`, `tests/integration/test_l3_blob_service_contracts.py`, and `test_l3_blob_upload_vertical_slice.py`. Historical L3 evidence records focused, PostgreSQL, Azurite, and composite results with explicit non-hosted limits.
- NEWCaostone target: `bizpulse/src/storage/azure_blob_workflow_storage.py`, `bizpulse/src/storage/postgres_entry_locks.py`.
- Required adaptation: one Demo workspace, fixed object namespaces, temporary upload TTL, normalized dataset/evidence/export objects, no Managed Identity assumption until the launch authorization chooses the exact Azure configuration.
- Revalidation: fake-client failure classification, Azurite lifecycle, ETag/conditional writes, bounded streaming, orphan inventory, PostgreSQL lock ordering, restart reads, and no local-disk fallback in cloud mode.

#### R3 Task 4 adoption record (adopted)

- Pinned inspection commit: `3af1c6bc20e9b925b148d05b6da4f4301310c293`.
- Source blob `bizpulse/src/storage/azure_blob_workflow_storage.py`: `d51bde3927345bc5c5049d423fb08334cd156f88`.
- Source blob `bizpulse/src/storage/postgres_entry_locks.py`: `146258ea63cf271757fdecc7c7e095069ba317d3`.
- Source blob `bizpulse/src/storage/storage_keys.py`: `1e536214c120ec62b4e63a9bda8226c3777d0dd2`.
- Evidence blob `bizpulse/tests/storage/test_azure_blob_workflow_storage.py`: `363262e0d8fd68ca1bb223688c4976d1c4245e47`.
- Evidence blob `bizpulse/tests/storage/test_postgres_entry_locks.py`: `bd6e73d15e10b3099a33c8809b0db2bda25f31da`.
- Target decision: selectively rewrite the bounded streaming, SHA-256, conditional Blob, ETag, deterministic PostgreSQL advisory-lock ordering, single deadline, and reverse partial-release seams. Do not copy old owner namespaces, old migrations, or old container wiring.
- Target paths: `bizpulse/src/storage/azure_blob_workflow_storage.py`, `bizpulse/src/storage/postgres_entry_locks.py`, `bizpulse/src/storage/keys.py`, and the fresh NEWCaostone container/lifecycle/repository seams.
- Target verification: PostgreSQL migration, real advisory-lock contention, append-only dataset/release repositories, lifecycle compensation/expiry/orphan inventory, and full Python regression passed. Real Azurite staging/promotion/hash/ETag/teardown passed with 3 tests. The exact approved SDK/Azurite pins require Azurite's documented `--skipApiVersionCheck` local-emulator compatibility flag; `package.json` records the controlled server command. Production npm dependencies report zero vulnerabilities; the dev-only Azurite dependency chain reports eight moderate advisories and no high/critical advisory, retained for Task 14 risk review without applying a breaking `npm audit fix --force` downgrade.
- Target implementation commit: `a89de1ddea209b871302a5912a92d3c84b12ea23` (`feat: add PostgreSQL and Blob object lifecycle`).

### R4. Action Inbox state machine and Outcome Review skeleton

- Decision: `Reuse candidate` for state transitions, immutable revisions, export/outcome separation, evidence links, and frontend state/view patterns.
- Source files: `bizpulse/src/services/action_inbox_service.py`, `bizpulse/src/services/outcome_review_service.py`, `bizpulse/src/repositories/action_inbox.py`, `bizpulse/src/repositories/action_outcomes.py`, `bizpulse/api/v1/routers/action_inbox.py`, `action_outcomes.py`, and `bizpulse/frontend/assets/features/action-inbox/`.
- Last material commits: action service `f292aac0f9ba54318241cd39a0f3a89ca5ae80f6`; outcome service review repair `e0c20ed6d4be72e35c801156c788eb76cc16b2a4`. Both are ancestors of the selected baseline.
- Formal reachability: v1 aggregate router -> action/action-outcome routers -> container services -> repositories -> action/outcome UI effects/state/view.
- Migration dependency: local migration 20 / Alembic `0003_action_inbox_v1`; outcomes extend local migration 26 / Alembic `0008_targets_outcomes`.
- Replacement check: listed source groups are byte-identical between the selected baseline and stored `origin/master`; the Action feature head `0b88769` and later account/outcome commits are ancestors of the selected baseline; no deletion appears.
- Test evidence: `tests/api/v1/test_action_inbox.py`, `test_action_outcomes.py`, `tests/services/test_action_inbox_service.py`, `tests/services/test_outcome_review_service.py`, `tests/integration/test_action_inbox_end_to_end.py`, `test_action_outcomes_end_to_end.py`, repository tests, and frontend action tests.
- NEWCaostone target: preserve `new -> reviewed -> approved|dismissed`; adjustment creates an immutable reviewed revision; export and outcome review remain independent and never imply execution/completion.
- Required adaptation: single operator plus anonymous per-session simulations; add Chat/forecast/Profit Bridge source metadata and the design's explicit second action for Chat draft creation.
- Revalidation: transition matrix, CAS/idempotency, evidence drift, export formula injection, per-session isolation, reload, outcome history, API, and frontend tests.

#### R4 Task 11 adoption record (adapted behavior, rebuilt target)

- Pinned inspection commit: `3af1c6bc20e9b925b148d05b6da4f4301310c293`; CAPTSONE remained read-only and no source file was copied.
- Service blobs: action lifecycle `6d71aa6113dbcf024b8b22245337d4f314d3382c`; outcome review `0b68b4924f5bcdf8687c01cfa939a2a289b914e4`.
- Repository blobs: actions `6e78ce4e05bb23b295da98169b0cb3754e3360be`; outcomes `4d0f98e9156991b7fe3329181ee03c2882e17e2e`.
- Router blobs: actions `b2352616ac808af8818d229b0972fddadb0e9d17`; outcomes `c659a7b311453c45651524c363b60ab4c4e2bf90`.
- Frontend blobs: state `455235c6293a474cfc94f267ba012752eb565df4`; effects `5eca1d7485d67ff452a59b0da70c79b06556160d`; view-model `b935999bb7d8a6dada6ba6b6e0cbc76c82ec6664`; view `13cbd5374fdb7e13fe8ef83b31543206e9b9c9ec`.
- Evidence blobs: action service `5e8c795c160b98d468f30bd1bac3ddc8169e5fa6`; outcome service `2b71911bf637391c01e33ab4ea2a26b091789f40`; action integration `7d4d1bca8f8e07789e343d33ed46d3bbf02b64aa`; outcome integration `91cf3eb6a0c5b6234d8da27e7f04f6dd5196a465`.
- Time-box decision: preserve the proved transition semantics and evidence-first UI pattern, but rebuild the target because the source depends on the rejected owner/multi-tenant schema, legacy migrations, and external integration surfaces. The target uses a single server-derived workspace/operator, immutable PostgreSQL revisions and decisions, fixed-version evidence references, viewer-session overlays, and bounded Demo-only Blob exports.
- Target verification required before adoption: exact transition/CAS and replay tests, PostgreSQL trigger tests, source/evidence drift checks, export formula hardening, no-external-write assertions, operator/viewer isolation, session expiry, restart recovery, bilingual UI, and an independent Critical/Important review.

### R5. Formal FastAPI/static HTML entry structure

- Decision: `Adapt candidate`, not a whole-file reuse approval.
- Source files: `bizpulse/api/main.py`, `bizpulse/api/v1/router.py`, `bizpulse/frontend/index.html`, and core API/data-source modules.
- Formal reachability proved at baseline: `api.main:create_app()` registers `/`, `/login`, protected `/app`, `/real -> /app`, `/assets`, and the v1 router; `frontend/index.html` loads `/assets/app.mjs` and exposes six primary navigation buttons.
- Migration dependency: none for the HTML route itself; auth/session dependencies are separate.
- Replacement check: `frontend/index.html` and `api/v1/router.py` are identical across the two divergent refs, but `api/main.py`, `app.mjs`, `views.mjs`, and `styles.css` differ. The latter files contain later Course Demo overlays and must not be spliced across refs.
- Test evidence: `tests/api/test_frontend_assets.py`, `tests/frontend/contracts.test.mjs`, `views.test.mjs`, `data-source.test.mjs`, and feature tests. Historical route/browser evidence is recorded in `CURRENT_STATUS.md`.
- Required adaptation: remove the external jsDelivr icon dependency, Course Demo bootstrapping, temporary user-key controls, multi-tenant/Clerk surfaces outside the single-operator contract, and any fallback to Demo values after a real request failure.
- Target: retain six primary navigation areas, reuse the evidence drawer and data-source boundary, and add Ask BizPulse as the first secondary page inside AI Decision Center.

## Pending verification and bounded adapt candidates

### P1. Import, recognition, mapping, standardization, atomic commit, and dataset versions

- Status: `Pending verification`; default to a fresh minimal implementation if the 4-hour core-data time box expires.
- Source chain: `api/v1/routers/import_workflows.py` and `import_workflow_completion.py` -> `workflow_api_service.py` -> preparation/commit services -> upload/dataset/workflow repositories -> local migrations 1-6 and PostgreSQL baseline.
- Reason pending: `dataset_preparation_service.py`, `dataset_commit_service.py`, local migration versions, Alembic environment, and migration head differ across the two divergent refs. Their latest changes include Course Demo workbook behavior. The source has strong historical tests, but no isolated current-baseline run occurred in this task.
- Historical test files: Stage 2A-1/2A-2 API integrations, preparation authorization/concurrency/integrity/service suites, commit/group suites, upload registry idempotency suites, dataset repository suites, and PostgreSQL foundation/commit tests.
- Decision gate: in a NEWCaostone isolated copy, first prove one synthetic workbook + one advertising CSV through restart-safe recognition, atomic multi-file commit, idempotent replay, temporary-original cleanup, PostgreSQL persistence, and Blob object integrity. Copy only files exercised by that path.

#### P1 Task 6 time-box decision: `Rebuild`

- Pinned inspection commit: `3af1c6bc20e9b925b148d05b6da4f4301310c293`; no CAPTSONE file was copied or modified.
- Formal route blobs: aggregate router `fbc997805bf56a2fb6aaaa83aa2ca82d019aa83f`; import router `248edfd4f5f61054243f6fd2e21e0e153aadaa7c`; completion router `0509f2a2dc0ba412dd9859ad7b98a6403b55af32`; upload parser `c7a1db8200396cef5fc87fc843719bb870897ba7`.
- Service blobs: workflow API `dfec153accfc75a6c7991d9477d06f6ea83687e9`; preparation `e62fd92f157fdb99b6f03f248fdb2ee0dfe820d0`; commit `7a6a405d4bf6aeef41f416b6d1dc46a009a230c4`; upload registry `9128695a53eb0716a3ec6cfa6b8b517968ecac5d`.
- Repository blobs: dataset versions `f8197024e6814f0c8657e4466215b70faf5adf81`; upload processing `0e9713250f7d72c6ac06e2cb743af8d6f1b7673c`; upload registry `1b14404c2740dbe6a41fb2c725c6f5598350d1b1`.
- Migration/evidence blobs: monolithic cloud baseline `edb63d9d844728358bbb64bf95f29df77efeca0b`; Course Demo role overlay `7fcf8eeec08a90af6f6d943eaffb5e42d09c8587`; L3 Blob vertical `eda0bcbf3a45429eebb253b1562c9c067ed39e63`; workflow/preparation/commit tests `fd32ee4835b9103ce3d701ea5e9c775fc76c3722`, `b357a577e46f9b68759ffe821802a5e729665ebf`, and `5c9222643933e430dea6a756eb9a49c313dc79b9`.
- Replacement/history finding: the two routers are stable across the selected refs, but the 1,254-line workflow, 2,053-line preparation, and 2,198-line commit services differ across the divergent refs. Their latest selected-line changes include Course Demo bundle behavior. They depend on explicit organization owners, manual workbook groups, multi-store scopes, old artifact/repository contracts, and the old migration chain.
- Executable-proof finding: the inspected L3 vertical uses `SQLiteUnitOfWork`, a fake Blob container, and local file locks. It proves useful failure semantics but not the approved NEWCaostone PostgreSQL/Azurite atomic import vertical. The later role migration is explicitly Course Demo-specific and has no downgrade.
- Target decision: the four-hour ceiling is closed early because the required exact isolated vertical cannot inherit these seams without importing disallowed architecture. Rebuild the approved bounded adapters, revisioned workflow, PostgreSQL repositories, Blob lifecycle, API, and UI against NEWCaostone `0002_import_versions`; mine only the recorded behavior as reference. No whole-file reuse is authorized for P1.
- Target attestation: implemented by rebuild in NEWCaostone commit `2306f99` (`feat: add atomic synthetic import and versions`). No CAPTSONE file was copied. Target verification passed Ruff; `9` frontend tests; `109` PostgreSQL-backed Python tests with `3` controlled Azurite skips; and `5` explicit PostgreSQL/Azurite tests. Independent review found no Critical or Important issue before commit.

### P2. Today Overview service and UI

- Status: `Pending adapt candidate`.
- Source chain: `api/v1/routers/today_overview.py` -> `today_overview_service.py` -> `today_overview_sources.py` -> existing immutable artifacts -> `features/today/`.
- Migration dependency: none in the original MVP.
- Reason pending: the service differs across divergent refs after Milestone 4 evidence binding. NEWCaostone should preserve the read-only projection pattern only after the exact chosen artifact contracts pass isolated tests.
- Tests: Today service/API/repository/end-to-end and frontend effects/state/view-model/view files.

### P3. Public cover, single-operator authentication, and anonymous Demo sessions

- Status: `Pending adapt candidate`; do not copy the multi-tenant account system wholesale.
- Proven seams: separate `/`, `/login`, `/app`; server-side opaque session patterns; CSRF helpers; HttpOnly/Secure cookie handling; Demo session persistence/rate limits.
- Reason pending: auth/Demo routes and services differ across the divergent refs; the old system is restricted Clerk/Cloudflare/multi-tenant plus Course Demo overlays, while NEWCaostone is one protected operator and anonymous viewers.
- Tests to mine selectively: frontend/login/welcome, account session service, Demo session API/service, CSRF, session admission/concurrency, and privacy-log tests.
- Rebuild requirement: credentials and operator identity remain server-only; viewer scope is fixed by a secure cookie; PostgreSQL restores unexpired sessions; no registration/invitation/team UI is introduced.

### P4. Product Opportunity and Operating Briefing presentation patterns

- Status: `Adapt candidate` for UI state/effects/evidence patterns only.
- Stable paths: `features/opportunities/`, `features/briefing/`, `opportunity_inbox_service.py`, and `operating_briefing_service.py` are byte-identical across the two refs and their material commits are ancestors of the selected baseline.
- Blocking differences: Opportunity scoring and persistence are coupled to Google Trends/other online source kinds; Operating Briefing is one-shot plan/generate history with temporary user-key behavior and is not a database Chat Box.
- Allowed reuse: nested AI Decision Center navigation, request-generation fencing, stale-result suppression, evidence drawer links, safe provider failure presentation, bounded history layout.
- Forbidden claim: neither module proves Ask BizPulse, a Profit Bridge, or the approved new-product forecast.

### P5. PostgreSQL engine, unit-of-work, Alembic, Docker, and Azure IaC patterns

- Status: `Reference/adapt candidate`.
- Proven seams: SQLAlchemy Core engine, psycopg, Alembic environment, PostgreSQL unit-of-work, fail-closed cloud composition, non-root container, Blob module, health/readiness, digest-bound release/rollback ordering, and Bicep module layout.
- Reason not directly reusable: `0001_cloud_baseline` is a monolithic 55+ table migration derived from the old product; later migrations add multi-tenant and Course Demo concerns. Old Bicep/release paths encode prior Gate C/Course Demo assumptions and cannot define NEWCaostone resources or costs.
- Decision: write a fresh linear NEWCaostone migration chain and new IaC parameter files; selectively adapt proven helpers only after focused tests.

## Rebuild list

| Capability | Decision and evidence |
|---|---|
| Ask BizPulse database Q&A | `Rebuild`. Exact-code search at the selected commit found no `Ask BizPulse`, `ai-chat`, or Chat Box implementation. Operating Briefing is explicitly one-shot. Build the approved whitelist QueryTool -> deterministic result -> AI explanation -> authoritative merge chain. |
| AI Chat persistence and APIs | `Rebuild`. Add the approved turns/tool-runs/evidence/attempts/saved-records schema, idempotency, `outcome_unknown`, per-session cleanup, and exact endpoints. |
| New-product forecast | `Rebuild`, completed locally in Task 9 at `6e7cb53`. Existing replenishment was not reused as a substitute. The new module implements 7/30/90-day low/base/high forecasts, confirmed pure-synthetic analogs, confidence gates, hidden-window backtests, session-pinned reads, and evidence. |
| Period-over-period Profit Bridge | `Rebuild` over adapted profit facts. The old calculator has profit layers and a settlement revenue bridge, but no complete approved contribution-profit driver bridge with residual reconciliation. |
| Pure synthetic source generator and manifest | `Rebuild`. Do not copy real-derived values or Course Demo assets without source proof. Generate all stores/SKUs/orders/ads/cost/inventory/forecast cases from versioned rules and fixed seeds. |
| Single-operator schema and public session schema | `Rebuild`. Old account/tenant/RLS schema is broader and the Course Demo schema is narrower/different. Implement only the approved single operator, one workspace, anonymous sessions, fixed dataset version, and per-session simulated actions. |
| Fresh PostgreSQL migration chain | `Rebuild`. Use NEWCaostone `0001` onward; do not paste the old monolithic cloud baseline or dual SQLite chain. |
| Full action-card Chat/forecast/bridge source metadata | `Rebuild` around the proven state machine. Old actions do not carry all new source fields or the second-step Chat draft contract. |
| Azure deployment declarations and launch authorization | `Rebuild` for NEWCaostone names, costs, resource group, PostgreSQL, Blob, app, secrets, exact image digest, recovery, and rollback. No external mutation is authorized now. |

## Rejected source

| Source | Reason |
|---|---|
| `bizpulse/_review_later/` and its inventory | Historical quarantine/audit record, not a runtime source. |
| Untracked `.superpowers/`, rendered review files, ZIPs, temporary worktrees, local copies, and local databases | Not immutable, not authoritative, and outside the formal entry chain. |
| Any CAPTSONE worktree/branch not pinned by exact commit and ledger entry | Branch name and timestamp do not establish authority; several worktrees are milestone/assignment/diagnostic overlays. |
| `bizpulse/app.py` Streamlit orchestration and legacy SQLite-only read APIs | Transitional compatibility surfaces; NEWCaostone formal product is FastAPI + HTML and hosted PostgreSQL-only. |
| `bizpulse/src/market_sources/google_trends_api.py`, `google_trends_csv.py`, related routes/repositories/scoring fields/tests, Mercado/Comex live adapters, market-image gateway | Explicitly outside the approved zero-online-market-data design. The selected source contains many live Google Trends references, so Product Opportunity cannot be copied wholesale. |
| Old temporary user OpenAI-key UI/credential selector and old model allowlist | NEWCaostone uses one operator-supplied server-only temporary key and fixed `gpt-5.4-mini-2026-03-17`, low effort. |
| Course Demo scripts, five-sheet role migration `0009`, course-specific Bicep/telemetry/verifiers, milestone submission overlays | Course/diagnostic delivery artifacts are not automatically part of the NEWCaostone formal product. Individual generic helpers may be reconsidered only through a new ledger row. |
| Old Azure Gate C resource names, manifests, pricing snapshots, deployment evidence, and hosted URLs | Environment-specific historical evidence; not authority for NEWCaostone deployment or current cost/readiness. |
| Real/private sample validators and any source-derived fixture | NEWCaostone permits only source-level pure synthetic data. |

## Adoption gate for every candidate

Before any item changes from candidate to adopted:

1. Copy only the exact candidate files into a NEWCaostone implementation branch/worktree after plan approval.
2. Record source commit, source blob IDs, target commit, and any rewritten interface in this ledger.
3. Run the focused source tests adapted to PostgreSQL-only and pure synthetic inputs.
4. Prove the target formal entry reaches the module and its schema is on the single NEWCaostone Alembic chain.
5. Re-run secret/PII, prohibited-market-source, large-file, and Git-status checks.
6. If proof exceeds the design time box, mark `Rebuild` and stop searching CAPTSONE.
