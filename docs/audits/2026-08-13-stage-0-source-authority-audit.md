# Stage 0 Source Authority and Repository Initialization Audit

Date: 2026-08-13 (America/Chicago)

Scope: local NEWCaostone initialization, preservation checks, and read-only CAPTSONE source audit. No feature code, dependency installation, test execution in CAPTSONE, remote operation, paid API call, GitHub publication, or Azure mutation was performed.

## 1. Approved source of truth

- Workspace: `/Users/maxli/Desktop/NEWCaostone`
- Read-only reference: `/Users/maxli/Desktop/CAPTSONE`
- Approved design: `docs/superpowers/specs/2026-08-13-newcaostone-demo-single-operator-design-v0.2.0.md`
- Original pre-task SHA-256 of v0.2.0: `0c3f51005014ea8df7dac45021c401b6e524a465ab3cc5d163b00f7e3f595df5`
- Preserved v0.1.0 SHA-256: `2c1f684a8800fc4354769302b4b3467c93760d30219c0d08c66d09557a0e5105`
- The only v0.2.0 edits are approval-state wording and the now-authorized Stage 0 transition. Product scope, security, data, model, storage, UI, acceptance, and external-authorization boundaries were not changed.

## 2. NEWCaostone pre-initialization evidence

Initial files:

```text
.DS_Store
docs/.DS_Store
docs/superpowers/.DS_Store
docs/superpowers/specs/2026-08-13-newcaostone-demo-single-operator-design-v0.1.0.md
docs/superpowers/specs/2026-08-13-newcaostone-demo-single-operator-design-v0.2.0.md
```

Initial Git result:

```text
fatal: not a git repository (or any of the parent directories): .git
```

Pre-initialization large-file check (`>10 MiB`): no output.

Pre-initialization sensitive filename/content scan: no matching key/credential file and no actual private-key, AWS key, OpenAI-style key, or long credential assignment match. The scan prints file names only, never matched secret values.

## 3. Initialization actions

- Added `.gitignore` covering secrets and `.env`, macOS/editor metadata, Python/Node caches and environments, logs, builds, local databases/dumps, Terraform state, controlled temporary uploads/downloads, and local evidence.
- Ran `git init -b main` in NEWCaostone.
- Did not configure a remote.
- Did not change global or repository Git identity.
- Existing Git identity check returned `git_identity=missing`; therefore no local checkpoint commit was created.
- Explicitly removed only the three pre-existing `.DS_Store` paths. Finder recreated the root and `docs/` files during the task; they are ignored and are re-cleaned during final verification.

## 4. CAPTSONE immutable source decision

Read-only commands established:

```text
Git root: /Users/maxli/Desktop/CAPTSONE
HEAD: 3af1c6bc20e9b925b148d05b6da4f4301310c293
refs/remotes/origin/master: bdbe53a3a74ac1a75849c044302cf32ad83ebbf1
merge base: f2fdd032cf5ba84d026e57dcf831ac86dcdb6374
divergence (HEAD...origin/master): 275  6
```

The source worktree was pre-existing dirty: `bizpulse/ROADMAP.md` and `bizpulse/docs/operations/private-launch-cost-record.md` were modified, and numerous review, presentation, brainstorm, milestone, ZIP, and report artifacts were untracked. These files were neither changed nor cleaned.

Decision:

- Use immutable local `HEAD` `3af1c6b...` as the Stage 0 inspection baseline because it is the checked-out local master line and contains the formal entry examined in this task.
- Use stored `origin/master` only as a second immutable comparison point. It was not fetched and is not called current.
- Do not use any moving worktree/branch name, modification time, uncommitted source, milestone copy, assignment snapshot, or ZIP as authority.
- Stable identical blobs across both refs strengthen a candidate but do not replace target-side tests.

## 5. Formal entry and runtime reachability

At the selected commit:

```text
api/main.py:create_app()
  -> FastAPI application
  -> /, /login, protected /app, /real -> /app
  -> /assets static mount
  -> api/v1/router.py
  -> versioned routers

/app
  -> frontend/index.html
  -> /assets/app.mjs
  -> RealDataSource + feature effects
  -> assets/views.mjs + features/*
```

The six primary frontend navigation areas are Workspace, Overview, Sales & Ads, Inventory, Profit, and Briefing & Actions. `frontend/index.html` and the v1 aggregate router are identical across the two divergent refs. `api/main.py`, `app.mjs`, `views.mjs`, and `styles.css` differ and have later Course Demo history; they are adaptation sources only.

