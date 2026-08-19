# NEWCaostone Azure Launch Handoff

<!-- authority:current:start -->
Current deployed and development facts are generated from `bizpulse/release/current_authority.json`.

- Deployed candidate: `537effe3036f77f83225beef12589bd447205a8b`
- Deployed attestation: `168349f0d6242405f37fa9a44dbad17f03063d96`
- Deployed image: `sha256:2a95c20046cde04a383a280b350a450c15cc7c46df92e1e8eaf5014eeb5c8512`
- Deployed revision: `newcaostone-demo-app--recover-78eaaf31-2a95c20`
- Hosted migration: `0008_ai_budget_ledger`
- Hosted AI: `disabled`
- Attested rollback candidate: `537effe3036f77f83225beef12589bd447205a8b`
- Attested rollback image: `sha256:2a95c20046cde04a383a280b350a450c15cc7c46df92e1e8eaf5014eeb5c8512`
- Repository migration: `0017_ai_turn_credential_binding`
- Repository AI capability: `implemented`
- Observation: `2026-08-16T01:26:00Z`
- Observation expires: `2026-08-16T20:25:35Z`
- This block grants no Azure, registry, secret, paid-AI, push, PR, CI, or deployment authority.
<!-- authority:current:end -->

## Supersession notice

This historical launch handoff is not a continuation authority. The generated
snapshot above expired when the 2026-08-16 partial release attempt began. Read
`CURRENT_STATUS.md`, `docs/handoffs/CURRENT_HANDOFF.md`, and
`bizpulse/docs/operations/2026-08-16-two-stage-release-partial-failure.md`
instead. Do not replay any command in this file.

<!-- authority:history:start -->

Last updated: 2026-08-15 (America/Chicago)

Handoff marker: the user originally paused implementation, verification, Git,
image, package, and Azure execution while this handoff was finalized. The user
subsequently explicitly resumed **local** inspection and verification. No
registry, Azure, Keychain, secret, provider, or paid operation resumed. A
successor must still not resume merely because this document exists; it needs a
fresh explicit user instruction and, for any external mutation, a new exact
SHA-bound package approval.

This document is the operational handoff for the bounded pure-synthetic Azure
Demo. It records identifiers, credential locations, failure history, current
evidence, and the exact continuation boundary. It deliberately contains no
password, credential hash, access token, connection string, storage key,
session pepper, or API key value.

## Current outcome

- Public URL: `https://newcaostone-demo-app.delightfulstone-15318d59.centralus.azurecontainerapps.io`
- Current source candidate: `3e933d083b3ab4dba36d8053f56ecf2d68d31f1e`
- Current attestation child: `cda718a0869bc8bb815ebe632e728c266f588d39`
- Current immutable image: `sellernorthbpacr.azurecr.io/bizpulse@sha256:95088291d0d9402d3b580b3fde5afce816bcc5281d1281be088cb1cbe713e1c7`
- Current image-input SHA-256: `69e53aecd6659df38db57c8090f8adf1363263c9d356b47c8a857f199a93f885`
- Ready revision: `newcaostone-demo-app--95088291d0d9`
- Runtime state: external HTTPS, Single revision mode, 100% latest traffic,
  one ready replica, PostgreSQL/Blob/foundation healthy, migration
  `0008_ai_budget_ledger`.
- AI state: disabled. There is no OpenAI secret, secret reference, base URL, or
  authorized paid-provider call in the deployed application.
- Evidence boundary: the application is online and healthy, but hosted
  browser/capacity/natural-expiry/restart/rollback acceptance is incomplete.
  It is not Production-ready.

Historical references below to `2173222`, `78e9e62`, or `cb77be5` describe
prior consumed package attempts only; they are not current runtime or rollback
authority.

## Azure identity and resource authority

