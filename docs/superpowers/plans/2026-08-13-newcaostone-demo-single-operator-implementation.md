# NEWCaostone Single-Operator Synthetic Azure Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public, repeatable, zero-real-data BizPulse Demo with one protected operator, anonymous viewer sessions, PostgreSQL, Azure Blob, deterministic analytics, new-product forecasting, Profit Bridge, evidence-constrained Ask BizPulse, complete human-controlled action cards, and an accepted Azure URL.

**Architecture:** Implement a FastAPI modular monolith in `NEWCaostone/bizpulse`, with a native HTML/CSS/ES-module frontend and six primary navigation areas. PostgreSQL is the only authority for durable state; Azure Blob stores versioned objects and exports. Deterministic services own every number; the OpenAI layer only plans against a closed tool catalog and explains server-produced structured evidence.

**Tech Stack:** Python 3.12; FastAPI 0.138.2; Uvicorn 0.49.0; SQLAlchemy Core 2.0.51; Alembic 1.18.5; psycopg 3.3.4; PostgreSQL 17; Azure Blob SDK 12.30.0; OpenAI Python SDK 2.52.0 Responses API; argon2-cffi 25.1.0; pandas 3.0.3; openpyxl 3.1.5; XlsxWriter 3.2.9; native browser ES modules; Node built-in test runner; pytest 9.1.1; Ruff 0.15.20; Azurite 3.36.0.

## Global Constraints

- Work only in `/Users/maxli/Desktop/NEWCaostone`. `/Users/maxli/Desktop/CAPTSONE` remains read-only.
- Preserve both existing design files. Do not delete, move, rename, overwrite, or regenerate approved `v0.2.0`.
- The design is approved; this plan must be approved before Task 1 functionality is implemented.
- Use only fixed-seed or hand-authored pure synthetic data. Do not use real data or any transformed, anonymized, aggregated, truncated, shuffled, or redacted derivative of real data.
- Do not import, call, scrape, automate, or display Google Trends or any other live online market data. Do not copy the old market-source adapters.
- Keep exactly one protected operator and one Demo workspace. Do not add registration, invitations, teams, billing, or customer multi-tenancy.
- Anonymous viewers cannot upload, publish, or modify shared data. Their Chat and simulated actions remain isolated to an opaque server-side session.
- Viewer session idle TTL is 30 minutes; absolute TTL is 2 hours; the data version is fixed when the session starts; unexpired sessions recover from PostgreSQL after restart.
- PostgreSQL is the hosted system of record. There is no hosted SQLite, in-memory, local-storage, or local-file persistence fallback.
- Azure Blob stores temporary uploads, immutable normalized artifacts/evidence, and expiring exports. Database metadata owns every valid object reference.
- The product runtime model is exactly `gpt-5.4-mini-2026-03-17` with `reasoning.effort: low`, set server-side. The browser cannot choose a model or provide a Key.
- Use the Responses API with structured outputs. Do not enable Web Search, File Search, Code Interpreter, MCP, hosted shell, or any provider tool.
- OpenAI receives no raw file, database credential, schema discovery, SQL, arbitrary row dump, real identifier, or cross-session state. The model never creates or executes SQL.
- Free-text Chat input is at most 2,000 characters; output is at most 1,200 tokens; only one AI request per session is in flight; model context includes at most the latest four safe turn summaries.
- A free-text question may use at most one planning call and one answer call; a recommended question uses a server-owned plan and skips the planning call. No automatic provider retry is allowed.
- The whitelist QueryTool result limits are 25 aggregate facts, 20 ranked items, 10 evidence aliases, two comparison periods, and a five-second read-only PostgreSQL transaction timeout.
- AI text cannot change numbers, units, evidence states, scopes, versions, or action quantities. Unknown, missing, duplicate, or invented `fact_ref` values fail closed.
- Action state remains `new -> reviewed -> approved|dismissed`. Adjustment creates an immutable reviewed revision. Export and outcome review are independent and never mean external execution or completion.
- No route writes to Shopee, UpSeller, advertising, purchasing, or any other external business system.
- Public and operator pages must show `Synthetic Demo Data`, `Demo-only`, and `Non-Production` boundaries.
- Preserve the evidence ladder: Designed, Implemented, Locally verified, CI verified, Deployed, Hosted verified, Azure Demo accepted. Never collapse one state into another.
- No GitHub push, remote creation, PR, Azure mutation, DNS, paid provider call, secret read/write, destructive cleanup, or permanent deletion occurs without its exact later authorization gate.

The fixed runtime model/snapshot, low reasoning support, Responses endpoint, function calling, and structured outputs are confirmed by the [official OpenAI GPT-5.4 mini documentation](https://developers.openai.com/api/docs/models/gpt-5.4-mini). This plan deliberately disables all model-hosted tools even though the model supports them.

---

## Authority and execution boundary

- Approved design: `docs/superpowers/specs/2026-08-13-newcaostone-demo-single-operator-design-v0.2.0.md`.
- Reuse authority: `REUSE_LEDGER.md`.
- CAPTSONE inspection baseline: `3af1c6bc20e9b925b148d05b6da4f4301310c293`.
- Copy only a ledger candidate's exact files after recording source blob IDs. If a time box expires, implement the target contract from scratch.
- Create an isolated implementation worktree after this plan is approved and the initial repository checkpoint exists. Do not create a worktree before the repository has a commit.
- Every task ends in a local commit and independently testable deliverable. External publication remains a separate gate.

## Target file map

```text
bizpulse/
  requirements.txt
  requirements-dev.txt
  package.json
  Dockerfile
  alembic.ini
  api/
    main.py
    container.py
    errors.py
    dependencies/{operator.py,session.py,csrf.py}
    routers/{health.py,operator_auth.py,demo_sessions.py,public_release.py}
    v1/router.py
    v1/routers/{imports.py,datasets.py,analyses.py,forecasts.py,profit_bridge.py,actions.py,ai_chat.py}
    v1/schemas/{common.py,imports.py,datasets.py,analyses.py,forecasts.py,profit_bridge.py,actions.py,ai_chat.py}
  src/
    config.py
    db/{engine.py,schema.py,unit_of_work.py,readiness.py}
    repositories/{operators.py,sessions.py,imports.py,datasets.py,analyses.py,forecasts.py,profit_bridges.py,actions.py,ai_chat.py,storage_objects.py}
    services/{operator_auth_service.py,demo_session_service.py,import_service.py,dataset_service.py,analysis_service.py,forecast_service.py,profit_bridge_service.py,action_service.py,ai_chat_service.py,public_release_service.py}
    storage/{protocol.py,azure_blob_workflow_storage.py,postgres_entry_locks.py,keys.py,lifecycle.py}
    synthetic/{generator.py,contracts.py,manifest.py,seed.py}
    adapters/{protocol.py,registry.py,upseller_excel.py,shopee_advertising_csv.py}
    analysis/{sales_ads_calculator.py,inventory_risk_calculator.py,fifo_cost_aging_calculator.py,operating_profit_calculator.py,replenishment_calculator.py,evidence.py}
    forecast/{contracts.py,analogs.py,new_product.py,backtest.py}
    profit/{contracts.py,bridge.py}
    actions/{contracts.py,state_machine.py,exports.py}
    ai/{contracts.py,query_catalog.py,query_executor.py,openai_gateway.py,answer_merge.py,prompts.py}
  frontend/
    welcome.html
    login.html
    index.html
    assets/{app.mjs,state.mjs,views.mjs,styles.css,welcome.mjs,welcome.css,login.mjs}
    assets/core/{api-client.mjs,auth-session.mjs,runtime-session.mjs,evidence-drawer.mjs}
    assets/data-sources/{public.mjs,operator.mjs}
    assets/features/{workspace,overview,analysis,inventory,profit,forecast,action-inbox,ask-bizpulse}/
    assets/i18n/catalog.mjs
  alembic/
    env.py
    script.py.mako
    versions/{0001_demo_foundation.py,0002_import_versions.py,0003_analysis_evidence.py,0004_forecast_profit.py,0005_actions.py,0006_ai_chat.py,0007_chat_session_fences.py,0008_ai_budget_ledger.py}
  scripts/{generate_synthetic_demo.py,seed_demo.py,maintain_storage.py,maintain_sessions.py,verify_no_prohibited_sources.py,verify_release.py,create_release_manifest.py}
  infra/{main.bicep,modules/app.bicep,modules/postgres.bicep,modules/storage.bicep,modules/monitoring.bicep,environments/demo.bicepparam}
  tests/{unit,api,repositories,services,integration,postgres,storage,frontend,security,acceptance}/
  tests/fixtures/synthetic/v1/{manifest.json,*.csv,*.xlsx}
```

Every Python package directory also gets `__init__.py`. The plan omits those mechanical files from later task lists unless an import boundary is the tested behavior.

## Fresh PostgreSQL migration chain

| Revision | Tables and constraints owned |
|---|---|
| `0001_demo_foundation` | `workspaces`, `operator_accounts`, `operator_sessions`, `demo_sessions`, `idempotency_receipts`; one active operator per workspace; token hashes only; 30-minute idle and 2-hour absolute timestamps; no API Key columns. |
| `0002_import_versions` | `storage_objects`, `import_workflows`, `upload_records`, `dataset_series`, `dataset_versions`, `dataset_artifacts`, `public_releases`; immutable version rows; one public pointer per workspace; object state `staging|available|quarantined|deleted`; no raw rows. |
| `0003_analysis_evidence` | `analysis_runs`, `analysis_dependencies`, `analysis_artifacts`, `evidence_items`; immutable completed results, typed analysis kind, algorithm version, input hash, evidence state, and prior-period links. |
| `0004_forecast_profit` | `new_product_forecasts`, `forecast_analogs`, `forecast_scenarios`, `profit_bridges`, `profit_bridge_items`; low/base/high and 7/30/90 constraints; bridge items reconcile to total delta with explicit residual. |
| `0005_actions` | `action_cards`, `action_card_revisions`, `action_decisions`, `action_exports`, `action_outcomes`, `demo_action_overlays`; state constraints and append-only revision/decision/output records. |
| `0006_ai_chat` | `ai_chat_turns`, `ai_chat_tool_runs`, `ai_chat_evidence`, `ai_chat_attempts`, `ai_chat_saved_records`; no SQL, credentials, raw provider bodies, or unrestricted row payloads. |
| `0007_chat_session_fences` | Append-only upgrade for per-session Chat epochs, causal turn ordering, and immutable sequence guards; committed `0006_ai_chat` remains unchanged. |
| `0008_ai_budget_ledger` | Append-only durable provider-attempt budget authority that survives ephemeral Chat/session cleanup and prevents daily/monthly budget reset. |

Downgrades are used only for fresh local migration tests before a revision is accepted. Release rollback never runs `alembic downgrade`; it restores a compatible app digest and, when needed, follows a separately approved database restore plan.

## Stage and test budget

| Stage | Tasks | Focused budget | Composite budget | Full budget | Browser/hosted gate |
|---|---:|---:|---:|---:|---|
| Foundation | 1-3 | Per RED/GREEN | 1 foundation composite | 0 | Local 1280/820/390 shell + auth/session |
| Data backbone | 4-6 | Per RED/GREEN | 1 PostgreSQL/Blob/import composite | 1 Python | Operator import + restart readback |
| Deterministic product | 7-10 | Per RED/GREEN | 1 analytics/frontend composite per vertical | 1 Python + 1 frontend | Public/operator analysis, forecast, bridge |
| Decision layer | 11-13 | Per RED/GREEN | 1 action/chat/security composite | 1 Python + 1 frontend | Chat, evidence, action draft, isolation |
| Release | 14-15 | Focused release checks | 1 local release composite | No duplicate full run unless release diff changes app behavior | Exact-15 local capacity, then authorized Azure hosted acceptance |

If a full command is non-green, diagnose and close exact affected nodes with focused tests. Do not relabel the consumed full run green unless a second full run is explicitly justified and approved under the current Stage budget.

## Task 1: Project scaffold, dependency boundary, and formal application shell

**Files:**

- Create: `bizpulse/requirements.txt`
- Create: `bizpulse/requirements-dev.txt`
- Create: `bizpulse/package.json`
- Create: `bizpulse/api/main.py`
- Create: `bizpulse/api/container.py`
- Create: `bizpulse/api/errors.py`
- Create: `bizpulse/api/routers/health.py`
- Create: `bizpulse/api/v1/router.py`
- Create: `bizpulse/src/config.py`
- Create: `bizpulse/frontend/welcome.html`
- Create: `bizpulse/frontend/login.html`
- Create: `bizpulse/frontend/index.html`
- Create: `bizpulse/frontend/assets/{app.mjs,state.mjs,views.mjs,styles.css,welcome.mjs,welcome.css,login.mjs}`
- Test: `bizpulse/tests/unit/test_config.py`
- Test: `bizpulse/tests/api/test_application_shell.py`
- Test: `bizpulse/tests/frontend/shell.test.mjs`

**Interfaces:**

- Produces `BizPulseSettings.from_env() -> BizPulseSettings` with runtime `local|cloud`, database URL, Blob endpoint/container, operator password hash, cookie/security settings, OpenAI model fixed to the approved snapshot, and budget switches.
- Produces `create_app(settings: BizPulseSettings, container: ApiContainer | None = None) -> FastAPI`.
- Produces `/health/live`, `/health/ready`, `/`, `/login`, protected `/app`, `/real -> /app`, `/assets`, and `/api/v1` mount points.
- Does not yet implement login, data, storage, AI, or business routes.

- [x] **Step 1: Create pinned dependency manifests and the local toolchain**

`requirements.txt` contains exactly the runtime packages and versions in the Tech Stack, including `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `azure-storage-blob`, `openai`, `argon2-cffi`, `pandas`, `openpyxl`, and `XlsxWriter`. `requirements-dev.txt` contains `pytest==9.1.1`, `ruff==0.15.20`, `httpx`, `testcontainers[postgres]`, and the project-owned test helpers at pinned versions. `package.json` is private, has no runtime browser dependency, and pins `azurite` to `3.36.0` under `devDependencies`.

Run: `cd /Users/maxli/Desktop/NEWCaostone/bizpulse && python3.12 -m venv .venv && .venv/bin/python -m pip install --require-hashes -r requirements.txt -r requirements-dev.txt && npm install --ignore-scripts`

Dependency lock/hash generation and any download are local engineering only after plan approval. Record package hashes in the two requirements files before the install command; do not use an unpinned transitive package or a global environment.

- [x] **Step 2: Write failing configuration and route tests**

```python
def test_model_is_fixed_and_cannot_be_overridden(monkeypatch):
    monkeypatch.setenv("BIZPULSE_OPENAI_MODEL", "forbidden-override")
    with pytest.raises(ConfigError, match="openai_model_must_equal_approved_snapshot"):
        BizPulseSettings.from_env()


def test_public_and_protected_shell_routes(app_client):
    assert app_client.get("/").status_code == 200
    assert app_client.get("/login").status_code == 200
    assert app_client.get("/app").status_code == 401
    assert app_client.get("/real", follow_redirects=False).status_code == 307
    assert app_client.get("/health/live").json() == {"status": "ok"}
```

- [x] **Step 3: Run the RED tests**

Run: `cd /Users/maxli/Desktop/NEWCaostone/bizpulse && .venv/bin/python -m pytest tests/unit/test_config.py tests/api/test_application_shell.py -q`

Expected: collection/import failure because the application shell does not exist.

- [x] **Step 4: Implement the fixed configuration contract and minimal shell**

```python
APPROVED_OPENAI_MODEL = "gpt-5.4-mini-2026-03-17"
APPROVED_REASONING_EFFORT = "low"


@dataclass(frozen=True, slots=True)
class BizPulseSettings:
    runtime_environment: Literal["local", "cloud"]
    database_url: str
    blob_container: str
    openai_model: str = APPROVED_OPENAI_MODEL
    openai_reasoning_effort: str = APPROVED_REASONING_EFFORT
    session_idle_seconds: int = 1800
    session_absolute_seconds: int = 7200
    chat_input_char_limit: int = 2000
    chat_output_token_limit: int = 1200


def create_app(settings: BizPulseSettings, container: ApiContainer | None = None) -> FastAPI:
    application = FastAPI(title="BizPulse Synthetic Demo", lifespan=lifespan)
    application.mount("/assets", StaticFiles(directory=FRONTEND_ASSETS_DIR), name="assets")
    application.include_router(health_router)
    application.include_router(v1_router)
    return application
```

The route implementation reads the three checked-in HTML files, does not template environment values into HTML, and serves no CDN link or remote image/font.

- [x] **Step 5: Implement six-primary-nav HTML and static frontend contract**

`frontend/index.html` contains exactly `workspace`, `overview`, `sales`, `inventory`, `profit`, and `briefing` primary controls. `Ask BizPulse` is not a seventh control; it is registered later under `briefing`.

- [x] **Step 6: Run Python and Node GREEN checks**

Run: `.venv/bin/python -m pytest tests/unit/test_config.py tests/api/test_application_shell.py -q`

Expected: all tests pass.

Run: `node --test tests/frontend/shell.test.mjs`

Expected: six primary routes, local-only assets, bilingual catalog hooks, and no model/Key control all pass.

- [x] **Step 7: Run static checks and commit**

Run: `.venv/bin/python -m ruff check api src tests && .venv/bin/python -m compileall -q api src && git diff --check`

Commit: `git add bizpulse && git commit -m "feat: establish NEWCaostone application shell"`

**Completion definition:** a fresh local process can serve health/public/login routes; `/app` fails closed without auth; assets are local; no data/AI behavior exists.

**Risk and rollback:** risk is accidental copy of old Course Demo shell or CDN assets. Roll back to the pre-Task commit; no schema exists yet.

**Authorization gate:** dependency download/install is local engineering after plan approval. No remote Git, provider, or Azure action is included.

## Task 2: PostgreSQL foundation and fresh Alembic authority

**Files:**

- Create: `bizpulse/alembic.ini`
- Create: `bizpulse/alembic/env.py`
- Create: `bizpulse/alembic/script.py.mako`
- Create: `bizpulse/alembic/versions/0001_demo_foundation.py`
- Create: `bizpulse/src/db/{engine.py,schema.py,unit_of_work.py,readiness.py}`
- Create: `bizpulse/src/repositories/{operators.py,sessions.py}`
- Create: `bizpulse/scripts/test_postgres.py`
- Test: `bizpulse/tests/postgres/test_migration_chain.py`
- Test: `bizpulse/tests/repositories/test_foundation_repositories.py`
- Test: `bizpulse/tests/unit/test_database_config.py`

**Interfaces:**

- Produces `create_postgres_engine(database_url: str, *, null_pool: bool = False) -> Engine`.
- Produces `PostgresUnitOfWork(engine: Engine)` with explicit `begin/commit/rollback` ownership.
- Produces `readiness(engine) -> DatabaseReadiness(revision, writable, latency_ms)`; readiness exposes no connection value.
- Produces repositories for one workspace, one operator, opaque operator sessions, opaque viewer sessions, and idempotency receipts.

- [x] **Step 1: Write failing migration and transaction tests**

```python
def test_empty_database_upgrades_to_exact_foundation_head(postgres_url):
    run_alembic(postgres_url, "upgrade", "head")
    assert current_revision(postgres_url) == "0001_demo_foundation"
    assert table_names(postgres_url) == {
        "alembic_version", "workspaces", "operator_accounts",
        "operator_sessions", "demo_sessions", "idempotency_receipts",
    }


def test_unit_of_work_rolls_back_all_rows(engine):
    with pytest.raises(RuntimeError):
        with PostgresUnitOfWork(engine) as uow:
            uow.execute(insert(workspaces).values(id="synthetic-demo"))
            raise RuntimeError("injected")
    assert count_rows(engine, "workspaces") == 0
```

- [x] **Step 2: Run the migration RED test**

Run: `.venv/bin/python scripts/test_postgres.py tests/postgres/test_migration_chain.py tests/repositories/test_foundation_repositories.py -q`

Expected: fail because Alembic/schema/repositories are missing.

- [x] **Step 3: Implement `0001_demo_foundation` with exact safety constraints**

```python
revision = "0001_demo_foundation"
down_revision = None


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind = 'single_operator_demo'", name="ck_workspaces_kind"),
    )