## 6. Migration authority

The selected source has two histories:

- SQLite compatibility migrations 1 through 27 in `src/migrations/versions.py`.
- PostgreSQL Alembic chain:

```text
0001
  -> 0002_product_opportunity_inbox
  -> 0003_action_inbox_v1
  -> 0004_identity_audit
  -> 0005_account_workspaces
  -> 0006_tenant_rls
  -> 0007_account_preferences
  -> 0008_targets_outcomes
  -> 0009_course_demo_workbook_roles
```

`0009_course_demo_workbook_roles` is a forward-only Course Demo overlay and is absent from stored `origin/master`. `0001_cloud_baseline` is monolithic and reflects the broader old product. NEWCaostone will not copy either history as its migration chain; the implementation plan defines a fresh PostgreSQL-only chain while allowing selective reuse of proved repository/transaction patterns.

## 7. Replacement and deletion checks

- The selected source commits for deterministic analyses, Blob, Opportunity, Briefing, Action Inbox, and Outcome Review are all ancestors of `3af1c6b...`.
- No deletion record was found on the selected baseline history for the inspected core service/calculator/storage/action paths.
- Analysis, opportunity/briefing, action, and Blob source groups are byte-identical across `HEAD` and stored `origin/master` except for separately recorded shell/import/auth overlays.
- Import preparation/commit, local migration versions, auth/Demo, and the main frontend shell do differ and therefore remain pending/adapt candidates.

## 8. Test evidence boundary

The source tree contains unit, repository, service, API, integration, frontend, PostgreSQL, storage/Azurite, security, and migration tests for the candidate modules. `CURRENT_STATUS.md` records exact historical test counts at exact feature commits and clearly separates green focused closures from non-green full-suite executions.

No CAPTSONE tests were run in this task because CAPTSONE must remain read-only and its tests can create databases, caches, processes, or storage artifacts. No dependency was installed. Historical test records are used only to qualify bounded reuse candidates; every adopted module must be executed in an isolated NEWCaostone target after plan approval.

## 9. Explicit exclusion results

- `_review_later/INVENTORY.md` is a tracked quarantine record and not source authority.
- Exact code search found no Ask BizPulse/AI Chat/Chat Box, new-product forecast, or approved Profit Bridge module in formal code/test paths.
- Exact code search found extensive Google Trends API/CSV references in routes, schema, demo seed, scoring, services, repositories, and tests. Those paths are rejected for NEWCaostone.
- Streamlit, SQLite-only compatibility paths, Course Demo-specific migration/scripts/infra, multi-tenant product surfaces, live market adapters, old user-key UX, private validators, and historic Azure/Gate C evidence are not wholesale reuse sources.

## 10. Commands executed and observed result classes

The audit used only read-only source commands in CAPTSONE: `git status`, `git rev-parse`, `git merge-base`, `git rev-list`, `git branch -vv`, `git worktree list`, `git log`, `git ls-files`, `git ls-tree`, `git show`, `git grep`, `git diff`, and `rg` over `git show` output.

NEWCaostone verification used `find`, `shasum`, `rg`, `git init`, `git status`, `git config --get`, and exact `.DS_Store` removal. No network command, test runner, build, database, application server, cloud CLI, or provider SDK was invoked.

Final post-write evidence:

- v0.1.0 SHA-256 stayed `2c1f684a8800fc4354769302b4b3467c93760d30219c0d08c66d09557a0e5105`; approved v0.2.0 SHA-256 is `584bac53383e40930251e332affb051385fd3b86876cf9eae25e37d56f91c0f5` and its line count stayed 1,271.
- No NEWCaostone file exceeded 10 MiB; sensitive filename and high-signal private-key/AWS/OpenAI/GitHub-token content scans returned no match.
- Scoped `git diff --cached --check` was clean for every task-created/modified file. The all-files check reports only the untouched v0.1.0 design's pre-existing final blank line, which was preserved rather than reformatted.
- The plan contains exactly Task 1 through Task 15 and no deferred-fill or external-value command placeholder.
- CAPTSONE refs remained `3af1c6b...`, `bdbe53a...`, and merge base `f2fdd03...`, with divergence `275/6`; its tracked status remained only the two pre-existing modified files and its untracked count was 76.
- The exact staged NEWCaostone status and no-commit/no-identity limitation are recorded in `CURRENT_STATUS.md` and `docs/handoffs/CURRENT_HANDOFF.md`.
