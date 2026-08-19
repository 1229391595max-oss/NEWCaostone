# NEWCaostone Next-AI Handoff

Last recovery package generation: 2026-08-16 17:46 CDT (America/Chicago)

## Release incident boundary

The public URL remains:

`https://newcaostone-demo-app.delightfulstone-15318d59.centralus.azurecontainerapps.io`

The earlier two-stage update and recovery chain partially executed. Candidate
`82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3`, attested by
`c573f2be9d8d6414143fbeab2fa2af788caf4f19`, was published, migrated and
seeded after the seed binding was corrected. Recovery V4 then deployed revision
`newcaostone-demo-app--713a6984d4a0`, switched 100% traffic and completed both
maintenance executions with AI disabled. Its final read-only fence rejected an
already-successful prepare execution solely because it predates the V4 issue
time. Health, browser, capacity, expiry, restart and rollback acceptance did
not run, so the Demo is not yet claimed hosted-accepted or Production ready.

Package SHA-256
`084ee41e9c79bb96b8e60cd3ac417cac30e9e8f18af5de88ab0304a2374493b6`
is consumed and must never be replayed. AI remained disabled; no OpenAI Key,
paid call, DNS, push, PR or CI operation occurred. Read
`bizpulse/docs/operations/2026-08-16-recovery-v4-partial-failure.md` before any
continuation.

## Local implementation to continue from

Use the isolated worktree:

`/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift`

Branch: `codex/integrated-viewer-ai-anti-drift`

Committed implementation candidate:
`82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3`

Candidate attestation commit:
`c573f2be9d8d6414143fbeab2fa2af788caf4f19`

Local recovery-controller commit:
`94137e6e95c745c5e6b68fa7de763be7d8faf46c`

V5 release-policy implementation head: `1f03a30`

Read `CURRENT_STATUS.md` and `docs/handoffs/CURRENT_HANDOFF.md` before any next
work. Do not return to the obsolete implementation worktree or start feature
work from the deployed SHA.

## Verified local result

The integrated Viewer/AI plan and corrective Viewer/Operator plan are locally
implemented. The no-reuse changed-path selector ran all 18 selected checks and
finished `verification_changed=passed`; the repository migration head is
`0014_import_base_lineage`.

Viewer file selection/drop is interaction-only and never reads or sends the
file; **Import demo data** activates the shared prepared data without copying or
recalculation. Operator retains authenticated import, recognition, mapping,
standardization, preview, commit, calculation, publish and export. The browser
has no AI-key field; AI availability is server-derived. Action simulation is
session-only and does not execute externally.

## Next authorized boundary

