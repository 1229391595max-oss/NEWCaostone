# NEWCaostone Current Status

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

## Admin AI post-R19 recovery adoption — local successor contract only

- Historical accepted R19 target:
  `newcaostone-demo-app--ai-off-9c35ae6a-2bf7086`.
- Current recovery-adoption target:
  `newcaostone-demo-app--recover-b-9c35ae6a-2bf7086`.
- Both bind immutable image digest
  `sha256:2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425`
  and tag `ai-962a4fa43804-9c35ae6a`; the recovery target requires exact
  `registry_only` identity, process AI disabled, and no AI bindings.

The recovery suffix is derived from the immutable R19 package-hash prefix and
terminal image-digest prefix. R19 remains consumed read-only provenance: never
replay R19, rewrite its failed receipt, or treat its historical `ai-off`
reconciliation as the current target. The bounded diagnosis observed the
recovery identifier and registry-only classification, but that diagnosis does
not prove hosted acceptance. This addendum is local design and implementation
only; no new Azure/public read, package, UUID, deployment, secret access, or
hosted-success claim occurred. A separately authorized exact-source read-only
refresh must still prove the complete 12+1 adoption contract before any local
authority update or later package work.

## Release incident — superseding status

The generated block above is the last internally bound application/image/schema
snapshot. It expired when the approved prepare Job started at
`2026-08-16T20:25:35Z`; its `Hosted migration` line describes the old image's
attested compatibility and is no longer a claim about the database's present
schema or public health.

The exact two-stage package with SHA-256
`084ee41e9c79bb96b8e60cd3ac417cac30e9e8f18af5de88ab0304a2374493b6`
was approved once and is consumed. It published candidate
`82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3`, attested by
`c573f2be9d8d6414143fbeab2fa2af788caf4f19`, as immutable image
`sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`.
The prepare Job then succeeded at migration `0014_import_base_lineage`, but the
seed Job failed with `seed_authority_mismatch` because its candidate container
was still bound to the preceding manifest/version arguments. No application
deployment, traffic switch, AI enablement, API Key access, paid call, hosted
acceptance, restart, or rollback rehearsal followed.

Azure control-plane readback at `2026-08-16T20:36:02Z` still selected the old
application image and revision at 100% latest traffic, but direct live and ready
requests both timed out. Therefore the Demo is not currently claimed healthy or
hosted-accepted. The immutable failure record is
`bizpulse/docs/operations/2026-08-16-two-stage-release-partial-failure.md`.

The first recovery package, SHA-256
`7e378f176589c590fafec782e7b29e564e85d4490b94ae0e7f163503ab1e1dbb`, was
approved once and is consumed. Its incident and registry checks passed, but
the `bind_seed` command was rejected by local Azure CLI argument parsing before
an Azure update request was dispatched. No Job state, seed data, application,
traffic, AI or secret state changed.