```

Create the remaining tables in this revision with these exact columns and constraints:

| Table | Required columns | Constraints |
|---|---|---|
| `operator_accounts` | `id UUID`, `workspace_id TEXT`, `login_name TEXT`, `password_hash TEXT`, `status TEXT`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ` | PK `id`; FK workspace; unique `(workspace_id, login_name)`; one partial unique active row per workspace; status in `active|disabled`; no raw password column. |
| `operator_sessions` | `id UUID`, `workspace_id TEXT`, `operator_id UUID`, `token_hash BYTEA`, `csrf_hash BYTEA`, `created_at TIMESTAMPTZ`, `last_seen_at TIMESTAMPTZ`, `idle_expires_at TIMESTAMPTZ`, `absolute_expires_at TIMESTAMPTZ`, `revoked_at TIMESTAMPTZ NULL` | PK `id`; workspace/operator FKs; unique `token_hash`; idle expiry at or before absolute expiry; no raw token column. |
| `demo_sessions` | `id UUID`, `workspace_id TEXT`, `token_hash BYTEA`, `csrf_hash BYTEA`, `source_address_hash BYTEA`, `dataset_version_id UUID NULL`, `status TEXT`, `created_at TIMESTAMPTZ`, `last_seen_at TIMESTAMPTZ`, `idle_expires_at TIMESTAMPTZ`, `absolute_expires_at TIMESTAMPTZ`, `ended_at TIMESTAMPTZ NULL` | PK `id`; workspace FK; unique `token_hash`; status in `active|ended|expired`; idle expiry at or before absolute expiry; the dataset FK is added by `0002` after the target table exists. |
| `idempotency_receipts` | `id UUID`, `scope_type TEXT`, `scope_id TEXT`, `operation TEXT`, `key_hash BYTEA`, `request_hash BYTEA`, `response_status INTEGER`, `response_body_hash BYTEA`, `outcome TEXT`, `created_at TIMESTAMPTZ`, `expires_at TIMESTAMPTZ` | PK `id`; unique `(scope_type, scope_id, operation, key_hash)`; outcome in `in_progress|succeeded|failed`; response status between 100 and 599 when present; no raw key/request/response body column. |

- [x] **Step 4: Implement engine, unit-of-work, readiness, and repositories**

All SQL uses SQLAlchemy expressions or bound parameters. No model text or request field becomes an identifier. Cloud runtime rejects non-PostgreSQL URLs. Repository projections never return token, CSRF, password, connection, or idempotency hashes.

- [x] **Step 5: Run GREEN, offline SQL, and restart checks**

Run: `.venv/bin/python scripts/test_postgres.py tests/postgres/test_migration_chain.py tests/repositories/test_foundation_repositories.py tests/unit/test_database_config.py -q`

Expected: upgrade, transaction rollback, repository scope, expiry, and restart tests pass.

Run: `BIZPULSE_DATABASE_URL=postgresql+psycopg://invalid alembic upgrade head --sql > .tmp/0001.sql && rg -n "operator_accounts|demo_sessions|idempotency_receipts" .tmp/0001.sql`

Expected: offline SQL contains all exact tables and no secret value; `.tmp/` remains ignored and is removed after review.

- [x] **Step 6: Commit**

Commit: `git add bizpulse/alembic.ini bizpulse/alembic bizpulse/src/db bizpulse/src/repositories bizpulse/scripts/test_postgres.py bizpulse/tests && git commit -m "feat: add PostgreSQL demo foundation"`

**Completion definition:** empty PostgreSQL upgrades to exact head; transactions roll back atomically; cloud mode cannot use SQLite; no credential value reaches projections/logs.

**Risk and rollback:** highest risk is schema overreach copied from the old 55+ table baseline. Roll back the Task commit and drop only the disposable local test database; no user database is touched.

## Task 3: Operator authentication, CSRF, and viewer session lifecycle

**Files:**

- Create: `bizpulse/src/services/{operator_auth_service.py,demo_session_service.py}`
- Create: `bizpulse/api/dependencies/{operator.py,session.py,csrf.py}`
- Create: `bizpulse/api/routers/{operator_auth.py,demo_sessions.py}`
- Modify: `bizpulse/api/main.py`
- Modify: `bizpulse/api/container.py`
- Modify: `bizpulse/frontend/login.html`
- Modify: `bizpulse/frontend/assets/login.mjs`
- Test: `bizpulse/tests/security/test_auth_csrf_cookies.py`
- Test: `bizpulse/tests/api/test_operator_auth.py`
- Test: `bizpulse/tests/api/test_demo_sessions.py`
- Test: `bizpulse/tests/services/test_demo_session_service.py`
- Test: `bizpulse/tests/frontend/login.test.mjs`

