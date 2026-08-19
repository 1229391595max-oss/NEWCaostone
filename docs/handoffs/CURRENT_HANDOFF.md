# NEWCaostone Current Handoff

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

## Release incident — read before continuing

The generated block above expired at the start of the approved migration Job.
The database advanced to repository migration `0014_import_base_lineage`, the
candidate seed binding was corrected and candidate data was seeded. Recovery
V4 then deployed candidate revision `newcaostone-demo-app--713a6984d4a0`,
switched 100% traffic and completed both maintenance executions with AI
disabled. Its final read-only fence rejected the older, already-successful
prepare execution because it predates V4's issue time. Health, browser,
capacity, expiry, restart and rollback acceptance did not run, so no hosted
acceptance or Production-readiness claim is valid.

The consumed package, completed operations, prohibited replays and exact
candidate evidence are recorded in
`bizpulse/docs/operations/2026-08-16-two-stage-release-partial-failure.md`.
No AI revision ran, no OpenAI Key was supplied, and no paid request occurred.

## Start here

Use
`/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift`
on branch `codex/integrated-viewer-ai-anti-drift`. Read `CURRENT_STATUS.md`,
then
`docs/superpowers/plans/2026-08-16-bizpulse-row-dedupe-multi-store-real-ai.md`,
then this file. The implementation baseline is
`d4ed425e8f9c5c2e271ef7e53a2276674500d4c3`; never use the deployed SHA above
as a changed-path baseline.

## Local result

Tasks 1–11 implement row-level dedupe, atomic conflict blocking, the low-traffic
second store, one three-scope selector across the product, BP Library paging,
Action reset, evidence-bound AI and the fixed nano limits. Operator retains all
canonical upload/calculation/publish/export functions. Viewer remains limited
to prepared Demo activation, read-only scope changes, Action simulation and AI.

Task 12 adds a candidate-image-bound release manifest, exact two-stage package
verification, sanitized stage receipt verification, and real-browser proof that
scope switching creates no canonical, analysis, forecast, bridge or release
rows. The package stage order is `data_scope_revision` then `ai_revision`; the
AI stage requires both stage-1 and 12-case qualification receipts and has the
exact stage-1 revision as rollback.

## Evidence and credential boundary

Tasks 1–12 remain local acceptance evidence. Task 13 and the recovery chain
later changed registry, Job templates, database state and finally deployed the
AI-disabled candidate at 100% traffic. The remaining hosted acceptance did not
run. Packages and receipts contain only descriptors, booleans and hashes, never
credential values; the expired generated block above must be read together
with the recovery records.

## Task 13 recovery continuation

Do not replay the original two-stage package or recovery V1. Recovery V1 passed
incident and registry checks, then its `bind_seed` command was rejected by the
local Azure CLI parser before an update request was dispatched. No Azure state
changed. Local commit `94137e6e95c745c5e6b68fa7de763be7d8faf46c` replaces
direct CLI container arguments with a mode-0600 atomic YAML binding document,
deletes that document after use, and performs exact readback. The incident
snapshot is
`bizpulse/release/incidents/2026-08-16-two-stage-partial-failure.json`, SHA-256
`a20b446d41f4a09e2c12944ea153352ccd11a470ddc68d18d5d186e61bf25d5e`.

