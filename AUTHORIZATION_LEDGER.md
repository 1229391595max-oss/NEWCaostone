# NEWCaostone Authorization Ledger

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

<!-- authority:history:start -->

## 2026-08-16 consumed two-stage package incident

The user approved exact package SHA-256
`084ee41e9c79bb96b8e60cd3ac417cac30e9e8f18af5de88ab0304a2374493b6`.
Stage 1 published and verified candidate image
`sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`,
updated the prepare and seed Job images, and completed prepare execution
`newcaostone-demo-prepare-pc747ae`. Seed execution
`newcaostone-demo-seed-8a8k7de` failed with `seed_authority_mismatch` because
the candidate seed image was paired with the preceding manifest/version
arguments. Execution stopped before application deployment, traffic change,
hosted acceptance, restart, rollback rehearsal, AI qualification, Key access or
paid calls. The package is consumed and grants no retry or continuation
authority. Exact evidence and the recovery boundary are recorded in
`bizpulse/docs/operations/2026-08-16-two-stage-release-partial-failure.md`.

Last checked: 2026-08-15 (America/Chicago)

## Current external authority correction

A 2026-08-15 read-only Azure snapshot supersedes historical “current” values
elsewhere in this ledger. The live bounded synthetic target is candidate
`3e933d083b3ab4dba36d8053f56ecf2d68d31f1e`, direct attestation child
`cda718a0869bc8bb815ebe632e728c266f588d39`, and immutable digest
`sha256:95088291d0d9402d3b580b3fde5afce816bcc5281d1281be088cb1cbe713e1c7`
with image-input
`69e53aecd6659df38db57c8090f8adf1363263c9d356b47c8a857f199a93f885`.
It is external HTTPS, Single mode, 100% latest traffic, one ready replica, and
AI-disabled. A future update must use that exact current pair as rollback;
every `2173222`/`78e9e62` reference below is historical only. All earlier
packages are consumed. No new registry, Azure, Keychain, secret, provider, or
paid operation is authorized until the user approves a newly generated exact
package SHA-256.

Current control state: the user subsequently explicitly resumed bounded local
inspection and verification after the handoff pause. This permits task-owned
Docker/PostgreSQL test infrastructure, review, and handoff updates; it does
not authorize registry, Azure, Keychain, secret, provider, paid, or other
external mutation. A new exact SHA-bound package approval remains required for
every future external write.

## Active local implementation authority

The user explicitly authorized the following local actions, and they were executed within NEWCaostone unless marked read-only:

- fully read the approved `v0.2.0` design;
- inventory files and Git state before and after initialization;
- initialize a local Git repository on `main`;
- create `.gitignore`;
- remove accurately located `.DS_Store` files and task-owned temporary/cache files only;
- update only the design's approval status without changing confirmed product scope;
- inspect CAPTSONE tracked files, exact commits, formal entry, migrations, histories, and tests read-only;
- write Stage 0 audit, reuse ledger, current status, authorization ledger, handoff, and detailed implementation plan;
- stage intentional local files and create one initial local checkpoint only if an existing Git identity is available;
- run local read-only/static hygiene validation.

The user subsequently approved the implementation plan and explicitly directed continuous execution in this chat. That approval authorizes ordinary local feature implementation, dependency installation, synthetic PostgreSQL/Azurite test infrastructure, local servers/browser checks, task-owned temporary cleanup, review, documentation, and local Git commits described by the plan. It does not authorize any external mutation.

On 2026-08-14 the user additionally authorized reading Azure configuration/state and asked for deployment assistance. This authorizes bounded read-only subscription, resource, provider-registration, cost, backup, network, registry-metadata, name-availability, and configuration inspection. The user's conditional permission to modify/delete older Azure resources does not identify an exact destructive target and therefore does not by itself authorize deletion; exact resources must first be proved to block launch and listed in the future value-complete package.

## Executed local actions

