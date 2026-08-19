# BizPulse Admin Operations and AI Control Design

**Date:** 2026-08-18  
**Status:** Approved design; implementation has not started  
**Scope:** A protected administrator console for data operations, application status, and safe OpenAI credential and channel control

## 1. Outcome

BizPulse will add a separate administrator console at `/admin`. The console will reuse the existing single Operator identity and session authority. It will not create a second credential system or expose administrator functions to public Demo sessions.

The first version provides:

- an operations-cockpit overview;
- the existing upload, recognition, mapping, validation, commit, and publish workflow;
- application-level system status;
- one shared OpenAI API key stored in Azure Key Vault;
- independent AI availability switches for ordinary Operator login and public Demo sessions;
- verified, compensating OpenAI API key rotation;
- append-only, secret-free administrator audit events.

Password rotation, session revocation, arbitrary Azure operations, and general infrastructure controls are outside this version.

## 2. Current-System Boundary

The existing application has one active Operator account per workspace. `/app` is protected by the opaque Operator cookie, while `/demo` is protected by a separate Demo session. Both actor kinds already submit AI turns through the same `/api/v1/ai-chat` router and the same `AIChatService` instance.

The current AI container construction is process-startup gated by `BIZPULSE_AI_ENABLED`, and the current Key Vault provider reads the latest secret value into a bounded in-memory cache. The administrator design replaces that release-time channel gate with a database-authoritative runtime gate and binds provider reads to an exact Key Vault secret version. This is required so every replica changes credentials at the same database commit boundary.

The earlier R19 AI-enablement attempt is closed and must not be replayed. Implementing and hosting this design requires a fresh exact-hash release package based on the then-current live Azure baseline.

## 3. Chosen Product and Layout Direction

The selected approach is a separate admin single-page shell using the existing frontend module conventions.

### Navigation

The left navigation contains:

1. Overview
2. Data Management
3. System Status
4. AI Management
5. Return to Workspace

The overview uses the selected “operations cockpit” layout:

- current published dataset version;
- most recent import and publish state;
- actionable failure count;
- recent data activity;
- database, Blob, configuration, migration, and AI summaries.

### Administrator entry

An authenticated Operator can enter the console in two ways:

- click **Administrator Console** in the `/app` sidebar footer; or
- visit `/admin` directly.

Unauthenticated document navigation to `/admin` or its child paths redirects to `/login?next=<allowlisted-admin-path>`. After successful login, the application returns to that path. The only accepted `next` targets are same-origin `/app` and known `/admin` paths. API authentication failures remain JSON `401` responses.

Public Demo users do not see an administrator link and cannot use an Operator-only route or API. Every admin shell route performs a server-side Operator resolution; frontend visibility is not an authorization boundary.

## 4. Architecture

### 4.1 Admin shell

`frontend/admin.html` and an admin entry module render the console. The following protected document routes return the same shell:

- `/admin`
- `/admin/data`
- `/admin/status`
- `/admin/ai`

The shell follows the established bilingual catalog, no-cache module graph, accessible controls, and responsive sidebar patterns. It does not contain secrets or server configuration in HTML.

### 4.2 Reused data-management workflow

Data Management reuses the current Operator import and dataset APIs. The existing Data Workspace controller will be extracted into a reusable, bounded component rather than copied. The admin shell supplies the same Operator data source and receives the same workflow receipts, version checks, conflict handling, and CSRF protections.

The admin console does not gain direct database, Blob, or Azure access from the browser.

### 4.3 Admin application services

The backend adds three focused services:

- `AdminSummaryService`: creates a safe overview from PostgreSQL projections and application readiness checks.
- `AIControlService`: owns the two channel gates, optimistic revision, reauthentication requirement, and audit events.
- `OpenAIKeyRotationService`: validates a candidate key, writes a new Key Vault version, performs exact-version readback, and compensates on partial failure.

These services depend on narrow repository and secret-provider interfaces so local tests use fakes and never require a real credential.

### 4.4 Shared runtime AI path

Operator and Demo turns continue through one `AIChatService` and one logical OpenAI gateway. Before reserving budget or contacting OpenAI, the service reads the workspace AI control row and checks the relevant channel:

- `actor_kind == "operator"` requires `operator_enabled`;
- `actor_kind == "demo"` requires `demo_enabled`.

Both branches obtain the same `key_version` from the control row and request that exact version from the provider. The provider cache is keyed by Key Vault version, not only by secret name. Therefore:

- requests that begin before a successful rotation use the old exact version;
- requests that begin after the database activation commit use the new exact version;
- replicas cannot drift merely because one process retained a 60-second cache entry.

## 5. Data Model

### 5.1 `ai_control_state`

One row exists per workspace:

- `workspace_id` — primary and tenant boundary;
- `operator_enabled` — ordinary-login channel gate;
- `demo_enabled` — public-Demo channel gate;
- `key_version` — server-only Key Vault version identifier;
- `key_fingerprint` — non-secret HMAC fingerprint for operator comparison;
- `verified_at` — timestamp of the last successful exact-version validation;
- `revision` — optimistic concurrency counter;
- `updated_by_operator_id` and `updated_at`.

The API never returns `key_version`. It returns only the fingerprint prefix, verification time, channel states, and revision.

### 5.2 `admin_audit_events`

Events are append-only and workspace scoped:

- event ID;
- workspace and Operator IDs;
- action kind;
- requested channel transition when applicable;
- prior and resulting control revisions;
- result and safe error code;
- request ID and timestamp.

API keys, passwords, Key Vault values, request bodies, connection strings, Azure resource IDs, and provider response bodies are prohibited fields.

## 6. Administrator APIs

All routes require the existing Operator cookie. Mutations additionally require an allowed same-origin request, CSRF token, current Operator password, and an idempotency key.

### Read APIs

- `GET /api/v1/admin/summary`
- `GET /api/v1/admin/ai`

Both responses use `Cache-Control: private, no-store` and `Vary: Cookie`.

### Mutation APIs

- `PATCH /api/v1/admin/ai/channels`
  - accepts `expected_revision`, desired `operator_enabled` and `demo_enabled`, and the current Operator password;
  - updates both flags in one database transaction;
  - does not permit either channel to start unless an exact Key Vault version has passed validation.

- `POST /api/v1/admin/ai/key-rotations`
  - accepts the candidate key and current Operator password as secret-valued request fields;
  - validates and activates one shared credential for both channels;
  - does not change either channel flag;
  - returns only the resulting fingerprint, verification time, revision, and safe result code.

The password and candidate key are represented as secret types, are excluded from object representations, and are cleared from local references after use. Request-body logging is forbidden for admin mutation paths.

## 7. Key-Rotation State Machine

Key rotation is a bounded saga because PostgreSQL, Azure Key Vault, and OpenAI cannot participate in one distributed transaction.

1. Authenticate the Operator session, origin, CSRF token, password, and idempotency key.
2. Acquire a PostgreSQL per-workspace control lock. A second operation returns `409 ADMIN_AI_OPERATION_BUSY`.
3. Read the prior exact Key Vault version and value into bounded server memory when a prior version exists.
4. Validate the candidate directly against the approved OpenAI base URL and the project-pinned model with a minimal, non-business prompt and bounded output. The call is non-retried.
5. If validation fails, discard the candidate and leave Key Vault, the control row, and channel flags unchanged.
6. Write the candidate as a new version of the canonical Key Vault secret.
7. Read that exact version back through the managed-identity provider and perform the same bounded validation.
8. If exact-version validation succeeds, atomically update `key_version`, fingerprint, verification time, revision, and audit event in PostgreSQL.
9. If a failure occurs after the Key Vault write, restore the prior value as a new latest version, retain the prior database version binding and channel flags, and record only a safe failure code.
10. If no prior credential exists and compensation is required, both channels remain disabled and the state becomes `unconfigured`.

An OpenAI timeout or network interruption is an unknown outcome. The controller does not automatically retry or activate the candidate.

## 8. Channel Switching

The AI Management page displays two separate controls:

- **Ordinary Login AI** for `/app` Operator requests;
- **Public Demo AI** for `/demo` requests.

Each transition requires current-password confirmation and the latest `expected_revision`. Turning a channel off rejects new turns for that actor kind before budget reservation or provider use. A turn already executing may finish. The other channel remains unchanged.

Turning a channel on requires:

- a non-null exact `key_version`;
- a successful validation timestamp for that version;
- a successful provider availability check bounded by the same no-retry policy.

The two channels always share the same credential version. The API and data model do not support per-channel keys.

## 9. Safe Status Projection

The overview refreshes every 30 seconds and immediately after a successful mutation. It reports only application-level states:

- database ready or unavailable;
- Blob ready or unavailable;
- configuration valid or invalid;
- current migration;
- current published dataset and recent workflow outcome;
- credential configured and verified state;
- ordinary-login and Demo AI channel states.