The generated successor was
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_PARTIAL_RELEASE_RECOVERY_V2.md`,
authorization ID `5b73b24d-2ae8-4245-a769-be9735b2fb24`, SHA-256
`91e210d5c41c430eec8685e39ae10377bdf293e96a5a77662f2e77a51b764f6a`, expiring
`2026-08-17T21:15:45Z`. It was approved once and is consumed. It successfully
rebound the seed Job and completed candidate seed execution
`newcaostone-demo-seed-vhamoeo`; deployment then failed during local Bicep
parameter evaluation because `BIZPULSE_DEPLOY_POSTGRES_PASSWORD`,
`BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH` and
`BIZPULSE_DEPLOY_SESSION_PEPPER` were absent. No deployment request, traffic
change, AI enablement or secret read followed. Read
`bizpulse/docs/operations/2026-08-16-recovery-v2-partial-failure.md`.

Do not replay V2 or resume at its deployment command. A successor must skip the
completed migration, binding and seed, and fail before Azure mutation unless
the three non-AI deployment variables are present. Reading or supplying those
values requires separate secure-mechanism authority; do not accept them in chat.
AI Stage 2 remains separate and out of scope until the AI-disabled application
is healthy and has a valid receipt.

## Recovery V3 retired; Recovery V4 partial deployment

Commits `e96ded2`, `2ad285d`, `ea2c160`, `47964c2` and `a6f6997` are the
original V3 preparation chain. The continuation evidence records successful
seed execution `newcaostone-demo-seed-vhamoeo`; the verifier requires the old
application revision at 100% traffic plus exact candidate-bound prepare/seed
Jobs and successful executions. The package builder includes only read-only
state/registry checks, application deploy and non-AI hosted acceptance.

The one-shot runner checks the exact approved package hash before Keychain,
loads all four non-AI launch/acceptance entries before the first Azure write,
verifies the Operator plaintext against the Argon2id hash, scopes secrets to
the Bicep or browser child, and creates a mode-0600 receipt before deployment.
An existing receipt or failed write consumes the package. V3 SHA-256
`94b89c07ff77b158d8e561f2a2fcf0d91ca5cb4943c0897b6d9cab93e3d369e7` was
approved once but stopped during local Python import before any Keychain read,
Azure request, receipt or mutation. It is retired; read
`bizpulse/docs/operations/2026-08-16-recovery-v3-local-entrypoint-stop.md`.

Commit `e59f8f1` fixes both direct entrypoints under regression coverage. The
owner-only V4 package was
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_SEEDED_RELEASE_RECOVERY_V4.md`,
authorization ID `993b492e-aba0-40e8-87e5-65019caaa291`, SHA-256
`978110287eb3335bcf5537ee59e9bd887a41eee9753861148680f1a5475beae8`, expiring
`2026-08-17T22:09:20Z`. It was approved once and is consumed. Deployment and
both maintenance executions succeeded; the AI-disabled candidate revision now
has 100% traffic. The final deploy-stage read-only fence failed because it
required the already-completed prepare and seed Jobs to execute after V4's
`not-before` time. Health, browser, capacity, expiry, restart and rollback did
not run. Do not replay V4. Read
`bizpulse/docs/operations/2026-08-16-recovery-v4-partial-failure.md`.

A successor must begin from the deployed candidate state, bind the exact
prepare, seed, session-maintenance and storage-maintenance execution identities,
omit all completed mutations and use a fresh package/hash approval. OpenAI
remains disabled and outside this recovery chain.

## Recovery V5 read-only preflight failed; V5 retired