- NEWCaostone `git init -b main`: executed.
- After the handoff continuation, Docker Desktop was started by the user and a
  task-owned PostgreSQL 17 container was used only for ephemeral test databases.
  The focused set passed `36`; the complete Python suite reached `517 passed,
  3 skipped, 1 failed`. The sole failure was a local Chrome launch abort before
  any application assertion. No Azure or secret authority was accessed.
- `.gitignore`: created.
- Design approval status: updated; v0.1.0 unchanged.
- Exact `.DS_Store` cleanup: executed; ignored copies can be recreated by Finder and are checked again at closeout.
- CAPTSONE audit: read-only commands only.
- Stage 0 documents and implementation plan: created.
- Repository-local Git identity: configured after the user explicitly authorized the exact name/email; global Git configuration was not changed.
- Initial checkpoint commit: created locally as the parentless root commit on `main`; no remote or publication action accompanied it.
- Isolated implementation worktree/branch: created locally under `.worktrees/implementation` on `codex/newcaostone-implementation`.
- Approved plan Tasks 1-12: implemented and locally committed through `99f17bd`.
- Task 8 local verification: Ruff, the complete PostgreSQL-backed Python suite (`164 passed, 3` controlled Azurite-only skips), all `36` frontend Node tests, and the local browser checkpoint passed. Independent review reported no Critical or Important issue.
- Task 9 local verification: Ruff, the complete PostgreSQL-backed Python suite (`195 passed, 3` controlled Azurite-only skips), all `42` frontend Node tests, staged hygiene, unchanged approved-design hash, and independent review passed. Independent review reported no Critical or Important issue.
- Task 10 local verification: Ruff, the complete PostgreSQL-backed Python suite (`206 passed, 3` controlled Azurite-only skips), all `48` frontend Node tests, staged hygiene, unchanged approved-design hash, and independent review passed. Prior FIFO coverage, discontinued-SKU assumptions, and exact default-scope authority were corrected before the reviewer reported no Critical or Important issue.
- Task 11 local verification: Ruff, the complete PostgreSQL-backed Python suite (`234 passed, 3` controlled Azurite-only skips), all `54` frontend Node tests, staged hygiene, unchanged approved design, and independent review passed. Exact evidence authority, immutable decisions, viewer pinning/expiry, durable safe export, bounded synthetic overlays, and operator outcome review were verified before the reviewer reported no Critical or Important issue.
- Task 12 local verification: Ruff and compile checks, the complete PostgreSQL-backed Python suite (`288 passed, 3` controlled Azurite-only skips), all `54` frontend Node tests, fixed fake-provider evaluations, staged hygiene, unchanged approved design, and independent review passed. The reviewer reported zero Critical, Important, and Minor findings. No real OpenAI Key was read, written, or validated, and no provider or paid request was made.
- Task 13 local verification: Ruff and compile checks, the complete PostgreSQL-backed Python suite (`301 passed, 3` controlled skips), all `76` frontend Node tests, real-browser UI state checks with fake providers, unchanged approved design, staged hygiene, and independent review passed. The reviewer reported zero Critical and Important findings.
- Task 14 local implementation and pre-candidate verification: security middleware, safe telemetry, exact-15/restart/rollback acceptance, real-Chrome public/operator/Chat/Action/import/publish/export checks, strict release verification, and detached two-commit attestation were implemented. The complete PostgreSQL-backed suite passed `346` with `3` controlled skips; all `78` frontend tests, Ruff, compile, and diff checks passed. Independent review reported zero Critical, Important, and Minor findings and Ready to commit. No real provider, remote, registry, Azure, DNS, secret, or paid operation was performed.
- Task 14 release authority is deliberately two-step: the reviewed candidate parent is followed by a manifest-only direct child; only a successful detached-candidate `--verify-attestation` makes the exact parent SHA Locally verified. Neither commit authorizes or proves CI, deployment, hosted acceptance, Azure acceptance, or Production readiness.
- Task14 candidate `6e5c1f98d3a68716ec687611dc3ccd03f44f2e7f` and manifest-only child `65ba0c9228b9dd53670f026fe188a42f74c26c37` were created locally; detached attestation succeeded.
- Task15 local deployment/recovery foundation checkpoint `4f33d7d3fdb6e2c9df146d2a1be7a5406362d32b` was created. It includes no Azure, registry, secret, provider, DNS, or hosted mutation. It is the new `0008`-compatible rollback-source baseline, not a deployed image or external rollback point.
- The first real Linux/amd64 Docker build found that `4f33d7d` lacked a hash-locked Linux-only SQLAlchemy dependency. The exact failure was retained as evidence; no incomplete image was tagged. Successor `c357c87d216715e215886e6bbaf31d9de6ab93fe` adds only the tested `greenlet==3.5.5` Linux wheel hash and is the buildable `0008`-compatible rollback-source baseline.
- Task15 focused local PostgreSQL, hosted/infra, authorization, registry-binding, Bicep, Ruff, compile, and diff checks were run. Exact local Linux/amd64 images for reviewed code checkpoint `ab7182197ce6c3bae10cf6f771a4696da4f874f5` and rollback baseline `c357c87` were built, inspected, and run against task-owned PostgreSQL/Azurite plus local HTTP health probes. Their local Docker IDs and image-input hashes are recorded in `CURRENT_STATUS.md`; neither is a registry digest or external authority.
- Task15 fresh pre-candidate verification passed `464` PostgreSQL-backed Python tests with `3` controlled skips, `79` frontend Node tests, Ruff, Python compile, `git diff --check`, and zero-warning local Bicep compilation. These results do not authorize or prove Docker, registry, Azure, provider, paid, hosted, or deployment state.
- A first Task15 attestation attempt (`de239217` candidate, `8198f600` manifest child) completed locally and then exposed time-dependent `pending` wording in its parent status/handoff. It is retained recoverably on branch `codex/newcaostone-implementation-v2`, but it is not the final Task15 authority.
- Final Task15 local authority is intentionally conditional and non-self-referential: the exact candidate and manifest-child SHAs come from Git plus `bizpulse/release/task15-local-release-manifest.json`, and local verification exists only when the child changes that single path, directly parents the named candidate, and a fresh detached `--verify-attestation` succeeds. This rule remains accurate in both the candidate parent and its manifest child.
- Azure CLI read-only discovery: executed for the single enabled subscription, resource groups/resources/locks/providers/role assignments, PostgreSQL configuration and backup metadata, storage/network/monitoring configuration, ACR repository/digest/authentication metadata, name availability, budget, and current actual cost. No access token, password, connection string, Key Vault value, or other secret was requested or returned.
- The read-only result selected existing ACR `sellernorthbpacr` for possible reuse and fresh prefix `newcaostone-demo` in `rg-bizpulse-centralus`. Existing staging/Course Demo resources are not required by the new topology and are not blockers, so no Azure deletion is proposed. `Microsoft.App` registration and all other external changes remain pending the exact launch package.
- The exact local preflight runner subsequently returned `azure_preflight=ok` against those live read authorities. It did not request a registry access token, expose a credential, register a provider, or mutate a resource.
- The managed-identity successor pre-candidate verification passed `475` PostgreSQL-backed Python tests with `3` controlled skips, all `79` frontend tests, Ruff, compile, diff, and zero-warning Bicep checks. These remain local evidence only.
- The user explicitly approved cleanup package SHA-256 `85541eae793c5d8810459f99a6431f5784d2cf92bf8077514e032023859335cf` and restricted no-AI launch package SHA-256 `fe23c4643847fccb46974e01e068de667074fd7fded3d29b9ded97b3eaea7718`, then confirmed continuous execution. The cleanup completed its exact `22/22` bounded targets while preserving ACR, Git, Keychain, and unrelated resources. The launch published immutable current digest `sha256:9c4cd507...` and retained rollback digest `sha256:c4073fd0...`, then created fresh private Phase 1 resources with AI disabled.
- That launch stopped before migration when the normal API startup path attempted `AnalysisRepository.recover_running` against the not-yet-created `analysis_runs` table. No migration, seed, Phase 2 activation, public ingress, hosted acceptance, paid provider call, or Production claim followed. Both exact packages are consumed and grant no retry authority.
- The user approved the dependency-free fenced-bootstrap design and implementation plan. Local implementation Tasks 1-4 produced commits `094c7c9`, `19cba66`, `a891152`, and `0c0f026`. This local authority includes testing, documentation, candidate construction, local Docker build/inspection, detached attestation, and generation of replacement packages; it does not authorize Azure cleanup or relaunch.
- The user later explicitly approved cleanup package SHA-256 `bbf28ceadab0fda1d1317613d818b1460d5fd3dc4cef9f90d6ff514280b5dc52` and restricted no-AI launch package SHA-256 `1c8477051e7e924371baeb35a26acdac476b9c80f7f7014d14fa0039032ffcc1`, confirmed continuous execution, and authorized safe generation/injection of the already declared random credentials. Cleanup completed its exact `20/20` scope while preserving ACR, Git, Keychain, and unrelated resources. The launch published and verified the exact current/rollback images, completed Phase 1, migration, synthetic seed, Phase 2 ARM, and both maintenance Jobs, then stopped at the final Phase 2 fence because the operator Argon2 authority drifted across a process restart. No hosted gate or paid AI ran. These two packages are consumed and grant no retry authority.
- The user further directed maximum-effort launch assistance while retaining the stated no-AI boundary. Local diagnosis, Microsoft-documentation lookup, remediation design/plan, tests, commits, image/package preparation, and read-only Azure refresh are authorized. Every new external execution still requires its replacement package's exact SHA256 approval; general intent does not substitute for value-complete command authority.
- The user explicitly approved cleanup package SHA-256 `a0d46c3de40cd3a68c79189e2772649f4fe1c9549600c9fe413756628e4e501b` and restricted no-AI launch package SHA-256 `c874b75314774fb259aa5807965f0a30d9892c4b14d30e0a3e3cad286487db45` for continuous execution. Cleanup completed its exact `21/21` target set while preserving ACR, Git, Keychain, and unrelated resources. The launch published/verified exact current and rollback images, completed Phase 1, migration `0008`, pure-synthetic seed, Phase 2, both maintenance Jobs, and the final phase2 fence. Exact public live/ready reads are healthy and AI remains disabled. Hosted acceptance stopped before browser execution because the local runner compared Azure resource-ID casing literally and Python.org's CA file did not use the macOS system trust store. These packages are consumed and grant no retry authority.
- Microsoft documents that Azure resource names may be returned with different casing and must be compared case-insensitively. Local hotfix `b055093` preserves full resource-ID binding with `casefold()` and uses a verified system-trust TLS context without disabling certificate or redirect validation. Focused hosted/infra/release verification passed `159`; direct hosted health returned `hosted_check=ok`. This is local/read-only evidence only. A new exact restricted no-AI `target_mode=update` package requires explicit complete-SHA approval before any further registry publication, Azure update, Job execution, restart, rollback rehearsal, or hosted acceptance check. Healthy PostgreSQL/Blob resources are not approved for cleanup.
- Hosted-authority hotfix candidate `f18368866503f7584fb139e64dd771584a5bb0c2` was fully verified, built as exact Linux/amd64 image `sha256:f5ec761afde1c71f6c09930357f83d93db4dd8dabce08f43fe30f1288dac3a46`, and locally attested by manifest-only child `27833f9cd423c8b4610b871ac5a48dbcf974f3a6`; detached verification returned `release_attestation=ok`.
- The user approved restricted no-AI update package SHA-256 `a8a0430e5dadba2284c7de94db122448d4e9441a51cde563f0c48a3401c52f9b`. Execution loaded only the declared Keychain credentials in memory and stopped at the first read-only update preflight with `azure_preflight_current_release_invalid`; no registry publication, provider registration, Azure mutation, Job, hosted check, cleanup, or paid AI occurred. The mismatch was fail-closed evidence that the package still named `8896/c407` as rollback while the exact healthy current deployment is `60e4ca5` / `sha256:10a376...`. This package is consumed and grants no retry. A new candidate/manifest/package must promote the current deployment as rollback authority.
- The user approved successor update package SHA-256 `d2a4f0efbd5ae9c0baa7614e92d7e4c6121ea04282e4a8dd631e20de8955284d`. It published/verified the exact `2173222` image, completed Phase 1, migration, and seed, then stopped at the activate fence because valid maintenance executions occurred after package issuance but before Phase 1 switched the Jobs to Manual. The app remained private/min-zero; the package is consumed.
- The user then approved V3 package SHA-256 `760967c477b41af4e56f02c7bd3f41ca5c3fb763e3a6e22d236679bd5d906b87` and authorized resume from migration. It completed migration/seed replay, activate, Phase 2, both maintenance Jobs, final phase2 fence, and health. The exact `2173222` / `sha256:78e9e62...` app is public, Single, 100% latest, migration `0008`, and AI disabled. Browser acceptance admitted a Viewer and logged in the Operator, then stopped before export/import because the fresh hosted seed had no Action Card; local browser setup had created one separately. Capacity, natural expiry, restart, and rollback did not run. V3 is consumed and grants no retry.
- The hosted seed-action/current-release remediation is locally implemented: it prepares an exact replenishment Action when complete and an exact Profit Bridge evidence-review Action for legitimate sales-only versions, then reviews/approves it. Hosted seed replay targets both the fixed seed version and the current public version and deduplicates identical IDs. It does not execute an external business action or enable AI. Same-version deduplication and the exact native-Terminal real-browser gate now pass (`2 passed in 23.26s`); Git plus the eventual direct manifest child, rather than this ledger, determine its candidate identity. A complete release verifier, independent review, exact Linux/amd64 image, direct manifest child, and restricted no-AI update package remain required before any further Azure write or hosted command.