| Authority | Exact value | Handling rule |
|---|---|---|
| Azure CLI user | `jialimax@outlook.com` | Authentication is owned by Azure CLI/macOS; no token is stored in this repository. |
| Tenant | `13d04c38-d91c-4f9f-8b65-6af2b515dd63` | Read before every future package execution. |
| Subscription | `fc89e7d3-5428-425e-863f-415859810c2c` (`Azure subscription 1`) | Must remain Enabled and match the next package exactly. |
| Resource group | `rg-bizpulse-centralus` | Contains NEWCaostone plus older unrelated SellerNorth resources; do not delete by prefix alone. |
| Region | `centralus` | Exact package value. |
| ACR | `sellernorthbpacr.azurecr.io`, repository `bizpulse`, Basic | ACR admin is disabled. Image pulls use managed identity, not a registry password. |
| Registry identity | `newcaostone-demo-registry` | Client ID `165532fa-1751-4fa8-8ccd-f60fcfd260c6`; principal ID `2162f54b-1ff6-4ece-bf81-8f3d7c467038`. |
| Container Apps environment | `newcaostone-demo-env` | Task-owned. |
| Application | `newcaostone-demo-app` | Task-owned public Demo surface. |
| Jobs | `newcaostone-demo-prepare`, `newcaostone-demo-seed`, `newcaostone-demo-sessions`, `newcaostone-demo-storage` | Exact job image/command/schedule is verified by phase fences. |
| PostgreSQL | `newcaostone-demo-pg`, administrator `bpoperator`, PostgreSQL 16 | Private network only; no password in files or argv. |
| Storage | `newcaostonedemost`, Standard_LRS | App/Jobs receive a server-generated Blob connection string as an Azure secret. |
| Monitoring | `newcaostone-demo-logs`, `newcaostone-demo-insights` | No secret values in handoff or release evidence. |
| Network | `newcaostone-demo-vnet`, private DNS `private.postgres.database.azure.com` | Preserve exact private PostgreSQL binding. |

The same resource group contains pre-existing `sellernorthbp-*` staging and
Course Demo resources. They were inspected read-only and were not required for
NEWCaostone. They are not implied cleanup targets and must not be deleted unless
a future value-complete cleanup package proves an exact blocker and the user
approves that package hash.

## Accounts, passwords, hashes, and keys

### macOS Keychain authorities

The launch controller reads these entries in memory. Values are never printed,
serialized, placed in a package, or passed in process arguments.

| Purpose | Keychain service | Keychain account | Child-process name / use |
|---|---|---|---|
| Operator login plaintext | `NEWCaostone Azure Demo Operator Password` | `operator` | `BIZPULSE_BROWSER_OPERATOR_PASSWORD`; used only by the protected operator browser flow. |
| Operator Argon2id hash | `NEWCaostone Azure Demo Operator Password Hash` | `operator` | `BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH`; verified against the plaintext before injection. |
| PostgreSQL administrator password | `NEWCaostone Azure Demo PostgreSQL Password` | `bpoperator` | `BIZPULSE_DEPLOY_POSTGRES_PASSWORD`; injected only into Bicep/Job child environments. |
| Demo session pepper | `NEWCaostone Azure Demo Session Pepper` | `newcaostone-demo-app` | `BIZPULSE_DEPLOY_SESSION_PEPPER`; server-side cookie/session authority. |

If macOS displays a dialog saying `security` wants to access one of these
items, do **not** infer the required password from its wording or screenshot.
First identify the triggering process and exact Keychain service/account, or
cancel and retry after that authority is confirmed. It may be a normal macOS
login-Keychain authorization, but it is never safe to paste a Demo operator,
Azure, database, session, or API secret into chat or a repository file to
bypass the prompt.

The Keychain entries were proved present during the last approved V3 launch,
because the controller loaded them and completed migration/seed/Phase 2. This
handoff does not re-read them, to avoid another unnecessary Keychain prompt.

### Application and Job secret names

The current Container App exposes exactly these Azure secret **names**:

- `database-url`
- `blob-connection-string`
- `operator-password-hash`
- `session-pepper`

The values are secure ARM parameters or are generated inside Bicep from the
task-owned PostgreSQL/Storage authority. Phase 1 exposes no application
secrets. Jobs receive only the exact four required authorities. A normal no-AI
Phase 2 also contains exactly those four names.