**Interfaces:**

- `OperatorAuthService.login(login_name: str, password: SecretStr, request_meta: RequestMeta) -> IssuedSession`.
- `DemoSessionService.create(source_address_hash: str, now: datetime) -> IssuedSession`.
- `resolve_operator(request) -> OperatorPrincipal`; `resolve_demo_session(request) -> DemoPrincipal`.
- Cookies: `bp_operator_session` and `bp_demo_session`, `HttpOnly`, `Secure` in cloud, `SameSite=Lax`, `Path=/`; CSRF token is returned separately and submitted via `X-CSRF-Token`.

- [x] **Step 1: Write failing auth/session tests**

```python
def test_demo_session_is_opaque_persisted_and_expires(client, clock):
    response = client.post("/api/demo/sessions", headers={"Origin": "https://demo.test"})
    assert response.status_code == 201
    assert "HttpOnly" in response.headers["set-cookie"]
    principal = resolve_cookie_in_fresh_app(response.cookies)
    assert principal.idle_expires_at == clock.now + timedelta(minutes=30)
    assert principal.absolute_expires_at == clock.now + timedelta(hours=2)


def test_mutation_rejects_missing_csrf(authenticated_client):
    assert authenticated_client.post("/api/v1/imports").status_code == 403
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/security/test_auth_csrf_cookies.py tests/api/test_operator_auth.py tests/api/test_demo_sessions.py tests/services/test_demo_session_service.py -q`

Expected: missing services/routes.

- [x] **Step 3: Implement server-only credential verification and token hashing**

Use `argon2-cffi` password verification. Generate 32-byte session and CSRF tokens with `secrets.token_urlsafe`; store only HMAC-SHA256 hashes using a server-only session-pepper setting. Compare hashes with `hmac.compare_digest`. Login responses and logs never include the password or stored hash.

- [x] **Step 4: Implement Origin/CSRF and session expiry**

All state-changing operator and viewer routes require an allowed same-origin value and matching CSRF header. Reads may extend idle expiry but never absolute expiry. Logout/End Session revokes immediately; maintenance marks expired sessions and removes ephemeral Chat/action rows after later migrations exist.

- [x] **Step 5: Run GREEN, restart, and frontend checks**

Run: `.venv/bin/python scripts/test_postgres.py tests/security/test_auth_csrf_cookies.py tests/api/test_operator_auth.py tests/api/test_demo_sessions.py tests/services/test_demo_session_service.py -q`

Run: `node --test tests/frontend/login.test.mjs`

Expected: authentication, generic failure responses, rate limiting, CSRF, cookie flags, restart recovery, expiry, and no registration path pass.

- [x] **Step 6: Commit**

Commit: `git add bizpulse && git commit -m "feat: add single-operator and viewer sessions"`

**Completion definition:** the operator can authenticate without exposing credentials; viewer sessions are isolated, persisted, resumable, and time-bounded; public writes fail without CSRF.

**Risk and rollback:** auth mistakes can expose protected routes. Roll back the Task commit and delete only disposable test-session rows. No real credential or external identity is configured.

## Task 4: Azure Blob protocol, object ledger, and temporary lifecycle

**Files:**

- Create: `bizpulse/alembic/versions/0002_import_versions.py`
- Create: `bizpulse/src/storage/{protocol.py,azure_blob_workflow_storage.py,postgres_entry_locks.py,keys.py,lifecycle.py}`
- Create: `bizpulse/src/repositories/{storage_objects.py,imports.py,datasets.py}`
- Create: `bizpulse/scripts/maintain_storage.py`
- Modify: `bizpulse/src/db/schema.py`
- Modify: `bizpulse/api/container.py`
- Test: `bizpulse/tests/storage/test_azure_blob_workflow_storage.py`
- Test: `bizpulse/tests/storage/test_postgres_entry_locks.py`
- Test: `bizpulse/tests/services/test_storage_lifecycle.py`
- Test: `bizpulse/tests/postgres/test_0002_import_versions.py`

**Interfaces:**

- `WorkflowStorage.put_staging(stream, *, max_bytes, media_type) -> StagedObject`.
- `WorkflowStorage.promote(staged_key, final_key, expected_sha256) -> AvailableObject`.
- `WorkflowStorage.open_verified(key, expected_sha256, max_bytes) -> BinaryIO`.
- `StorageLifecycle.finalize_success/finalize_failure/expire/orphan_inventory` update database and Blob with database authority and explicit object states.

- [x] **Step 1: Write failing storage/migration tests**

```python
def test_blob_success_is_not_publishable_before_database_commit(storage, uow):
    staged = storage.put_staging(BytesIO(b"synthetic"), max_bytes=64, media_type="text/csv")
    with pytest.raises(InjectedCommitFailure):
        finalize_with_injected_commit_failure(uow, storage, staged)
    assert storage.exists(staged.key)
    assert repository.find_available(staged.sha256) is None


def test_cloud_storage_never_falls_back_to_disk(cloud_settings):
    with pytest.raises(StorageUnavailable, match="blob_unavailable"):
        build_storage(cloud_settings, failing_blob_client())
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/python scripts/test_postgres.py tests/postgres/test_0002_import_versions.py tests/storage/test_postgres_entry_locks.py -q`

Run: `node --test tests/storage/test_azure_blob_workflow_storage.py` is not used; Blob tests remain Python and run through pytest.

Expected: missing revision/storage implementation.

- [x] **Step 3: Implement `0002_import_versions`**

Create exact tables listed in the migration map. `storage_objects.object_key` is unique; `dataset_versions` and `dataset_artifacts` are immutable; `public_releases` has one active pointer per workspace and never overwrites history. Add the now-valid `demo_sessions.dataset_version_id -> dataset_versions.id` FK.

- [x] **Step 4: Selectively adapt the proved Blob/lock seams**

Record CAPTSONE source blob IDs in `REUSE_LEDGER.md` before copy. Keep bounded streaming, transfer concurrency 1, conditional create/replace/delete, ETag reads, fixed safe errors, deterministic lock ordering, one deadline, and reverse partial release. Replace old owner namespaces with `workspace/session/version/run` key builders.

- [x] **Step 5: Implement lifecycle convergence**

Temporary uploads are deleted after success, rejection, failure, cancellation, or expiry. Immutable normalized/evidence objects delete only through a later authorized retention flow; the current maintenance command inventories and quarantines orphans but performs no permanent deletion.

- [x] **Step 6: Run GREEN with PostgreSQL and Azurite**

Run: `.venv/bin/python scripts/test_postgres.py tests/postgres/test_0002_import_versions.py tests/storage/test_postgres_entry_locks.py tests/services/test_storage_lifecycle.py -q`

Run: `./node_modules/.bin/azurite --silent --location .tmp/azurite --blobHost 127.0.0.1 --blobPort 10000` in a controlled session, then `.venv/bin/python -m pytest tests/storage/test_azure_blob_workflow_storage.py -q`, then stop the exact process and remove `.tmp/azurite`.

Expected: ETag, streaming, compensation, lifecycle, orphan inventory, no-fallback, and teardown checks pass.

- [x] **Step 7: Commit**

Commit: `git add bizpulse REUSE_LEDGER.md && git commit -m "feat: add PostgreSQL and Blob object lifecycle"`

**Completion definition:** every object has a PostgreSQL ledger state; no staging object becomes public before transaction success; cloud storage fails closed; Azurite and PostgreSQL tests leave no listener/process/root residue.

**Risk and rollback:** cross-system partial failure. Roll back application code to the Task 3 commit; local test database/storage are disposable. Hosted migration is not authorized.

## Task 5: Versioned pure-synthetic generator, manifest, and seed contract

**Files:**

- Create: `bizpulse/src/synthetic/{contracts.py,generator.py,manifest.py,seed.py}`
- Create: `bizpulse/scripts/{generate_synthetic_demo.py,seed_demo.py,verify_no_prohibited_sources.py}`
- Create: `bizpulse/tests/fixtures/synthetic/v1/manifest.json`
- Create: generated `bizpulse/tests/fixtures/synthetic/v1/*.csv` and `*.xlsx`
- Test: `bizpulse/tests/unit/test_synthetic_generator.py`
- Test: `bizpulse/tests/security/test_synthetic_source_boundary.py`
- Test: `bizpulse/tests/integration/test_synthetic_seed.py`

**Interfaces:**

- `generate_demo(seed: int = 20260813, schema_version: str = "synthetic.v1") -> SyntheticBundle`.
- `SyntheticManifest` records generator commit/version, seed, file paths, SHA-256, row counts, date range, currency, required scenario IDs, and `source_classification="pure_synthetic"`.
- `seed_demo(bundle, uow, storage) -> SeedResult` is idempotent by manifest hash and never contacts a network.

- [x] **Step 1: Write failing deterministic/privacy tests**

```python
def test_same_seed_produces_same_manifest_bytes(tmp_path):
    first = generate_and_write(tmp_path / "a", seed=20260813)
    second = generate_and_write(tmp_path / "b", seed=20260813)
    assert first.manifest_bytes == second.manifest_bytes
    assert first.file_hashes == second.file_hashes


def test_bundle_contains_named_acceptance_scenarios(bundle):
    assert set(bundle.scenario_ids) >= {
        "sales_ads_growth", "inventory_stockout", "fifo_aging",
        "profit_decline_ad_spend", "new_product_low_base_high",
        "profit_bridge_residual", "chat_clarification", "action_outcome",
    }
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/unit/test_synthetic_generator.py tests/security/test_synthetic_source_boundary.py -q`

Expected: missing generator/fixtures.

- [x] **Step 3: Implement deterministic synthetic entities**

Use obvious namespaces such as `SYNTH-STORE-01`, `SYNTH-SKU-001`, and `SYNTH-ORDER-000001`; Brazil currency is BRL; every date/value is generated from code-owned distributions and explicit scenario overrides. Generate sales, advertising, inventory snapshots/movements, receipt lots, outbound events, expenses, platform fees, fulfillment, refunds, FX assumptions, forecasts, and action outcomes.

- [x] **Step 4: Implement source-boundary scanner**

The scanner rejects email/phone/address/credential/connection-string patterns, unapproved identifiers, forbidden source labels (`google_trends`, `mercado_live`, `real`, `private`), external URLs, and any file not declared in the manifest. It reports file/field/rule only, never the matched value.

- [x] **Step 5: Generate, verify, and seed twice**

Run: `.venv/bin/python scripts/generate_synthetic_demo.py --seed 20260813 --output tests/fixtures/synthetic/v1`

Run: `.venv/bin/python scripts/verify_no_prohibited_sources.py tests/fixtures/synthetic/v1`

Run: `.venv/bin/python scripts/test_postgres.py tests/integration/test_synthetic_seed.py -q`

Expected: two seeds return the same release/version IDs, all hashes match, no network is called, and PostgreSQL/Blob counts are unchanged on replay.

- [x] **Step 6: Commit**

Commit: `git add bizpulse/src/synthetic bizpulse/scripts bizpulse/tests && git commit -m "feat: add deterministic synthetic demo data"`

**Completion definition:** a clean checkout can regenerate byte-identical declared fixtures; all accepted product scenarios exist; no real-derived or online source is present.

**Risk and rollback:** plausible-looking synthetic data can be mistaken for sourced facts. Keep the namespace/banner/manifest proof; roll back the Task commit and regenerate only from the approved generator, never from old datasets.

## Task 6: Operator import, recognition, mapping, standardization, and atomic versions

**Files:**