Recovery V1 and V2 are consumed. V2 was
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_PARTIAL_RELEASE_RECOVERY_V2.md`,
authorization ID `5b73b24d-2ae8-4245-a769-be9735b2fb24`, SHA-256
`91e210d5c41c430eec8685e39ae10377bdf293e96a5a77662f2e77a51b764f6a`, expiring
`2026-08-17T21:15:45Z`. It rebound the seed Job and candidate seed execution
`newcaostone-demo-seed-vhamoeo` succeeded. Deployment then stopped locally
before Azure dispatch because three non-AI deployment environment variables
were missing. The application and traffic remain unchanged; AI is disabled and
no OpenAI Key or other secret value was accessed.

No further cloud mutation or secret-store access is authorized by this handoff.
A new package must recognize completed migration/binding/seed and preflight
`BIZPULSE_DEPLOY_POSTGRES_PASSWORD`,
`BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH` and
`BIZPULSE_DEPLOY_SESSION_PEPPER` before any mutation. Supplying or reading
those values requires separate secure authorization; never put them in chat.
Keep local verification, hosted acceptance, Azure acceptance and Production
readiness as separate states.

Still deferred: Product Opportunity web search, operator account/password
management, real customer files, real/paid AI, marketplace actions and hosted
acceptance.

## V3 retired; V4 partially deployed and consumed

The isolated branch contains the local-only successor through commit
`a6f6997`. It models the exact state as
`seeded_awaiting_application_deploy`, verifies the old app/traffic and the
candidate-bound successful prepare/seed executions, omits all completed stages,
and provides a package-hash-first one-shot runner. The runner preloads the
three deployment credentials plus the existing Operator plaintext needed for
the full browser gate before the first Azure write; it verifies the plaintext
against the Argon2id hash and never serializes a value.

The owner-only V3 package SHA-256
`94b89c07ff77b158d8e561f2a2fcf0d91ca5cb4943c0897b6d9cab93e3d369e7` was
approved once. Its controller and first read-only child stopped at local Python
import before any Keychain read, Azure request, receipt or mutation. V3 is
retired; read
`bizpulse/docs/operations/2026-08-16-recovery-v3-local-entrypoint-stop.md`.

Commit `e59f8f1` adds direct-entrypoint regression coverage and fixes both
affected entrypoints. A fresh owner-only V4 package was generated at
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_SEEDED_RELEASE_RECOVERY_V4.md` with
authorization ID `993b492e-aba0-40e8-87e5-65019caaa291`, SHA-256
`978110287eb3335bcf5537ee59e9bd887a41eee9753861148680f1a5475beae8`, and expiry
`2026-08-17T22:09:20Z`. Generation read no Keychain value and made no Azure
request. The generation-time receipt is
`bizpulse/docs/operations/2026-08-16-recovery-v4-package.md`.

That exact V4 hash was approved once and the package is now consumed. Its
seeded and registry checks passed, deployment returned success,
the AI-disabled candidate revision now has 100% traffic, and the two exact
maintenance executions succeeded. The final read-only phase-2 fence failed
because it required the deliberately skipped, already-successful prepare/seed
Jobs to execute again after the V4 issue time. No health, browser, capacity,
expiry, restart or rollback acceptance followed. Do not replay or manually
resume V4. Read
`bizpulse/docs/operations/2026-08-16-recovery-v4-partial-failure.md`.

Any successor must model the deployed candidate state, bind exact completed Job
execution identities, omit deployment and every completed Job, and require a
fresh exact-hash approval before the remaining hosted acceptance steps.

## Recovery V5 read-only preflight failed; V5 retired

The deployed-continuation verifier, owner-only package builder, one-shot runner
and release-policy coverage are locally complete through `1f03a30`. Focused V5
tests passed `35`; the policy's exact release-static argv passed `226` with two
known skips; selector tests passed `64`; `authority_contract=ok` and
`verification_changed=passed` with base `16f5220 --no-reuse`.