Local recovery-controller commit
`94137e6e95c745c5e6b68fa7de763be7d8faf46c` replaces that unsafe CLI argument
shape with a mode-0600 atomic YAML update plus exact post-update readback. The
versioned incident snapshot at
`bizpulse/release/incidents/2026-08-16-two-stage-partial-failure.json` now has
SHA-256 `a20b446d41f4a09e2c12944ea153352ccd11a470ddc68d18d5d186e61bf25d5e`.
The new mode-0600 successor package is
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_PARTIAL_RELEASE_RECOVERY_V2.md`,
authorization ID `5b73b24d-2ae8-4245-a769-be9735b2fb24`, SHA-256
`91e210d5c41c430eec8685e39ae10377bdf293e96a5a77662f2e77a51b764f6a`, expiring
`2026-08-17T21:15:45Z`, was approved once and is now consumed. It successfully
rebound the seed Job and completed candidate seed execution
`newcaostone-demo-seed-vhamoeo`. The first deployment command then stopped
before Azure dispatch because three required non-AI deployment environment
variables were absent. No application deployment, traffic switch, AI
enablement or secret access followed. The immutable receipt is
`bizpulse/docs/operations/2026-08-16-recovery-v2-partial-failure.md`.

## Recovery V3 retired; Recovery V4 consumed with partial deployment

The V3 design and implementation chain through `a6f6997` added a strict
`seeded_awaiting_application_deploy` record, Azure read-only verifier,
hash-first one-shot runner and release-policy coverage. V3 SHA-256
`94b89c07ff77b158d8e561f2a2fcf0d91ca5cb4943c0897b6d9cab93e3d369e7` was
approved once, but its direct Python entrypoints stopped during local import.
No receipt, Keychain read, Azure request or mutation occurred. V3 is retired;
the immutable incident evidence is
`bizpulse/docs/operations/2026-08-16-recovery-v3-local-entrypoint-stop.md`.

Commit `e59f8f1` adds direct-entrypoint regression tests and fixes project-root
bootstrapping in both affected scripts. The runner still omits registry
publication, migration, Job binding and seed; those operations are already
complete.

Before its Azure write, the V4 runner verified the separately approved package
SHA-256, continuation and control hashes, expiry, old application traffic,
candidate-bound Jobs, successful prepare/seed executions, and both registry
digests. It then required all four existing non-AI Keychain entries:
the PostgreSQL password, Operator Argon2id hash, session pepper and Operator
plaintext used only by the authenticated browser gate. The plaintext verified
against the hash. Package generation read none of these values; the runner
injected deploy values only into Bicep, with no value in argv, output, package
or receipt. The browser stage was not reached.

The owner-only package
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_SEEDED_RELEASE_RECOVERY_V4.md`,
authorization ID `993b492e-aba0-40e8-87e5-65019caaa291`, SHA-256
`978110287eb3335bcf5537ee59e9bd887a41eee9753861148680f1a5475beae8`, expiring
`2026-08-17T22:09:20Z`, was approved once and is consumed. Seeded and registry
checks passed; the Azure deployment and both maintenance executions succeeded.
The candidate revision `newcaostone-demo-app--713a6984d4a0` now has 100%
traffic, one ready replica and AI disabled. The final deploy-stage read-only
fence then rejected the already-completed prepare execution because it predates
the V4 `not-before` threshold. Health, browser, capacity, expiry, restart and
rollback acceptance did not run. Do not replay V4. The immutable evidence is
`bizpulse/docs/operations/2026-08-16-recovery-v4-partial-failure.md`. OpenAI Key
access, AI enablement and paid requests remain separate and absent.

## Recovery V5 read-only preflight failed; V5 retired

The deployed-continuation and V5 control chain is implemented locally through
commit `1f03a30`. It binds the exact V4 package, candidate revision and four
successful Job execution identities, and rejects substituted executions,
application/traffic/AI drift or failed later maintenance executions. V5 omits
deployment and every completed mutation.