There is no `openai-api-key` secret and no `OPENAI_API_KEY` environment
reference. A future AI task must use a separate explicit paid-AI package,
dedicated low-value key, hard budget, no SDK retry, fixed smoke cases, and
immediate revocation. That future work is not authorized by this handoff.

### Other identities

- Demo operator login name: `operator`.
- Repository-local Git identity: `Max Li <1229391595max@gmail.com>`; global Git
  configuration was not changed.
- ACR authentication: user-assigned managed identity only; ACR admin is false,
  so there is no ACR username/password to transfer.
- Azure CLI credential/token: owned by the Azure CLI signed-in session; never
  copy its cache or tokens into this project.
- Blob storage key and PostgreSQL URL: never retrieve for handoff prose. Azure
  constructs/injects them through secure parameters and secret references.

## Recent launch failures and what they proved

| Attempt | Exact result | Resolution / current rule |
|---|---|---|
| Cleanup `85541eae...` + launch `fe23c464...` | Phase 1 used the normal API before migrations, so startup queried missing `analysis_runs`. | Added a dependency-free Phase 1 fence server, internal ingress, zero replicas, and exact drain verification before migration. Both packages are consumed. |
| Cleanup `bbf28cea...` + launch `1c847705...` | Migration/seed/Phase 2 ran, but the Operator Argon2 hash changed after process restart and final authority failed. | Persist one verified Argon2id hash in Keychain and verify it against the same plaintext before every phase. Both packages are consumed. |
| Cleanup `a0d46c3d...` + launch `c874b753...` | Runtime became healthy, but hosted checks rejected Azure resource-ID casing and Python.org CA trust differed from macOS trust. | Commit `b055093` compares Azure IDs case-insensitively while preserving full binding and uses the verified macOS system trust path. Both packages are consumed. |
| Update `a8a0430e...` | Read-only preflight rejected a stale rollback image named in the package. | Promote the exact healthy deployed image as the next rollback authority; never substitute a remembered digest. Package consumed without write. |
| Update V2 `d2a4f0ef...` | Published `2173222`, migrated, and seeded, then activate fence found maintenance executions newer than package issuance. | Package stopped private/min-zero. A fresh package/authorization was required. V2 is consumed. |
| Update V3 `760967c4...` | Completed migration/seed replay, Phase 2, maintenance, final fence, and health. Browser admitted Viewer and Operator, then found no Action Card. | Root cause: the local acceptance helper manually created an Action while the production hosted seed did not. V3 is consumed; no capacity/expiry/restart/rollback ran. |
| First local Action successor | It generated only a replenishment Action. The browser's imported v2 is sales-only, so replenishment had no exact SKU authority and publication failed `PUBLIC_RELEASE_INELIGIBLE`. | Public Action authority now uses replenishment when complete and an exact Profit Bridge evidence-review Action when inventory/policy are missing. Missing data stays explicit; it is not zeroed. |
| Local real-Chrome successor | Python's 90-second outer process timeout killed an otherwise bounded browser flow before its precise error surfaced. | Outer local gate is 180 seconds; every Chrome/CDP and UI wait remains independently bounded. The fixed full real-Chrome vertical passed in 52.96 seconds and proved the current v2 has an approved Action. |
| Local test invocation | One RED command accidentally used system Python and failed to import `psycopg`. | Not a product/Azure failure. Use `bizpulse/.venv/bin/python scripts/test_postgres.py ...`. |

## Packages and retry authority

- All cleanup/launch/update hashes listed above are consumed. Do not rerun
  them, even if a command appears idempotent.
- Current V3 package:
  `.tmp/LAUNCH_AUTHORIZATION_HOSTED_AUTHORITY_UPDATE_V3.md`, SHA-256
  `760967c477b41af4e56f02c7bd3f41ca5c3fb763e3a6e22d236679bd5d906b87`,
  mode `0600`, consumed.