- Create: `bizpulse/src/adapters/{protocol.py,registry.py,upseller_excel.py,shopee_advertising_csv.py}`
- Create: `bizpulse/src/services/{import_service.py,dataset_service.py}`
- Modify: `bizpulse/src/repositories/{imports.py,datasets.py,storage_objects.py}`
- Create: `bizpulse/api/v1/routers/{imports.py,datasets.py}`
- Create: `bizpulse/api/v1/schemas/{imports.py,datasets.py}`
- Modify: `bizpulse/api/v1/router.py`
- Modify: `bizpulse/api/container.py`
- Create: `bizpulse/frontend/assets/features/workspace/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Test: `bizpulse/tests/services/test_import_service.py`
- Test: `bizpulse/tests/services/test_dataset_service.py`
- Test: `bizpulse/tests/api/v1/test_imports.py`
- Test: `bizpulse/tests/integration/test_atomic_import_version.py`
- Test: `bizpulse/tests/frontend/workspace.test.mjs`
- Test: `bizpulse/tests/security/test_upload_boundary.py`

**Interfaces:**

- `POST /api/v1/import-workflows` creates an operator-owned workflow with `Idempotency-Key`.
- `POST /api/v1/import-workflows/{workflow_id}/uploads` accepts one bounded `.xlsx` or `.csv` per request and requires `Idempotency-Key`.
- `POST .../{upload_id}/recognition`, `PUT .../{upload_id}/mapping`, `POST .../{upload_id}/standardization`, `GET .../{upload_id}/preview`, `GET .../commit-plan`, and `POST .../commit` implement explicit revisions and exact replay.
- `ImportService.commit(workflow_id, expected_revision, idempotency_key) -> CommitResult` commits all active files or none and promotes immutable normalized artifacts only after the database transaction succeeds.

- [x] **Step 1: Time-box selective source proof before copy**

Inspect only the `P1` files in `REUSE_LEDGER.md`. Record each source blob ID and target file in the ledger. Stop at four hours; if the current baseline cannot pass the exact isolated import vertical, implement the interfaces above from scratch.

- [x] **Step 2: Write failing atomic/import-boundary tests**

```python
def test_two_file_commit_is_atomic(client, synthetic_workbook, synthetic_ads_csv):
    workflow = create_workflow(client)
    upload_and_prepare(client, workflow, synthetic_workbook)
    upload_and_prepare(client, workflow, synthetic_ads_csv, inject_invalid_mapping=True)
    response = commit(client, workflow)
    assert response.status_code == 409
    assert dataset_version_count(workflow) == 0
    assert current_series_pointer_count(workflow) == 0


def test_upload_with_pii_pattern_is_rejected_without_echo(client, workbook_with_email):
    response = upload(client, workbook_with_email)
    assert response.status_code == 422
    assert response.json()["code"] == "SYNTHETIC_SOURCE_BOUNDARY_FAILED"
    assert "@" not in response.text
```

- [x] **Step 3: Run RED**

Run: `.venv/bin/python scripts/test_postgres.py tests/services/test_import_service.py tests/services/test_dataset_service.py tests/api/v1/test_imports.py tests/integration/test_atomic_import_version.py tests/security/test_upload_boundary.py -q`

Expected: route/service failures.

- [x] **Step 4: Implement bounded adapters and revisioned workflow**

Adapters inspect content, not filename alone; cap workbook worksheets, rows, columns, cells, expanded ZIP bytes, wall time, and parser concurrency. Mapping produces a versioned JSON schema with only known canonical fields. Standardization outputs canonical UTF-8 JSON or Parquet only after validation; preview reads the exact candidate artifact that commit will use.

Supported first-release source roles are exact synthetic versions of UpSeller daily sales, product sales, product/inventory sales, inventory movement, receipt lots, outbound events, operating expenses, settlements, FX assumptions, replenishment policy, and Shopee advertising. Every adapter declares `adapter_id`, `adapter_version`, `canonical_schema`, size/shape limits, and required fields.

- [x] **Step 5: Implement atomic commit, replay, and original cleanup**

The commit transaction creates immutable `dataset_versions`, updates series current pointers only after all candidates are valid, writes object-reference metadata, and stores the idempotency receipt. Blob promotion uses staged-to-final conditional writes; a database failure leaves final objects unreferenced/unpublishable and schedules bounded cleanup. Exact request replay returns the original result; same key/different request returns `409 IDEMPOTENCY_CONFLICT`.

- [x] **Step 6: Implement operator Workspace UI**

The frontend owns browser `File` objects only in effects, never reducer state. It shows source confirmation, recognition, mapping, quality, preview, commit plan, version result, and safe failure states. Viewer sessions never receive the workspace routes or controls.

- [x] **Step 7: Run GREEN and restart replay**

Run: `.venv/bin/python scripts/test_postgres.py tests/services/test_import_service.py tests/services/test_dataset_service.py tests/api/v1/test_imports.py tests/integration/test_atomic_import_version.py tests/security/test_upload_boundary.py -q`

Run: `node --test tests/frontend/workspace.test.mjs`

Expected: atomicity, replay, CAS, duplicate detection, PII/key rejection, formula-injection defense, cleanup, restart restore, and operator-only UI pass.

- [x] **Step 8: Run the Data Backbone composite and commit**

Run: `.venv/bin/python scripts/test_postgres.py tests/postgres tests/storage tests/services/test_storage_lifecycle.py tests/integration/test_atomic_import_version.py -q`

Run: `.venv/bin/python -m pytest tests -q` once for the Stage's full Python budget.

Commit: `git add bizpulse REUSE_LEDGER.md && git commit -m "feat: add atomic synthetic import and versions"`

**Completion definition:** the operator can import declared pure-synthetic files through one atomic, replay-safe PostgreSQL/Blob version; originals follow the required lifecycle; viewers cannot upload.

**Risk and rollback:** partial versions and decompression abuse. Roll back the Task commit; migrate only disposable local databases back during migration testing. Never downgrade a retained release database.

## Task 7: Deterministic existing analytics, evidence, and immutable runs

**Files:**

- Create: `bizpulse/alembic/versions/0003_analysis_evidence.py`
- Create/adapt: `bizpulse/src/analysis/{sales_ads_calculator.py,inventory_risk_calculator.py,fifo_cost_aging_calculator.py,operating_profit_calculator.py,replenishment_calculator.py,evidence.py}`
- Create: `bizpulse/src/repositories/analyses.py`
- Create: `bizpulse/src/services/analysis_service.py`
- Create: `bizpulse/api/v1/routers/analyses.py`
- Create: `bizpulse/api/v1/schemas/analyses.py`
- Modify: `bizpulse/api/v1/router.py`
- Modify: `bizpulse/api/container.py`
- Test: `bizpulse/tests/unit/analysis/test_sales_ads.py`
- Test: `bizpulse/tests/unit/analysis/test_inventory.py`
- Test: `bizpulse/tests/unit/analysis/test_fifo.py`
- Test: `bizpulse/tests/unit/analysis/test_operating_profit.py`
- Test: `bizpulse/tests/unit/analysis/test_replenishment.py`
- Test: `bizpulse/tests/integration/test_analysis_vertical.py`
- Test: `bizpulse/tests/postgres/test_0003_analysis_evidence.py`

**Interfaces:**

- `AnalysisService.plan(kind, dataset_version_id, scope) -> AnalysisPlan`.
- `AnalysisService.run(plan, idempotency_key) -> AnalysisResult` for exact kinds `sales_ads`, `inventory_risk`, `fifo_cost_aging`, `operating_profit`, and `replenishment`.
- `GET /api/v1/analyses/{run_id}`, `/snapshot`, and `/evidence/{evidence_id}` return immutable, hash-verified projections.
- Every output includes `dataset_version_id`, `algorithm_version`, `input_hash`, coverage, evidence states, limitations, and currency/period/store scope.

- [x] **Step 1: Record selective source copies and write characterization tests**

For R1/R2, record source commit/blob IDs before copying. First run copied pure calculators against source-derived synthetic unit fixtures, then rewrite only the repository/service boundary. Characterization tests pin exact Decimal outputs, unavailable states, signature hashes, and evidence references.

- [x] **Step 2: Write failing migration/vertical tests**

```python
def test_missing_cost_is_unknown_not_zero(operating_profit_input):
    result = calculate_operating_profit(operating_profit_input.without("fulfillment_cost"))
    assert result.contribution_profit.value is None
    assert result.contribution_profit.evidence_state == "unknown"
    assert "fulfillment_cost_missing" in result.limitations


def test_same_input_reuses_exact_immutable_run(analysis_service, plan):
    first = analysis_service.run(plan, idempotency_key="one")
    second = analysis_service.run(plan, idempotency_key="two")
    assert second.run_id == first.run_id
    assert second.disposition == "reused"
```

- [x] **Step 3: Run RED/characterization**

Run: `.venv/bin/python -m pytest tests/unit/analysis -q`

Expected: copied characterization may pass; new service/migration integration remains RED.

- [x] **Step 4: Implement `0003_analysis_evidence` and service publication**

Create the exact tables in the migration map. A `completed` run has one immutable artifact hash; `running` rows become safely failed on restart; failed publication never replaces a prior success. Evidence items use `measured|derived|assumed|unknown`, stable aliases, formula/version/source references, and no internal object key.

- [x] **Step 5: Implement the five deterministic calculations**

- Sales/Ads: totals, AOV, ROAS, ACOS, SKU ranking, trends, anomalies, and explicit unavailable advertising/product comparisons.
- Inventory: current/projected cover, stockout/overstock risk, mapping/velocity evidence, and no guessed joins.
- FIFO/Cost Aging: lot allocation, landed/simple cost, 90/120-day aging, and partial-coverage warnings.
- Operating Profit: net revenue, COGS, platform, advertising, refund loss, fulfillment, tax if present, FX, other mapped costs, gross/contribution/operating layers, missing input not zero.
- Replenishment: existing-SKU low/base/high demand, quantity/timing/priority/cash availability and explicit insufficient-demand states; this is separate from Task 9 new-product forecast.

- [x] **Step 6: Run GREEN and persistence tests**

Run: `.venv/bin/python scripts/test_postgres.py tests/postgres/test_0003_analysis_evidence.py tests/unit/analysis tests/integration/test_analysis_vertical.py -q`

Expected: calculators, immutable publication, exact reuse, failure preservation, evidence, and restart recovery pass.

- [x] **Step 7: Commit**

Commit: `git add bizpulse REUSE_LEDGER.md && git commit -m "feat: add deterministic analysis evidence"`

**Completion definition:** one synthetic version produces all existing deterministic analytical runs; every number is traceable; missing input is never zeroed; no model is needed.

**Risk and rollback:** formula drift from selective reuse. Keep characterization tests and source blob entries. Roll back code to Task 6; retain `0003` on any non-disposable database and use an app version compatible with it.

## Task 8: Public release pointer, version-pinned sessions, and analytical frontend

**Files:**

- Create: `bizpulse/src/services/public_release_service.py`
- Modify: `bizpulse/src/repositories/datasets.py`
- Create: `bizpulse/api/routers/public_release.py`
- Modify: `bizpulse/api/routers/demo_sessions.py`
- Modify: `bizpulse/api/main.py`
- Create: `bizpulse/frontend/assets/core/{api-client.mjs,auth-session.mjs,runtime-session.mjs,evidence-drawer.mjs}`
- Create: `bizpulse/frontend/assets/data-sources/{public.mjs,operator.mjs}`
- Create: `bizpulse/frontend/assets/features/overview/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Create: `bizpulse/frontend/assets/features/analysis/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Create: `bizpulse/frontend/assets/features/inventory/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Create: `bizpulse/frontend/assets/features/profit/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Create: `bizpulse/frontend/assets/core/charts.mjs`
- Modify: `bizpulse/frontend/assets/{app.mjs,state.mjs,views.mjs,styles.css}`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Test: `bizpulse/tests/services/test_public_release_service.py`
- Test: `bizpulse/tests/api/test_public_release.py`
- Test: `bizpulse/tests/integration/test_session_version_pinning.py`
- Test: `bizpulse/tests/frontend/{runtime-session.test.mjs,analytics.test.mjs,evidence-drawer.test.mjs,charts.test.mjs}`

**Interfaces:**

- `PublicReleaseService.publish(dataset_version_id, expected_current_id, idempotency_key) -> ReleaseResult`.
- A new viewer session pins the current public dataset version; an existing session never follows a later publish.
- `PublicDataSource` receives scope only from its server session and has no upload/publish methods.
- `OperatorDataSource` exposes import/version/publish operations after operator auth.

- [x] **Step 1: Write failing publish/pinning tests**

```python
def test_new_release_does_not_change_existing_viewer_session(client, release_v1, release_v2):
    viewer = create_viewer(client)
    assert viewer.get("/api/v1/analyses/current").json()["dataset_version_id"] == release_v1
    operator_publish(client, release_v2)
    assert viewer.get("/api/v1/analyses/current").json()["dataset_version_id"] == release_v1
    assert create_viewer(client).get("/api/v1/analyses/current").json()["dataset_version_id"] == release_v2
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/python scripts/test_postgres.py tests/services/test_public_release_service.py tests/api/test_public_release.py tests/integration/test_session_version_pinning.py -q`

Expected: missing publish/session binding.

- [x] **Step 3: Implement release pointer and fixed viewer scope**

Only complete, pure-synthetic, quality-passed versions can publish. Publish inserts history and atomically changes the workspace pointer with CAS. Viewer session creation fails safely if no release exists; version deletion is not exposed.

- [x] **Step 4: Adapt frontend shell without mixing divergent old assets**

Use the approved six-nav structure. Copy only ledgered feature patterns; do not copy Course Demo bootstrapping. All requests use same-origin `ApiClient`; a failed Real/public request renders unavailable/error, never Demo numbers. Bundle icons as local inline SVG symbols.

- [x] **Step 5: Implement analytical charts**

`charts.mjs` renders accessible local SVG only: line charts for trends, sorted bars for comparisons/drivers, segmented bars or risk matrix for inventory. Each figure includes title, text summary, period, metric definition, data version, and evidence control. No decorative image is added.

- [x] **Step 6: Run GREEN and frontend composite**

Run: `.venv/bin/python scripts/test_postgres.py tests/services/test_public_release_service.py tests/api/test_public_release.py tests/integration/test_session_version_pinning.py -q`

Run: `node --test tests/frontend/runtime-session.test.mjs tests/frontend/analytics.test.mjs tests/frontend/evidence-drawer.test.mjs tests/frontend/charts.test.mjs`

Expected: publish CAS, old/new session pinning, role boundaries, no fallback, charts, evidence, bilingual labels, stale-request fencing, and 1280/820/390 layout contracts pass.

- [x] **Step 7: Local browser checkpoint and commit**

Run server: `.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000`

Browser checklist: public banner/version; Overview/Sales/Inventory/Profit reads; evidence drawer; operator login/import/version/publish; old viewer stays pinned; new viewer sees the new release; no external network/console error; 1280/820/390 no blocking overflow.

Commit: `git add bizpulse && git commit -m "feat: publish versioned analytical demo"`

**Completion definition:** viewers read a fixed public synthetic release across refresh/restart; operator publish is atomic; existing analytical pages and evidence work without AI.

**Risk and rollback:** session drift or public mutation. Roll back the application commit; atomically repoint public release to the prior valid dataset version through the operator service. Do not delete versions.

## Task 9: New-product 7/30/90-day deterministic forecast

**Files:**

- Create: `bizpulse/alembic/versions/0004_forecast_profit.py`
- Create: `bizpulse/src/forecast/{contracts.py,analogs.py,new_product.py,backtest.py}`
- Create: `bizpulse/src/repositories/forecasts.py`
- Create: `bizpulse/src/services/forecast_service.py`
- Create: `bizpulse/api/v1/routers/forecasts.py`
- Create: `bizpulse/api/v1/schemas/forecasts.py`
- Create: `bizpulse/frontend/assets/features/forecast/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Modify: `bizpulse/frontend/assets/{app.mjs,views.mjs,styles.css}`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Test: `bizpulse/tests/unit/forecast/test_analogs.py`
- Test: `bizpulse/tests/unit/forecast/test_new_product.py`
- Test: `bizpulse/tests/unit/forecast/test_backtest.py`
- Test: `bizpulse/tests/api/v1/test_forecasts.py`
- Test: `bizpulse/tests/frontend/forecast.test.mjs`