The generated package is
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md`,
authorization ID `75bbbbb4-69e9-4b38-921e-08f64b0bd6cf`, SHA-256
`656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab`, expiring
`2026-08-17T22:46:52Z`. V5 was separately approved and invoked once. It stopped
during `deployed_preflight` after a successful application read and before
revision, Job, registry, Keychain or hosted-acceptance work. The V5 receipt is
absent, but V5 is retired and grants no replay or manual-resume authority. The
failure was caused by whole-object comparison against Azure-owned scale
defaults; the approved `minReplicas=1` and `maxReplicas=1` values did not drift.

V5 performs only exact deployed/registry readbacks followed by health, browser,
capacity, expiry, restart/readback and rollback acceptance. It reads only the
Operator hash/plaintext pair after both readbacks pass, passes plaintext only
to the browser child, keeps AI disabled and contains no deployment, Job, seed,
migration or OpenAI command. Read
`bizpulse/docs/operations/2026-08-16-recovery-v5-readonly-preflight-failure.md`.
Do not replay V5 or manually resume any child command from it.

No plaintext password, API key, token, connection string or session pepper is
stored here.

## Recovery V6 read-only preflight failed; V6 retired

V5 is retired after its approved read-only preflight failure. V6 was separately
approved and invoked once. It stopped during `deployed_preflight` after
successful application, revision, prepare Job and prepare execution reads, and
before the remaining Jobs, registry, Keychain or hosted-acceptance work. Its
receipt is absent, but V6 is retired and grants no replay or manual-resume
authority. Hosted health, browser, capacity, expiry, restart and rollback
acceptance remain pending; AI remains disabled and no OpenAI Key or paid request
was involved.

The mode-`0600` package is
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md`,
authorization ID `34059824-5881-4bbd-a03c-9389ba6a175a`, SHA-256
`b66cd4d1b2cb84391045376cbc262db040394b388b9322385a90954c63406de4`, issued
`2026-08-16T23:03:44Z` and expiring `2026-08-17T23:03:44Z`. The V6 execution
receipt is absent. Focused V6 tests passed `41`; release-static passed `232`
with two declared skips; selector passed `64`; docs authority and non-reused
changed-path gates passed. Read
`bizpulse/docs/operations/2026-08-16-recovery-v6-readonly-preflight-failure.md`.
All four Azure calls were read-only and returned exit code `0`; the local
verifier rejected the first prepare Job/bound execution contract. Its exact
subcode was hidden by the generic runner wrapper. Do not replay V6 or issue a
new diagnostic Azure read without separate authority.

## Diagnostic D1 consumed; continue with local D2 integration only

D1 package SHA-256
`8b05ef98021b7111aa556d39342270425b10c35b7976bda5b065540ccf1a73af`
was approved and invoked exactly once. Its two read-only `az rest` child
commands exited `0`; local collection parsing failed because the successful
terminal revisions page omitted optional `nextLink`. The mode-`0600` failed
receipt SHA-256 is
`386a7ef0d83129f01842150e466dcfc96e9d9dec42d3a3447980395109b12bc5`.
It records completed role `application`, `diagnostic_arm_response_invalid`, and
no observation. Never replay D1.

D1 was bound to clean committed control commit `38f8768`; this was not an
uncommitted-change failure. The feature branch remains unmerged. The graph was
`6 234` when the D2 investigation began, was `6 240` after six D2 commits
through `6f8e33c`, and is `6 241` with this closeout; five `main`-only commits
are patch-equivalent and `ef78397` is unique. Use the approved isolated
integration procedure and do not blind-merge or rebase.

D2 code and runbook are local only. Feature verification passed with 113
focused tests, 346 policy-static passes and two declared skips, authority
contract, and non-reused `verify_changed` from `5db9c6f`. Create
`codex/integrated-viewer-ai-anti-drift-d2-integration` from current `main`,
resolve only the two preclassified authority add/add conflicts, and verify the
integration candidate before generating a D2 package. Package generation does
not authorize Azure execution. Read
`bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d1-failure.md` and
`bizpulse/docs/operations/DEPLOYED_RELEASE_DIAGNOSTIC_D2.md`.

## D2 integration complete; generate locally and stop

Continue only in
`/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift-d2-integration`
on `codex/integrated-viewer-ai-anti-drift-d2-integration`. Merge `49dcff0`
joined main `ef78397` and feature `873f99e`; exactly the two predicted authority
files conflicted and resolved to the later feature-side versions. Main remains
unchanged.

Because main is a docs-only skeleton, a main-base incremental selector sees the
entire 560-path project, including 111 unmapped files and eight immutable
attestations requiring full-release proof. Do not weaken that fail-closed
policy. Candidate `fb3d514` passed the full 8-check local release verifier, and
the actual integration delta from `873f99e` passed all nine non-reused selected
checks. Focused D2 remains 113 passed; release static remains 346 passed with
two declared skips.

Generate the owner-only D2 package locally only after confirming a clean current
integration HEAD/tree and absent D2 package/receipt/observation. Then stop and
request approval of the exact package SHA-256. Do not invoke the runner or any
Azure command. Read
`bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d2-integration.md`.