## Explicitly not authorized and not executed

- modifying, indexing, cleaning, committing, rebasing, resetting, checking out, or generating any file in CAPTSONE;
- copying the entire CAPTSONE repository or any unverified module;
- reading or using real/private business data;
- Google Trends or any online market source;
- real OpenAI API request, Key validation, Key read/write, or paid API call;
- creating a Git remote, GitHub repository/branch/PR, push, CI dispatch, or registry publication;
- any Azure provider registration, resource creation/update/delete, migration, deployment, restart, hosted verification, registry-token retrieval/publication, or cost-bearing action beyond the already consumed exact packages;
- DNS/custom-domain/Cloudflare change;
- external business-system write;
- permanent deletion, database destruction, Blob deletion, branch/worktree deletion, or cleanup beyond exact `.DS_Store`/task temporary files;
- modifying global Git configuration.

## Local plan gate

The implementation plan at `docs/superpowers/plans/2026-08-13-newcaostone-demo-single-operator-implementation.md` was explicitly approved by the user. Tasks 1-15 may proceed locally in sequence under that plan. This approval does not broaden external authority or bypass later plan gates.

## Future external gates

1. Azure read-only refresh is authorized for the exact healthy-but-not-hosted-accepted Phase 2 state.
2. A newly generated value-complete restricted no-AI `target_mode=update` package, bound to current `2173222/78e9e62` rollback authority, must receive approval of its complete exact SHA-256 before any registry publication, Azure update, secret injection, Job execution, restart, rollback rehearsal, or hosted verification.
3. No cleanup package is currently required or authorized. The healthy synthetic PostgreSQL/Blob authorities must be preserved. All consumed prior packages, including `a0d46c3d...` and `c874b753...`, must not be reused.

No old authorization, design approval, plan approval, reachable URL, or local test result can substitute for those gates.

<!-- authority:history:end -->