**Interfaces:**

- `select_analogs(candidate: ProductCandidate, catalog: Sequence[HistoricalSku]) -> tuple[Analog, ...]` returns a deterministic ranked list; the operator must confirm it.
- `forecast_new_product(request: ForecastRequest, confirmed_analogs: Sequence[Analog]) -> ForecastResult` returns low/base/high units, revenue, contribution profit, stock cover, and first-order guidance for horizons 7/30/90.
- `ForecastService.create/confirm_analogs/run/get/backtest` persists the exact input, analog set, algorithm version, assumptions, and evidence.

- [x] **Step 1: Write failing formula and evidence tests**

```python
def test_forecast_is_reproducible_and_ordered(forecast_request, confirmed_analogs):
    first = forecast_new_product(forecast_request, confirmed_analogs)
    second = forecast_new_product(forecast_request, tuple(reversed(confirmed_analogs)))
    assert first == second
    for horizon in (7, 30, 90):
        scenario = first.by_horizon[horizon]
        assert scenario.low_units <= scenario.base_units <= scenario.high_units


def test_unconfirmed_analogs_cannot_run(service, request):
    with pytest.raises(ForecastBlocked, match="analogs_not_confirmed"):
        service.run(request)
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/unit/forecast tests/api/v1/test_forecasts.py -q`

Expected: missing forecast/migration/service.

- [x] **Step 3: Implement deterministic analog scoring**

Normalize only operator-provided synthetic category/attributes. Score is `0.45*category_match + 0.25*attribute_jaccard + 0.15*price_proximity + 0.15*launch_window_coverage`; ties break by synthetic SKU key. Return at most five candidates with component evidence. No online or model knowledge enters the score.

- [x] **Step 4: Implement exact three-scenario formulas**

For confirmed analog `i`, weight `w_i` is its normalized score and daily units `d_i` use its complete synthetic history. Base analog demand is `sum(w_i*d_i)/sum(w_i)`. For horizon `h`, base units are rounded half-up from:

```text
base_units(h) = daily_analog_demand
                * h
                * launch_ramp[h]
                * clamp((planned_net_price / weighted_analog_net_price) ** -1.2, 0.60, 1.40)
                * clamp(1 + 0.15 * (planned_daily_ad / weighted_analog_daily_ad - 1), 0.80, 1.20)
```

`launch_ramp = {7: 0.65, 30: 0.90, 90: 1.00}`. Low/base/high multipliers are `0.70/1.00/1.30` for high confidence, `0.60/1.00/1.40` for medium, and no precise forecast for low confidence. Confidence is high only with at least three confirmed analogs, 90 complete days, all cost fields, and no unknown evidence; medium requires two analogs and 30 days; otherwise low/blocked. Revenue and contribution profit use server-owned deterministic prices/costs. Recommended first order is `max(0, ceil(high_units(min(90, max(30, lead_time_days))) + safety_stock_units - opening_inventory_units))`.

The formula rejects non-positive planned or weighted analog net price. For advertising, when both planned and weighted analog daily spend equal zero the factor is exactly `1.00`; when the weighted analog spend is zero but planned spend is positive, the request is blocked with `analog_ad_baseline_missing`. Decimal arithmetic and round-half-up are used through final unit rounding.

- [x] **Step 5: Implement hidden-window backtest**

Backtest synthetic launches by cutting history before launch and reporting MAE, WAPE, low/high interval coverage, analog sensitivity, and exact-repeat equality. These results are labeled synthetic Demo behavior, not real-market accuracy.

- [x] **Step 6: Implement forecast UI**

Show editable synthetic product inputs, ranked analog evidence, explicit confirmation, low/base/high interval chart with baseline, 7/30/90 tabs, confidence reasons, missing/assumed inputs, stock coverage, and action-draft eligibility. No Google Trends control, market image, or online refresh exists.

- [x] **Step 7: Run GREEN and commit**

Run: `.venv/bin/python scripts/test_postgres.py tests/postgres/test_0004_forecast_profit.py tests/unit/forecast tests/api/v1/test_forecasts.py -q`

Run: `node --test tests/frontend/forecast.test.mjs`

Expected: formulas, confidence/blocking, backtest, persistence, evidence, no-network tripwire, bilingual UI, and chart pass.

Commit: `git add bizpulse && git commit -m "feat: add deterministic new product forecast"`

**Completion definition:** the operator/viewer can inspect a repeatable three-scenario new-product forecast based only on confirmed synthetic analogs and explicit assumptions.

**Risk and rollback:** a precise-looking forecast may overstate certainty. Low evidence blocks precision; UI labels synthetic assumptions. Roll back app code to Task 8; keep forward migration compatible.

## Task 10: Contribution-profit authority and reconciling Profit Bridge

**Files:**

- Create: `bizpulse/src/profit/{contracts.py,bridge.py}`
- Create: `bizpulse/src/repositories/profit_bridges.py`
- Create: `bizpulse/src/services/profit_bridge_service.py`
- Create: `bizpulse/api/v1/routers/profit_bridge.py`
- Create: `bizpulse/api/v1/schemas/profit_bridge.py`
- Modify: `bizpulse/api/v1/router.py`
- Modify: `bizpulse/api/container.py`
- Modify: `bizpulse/frontend/assets/features/profit/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Test: `bizpulse/tests/unit/profit/test_bridge.py`
- Test: `bizpulse/tests/services/test_profit_bridge_service.py`
- Test: `bizpulse/tests/api/v1/test_profit_bridge.py`
- Test: `bizpulse/tests/frontend/profit-bridge.test.mjs`

**Interfaces:**

- `build_profit_bridge(current: ProfitPeriod, baseline: ProfitPeriod, tolerance: Decimal = Decimal("0.01")) -> ProfitBridge`.
- `ProfitBridgeService.run(dataset_version_id, current_period, comparison_period, scope) -> StoredProfitBridge`.
- `GET /api/v1/profit-bridges/{bridge_id}` returns total delta, ordered drivers, evidence states, unknown/missing inputs, residual, and exact reconciliation status.

- [x] **Step 1: Write failing bridge/reconciliation tests**

```python
def test_complete_bridge_reconciles_to_one_cent(current, baseline):
    bridge = build_profit_bridge(current, baseline)
    assert bridge.total_change == sum(item.amount for item in bridge.items)
    assert abs(bridge.residual) <= Decimal("0.01")
    assert bridge.reconciled is True


def test_missing_fulfillment_is_unknown_not_allocated(current_without_fulfillment, baseline):
    bridge = build_profit_bridge(current_without_fulfillment, baseline)
    assert bridge.reconciled is False
    assert bridge.item("fulfillment").evidence_state == "unknown"
    assert bridge.residual != Decimal("0")
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/unit/profit/test_bridge.py tests/services/test_profit_bridge_service.py tests/api/v1/test_profit_bridge.py -q`

Expected: missing bridge domain/service.

- [x] **Step 3: Implement contribution-profit contract**

For each period, contribution profit is net sales less COGS, platform fees, advertising, refund loss, fulfillment/logistics, tax when present, FX effect, and other mapped variable costs. A missing required component makes completeness partial/unknown; it is never assumed zero.

- [x] **Step 4: Implement exact fixed-order decomposition**

For baseline total units `Q0`, current units `Q1`, baseline SKU margin `m0_s`, and baseline weighted mean margin `mbar0`:

```text
volume = (Q1 - Q0) * mbar0
mix = sum_s((q1_s - q0_s) * (m0_s - mbar0))
price_discount = sum_s(q1_s * (net_unit_revenue1_s - net_unit_revenue0_s))
product_cost = -sum_s(q1_s * (unit_cogs1_s - unit_cogs0_s))
platform_fee = -(platform_fee_total1 - platform_fee_total0)
advertising = -(advertising1 - advertising0)
refund = -(refund_loss1 - refund_loss0)
fulfillment = -(fulfillment1 - fulfillment0)
tax = -(tax1 - tax0)
fx = fx_effect1 - fx_effect0
other_mapped = -(other_variable_cost1 - other_variable_cost0)
residual = total_contribution_profit_change - sum(known drivers)
```

New/discontinued SKU baselines use explicit zero quantity and the nearest valid baseline unit component; if that component is unavailable, its amount remains in residual/unknown. The fixed driver order is volume, price/discount, mix, advertising, refunds, fulfillment, platform fees, COGS, FX, tax, other mapped, residual. Complete inputs must reconcile within BRL 0.01.

- [x] **Step 5: Persist immutable bridge and render waterfall**

Store the exact current/baseline analysis IDs, formula version, driver values, evidence, and residual. The frontend waterfall starts at baseline contribution profit, shows signed drivers in fixed order, ends at current contribution profit, and always shows residual if nonzero/unknown.

- [x] **Step 6: Run GREEN and deterministic product composite**

Run: `.venv/bin/python scripts/test_postgres.py tests/unit/profit/test_bridge.py tests/services/test_profit_bridge_service.py tests/api/v1/test_profit_bridge.py -q`

Run: `node --test tests/frontend/profit-bridge.test.mjs`

Run: `.venv/bin/python scripts/test_postgres.py tests/unit/analysis tests/unit/forecast tests/unit/profit tests/integration/test_analysis_vertical.py -q`

Expected: exact reconciliation, incomplete residual, evidence, idempotent persistence, API, and accessible waterfall pass.

- [x] **Step 7: Commit**

Commit: `git add bizpulse && git commit -m "feat: add reconciling profit bridge"`

**Completion definition:** the Demo explains contribution-profit change with deterministic, evidence-labeled drivers and never forces unknown amounts into plausible categories.

**Risk and rollback:** non-reconciling bridges can mislead. Preserve residual and fail closed. Roll back app code; retain compatible schema and previous immutable bridge results.

## Task 11: Complete action cards, immutable decisions, export, and outcome review

**Files:**

- Create: `bizpulse/alembic/versions/0005_actions.py`
- Create: `bizpulse/src/actions/{contracts.py,state_machine.py,exports.py}`
- Create: `bizpulse/src/repositories/actions.py`
- Create: `bizpulse/src/services/action_service.py`
- Create: `bizpulse/api/v1/routers/actions.py`
- Create: `bizpulse/api/v1/schemas/actions.py`
- Create: `bizpulse/frontend/assets/features/action-inbox/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Modify: `bizpulse/frontend/assets/{app.mjs,views.mjs,styles.css}`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Test: `bizpulse/tests/unit/actions/test_state_machine.py`
- Test: `bizpulse/tests/services/test_action_service.py`
- Test: `bizpulse/tests/api/v1/test_actions.py`
- Test: `bizpulse/tests/integration/test_action_card_end_to_end.py`
- Test: `bizpulse/tests/frontend/action-inbox.test.mjs`
- Test: `bizpulse/tests/security/test_action_export.py`