The owner-only package
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md`,
authorization ID `75bbbbb4-69e9-4b38-921e-08f64b0bd6cf`, SHA-256
`656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab`, expiring
`2026-08-17T22:46:52Z`, was separately approved and invoked once. It stopped
during `deployed_preflight` after a successful application read and before
revision, Job, registry, Keychain or hosted-acceptance work. The V5 receipt is
absent, but V5 is retired and grants no replay or manual-resume authority. The
failure was caused by whole-object comparison against Azure-owned scale
defaults; the approved `minReplicas=1` and `maxReplicas=1` values did not drift.

The exact remaining order is deployed-state readback, registry readback,
health, authenticated browser, capacity, expiry, restart/readback and rollback.
V5 may read only the existing Operator hash/plaintext pair after both read-only
checks pass; the plaintext is scoped only to browser acceptance. It never reads
the PostgreSQL password, session pepper or OpenAI Key. Read
`bizpulse/docs/operations/2026-08-16-recovery-v5-readonly-preflight-failure.md`.
Hosted acceptance and Production readiness remain pending.

## Recovery V6 read-only preflight failed; V6 retired

V5 is retired after its approved read-only preflight failure. V6 was separately
approved and invoked once. It stopped during `deployed_preflight` after
successful application, revision, prepare Job and prepare execution reads, and
before the remaining Jobs, registry, Keychain or hosted-acceptance work. Its
receipt is absent, but V6 is retired and grants no replay or manual-resume
authority. Hosted health, browser, capacity, expiry, restart and rollback
acceptance remain pending; AI remains disabled and no OpenAI Key or paid request
was involved.

The owner-only V6 package is
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md`,
authorization ID `34059824-5881-4bbd-a03c-9389ba6a175a`, SHA-256
`b66cd4d1b2cb84391045376cbc262db040394b388b9322385a90954c63406de4`, issued
`2026-08-16T23:03:44Z` and expiring `2026-08-17T23:03:44Z`. It was generated
exactly once with mode `0600`; `.tmp/RECOVERY_V6_EXECUTION_RECEIPT.json` is
absent. Read
`bizpulse/docs/operations/2026-08-16-recovery-v6-readonly-preflight-failure.md`.
The exact local verifier subcode was not retained by the generic runner wrapper;
do not guess, replay V6 or perform a diagnostic Azure read without new authority.

Last local acceptance: 2026-08-16 (America/Chicago)

## Integrated Viewer / Store Scope / AI result

The approved local plan in
`docs/superpowers/plans/2026-08-16-bizpulse-row-dedupe-multi-store-real-ai.md`
is implemented through Task 12 in the isolated worktree
`/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift`
on branch `codex/integrated-viewer-ai-anti-drift`. The changed-path baseline is
`BATCH_BASE_SHA=d4ed425e8f9c5c2e271ef7e53a2276674500d4c3`; the deployed SHA above is
compare-only.

Local behavior now includes row-level import deduplication with atomic conflict
blocking, a deterministic low-traffic second store, All/Main/Launch scope over
the seven Viewer and Operator surfaces, the paged BP Library workbook, resettable
Viewer Action simulation, and scope/evidence-bound Ask BizPulse. Operator keeps
the complete authenticated upload, recognition, mapping, preview, immutable
commit, deterministic calculation, publish and export workflow. Viewer cannot
upload or recompute canonical data.

The approved AI snapshot is exactly `gpt-5.4-nano-2026-03-17`, low reasoning,
2,800 maximum output tokens, 120 daily attempts, 150,000 monthly tokens, 3
attempts per session per minute, 20 global attempts per minute and 15 concurrent
turns. The browser has no Key field. The paid qualification gate is inert unless
Task 13 supplies the Key through its dedicated hidden process variable.

## Task 12 release boundary

Task 12 creates one candidate-addressed local attestation and one ignored,
mode-0600, hash-approved two-stage package:

1. `data_scope_revision`: the immutable candidate image, migration `0014`,
   AI disabled, no OpenAI secret, and full non-AI hosted acceptance.
2. `ai_revision`: the same image and data authority, allowed only after the
   exact stage-1 receipt and all 12 fixed-model qualification cases pass; it
   permits one hosted paid-AI smoke and routes back to the exact stage-1
   revision on failure.

The package contains target, digest, migration, seed, command, retry, stop,
secret-presence, cost and expiry authority but never contains the Key. Its
exact candidate SHA, attestation SHA, image digest, package SHA256 and expiry
are reported after the two-commit protocol; they cannot be self-embedded in
this candidate document.

## Local acceptance evidence

- Fresh task-owned PostgreSQL migrates through `0014_import_base_lineage`.
- The complete Task 11 non-reused gate passed: 170 frontend tests, five real
  browser scenarios, migration, restart, rollback, release, policy and AI
  qualification/static gates.
- Task 12 adds a real-Chrome `scope-readonly` gate at 390px. It switches all
  three scopes, verifies English/Chinese and keyboard focus, reads the main
  business surfaces, records zero external requests and proves that dataset,
  artifact, analysis, forecast, profit-bridge and public-release row counts are
  unchanged by Viewer scope switching.