- The `.tmp` directory is ignored local working material. It may contain old
  packages and controllers but no package is authority without exact current
  Git/image/manifest binding plus an unexpired user-approved full SHA-256.
- Healthy PostgreSQL, Blob, ACR, network, monitoring, and current runtime must
  be preserved. No cleanup package is currently needed.

## Current local successor state

The implementation worktree contains the bounded Action/publication repair and
documentation changes. Git `HEAD`, worktree status, and the eventual direct
manifest child—not this handoff prose—determine whether it is committed and
which exact successor it represents.
Local PostgreSQL verification is green, including the new same-version
deduplication path. The exact browser gate was subsequently run from the
native macOS Terminal with its required PostgreSQL wrapper and passed `2` tests
in `23.26s`; it covers the static timeout contract plus the real browser
release gate. The Codex terminal sandbox still cannot launch Chromium, but
that is an environment limitation only and must not be "fixed" by modifying
the user's Chrome installation. Complete release verification, a focused final
review, candidate commit, Linux/amd64 image, manifest-only child, detached
attestation, and a new mode-`0600` no-AI update package are still required.

### Exact continuation point

- Worktree: `/Users/maxli/Desktop/NEWCaostone/.worktrees/implementation`
- Branch: `codex/newcaostone-implementation-v3`
- The deployed baseline is `cb77be510c2bd4e8c8fdcafcbe260bd0aba89439`.
  Resolve the successor's `HEAD` and clean/dirty state with Git at continuation
  time; no successor is attested, built, published, deployed, or
  hosted-accepted until its direct manifest child and detached verifier prove
  it.
- The checked-in `bizpulse/release/task15-local-release-manifest.json` is
  intentionally deleted in the working diff. A replacement may be created only
  after the new candidate commit and fresh release verification.
- The same-version Action-deduplication regression is now green. The focused
  PostgreSQL set is `36 passed in 23.15s`.
- The earlier complete Python run reached `517 passed, 3 skipped, 1 failed`
  only because the Codex-terminal Chromium host failed before an application
  assertion. It is historical environment evidence, not a remaining product
  test failure: the exact native-Terminal command subsequently passed `2` tests
  in `23.26s`.
- Do not claim the successor fully release-verified until the wider release
  gates, candidate image, direct manifest child, and detached verifier pass.

The original pause-point successor scope was:

```text
M  AUTHORIZATION_LEDGER.md
M  CURRENT_STATUS.md
M  bizpulse/api/container.py
D  bizpulse/release/task15-local-release-manifest.json
M  bizpulse/scripts/browser_release_gate.mjs
M  bizpulse/scripts/seed_demo.py
M  bizpulse/scripts/verify_release.py
M  bizpulse/src/services/public_release_service.py
M  bizpulse/src/synthetic/seed.py
M  bizpulse/tests/acceptance/support.py
M  bizpulse/tests/acceptance/test_browser_smoke.py
M  bizpulse/tests/acceptance/test_rollback_compatibility.py
M  bizpulse/tests/hosted/test_seed_demo_script.py
M  bizpulse/tests/integration/test_synthetic_seed.py
M  bizpulse/tests/release/test_release_scripts.py
M  bizpulse/tests/services/test_ai_chat_container.py
M  bizpulse/tests/services/test_public_release_service.py
M  docs/handoffs/CURRENT_HANDOFF.md
?? bizpulse/src/services/demo_action_authority.py
?? docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md
?? docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md
```

Use `git status --short` rather than this historical scope list before staging.

### Successor repair now present but not fully closed

1. `DemoActionAuthority` now owns an idempotent approved Action authority for
   each public release version.
2. It prefers an exact replenishment Action when the deterministic result has a
   usable SKU, quantity, date, and priority.
3. For a legitimate sales-only imported version with unavailable inventory or
   policy evidence, it creates an exact Profit Bridge evidence-review Action.
   Unknown inputs stay unknown; the fallback does not invent a replenishment
   quantity and does not turn missing values into zero.
4. `PublicReleaseService` now prepares and verifies this Action before a version
   may become public.