**Interfaces:**

- `ActionService.create_draft(source: ActionSource, facts: Sequence[FactRef], idempotency_key: str) -> ActionCard` creates only `new`.
- `review`, `adjust`, `approve`, and `dismiss` enforce revision/CAS and append-only decisions.
- `export(action_id, revision, format="xlsx") -> ActionExport` creates a Demo file and never calls an external platform.
- `record_outcome(action_id, revision, synthetic_result, evidence) -> ActionOutcome` appends a human review without changing Action state.
- Viewer operations write `demo_action_overlays` scoped to the current Demo session and expire with it.

- [x] **Step 1: Write failing transition and authority tests**

```python
@pytest.mark.parametrize(
    ("start", "command", "allowed"),
    [
        ("new", "approve", False),
        ("new", "review", True),
        ("reviewed", "adjust", True),
        ("reviewed", "approve", True),
        ("reviewed", "dismiss", True),
        ("approved", "export", True),
        ("approved", "record_outcome", True),
        ("approved", "dismiss", False),
    ],
)
def test_action_transition_matrix(start, command, allowed):
    assert can_apply(start, command) is allowed


def test_export_does_not_mark_executed(action_service, approved_action):
    exported = action_service.export(approved_action.id, approved_action.revision)
    current = action_service.get(approved_action.id)
    assert exported.status == "available"
    assert current.status == "approved"
    assert not hasattr(current, "executed")
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/unit/actions/test_state_machine.py tests/services/test_action_service.py tests/api/v1/test_actions.py -q`

Expected: missing schema/domain/service.

- [x] **Step 3: Implement `0005_actions` and append-only authority**

Create the exact tables in the migration map. `action_cards` stores stable identity/current revision/source type; immutable revisions store suggestion, target, period, quantities/budget/date/threshold, expected impact, confidence, limitations, data/analysis/forecast/bridge/Chat source IDs, and evidence references. Decisions, exports, and outcomes are separate rows. Database checks enforce terminal states and session scope.

- [x] **Step 4: Selectively adapt the proved state machine/UI patterns**

Record source blob IDs from R4. Preserve `new -> reviewed -> approved|dismissed`, immutable adjustment, independent export, and independent outcome review. Remove old multi-tenant fields not needed by the Demo, but keep server-derived workspace/operator/session scope.

- [x] **Step 5: Implement safe Demo exports**

Export only approved operator cards. Prefix cells beginning with `=`, `+`, `-`, or `@` with an apostrophe; use obvious synthetic IDs; include Demo-only banner, source version/evidence, decision, and `Not sent to an external platform`. Viewer simulations do not create a Blob export.

- [x] **Step 6: Implement Action Inbox UI**

Show evidence, revisions, decision reason, export status, and outcome history. Use explicit `Review`, `Adjust`, `Approve`, `Dismiss`, `Export Demo File`, and `Record Synthetic Outcome` controls according to state. Never show `Completed` or `Executed`.

- [x] **Step 7: Run GREEN and end-to-end checks**

Run: `.venv/bin/python scripts/test_postgres.py tests/unit/actions tests/services/test_action_service.py tests/api/v1/test_actions.py tests/integration/test_action_card_end_to_end.py tests/security/test_action_export.py -q`

Run: `node --test tests/frontend/action-inbox.test.mjs`

Expected: transition, revision, evidence drift, replay, operator/viewer isolation, export hardening, outcome history, bilingual UI, and restart recovery pass.

- [x] **Step 8: Commit**

Commit: `git add bizpulse REUSE_LEDGER.md && git commit -m "feat: add human-controlled action cards"`

**Completion definition:** deterministic analytics/forecast/bridge can create evidence-backed `new` drafts; the operator closes the human loop without external write; viewer actions remain temporary and isolated.

**Risk and rollback:** UI copy can imply real execution. Contract tests forbid `executed/completed`; rollback app code while retaining append-only records and compatible schema.

## Task 12: Ask BizPulse whitelist query engine and evidence-constrained AI backend

**Files:**

- Create: `bizpulse/alembic/versions/0006_ai_chat.py`
- Create: `bizpulse/src/ai/{contracts.py,query_catalog.py,query_executor.py,openai_gateway.py,answer_merge.py,prompts.py}`
- Create: `bizpulse/src/repositories/ai_chat.py`
- Create: `bizpulse/src/services/ai_chat_service.py`
- Create: `bizpulse/api/v1/routers/ai_chat.py`
- Create: `bizpulse/api/v1/schemas/ai_chat.py`
- Modify: `bizpulse/api/v1/router.py`
- Modify: `bizpulse/api/container.py`
- Test: `bizpulse/tests/unit/ai/test_query_catalog.py`
- Test: `bizpulse/tests/unit/ai/test_query_executor.py`
- Test: `bizpulse/tests/unit/ai/test_answer_merge.py`
- Test: `bizpulse/tests/services/test_ai_chat_service.py`
- Test: `bizpulse/tests/api/v1/test_ai_chat.py`
- Test: `bizpulse/tests/security/test_ai_chat_boundary.py`
- Test: `bizpulse/tests/fixtures/ai/evaluation_cases.json`

**Interfaces:**

- Exact QueryTool names: `metric_lookup`, `trend_compare`, `sku_rank`, `profit_bridge_explain`, `inventory_risk_lookup`, `forecast_lookup`, `data_quality_lookup`, `action_card_lookup`.
- `QueryCatalog.plan_for_recommended(question_id, scope) -> QueryPlan` uses no model.
- `OpenAIGateway.plan(question, capability_catalog) -> QueryPlan` uses one structured Responses request.
- `QueryExecutor.execute(plan, server_scope) -> ToolResult` owns parameterized read-only queries and fixed limits.
- `OpenAIGateway.explain(question, result) -> ModelExplanation` uses one structured Responses request.
- `merge_answer(result, explanation) -> ChatAnswer` keeps all facts/scope/evidence server-authoritative.
- API: `GET/POST /api/v1/ai-chat/turns`, `GET /api/v1/ai-chat/turns/{turn_id}`, `POST .../{turn_id}/action-card-drafts`, `DELETE /api/v1/ai-chat/session`.

- [x] **Step 1: Write failing whitelist/query-scope tests**

```python
def test_model_plan_cannot_supply_scope_or_sql(catalog, executor, demo_scope):
    plan = QueryPlan.model_validate({
        "tool": "metric_lookup",
        "arguments": {"metric": "revenue", "period": "current"},
    })
    result = executor.execute(plan, demo_scope)
    assert result.scope.dataset_version_id == demo_scope.dataset_version_id
    assert "sql" not in result.model_dump_json().lower()


@pytest.mark.parametrize("tool", ["sql", "schema_lookup", "export_rows", "write_action"])
def test_unknown_or_mutating_tool_fails_before_database(tool, executor, query_counter):
    with pytest.raises(QueryPlanRejected, match="unknown_tool"):
        executor.execute_unvalidated({"tool": tool, "arguments": {}}, fixed_scope())
    assert query_counter.value == 0
```

- [x] **Step 2: Write failing authoritative-merge and provider-failure tests**

```python
def test_invented_fact_ref_fails_closed(tool_result):
    explanation = ModelExplanation(answer="Revenue improved", fact_refs=["fact-999"])
    with pytest.raises(AnswerMergeRejected, match="unknown_fact_ref"):
        merge_answer(tool_result, explanation)


def test_provider_outcome_unknown_is_not_retried(service, fake_provider):
    fake_provider.raise_after_send(ProviderOutcomeUnknown())
    turn = service.submit(question="Why did profit change?", idempotency_key="one")
    assert turn.status == "outcome_unknown"
    assert fake_provider.attempts == 1
```

- [x] **Step 3: Run RED**

Run: `.venv/bin/python -m pytest tests/unit/ai tests/services/test_ai_chat_service.py tests/api/v1/test_ai_chat.py tests/security/test_ai_chat_boundary.py -q`

Expected: missing AI Chat domain/migration/service.

- [x] **Step 4: Implement `0006_ai_chat`**

Create exact tables from the migration map. Turns store bounded safe question text or recommended ID, server scope, plan/output schema versions, idempotency request hash, state, safe summary, and timestamps. Tool runs store validated arguments and bounded result summary/hash. Attempts store stage/model/token counts/status/error code. No table has SQL, DB URL, API Key, raw provider body, raw file row, or unrestricted result JSON.

- [x] **Step 5: Implement strict plan models and catalog**

```python
class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: Literal[
        "metric_lookup", "trend_compare", "sku_rank",
        "profit_bridge_explain", "inventory_risk_lookup",
        "forecast_lookup", "data_quality_lookup", "action_card_lookup",
    ]
    arguments: QueryArguments


class ChatAnswer(BaseModel):
    turn_id: str
    status: Literal["answered", "clarification_required", "unsupported", "failed"]
    answer: str
    scope: AnswerScope
    facts: tuple[AuthoritativeFact, ...]
    limitations: tuple[str, ...]
    suggested_questions: tuple[str, ...]
    action_card_draft_eligible: bool
```

Each tool has an exact field/metric/filter/time-window enum and output model. Owner/workspace/session/dataset version/store scope are absent from model arguments and injected by the server. Result sizes are checked before execution and again before provider input.

- [x] **Step 6: Implement read-only parameterized executor**

Open a transaction with `SET TRANSACTION READ ONLY` and `SET LOCAL statement_timeout = '5s'`. Execute only registered SQLAlchemy statement builders. Return aggregates/defined ranks only. Reject arbitrary identifiers, JOIN graphs, schema questions, raw rows, unsupported causal claims, large periods, and cross-session/action references.

- [x] **Step 7: Implement fixed OpenAI Responses gateway**

The gateway always uses `gpt-5.4-mini-2026-03-17`, `reasoning={"effort": "low"}`, structured JSON schema, and `max_output_tokens=1200`. It sends only the closed catalog/question for planning, then the question plus bounded ToolResult for explanation. It configures no tools and never sends raw files, SQL, schema, credentials, unrestricted history, or provider-generated scope. Input over 2,000 characters and suspected secret/PII patterns are rejected before the provider.

- [x] **Step 8: Implement idempotency, budgets, and second-step Action draft**

Exact replay returns the same turn and never calls the provider again. Same key/different payload returns conflict. One in-flight turn per session is enforced in PostgreSQL. Rate/concurrency/daily-monthly budget checks run before an attempt row starts. Action draft eligibility is server-calculated; clicking draft re-reads the turn, dataset version, tool result hash, and evidence before calling `ActionService.create_draft`.

- [x] **Step 9: Run GREEN with fake providers only**

Run: `.venv/bin/python scripts/test_postgres.py tests/unit/ai tests/services/test_ai_chat_service.py tests/api/v1/test_ai_chat.py tests/security/test_ai_chat_boundary.py -q`

Expected: eight tools, recommended no-plan-call path, free-text two-call maximum, scope injection, query limits/timeouts, injection rejection, exact fact merge, replay, outcome unknown, budget fail-closed, cleanup, and Action second-step pass. Provider attempt counts are asserted; no paid call occurs.