- AI behavior is tested only with fake providers. No OpenAI request or Key was
  used during Tasks 1–12.

## Evidence states

| State | Result |
|---|---|
| Designed / implemented | Tasks 1–12 implemented locally. |
| Local acceptance | PostgreSQL, Azurite, local Chrome and fake-provider gates only. |
| Local release proof | Candidate-addressed attestation plus exact two-stage package. |
| Azure / registry / hosted | Candidate image, migration, seed binding/data, application deployment and maintenance executions are complete; candidate traffic is 100%, but health and remaining hosted acceptance are not proved. |
| Hosted AI | Still disabled. |
| Paid AI / real Key | Not used. Task 13 only. |
| Push / PR / CI / deployment | Not performed. |
| Production ready | No. This remains a bounded sample-data Demo. |

## Stop boundary

The original two-stage package and Recoveries V1–V6 are consumed or retired and
grant no replay authority. V5 and V6 must not be executed again or manually resumed;
Product Opportunity web search, account management, real customer files,
hosted AI and marketplace actions remain deferred.

## Diagnostic D1 consumed; D2 local repair and integration pending

The owner-only D1 package SHA-256
`8b05ef98021b7111aa556d39342270425b10c35b7976bda5b065540ccf1a73af`
was approved and invoked exactly once. Both read-only `az rest` child commands
exited `0`; the local parser then rejected the successful revisions collection
because Azure omitted the optional terminal `nextLink`. D1 is consumed and must
never be replayed. Its mode-`0600` failed receipt has SHA-256
`386a7ef0d83129f01842150e466dcfc96e9d9dec42d3a3447980395109b12bc5`,
records only completed role `application`, and binds no observation.

The failure was not caused by uncommitted code: D1 was bound to clean committed
control commit `38f8768`. The feature branch is still not
merged to `main`, but that is an integration task rather than the D1 parser
cause. At D2 investigation start the graph was `6 234`; after six local D2
design/repair commits through `6f8e33c` it was `6 240`, and this closeout makes
it `6 241`. Five `main`-only commits are patch-equivalent and `ef78397` is the
one unique redirect, so do not perform a blind rebase or direct merge.

D2 local repair and its branch-bound runbook are implemented through `6f8e33c`.
Feature verification passed: 113 focused tests, policy `release_static` with
346 passed and two declared skips, authority contract, and non-reused
`verify_changed` from `5db9c6f`. The next local step is the preclassified
isolated integration branch. No D2 package has been generated or executed, and
no new Azure, registry, Keychain, URL, AI, or paid access is authorized. Read
`bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d1-failure.md`.

## D2 isolated integration candidate

The isolated branch
`codex/integrated-viewer-ai-anti-drift-d2-integration` now contains the feature
work plus the unique `main` handoff redirect. Merge commit `49dcff0` has exact
parents `ef78397` and `873f99e`; only the two preclassified add/add authority
files conflicted, and both resolved to the later feature-side content. `main`
remains unmoved at `ef78397`.

The first-import topology exposed that main-base `verify_changed` cannot be an
incremental proof: `main` has no `bizpulse/`, so 560 paths appear changed, 111
are unmapped, and eight historical attestations correctly require the
non-cacheable full release gate. The policy was not weakened. The clean entire
candidate `fb3d514` instead passed the 8-check local full release verifier, and
the integration-only delta from `873f99e` passed all nine non-reused selected
checks. D2-focused tests remain 113 passed and policy `release_static` remains
346 passed with two declared skips.

The D2 package, receipt, and observation are still absent. The next authorized
action is local D2 package generation followed by a stop for exact-SHA approval;
D2 execution and every Azure, registry, Keychain, URL, AI, push, PR, CI, deploy,
or `main` update remain unauthorized. Read
`bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d2-integration.md`.