It does not expose Key Vault names, secret names, subscription or tenant IDs, managed-identity IDs, registry details, connection strings, stack traces, or raw exception messages. The browser never calls Azure control-plane or Key Vault APIs.

## 10. Failure Handling

- Missing or expired Operator session: document navigation redirects to login; API returns `401`.
- Invalid CSRF or origin: `403` with a stable safe code.
- Invalid current password: generic `401 ADMIN_REAUTHENTICATION_FAILED`, subject to the existing bounded authentication-attempt policy.
- Stale optimistic revision: `409 ADMIN_AI_STATE_CONFLICT` with the current safe projection.
- Concurrent control operation: `409 ADMIN_AI_OPERATION_BUSY`.
- Candidate rejected by OpenAI: `422 ADMIN_AI_KEY_REJECTED` without provider body details.
- Provider outcome unknown: `503 ADMIN_AI_VALIDATION_OUTCOME_UNKNOWN`; no automatic retry.
- Key Vault or managed-identity failure: `503 ADMIN_AI_SECRET_UNAVAILABLE`; prior state remains authoritative.
- AI channel disabled: AI turn returns a stable `503 AI_CHAT_CHANNEL_DISABLED` before provider use.

All admin responses are private and non-cacheable. Secret-bearing inputs are never echoed in validation errors.

## 11. Security and Azure Boundary

OpenAI credentials remain server-side. The browser submits a candidate only over the existing HTTPS origin, and the server stores the accepted credential only in Azure Key Vault. No credential is stored in PostgreSQL, Blob, HTML, JavaScript state persistence, local storage, session storage, cookies, logs, traces, receipts, or delivery documents.

The hosted application uses a task-owned managed identity and a least-privilege Key Vault data-plane assignment scoped to the canonical secret. It receives no Key Vault permission-management role and no general Azure control-plane mutation role. Key Vault audit diagnostics remain enabled.

The system continues to use the fixed approved OpenAI base URL, pinned project model, bounded timeouts, zero SDK retries for qualification, and existing AI spend and concurrency limits.

## 12. Test Strategy

### Unit and service tests

- channel selection for Operator and Demo principals;
- one shared exact secret version for both actor kinds;
- optimistic revision and PostgreSQL control locking;
- current-password verification without issuing a new session;
- candidate rejection before Key Vault write;
- exact-version readback activation;
- compensation after post-write failure;
- unknown provider outcome with no retry;
- provider cache isolation by secret version;
- append-only audit projection without secret values.

### API and security tests

- `/admin` and all child paths require Operator authority;
- Demo sessions cannot load the shell or call admin APIs;
- `next` redirects accept only allowlisted same-origin paths;
- every mutation requires origin, CSRF, password, and idempotency;
- API responses, exception representations, logs, database rows, HTML, and browser storage contain no submitted key or password;
- safe headers and no-store policy cover every admin response;
- rate limiting and body-size limits apply to reauthentication and rotation.

### Frontend tests

- operations-cockpit overview rendering;
- data workflow reuse without duplicated state authority;
- independent channel buttons and confirmation states;
- password and key inputs are cleared after success or failure;
- loading, conflict, validation-failure, rollback, and unavailable states;
- bilingual labels, keyboard operation, focus return, and accessible status announcements.

### Integration and hosted acceptance

Local integration uses fake OpenAI and Key Vault adapters. No real API key is used locally.

Hosted acceptance uses a fresh release package and performs, in order:

1. protected `/admin` entry and safe login return;
2. summary and data-management read checks;
3. one real candidate-key rotation through the admin page;
4. ordinary-login AI turn using the resulting fingerprint and version binding;
5. Demo AI turn using the same binding;
6. independent disable and enable checks for each channel;
7. rejected candidate check proving the prior key and channel states remain active;
8. secret-leak scans over responses, logs, audit rows, and saved delivery evidence.

Hosted success is not inferred from local tests, a successful image build, a reachable URL, or a Key Vault write alone. It requires both actor kinds to complete real hosted AI turns against the same activated credential version.

## 13. Delivery Boundary

Implementation will use test-driven development and a detailed implementation plan after this document is reviewed. Deployment, Azure identity or role changes, Key Vault writes, and hosted credential validation are separate evidence states.

No stopped or failed authorization package may be replayed. Any hosted release or AI activation must be generated fresh from the exact implementation commit, exact image digest, current authority files, and a newly observed Azure baseline.