The deployed continuation, exact state verifier, V5 builder, one-shot runner
and release-policy mapping are complete locally through `1f03a30`. The
owner-only package is
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md`,
authorization ID `75bbbbb4-69e9-4b38-921e-08f64b0bd6cf`, SHA-256
`656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab`, expiring
`2026-08-17T22:46:52Z`. V5 was separately approved and invoked once. It stopped
during `deployed_preflight` after a successful application read and before
revision, Job, registry, Keychain or hosted-acceptance work. The V5 receipt is
absent, but V5 is retired and grants no replay or manual-resume authority. The
failure was caused by whole-object comparison against Azure-owned scale
defaults; the approved `minReplicas=1` and `maxReplicas=1` values did not drift.

V5 omits deployment and all completed Jobs. Its only stages are exact
deployed/registry readbacks, health, browser, capacity, expiry,
restart/readback and rollback. It may read only the Operator hash/plaintext
pair after readbacks pass; plaintext is browser-only. It does not read the
PostgreSQL password, session pepper or OpenAI Key, and AI remains disabled.

Local evidence: focused V5 `35 passed`; release-static `226 passed, 2 skipped`;
selector `64 passed`; authority and non-reused changed-path gates passed. Read
`bizpulse/docs/operations/2026-08-16-recovery-v5-readonly-preflight-failure.md`.
Do not execute V5 again or manually resume any child command from it.

## Recovery V6 read-only preflight failed; V6 retired

V5 is retired after its approved read-only preflight failure. V6 was separately
approved and invoked once. It stopped during `deployed_preflight` after
successful application, revision, prepare Job and prepare execution reads, and
before the remaining Jobs, registry, Keychain or hosted-acceptance work. Its
receipt is absent, but V6 is retired and grants no replay or manual-resume
authority. Hosted health, browser, capacity, expiry, restart and rollback
acceptance remain pending; AI remains disabled and no OpenAI Key or paid request
was involved.

The owner-only package is
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md`,
authorization ID `34059824-5881-4bbd-a03c-9389ba6a175a`, SHA-256
`b66cd4d1b2cb84391045376cbc262db040394b388b9322385a90954c63406de4`, issued
`2026-08-16T23:03:44Z` and expiring `2026-08-17T23:03:44Z`. Its mode is `0600`
and `.tmp/RECOVERY_V6_EXECUTION_RECEIPT.json` is absent. The four completed Azure
calls were read-only; the local verifier rejected the first prepare Job/bound
execution contract before registry or Keychain. Read
`bizpulse/docs/operations/2026-08-16-recovery-v6-readonly-preflight-failure.md`.
The next boundary requires a new diagnostic/recovery design and separate
authority; V6 must not be replayed or manually resumed.

## Diagnostic D1 closeout and current local boundary

D1 package SHA-256
`8b05ef98021b7111aa556d39342270425b10c35b7976bda5b065540ccf1a73af`
was approved and executed once. Both allowlisted read-only `az rest` child
commands exited `0`; the D1 parser rejected the terminal revisions collection
only because Azure omitted optional `nextLink`. D1 is consumed. Its owner-only
failed receipt SHA-256 is
`386a7ef0d83129f01842150e466dcfc96e9d9dec42d3a3447980395109b12bc5`,
and no observation exists.

The package was bound to clean committed control commit `38f8768`, so
uncommitted or missing work was not the cause. The feature branch is not merged
to `main`. The graph moved from `6 234` at investigation start to `6 240` after
the six D2 commits through `6f8e33c`, and to `6 241` with this closeout; five
`main`-only commits are patch-equivalent and `ef78397` is the unique handoff
redirect. Preserve that authority by using the planned isolated integration
branch and exact two-conflict resolution rather than a blind merge or rebase.

D2 locally repairs the parser, failure provenance, evidence persistence, and
completion timestamps. Its generator accepts only
`codex/integrated-viewer-ai-anti-drift-d2-integration`. Local feature
verification is complete: 113 focused tests, 346 policy-static passes with two
declared skips, authority contract, and non-reused `verify_changed` from
`5db9c6f`. Complete integration verification before generating the owner-only
D2 package, then stop. D2 execution requires a separate exact-SHA approval and
is not authorized by this handoff. Read
`bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d1-failure.md`.

## D2 integration candidate ready for local package generation

The isolated integration branch merges main `ef78397` and feature `873f99e` at
`49dcff0`. Exactly the two preclassified add/add authority conflicts occurred;
both use the newer feature-side handoff/design. Main was not moved.

The docs-only main base makes the complete project look like a 560-path
incremental change. The selector correctly blocks on 111 unmapped paths and
eight immutable attestations rather than pretending to pass. No policy was
weakened. The entire clean candidate `fb3d514` passed the 8-check local full
release gate, while the real integration delta from `873f99e` passed all nine
non-reused selected checks. Focused D2 is 113 passed and the checked-in static
release suite is 346 passed with two declared skips.

D2 has not been generated or executed. Confirm clean integration identity and
absent D2 evidence files, generate the local owner-only package, validate its
mode and SHA-256, and stop. Any runner invocation or Azure read requires a new
explicit exact-SHA approval. Read
`bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d2-integration.md`.
