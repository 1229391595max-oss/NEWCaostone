# Deployed Release Diagnostic D1 Failure Closeout

Status: D1 executed once, failed locally after read-only Azure responses, and is
permanently consumed. This record grants no replay or successor execution
authority.

## Immutable artifacts

- Package: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md`
- Package SHA-256:
  `8b05ef98021b7111aa556d39342270425b10c35b7976bda5b065540ccf1a73af`
- Authorization ID: `9e4b37fe-1bc2-4d1f-a90d-db66ac73cee7`
- Bound branch: `codex/integrated-viewer-ai-anti-drift`
- Bound committed HEAD: `38f8768e6a9202d7c7aba0676bd5408c743f8abd`
- Bound tree: `4610da18bc1bb00adb1cfa902866e9495caf5382`
- Receipt: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json`
- Receipt SHA-256:
  `386a7ef0d83129f01842150e466dcfc96e9d9dec42d3a3447980395109b12bc5`
- Receipt mode and size: `0600`, 551 bytes
- Observation: absent

Do not edit, delete to replay, regenerate under the D1 identity, or otherwise
reuse these artifacts.

## Exact outcome

The approved runner was invoked once. Its application GET and revisions GET
were both read-only `az rest` commands and both child processes exited `0`.
The receipt records one completed logical resource role, `application`, then a
safe failure with code `diagnostic_arm_response_invalid`. No Azure mutation,
registry access, Keychain access, public URL request, AI access, or paid request
occurred.

The revisions collection was a valid terminal Azure collection page with a
`value` array and no `nextLink`. D1's local parser incorrectly required the
top-level keys to be exactly `value` plus `nextLink`, so it rejected the
successful response before marking the revisions logical read complete. The
receipt's old `local/local` provenance reflects a second local observability
defect; it does not identify an Azure resource failure.

Because D1 intentionally stores no raw ARM body, the immutable receipt contains
only allowlisted metadata. The local command audit and parser reproduction are
the basis for the root-cause classification; no raw response or secret value is
added to this closeout.

## Git and integration finding

D1 was not run from uncommitted work. Its package binds the clean committed
HEAD and tree shown above, so a missing local commit did not cause the failure.
The feature branch had not been merged to `main`, but that also did not cause
the parser rejection.

At the start of the D2 investigation, `main...HEAD` was `6 234`. Five of the six
`main`-only commits were patch-equivalent to design and handoff commits already
introduced on the feature branch; only `ef78397` was unique. After the six D2
design, plan, and repair commits through `6f8e33c`, the count was `6 240`; this
closeout makes it `6 241`. A blind merge or rebase remains unsafe. The approved
next local step is an isolated integration branch from `main`, a
no-fast-forward merge, and exact resolution of only the two preclassified
add/add authority conflicts.

## D2 boundary

D2 repairs terminal-page compatibility, safe failure provenance, evidence
persistence, and completion timestamps. Its generator is bound only to
`codex/integrated-viewer-ai-anti-drift-d2-integration`. Local implementation,
testing, integration, and package generation grant no Azure authority.

D1 does not disprove deployed health. Hosted health, browser acceptance,
capacity, expiry, restart/readback, rollback acceptance, AI availability, and
Production readiness all remain unverified. Any D2 execution requires a newly
generated package and separate approval containing that package's exact
SHA-256.

Feature-branch verification passed before this closeout commit: 113 focused
diagnostic tests; the exact policy-owned `release_static` selection with 346
passed and two declared skips; Ruff, formatting, Python compilation, Bicep, and
authority-contract gates; and non-reused `verify_changed` against
`5db9c6f1a7487734167fdb8128b68665d79c4a00`.
