# Deployed Release Diagnostic D2

Status: local successor tooling and runbook. This document grants no Azure
execution authority.

## Purpose and evidence boundary

D2 replaces the consumed D1 attempt. It repairs Azure collection-terminal-page
compatibility, records safe stage and resource-role provenance, and hardens
owner-only evidence finalization. D1 remains immutable and must never be
replayed.

D2 is still a one-shot, read-only diagnostic. It may use only HTTPS `GET`
requests to the package's exact allowlisted `management.azure.com` paths with
API version `2024-03-01`. It has a retry limit of zero. It does not mutate
Azure, access a registry or Keychain, request a public URL, enable AI, or call
an AI provider.

A completed D2 observation supports only
`read_only_deployed_state_observed`. It is not Hosted verified, Azure accepted,
Production ready, Demo health, recovery success, or AI availability.

## Fixed local artifacts

- Package: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md`
- Attempt receipt: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_ATTEMPT_RECEIPT.json`
- Sanitized observation: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_OBSERVATION.json`
- Deployed continuation:
  `release/incidents/2026-08-16-recovery-v4-deployed-continuation.json`

The package, receipt, and observation use file mode `0600`. Raw ARM responses,
stdout, stderr, environment values, secrets, and access tokens are never
written to the receipt or observation.

## Generate the local package

Generate D2 only from a clean committed worktree on
`codex/integrated-viewer-ai-anti-drift-d2-integration`, after both feature and
integration verification gates pass:

```bash
.venv/bin/python scripts/create_deployed_release_diagnostic_package.py \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --continuation-reference release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --output .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md \
  --expires-hours 24
```

Generation performs only local Git, control-hash, toolchain, continuation, and
Bicep validation. It makes no Azure request. The generator rejects the old
implementation branch and any other branch.

Independently validate the artifact:

```bash
stat -f '%Lp %N' .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_ATTEMPT_RECEIPT.json
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_OBSERVATION.json
git status --short
```

Stop after generation. Report the exact package path, authorization ID, UTC
expiry, branch, HEAD, tree SHA, file mode, and SHA-256. Package generation and
local validation do not authorize execution.

## Separately approved one-shot execution

Execution is outside the local D2 implementation scope. Only after the user
separately approves the exact generated SHA-256 may the following command shape
be used, with that exact value substituted for `<APPROVED_SHA256>`:

```bash
.venv/bin/python scripts/run_deployed_release_diagnostic.py \
  --package .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md \
  --approved-sha256 <APPROVED_SHA256> \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --receipt .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_ATTEMPT_RECEIPT.json \
  --observation .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_OBSERVATION.json
```

The runner creates the owner-only `started` receipt before its first ARM GET.
Any existing D2 receipt consumes the package whether its status is `started`,
`failed`, or `completed`. A receipt-writing crash remains consumed. Never retry
the package, delete its receipt to replay it, or run a child ARM command
manually. A successor attempt requires a new package and new exact-SHA approval.