- [x] **Step 10: Run fixed evaluation set and commit**

Run: `.venv/bin/python -m pytest tests/services/test_ai_chat_service.py -k evaluation_cases -q`

Evaluation cases include supported metrics/trends/ranks, Profit Bridge, inventory, forecast, data quality, Action status, clarification, no-data, unsupported schema/SQL, prompt injection, secret/PII, cross-session scope, invented facts, timeout, budget exhausted, and provider unavailable.

Commit: `git add bizpulse && git commit -m "feat: add evidence-constrained Ask BizPulse backend"`

**Completion definition:** Ask BizPulse answers only from server-produced synthetic facts/evidence; the model cannot select scope, query SQL, change a number, or create an Action without a second explicit request.

**Risk and rollback:** prompt injection, cost, and authoritative-data drift. Fail closed at plan validation and answer merge; keep deterministic pages available. Roll back AI routes/gateway while retaining read-only historical turn status; disable AI with server configuration.

**Authorization gate:** all Task 12 tests use fake providers. A real OpenAI Key and paid smoke remain unapproved until Task 15's exact launch authorization.

## Task 13: Ask BizPulse UI, conversation recovery, and cross-feature Action handoff

**Files:**

- Create: `bizpulse/frontend/assets/features/ask-bizpulse/{state.mjs,effects.mjs,view-model.mjs,view.mjs}`
- Modify: `bizpulse/frontend/assets/{app.mjs,state.mjs,views.mjs,styles.css}`
- Modify: `bizpulse/frontend/assets/features/{inventory,profit,forecast,action-inbox}/*.mjs`
- Modify: `bizpulse/frontend/assets/i18n/catalog.mjs`
- Modify: `bizpulse/src/services/demo_session_service.py`
- Create: `bizpulse/scripts/maintain_sessions.py`
- Test: `bizpulse/tests/frontend/ask-bizpulse-state.test.mjs`
- Test: `bizpulse/tests/frontend/ask-bizpulse-effects.test.mjs`
- Test: `bizpulse/tests/frontend/ask-bizpulse-view-model.test.mjs`
- Test: `bizpulse/tests/frontend/ask-bizpulse-view.test.mjs`
- Test: `bizpulse/tests/integration/test_chat_session_recovery.py`
- Test: `bizpulse/tests/integration/test_chat_action_handoff.py`
- Test: `bizpulse/tests/security/test_cross_session_isolation.py`

**Interfaces:**

- `Ask BizPulse` is the first secondary page under the existing `briefing`/AI Decision Center primary area, followed by Product Opportunities, Favorites, and Operating Advice where retained.
- `Ask about this` passes only a server-issued scope reference in navigation state; the backend restores and validates the legal scope.
- Frontend state stores safe API projections, not database rows, provider bodies, SQL, credentials, or raw Key values.

- [x] **Step 1: Write failing UI state/effects tests**

```javascript
test("double submit produces one turn request", async () => {
  const api = fakeApi();
  const effects = createAskBizPulseEffects({ api });
  effects.submit({ question: "Why did profit change?" });
  effects.submit({ question: "Why did profit change?" });
  await effects.settle();
  assert.equal(api.turnRequests.length, 1);
});

test("answer text is rendered as text and cannot inject HTML", () => {
  const html = renderAnswer(answer({ answer: "<img src=x onerror=alert(1)>" }));
  assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img/);
});
```

- [x] **Step 2: Run RED**

Run: `node --test tests/frontend/ask-bizpulse-*.test.mjs`

Expected: feature files missing.

- [x] **Step 3: Implement page structure and request fencing**

Header shows Synthetic Demo, fixed dataset version, store, period, and BRL. First view has 4-6 server-published recommended questions. Each answer renders conclusion, authoritative facts, evidence states/links, limitations, suggested questions, and a separate draft-action button when eligible. Submit uses one generated idempotency key, disables while in flight, and suppresses stale responses after scope/session changes.

- [x] **Step 4: Implement safe history and recovery**

The page lists current-session turns from the API. Only the last four server-generated safe summaries are eligible for model context; older visible turns remain client-visible/API-readable but are not re-sent automatically. Refresh/reopen restores unexpired turns. End Session deletes Chat/tool/evidence/attempt summaries and viewer action overlays for only that session.

- [x] **Step 5: Implement cross-feature handoff and evidence drawer**

Profit Bridge, Inventory, Forecast, and Action pages add `Ask about this` as a secondary control. Navigation passes a server scope token, not raw IDs supplied by the user. Evidence opens the global drawer. Action draft requires a second click and handles `evidence_changed` by asking the user to refresh/requery.

- [x] **Step 6: Run GREEN integration/security tests**

Run: `node --test tests/frontend/ask-bizpulse-*.test.mjs`

Run: `.venv/bin/python scripts/test_postgres.py tests/integration/test_chat_session_recovery.py tests/integration/test_chat_action_handoff.py tests/security/test_cross_session_isolation.py -q`

Expected: recommended/free-text, clarification, no-data, unsupported, failure, evidence, recovery, end-session cleanup, Action draft, scope drift, and two-viewer isolation pass.

- [x] **Step 7: Decision-layer full/composite and browser gate**

Run: `.venv/bin/python scripts/test_postgres.py tests/unit/ai tests/unit/actions tests/services/test_ai_chat_service.py tests/services/test_action_service.py tests/integration/test_chat_session_recovery.py tests/integration/test_chat_action_handoff.py tests/security -q`

Run: `node --test tests/frontend/*.test.mjs` once for the Stage full frontend budget.

Run: `.venv/bin/python -m pytest tests -q` once for the Stage full Python budget.

Browser checklist at 1280/820/390: recommended question; free text; clarification; evidence drawer; `Ask about this`; second-step draft; viewer simulated review/approve/dismiss; refresh/reopen; second viewer cannot see state; End Session clears; provider unavailable leaves deterministic pages usable; no HTML injection/console/external network.

- [x] **Step 8: Commit**

Commit: `git add bizpulse && git commit -m "feat: complete Ask BizPulse and action handoff"`

**Completion definition:** Ask BizPulse is usable and recoverable in the AI Decision Center; evidence and Action flow are explicit; cross-session and scope boundaries hold at browser and integration levels.

**Risk and rollback:** stale UI state could act on changed evidence. Request-generation fencing plus server revalidation closes it. Roll back frontend/route registration and disable AI; deterministic product and Actions remain available.

## Task 14: Security hardening, observability, capacity, and local release candidate

**Files:**

- Create: `bizpulse/src/observability.py`
- Create: `bizpulse/api/security_policy.py`
- Create: `bizpulse/api/request_context.py`
- Create: `bizpulse/scripts/verify_release.py`
- Create: `bizpulse/scripts/create_release_manifest.py`
- Create: `bizpulse/tests/security/{test_headers.py,test_logs.py,test_errors.py,test_rate_limits.py,test_no_prohibited_network.py}`
- Create: `bizpulse/tests/acceptance/test_exact_15_sessions.py`
- Create: `bizpulse/tests/acceptance/test_restart_readback.py`
- Create: `bizpulse/tests/acceptance/test_rollback_compatibility.py`
- Modify: `bizpulse/api/main.py`
- Modify: `bizpulse/api/errors.py`
- Modify: `bizpulse/src/config.py`
- Modify: `CURRENT_STATUS.md`
- Modify: `AUTHORIZATION_LEDGER.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`

**Interfaces:**

- Every request gets an opaque request ID; structured logs allowlist method, route template, status, duration, safe error code, tool name, dataset version hash prefix, and token counts.
- Security middleware applies CSP, frame denial, MIME sniffing denial, referrer policy, permissions policy, HTTPS/HSTS in cloud, request/body limits, and safe cache policy.
- `verify_release.py` fails unless migration head, pure-synthetic manifest, fixed model, no prohibited source, no secret/large artifact, deterministic tests, exact-15 capacity, restart, and rollback compatibility evidence all pass.

- [x] **Step 1: Write failing log/header/error tests**

```python
def test_logs_do_not_contain_sensitive_payload(caplog, client):
    secret = "synthetic-secret-sentinel"
    client.post("/api/v1/ai-chat/turns", json={"question": secret}, headers=csrf_headers())
    assert secret not in caplog.text
    assert "database_url" not in caplog.text.lower()


def test_error_is_stable_and_path_free(client, injected_internal_error):
    response = client.get("/api/v1/analyses/current")
    assert response.status_code == 500
    assert response.json() == {"code": "INTERNAL_ERROR", "request_id": response.json()["request_id"]}
    assert "/Users/" not in response.text
```

- [x] **Step 2: Run RED**

Run: `.venv/bin/python -m pytest tests/security/test_headers.py tests/security/test_logs.py tests/security/test_errors.py tests/security/test_rate_limits.py tests/security/test_no_prohibited_network.py -q`

Expected: missing middleware/policies.

- [x] **Step 3: Implement fail-closed policies and safe telemetry**

Use route templates rather than raw paths in logs. Do not log complete questions, answers, provider bodies, DB results, cookies, headers, file names/content, IDs beyond approved hashes, or exception text. Public AI has session rate control, global concurrency, rolling request control, and mandatory daily/monthly budget limits. Rejections preserve deterministic pages.

- [x] **Step 4: Execute exact-15 local capacity and restart tests**

Use local PostgreSQL, Azurite, fixed synthetic release, fake provider with bounded latency, one application process replacement, and 15 viewer sessions from the same simulated source. Assert 15 distinct sessions, fixed versions, page reads, one Chat turn each, no cross-session data, rate-limit policy permits admission, database/Blob reads persist, and the replacement process restores unexpired state.

Run: `.venv/bin/python scripts/test_postgres.py tests/acceptance/test_exact_15_sessions.py tests/acceptance/test_restart_readback.py -q`

Expected: exact 15 pass within the test's declared 60-second admission and 300-second complete-flow ceilings; no listener/process/temp root remains.

- [x] **Step 5: Run rollback compatibility and release verifier**

Run: `.venv/bin/python scripts/test_postgres.py tests/acceptance/test_rollback_compatibility.py -q`

Run: `.venv/bin/python scripts/verify_release.py --manifest tests/fixtures/synthetic/v1/manifest.json`

Expected: previous compatible app revision reads the forward schema; public pointer can repoint to the prior immutable version; prohibited-source/secret/large-file/Git-status checks are green.

- [x] **Step 6: Complete one bounded final self-review**

Review the approved design, this plan, `REUSE_LEDGER.md`, the implementation-base-to-HEAD diff, focused/composite evidence, public routes, migration head, session/AI/action boundaries, and release manifest. Close every Critical/Important/Moderate issue with focused tests. Do not repeat the whole review.

- [x] **Step 7: Run the final local full/static/browser gates once**

Run: `.venv/bin/python -m pytest tests -q`

Run: `node --test tests/frontend/*.test.mjs`

Run: `.venv/bin/python -m ruff check api src scripts tests && .venv/bin/python -m compileall -q api src scripts && git diff --check`

Browser: repeat the full public/operator/Chat/Action route at 1280/820/390 with network and console inspection, one process restart, two simultaneous viewers, AI failure/budget states, and local-only assets.

- [x] **Step 8: Create immutable local release manifest and commit**

The manifest records Git SHA, synthetic manifest hash, migration head `0007_chat_session_fences`, dependency hashes, test evidence, image input hash, model snapshot, fixed configuration names without values, and rollback-compatible prior SHA. It contains no secret or private environment value.

First commit the reviewed Task 14 code and status documents as the clean candidate with `git commit -m "chore: close local NEWCaostone release candidate"`. On that exact clean commit, run `create_release_manifest.py`; stage only `bizpulse/release/local-release-manifest.json`; commit it as the candidate's manifest-only direct child with `git commit -m "docs: attest local release candidate"`; then run `create_release_manifest.py --verify-attestation`. The verifier must recreate the candidate in a detached task-owned worktree, rerun all gates, exact-compare the evidence, and fail closed on any cleanup or dependency mismatch. Step 8 is complete only after that child attestation verifies; the candidate parent must not pre-claim its own SHA.

**Completion definition:** the exact Git SHA is Locally verified with one truthful full-suite record, exact-15 capacity, restart, security, browser, and rollback compatibility; it is not CI verified, deployed, hosted verified, accepted, or Production-ready.

**Risk and rollback:** a broad late change invalidates evidence. Any post-gate behavior/dependency/migration change returns to the smallest affected task and repeats only required gates before a new release SHA.