5. `ApiContainer` wires that authority into the real cloud service graph.
6. The real-Chrome acceptance fixture now uses the production hosted seed path
   instead of manually inserting an Action that masked the production gap.
7. `scripts/seed_demo.py` now prepares Action authority for both the fixed
   synthetic seed version and the current public version, deduplicating them.
   This last current-version backfill is what repairs the already-public Azure
   v2 when the idempotent seed Job is replayed.

### Verification evidence after local continuation

- Service RED/GREEN for publication Action eligibility: passed after the new
  authority was wired.
- Container wiring test: passed.
- Demo Action authority test: passed.
- Focused PostgreSQL migration, seed, publication, container, and hosted-seed
  combination: `36 passed in 23.15s`.
- Production-path full real-Chrome vertical: `1 passed in 52.96s`; it imported
  and published v2 and then proved the current v2 had an approved Action.
- Hosted seed current-version and same-version deduplication tests:
  `4 passed in 0.51s`.
- Manual local in-app-browser evidence (task-owned PostgreSQL/Azurite only): a
  public Demo session loaded Overview and evidence/limitation states, opened the
  evidence-backed replenishment Action, recorded a synthetic review, opened the
  server-pinned Ask-about-this context, and ended the chat session. Returning to
  Action Inbox showed the session overlay had been cleared. Browser console
  errors were empty. This is useful interactive evidence only; it does not
  replace the exact terminal/CI browser gate.
- Exact native-Terminal browser command:
  `cd /Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse && .venv/bin/python scripts/test_postgres.py tests/acceptance/test_browser_smoke.py -q -rs`
  passed `2` tests in `23.26s`. The historical `517 passed, 3 skipped, 1
  failed` result remains a Codex-terminal Chromium-host limitation only.
- Full Node, full release, Bicep, Docker image, detached-attestation, and
  independent final review gates have not been rerun on this dirty successor.

### First safe command after an explicit resume

The browser evidence is already captured. Inspect the complete diff, rerun
focused release checks as needed, and continue the verification sequence below.
Do not run an old launch controller or any Azure command as the first action.

## Exact continuation sequence

1. Finish all local PostgreSQL/Node/browser/release/infra checks and independent
   review; stop on any Critical or Important finding.
2. Commit the successor candidate using `2173222` / `sha256:78e9e62...` as the
   exact compatible rollback baseline.
3. Build and inspect the exact Linux/amd64 image, then add only the direct
   Task15 manifest child and pass detached attestation.
4. Refresh Azure read-only authority and generate one restricted no-AI
   `target_mode=update` package. No cleanup package is expected.
5. Present the package's complete SHA-256 to the user. No registry/Azure/Job or
   hosted mutation may occur until that exact hash is approved.
6. After approval, run continuously in the package's exact order and preserve
   the longer bounded waits: registry verify, private Phase 1, migrate, seed,
   activate, canonical Phase 2, maintenance, health, browser, exact-15,
   natural expiry, restart readback, rollback/forward readback.

## Stop conditions

- Any secret value appears in a file, diff, log, command argument, or chat.
- Current Azure image/revision/traffic/AI/secret state differs from this file.
- The next package names any target, digest, rollback, command, cost, secret
  presence, or retry allowance different from its approved SHA-bound content.
- PostgreSQL/Blob authority is missing or a migration downgrade is proposed.
- A consumed package is reused, or the next package is executed before exact
  hash approval.
- Any result is described as hosted accepted or Production-ready before every
  required hosted gate has actually passed.

## Files a successor must read in order

1. `docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md`
2. this file
3. `docs/handoffs/CURRENT_HANDOFF.md`
4. `CURRENT_STATUS.md`
5. `AUTHORIZATION_LEDGER.md`
6. the approved design and the active remediation plan named in
   `docs/handoffs/CURRENT_HANDOFF.md`
7. `git status`, `git diff`, and the exact files changed above

Conversation summaries are navigation aids only. They are not authority for
completion, credentials, external mutation, or exact package approval.

<!-- authority:history:end -->
