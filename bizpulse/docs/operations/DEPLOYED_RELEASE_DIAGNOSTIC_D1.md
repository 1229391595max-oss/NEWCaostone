# Deployed Release Diagnostic D1

Status: local read-only diagnostic tooling. This document grants no Azure
execution authority.

## Purpose and evidence boundary

D1 compares the exact V4 deployed continuation with a desired projection
compiled locally from `infra/modules/app.bicep`. If separately approved and
executed once, it may read the Container App, its revision collection, four
Container Apps Jobs and their complete execution collections through Azure
Resource Manager.

D1 allows only HTTPS `GET` requests to `management.azure.com` with API version
`2024-03-01`. It does not deploy, restart, roll back, start a Job, access the
registry, read Keychain, request the public Demo URL, enable AI or call an AI
provider. It uses core `az rest`; the Container Apps extension version is
recorded as evidence but the extension is not invoked.

A completed observation supports only the claim
`read_only_deployed_state_observed`. It is not Hosted verified, Azure accepted,
Production ready, Demo health, recovery success or AI availability. Any later
Recovery V7 requires a separate design and authorization.

## Fixed local artifacts

- Package: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md`
- Attempt receipt: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json`
- Sanitized observation: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_OBSERVATION.json`
- Deployed continuation:
  `release/incidents/2026-08-16-recovery-v4-deployed-continuation.json`

The package, receipt and observation use file mode `0600`. Raw ARM responses,
stdout, stderr, environment values, secret values and access tokens are never
written to either JSON artifact.

## Generate the local package

Run generation only from a clean committed
`codex/integrated-viewer-ai-anti-drift` worktree after the plan's local gates:

```bash
.venv/bin/python scripts/create_deployed_release_diagnostic_package.py \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --continuation-reference release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --output .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md \
  --expires-hours 24
```

Generation performs local Git, control-hash, toolchain and Bicep validation. It
does not access Azure, Keychain, a registry, the public URL or AI. Record the
printed absolute path, authorization ID, UTC expiry and SHA-256.

Independently validate the artifact:

```bash
stat -f '%Lp %N' .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_OBSERVATION.json
git status --short
```

Stop after generation and request explicit approval of that exact SHA-256.
Generating or validating the package does not authorize the runner.

## Separately approved one-shot execution

Only after the user approves the exact generated SHA-256 may the following
shape be used with that value substituted for `<APPROVED_SHA256>`:

```bash
.venv/bin/python scripts/run_deployed_release_diagnostic.py \
  --package .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md \
  --approved-sha256 <APPROVED_SHA256> \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --receipt .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json \
  --observation .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_OBSERVATION.json
```

The runner validates package SHA, expiry, Git HEAD/tree, tracked cleanliness,
toolchain, control closure, continuation and compiled desired projection before
creating a receipt. It creates the `started` receipt before the first ARM GET.

Any existing receipt consumes the package, whether its status is `started`,
`failed` or `completed`. A crash intentionally leaves `started`; do not replay
the package or run a child command manually. A failed receipt contains only an
allowlisted code, stage and resource role. A completed receipt binds the
mode-`0600` sanitized observation by SHA-256.