## Task 15: Authorized Azure infrastructure, deployment, recovery, and Demo acceptance

**Files:**

- Create: `bizpulse/Dockerfile`
- Create: `bizpulse/infra/main.bicep`
- Create: `bizpulse/infra/modules/{app.bicep,postgres.bicep,storage.bicep,monitoring.bicep}`
- Create: `bizpulse/infra/environments/demo.bicepparam`
- Create: `bizpulse/docs/runbooks/{DEPLOY.md,ROLLBACK.md,RECOVERY.md,AI_KEY_REVOCATION.md,DEMO_SHUTDOWN.md}`
- Create after local preflight: `LAUNCH_AUTHORIZATION.md`
- Create after acceptance planning: `CLEANUP_AUTHORIZATION.md`
- Create: `bizpulse/tests/infra/test_bicep_contract.py`
- Create: `bizpulse/tests/release/test_container_contract.py`
- Create: `bizpulse/tests/release/test_release_manifest.py`
- Create: `bizpulse/tests/hosted/verify_azure_demo.py`
- Create: `bizpulse/scripts/verify_registry_image.py`
- Create: `bizpulse/alembic/versions/0008_ai_budget_ledger.py`
- Create after the final Task 15 candidate: `bizpulse/release/task15-local-release-manifest.json`
- Modify: `CURRENT_STATUS.md`
- Modify: `AUTHORIZATION_LEDGER.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`

**Interfaces:**

- One non-root immutable application image runs `api.main:app` on port 8000.
- Bicep declares one Azure application runtime, PostgreSQL, private Blob container, monitoring/logging, HTTPS-only configuration, and server-side secret setting names. Exact resource names, subscription, region, SKU, budget, and cost cap are materialized only in the authorization package.
- `verify_azure_demo.py` accepts an exact HTTPS URL, release SHA/digest, expected migration head, expected synthetic manifest hash, and safe secret-presence flags; it outputs identifiers/status/counts only.

- [x] **Step 1: Write failing container/IaC/release tests**

```python
def test_container_is_non_root_and_digest_labelled(container_inspect):
    assert container_inspect.user == "bizpulse"
    assert container_inspect.oci_revision == EXPECTED_GIT_SHA
    assert container_inspect.command == [
        "python", "-m", "uvicorn", "api.main:app",
        "--host", "0.0.0.0", "--port", "8000", "--workers", "1",
    ]


def test_bicep_has_postgres_blob_https_and_no_sqlite(compiled_template):
    assert compiled_template.postgres_count == 1
    assert compiled_template.private_blob_container_count == 1
    assert compiled_template.https_only is True
    assert "sqlite" not in compiled_template.serialized.lower()
```

- [x] **Step 2: Implement and locally verify immutable container/IaC**

The Dockerfile copies only application code, local frontend assets, declared synthetic manifest/seed assets, and hashed dependencies; uses a pinned Python 3.12 base digest; runs as `bizpulse`; exposes health; contains no `.env`, Key, DB, log, cache, test artifact, CAPTSONE path, or mutable tag assumption.

Run: `.venv/bin/python -m pytest tests/infra tests/release -q`

Run: `az bicep build --file infra/main.bicep --stdout > .tmp/main.json` only as local compilation; it must not log in or call Azure Resource Manager.

Run the exact current and rollback-compatible contexts with both authority labels: `docker build --platform linux/amd64 --build-arg SOURCE_REVISION=<exact-sha> --build-arg IMAGE_INPUT_SHA256=<exact-image-input-sha256> --tag newcaostone-local:<short-sha> .`; inspect user/labels/contents and run local PostgreSQL/Azurite smoke. Do not publish either image in this local step.

- [ ] **Step 3: Create a value-complete launch authorization package and stop**

Generate `LAUNCH_AUTHORIZATION.md` from read-only subscription/preflight information only after separate permission to read Azure account/resource state. The package must contain actual subscription, region, resource group, generated names, SKU, one-time/monthly cost estimate and hard cap, Git SHA, image digest, migration head, Blob/PostgreSQL configuration, server setting names, OpenAI budget, exact create/update/migrate/deploy/smoke/restart/browser/recovery/rollback commands, retry counts, stop conditions, and whether GitHub/registry publication is included. It contains no secret value.

Stop and request one explicit approval. Plan approval alone does not authorize any Azure, registry, GitHub, secret, paid API, or DNS action.

- [ ] **Step 4: After exact authorization, execute recovery-first release order**

Execute only package commands and only within its cost cap:

```text
read-only recovery/config preflight
-> publish both exact current and `0008`-compatible rollback image digests if authorized
-> remotely verify each digest's source-SHA and image-input OCI labels
-> provision/update declared resources in private phase 1
-> verify backup/restore prerequisites and phase-1 drain fence
-> migrate PostgreSQL to 0008_ai_budget_ledger
-> seed and verify the exact synthetic authority
-> run budget/provider failure rehearsals and recover private/min0 after each
-> deploy canonical phase 2, maintenance jobs, and phase-2 fence
-> /health/live and /health/ready
-> public/operator API smoke
-> exact-15 and real 30-minute idle-expiry acceptance
-> application restart and PostgreSQL/Blob readback
-> browser acceptance
-> authorized paid AI smoke only when separately included
-> rollback rehearsal to prior compatible digest and forward again
-> signed release/acceptance evidence
```

No automatic provider retry, mutable image tag, database downgrade, SQLite fallback, or undeclared resource is allowed. A material target/cost/digest/migration/rollback change stops and requires a new package.

- [ ] **Step 5: Run hosted verifier and browser acceptance**

Run: `.venv/bin/python tests/hosted/verify_azure_demo.py --authorization LAUNCH_AUTHORIZATION.md`. The verifier reads the exact URL, release SHA/digest, migration head, manifest hash, and permitted checks from the approved document and rejects a missing, extra, or unhashed value.

Expected hosted evidence:

- exact release SHA/digest and migration head;
- PostgreSQL and Blob actual configuration, no local fallback;
- operator synthetic import/atomic commit/publish/export/outcome;
- old/new viewer version pinning, refresh/reopen/expiry/end-session;
- 15 simultaneous viewer sessions and same-network admission;
- deterministic analyses, forecast, Profit Bridge, Action cards;
- recommended/free-text Chat, evidence, second-step draft, isolation, injection/SQL rejection, budget/provider failure;
- restart readback and rollback rehearsal;
- 1280/820/390 browser flow, local asset policy, no blocking console/layout issue;
- Demo-only/non-Production labeling and no external business write.

- [ ] **Step 6: Record evidence states without overclaiming**

Update status independently: `Deployed` only after exact digest/URL; `Hosted verified` only after actual config/restart/browser evidence; `Azure Demo accepted` only after every design acceptance item passes. Never label Production-ready.

- [ ] **Step 7: Prepare separate cleanup/revocation package**

`CLEANUP_AUTHORIZATION.md` lists exact resource/object/branch targets, retention, recoverability, cost effect, and user-owned items. Permanent deletion and resource teardown wait for explicit approval. The runbook instructs the user or separately authorized process to revoke the dedicated OpenAI Key first, then delete the Azure server setting; no key value enters evidence.

- [ ] **Step 8: Commit local evidence records only**

Commit local source/runbook/status/evidence identifiers after removing secret/private artifacts. Generate `bizpulse/release/task15-local-release-manifest.json` only for the clean final Task 15 candidate, commit it as the candidate's direct manifest-only child, and run detached attestation verification. Push remains separate unless the launch package explicitly authorized it.

**Completion definition:** the exact Azure URL passes full hosted, restart, capacity, recovery, rollback, browser, AI, and security acceptance and is recorded as `Azure Demo accepted`; it remains Demo-only and non-Production.

**Risk and rollback:** cost overrun, failed migration, wrong digest, lost state, leaked Key, or misleading hosted claim. Every condition has a package stop rule; rollback uses the prior immutable compatible image and data/public-version recovery, never a destructive downgrade. Key revocation and cleanup are separate explicit gates.

## External authorization gates

| Gate | Required before | Exact authorization content |
|---|---|---|
| Plan approval | Task 1 code | Approval of this exact plan; no product redesign required. |
| Source adoption | Each selective copy | Ledger row with source commit/blob, target path, time box, and isolated tests; no new user prompt if within the approved plan. |
| Git identity/publication | Initial/local commits and any remote operation | Existing Git identity must be available for commits. Remote creation, push, PR, CI, or registry publication requires explicit inclusion in a later package. |
| Azure read-only preflight | Reading subscription/resource state | Exact read scope and account/subscription context; no mutation. |
| Launch authorization | Any Azure/registry/GitHub/secret/paid provider mutation | Value-complete `LAUNCH_AUTHORIZATION.md`, exact target/cost/digest/migration/rollback/retry scope. |
| Real OpenAI smoke | One paid provider call set | Dedicated temporary Key already configured server-side, exact evaluation cases, token/cost cap, no retry, and evidence fields. |
| Cleanup/revocation | Permanent resource/object/branch deletion or Key operation | Value-complete `CLEANUP_AUTHORIZATION.md`; Key value is never requested in chat or committed. |

## Rollback points

| Point | Recovery |
|---|---|
| Initial Stage 0 checkpoint | Restore approved design, ledgers, and plan; no app/schema exists. |
| Task 1 shell | Revert shell commit; no durable data. |
| `0001`-`0007` local development | Drop only disposable test databases/storage after exact ownership validation; never touch user/hosted data. |
| Post-import public release | Repoint to prior immutable dataset version; never delete the failed/new version during ordinary rollback. |
| Analysis/forecast/bridge/action/Chat | Disable the route/capability and run prior schema-compatible application commit; preserve immutable records. |
| Local release candidate | Use prior commit/release manifest and repeat only affected gates. |
| Azure deployment | Deploy prior approved image digest after compatibility/recovery preflight; verify health, PostgreSQL/Blob readback, sessions, and public release. Do not run Alembic downgrade. |
| Azure data incident | Stop writes, follow the authorized combined PostgreSQL + Blob restore runbook, verify sentinel/object ledger/version pointers, then reaccept the Demo. |

## Final definition of done

The plan is complete only when every item in approved design section 20 has corresponding automated, local browser, and hosted evidence. Specifically:

- the source/reuse ledger proves every reused module;
- all input is source-level pure synthetic;
- operator import/atomic commit/version/publish/export/outcome works;
- anonymous viewers are read-only, isolated, resumable, expiring, and version-pinned;
- PostgreSQL/Blob are actual hosted authorities;
- deterministic analytics, new-product 7/30/90 low/base/high forecast, and reconciling Profit Bridge work with evidence;
- Ask BizPulse uses only eight whitelist tools, server scope, bounded read-only queries, exact fact refs, and safe failure;
- Chat creates `new` Action only on the second explicit click after evidence revalidation;
- complete Action revisions/decisions/exports/outcomes preserve human authority and never imply external execution;
- fixed model/effort, Key/budget, provider failure, input/output, concurrency, logs, and no-tool contracts pass;
- no Google Trends/online market/real-data/external business write exists;
- exact-15 capacity, restart readback, recovery, rollback, browser viewports, and URL pass;
- release records remain Demo-only/non-Production, and Key revocation/cleanup have separate controlled instructions.

## Plan self-review

- Spec coverage: every approved design section maps to Tasks 1-15 and the final definition above; no confirmed capability is omitted.
- Completeness scan: every implementation step has files, commands, expected evidence, completion criteria, risk, rollback, and authority boundary. Runtime values that require external authority are generated into a value-complete authorization document before mutation and cannot be guessed in this plan.
- Type consistency: `dataset_version_id`, `analysis_run_id`, `forecast_id`, `profit_bridge_id`, `action_id/revision`, `turn_id`, `fact_ref`, evidence state, idempotency key hash, and server-derived session/workspace scope retain the same meanings across migrations, services, APIs, frontend, and tests.
- Scope consistency: Task 7 existing replenishment is separate from Task 9 new-product forecast; Task 10 Profit Bridge is deterministic; Task 12 Chat is not SQL and cannot replace Tasks 7-10; Task 11/12 maintain the second-action draft gate.
- Evidence consistency: local tests cannot produce CI/Deployed/Hosted/Azure-accepted status, and an Azure URL alone cannot produce hosted acceptance.

Plan complete and saved to `docs/superpowers/plans/2026-08-13-newcaostone-demo-single-operator-implementation.md`. Implementation remains stopped until the user approves this exact plan.
