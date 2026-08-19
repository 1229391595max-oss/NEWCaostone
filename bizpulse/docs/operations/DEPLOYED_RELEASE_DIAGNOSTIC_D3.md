# Deployed Release Diagnostic D3

Status: local package-generation and approval runbook. This document grants no
execution authority.

## Purpose and boundary

D3 is a new, separately approved diagnostic package. D2 is permanently
consumed and must not be replayed. D3 permits only the package's allowlisted
HTTPS `GET` diagnostic reads after separate approval; its retry limit is zero.

No D3 operation may use manual `az rest`, retries, receipt deletion, public URL
access, registry access, Keychain access, AI access, deployment, or a D1/D2
replay. The package does not authorize Azure mutation.

## Fixed local artifacts

- Package: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D3.md`
- Attempt receipt: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D3_ATTEMPT_RECEIPT.json`
- Sanitized observation: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D3_OBSERVATION.json`
- Deployed continuation:
  `release/incidents/2026-08-16-recovery-v4-deployed-continuation.json`

The package, receipt, and observation must use mode `0600`. Do not store raw
responses, command output, credentials, or other sensitive content in these
artifacts.

## Generate locally

From the `bizpulse` repository directory on the authorized D3 branch, generate
the package locally:

```bash
.venv/bin/python scripts/create_deployed_release_diagnostic_package.py \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --continuation-reference release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --output .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D3.md \
  --expires-hours 24
```

Generation is local-only. Stop after it completes and record the package path,
file mode, and SHA-256 for review. Generation is not approval to execute.

## Exact-SHA approval and one-shot execution

Before any D3 execution, the user must separately approve the exact SHA-256 of
the generated D3 package. A different package, regenerated package, changed
SHA-256, expired package, or any existing D3 receipt requires a new package and
new exact-SHA approval.

Once approved, execution remains GET-only and one-shot: do not retry after any
failure or interruption. Never delete or replace a receipt to make the package
appear unused. Do not use a manual `az rest` command or another substitute to
repeat, complete, or investigate a D3 read. A later attempt needs a new
package and explicit authorization.

## Evidence limits

A D3 package, local generation, or a D3 observation does not prove hosted
health, deployment success, browser acceptance, recovery success, AI
availability, or Production readiness.
