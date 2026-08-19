# BizPulse / NEWCaostone

> Private team preview. Local implementation and hosted evidence are reported separately. This repository is not a Production release.

中文说明：这是给项目组员查看的当前代码预览，重点说明已经实现的功能、证据边界和下一步计划；不代表 AI、多人账号或 Production 已完成。

## Product goal

BizPulse helps small cross-border e-commerce teams turn fragmented marketplace spreadsheets into traceable operating decisions. The product keeps deterministic calculations and versioned evidence authoritative, then uses AI only as a bounded explanation and prioritization layer.

The current preview is a sample-data, single-Operator system. It is designed for a controlled team demonstration and continued engineering work, not unrestricted customer onboarding.

## Product surfaces

| Surface | Intended user | Current boundary |
|---|---|---|
| **Synthetic Demo** | Teammates and invited viewers | Uses built-in synthetic data. Viewers can explore prepared results and simulate selected actions, but cannot upload personal files or recompute canonical data. |
| **Operator App** | The authenticated single Operator | Runs the formal import workflow, deterministic analyses, forecasts, publishing, exports, and Action Inbox decisions for supported data formats. |
| **Admin Console** | The authenticated platform administrator | Provides protected operational status, data-management views, Operator reauthentication, AI channel controls, and controlled Key Vault rotation workflows. The code is locally implemented; hosted Admin acceptance remains open. |

## Implemented now

- PostgreSQL schema and migrations through repository revision `0017_ai_turn_credential_binding`.
- Formal import workflow: upload, recognize, map, standardize, preview, commit an immutable dataset version, and run calculations.
- Row-level deduplication, atomic conflict blocking, import lineage, and versioned evidence.
- Sales, Inventory, Profit, Profit Bridge, Forecast, and Today Overview surfaces.
- All/Main/Launch store scope across the main analytical surfaces.
- BP Library workbook browsing and dataset export support.
- Action Inbox decisions plus resettable Viewer-side simulation overlays.
- Ask BizPulse turn persistence, preset auditing, session fences, rate limits, budgets, and evidence-bound answer construction.
- Protected Admin shell, operations cockpit, system status, Admin JSON APIs, current-password reauthentication, idempotent AI control operations, and exact Key Vault secret-version binding.
- Independent database-authoritative AI switches for the Operator App and Synthetic Demo.
- Local release, policy, migration, browser, and hosted-acceptance tooling.

Detailed evidence and limitations are in [Team Status](docs/TEAM_STATUS.md).

## Evidence-first AI boundary

AI is not the source of sales, inventory, profit, forecast, or action facts. Those values come from deterministic services and versioned evidence. Ask BizPulse may explain or prioritize that evidence, but it does not autonomously upload files, change canonical data, execute marketplace actions, or search the public web.

The current hosted AI state is **disabled**. The real API key is not stored in Git, the browser, the database, or these documents. Admin-based validation and enablement remain a separately authorized hosted step.

## Architecture

| Layer | Current implementation |
|---|---|
| Web/API | FastAPI application with server-rendered shells and browser-native ES modules |
| Data | PostgreSQL with Alembic migrations and immutable dataset/analysis records |
| File evidence | Azure Blob-compatible storage seam; Azurite is used for local verification |
| Product logic | Deterministic import, analysis, forecast, profit, evidence, and action services |
| Identity | Public synthetic Demo sessions plus one authenticated Operator |
| AI control | Server-side OpenAI Responses integration, database channel authority, budgets, Key Vault exact-version references, and fail-closed controls |
| Hosting | Azure Container Apps/Bicep tooling with release, rollback, and acceptance gates |

## Repository map

- `bizpulse/api/` — FastAPI app, routes, authentication, and HTTP boundaries.
- `bizpulse/src/` — domain services, repositories, storage, AI controls, and deterministic logic.
- `bizpulse/frontend/` — Operator, Viewer, Admin, analytics, library, action, and AI interfaces.
- `bizpulse/alembic/` — PostgreSQL migration chain.
- `bizpulse/tests/` — unit, API, security, database, browser, release, infrastructure, and hosted-control tests.
- `bizpulse/scripts/` — local verification, data preparation, release, diagnosis, and maintenance tooling.
- `bizpulse/infra/` — Azure Bicep infrastructure.
- `CURRENT_STATUS.md` — detailed engineering and release evidence, including historical incidents.
- `docs/TEAM_STATUS.md` — concise teammate-facing status.
- `docs/ROADMAP.md` — prioritized next work.

## Local setup and verification

Prerequisites:

- Python 3.12
- Node.js 24.18 or newer
- PostgreSQL
- Azurite for Blob-compatible local verification
- macOS/Chrome/Bicep only for checks that explicitly require them

From `bizpulse/`:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes --requirement requirements.txt
npm ci

.venv/bin/python -m pytest -q
npm test
.venv/bin/python -m ruff check api src scripts tests alembic
.venv/bin/python scripts/check_authority_contract.py --mode docs
```

The local application entrypoint is:

```bash
.venv/bin/python -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log
```

Application startup also requires the local PostgreSQL, Blob/Azurite, migration, and demo/bootstrap state expected by the current configuration. Do not reuse cloud credentials for local development, and do not place secrets in Git or chat.

## Current status and roadmap

- [Team Status](docs/TEAM_STATUS.md) — implemented, verified, hosted, and deferred states.
- [Roadmap](docs/ROADMAP.md) — P0/P1/P2 priorities.
- [Detailed Current Status](CURRENT_STATUS.md) — full release and authority record.
- [Current Handoff](docs/handoffs/CURRENT_HANDOFF.md) — engineering continuation boundary.

## Team rules

- Keep deterministic calculations and verified records authoritative.
- Separate local implementation, local tests, GitHub CI, deployment, hosted acceptance, and Production readiness.
- Use focused branches and reviewable commits; do not push local outputs or authorization packages.
- Never request, paste, log, commit, or echo passwords, API keys, tokens, connection strings, or secret values.
- Treat Demo data and behavior as synthetic unless a separately verified source says otherwise.
- Do not claim arbitrary Excel compatibility, multi-account tenancy, hosted AI, marketplace integration, or autonomous actions until those items have their own implementation and evidence.
