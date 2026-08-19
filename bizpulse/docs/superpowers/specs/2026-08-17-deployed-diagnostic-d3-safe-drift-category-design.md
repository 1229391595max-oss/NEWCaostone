# Deployed Release Diagnostic D3: Safe Drift Categories

**Date:** 2026-08-17
**Status:** approved design; local implementation only until a new package receives an exact-SHA approval
**Predecessor:** D2 attempt `ce1811a2-2d89-4f11-b1ba-3dcb40e4a6fb`

## 1. Decision and boundary

D2 completed all six allowlisted Azure `GET` reads and then failed with the
safe tuple:

```text
code=diagnostic_application_drift
stage=application
resource_role=application
```

That proves that the failure was neither pagination nor request authorization,
but the D2 receipt deliberately does not say which application-contract check
failed. D3 improves that local diagnostic evidence only. It does **not** change
Azure resources, retry D2, access a registry, Keychain, public URL, or AI
provider, or retain a raw ARM response.

D1 and D2 packages, receipts, observations, commits, and conclusions remain
immutable. The consumed D2 receipt is never deleted or replayed.

## 2. Goal

When a future one-shot D3 read finds application-contract drift, its owner-only
failure receipt shall identify one fixed, non-sensitive `mismatch_category`.
It shall never contain an actual value, expected value, arbitrary ARM field
name, environment value, secret value, digest, raw response fragment, URL
query, stdout, stderr, or token.

The result is a safe diagnosis such as:

```json
{
  "code": "diagnostic_application_drift",
  "stage": "application",
  "resource_role": "application",
  "mismatch_category": "ingress_traffic"
}
```

The category states only which stable comparison family failed; it does not
prove an Azure configuration is wrong or identify the differing value.

## 3. Chosen approach

Use a closed allowlist of categories generated solely by local comparison
branches. D3 does not derive a category from a remote string or persist remote
data.

| Category | Local comparison family |
| --- | --- |
| `container_image` | container image identity |
| `revision_state` | latest/ready revision and active revision health/state |
| `ingress_traffic` | ingress protocol, exposure, FQDN, and traffic contract |
| `environment_binding` | managed-environment identity and allowlisted environment binding names |
| `probe_contract` | health/readiness probe structure |
| `scale` | minimum and maximum replicas |
| `resource_limits` | CPU/memory resource contract |
| `secret_reference_names` | allowlisted secret-reference name set only |
| `container_runtime` | container name, command, or arguments |

No category for a raw Azure default, value, or unknown field exists. An
unclassifiable application shape remains the existing safe
`diagnostic_application_drift` result with `mismatch_category` set to `null`.

## 4. Contract and compatibility

### 4.1 Receipt

D3 introduces `newcaostone.deployed-release-diagnostic-attempt.v2` for its own
new receipt filename. The D3 `failure` object has exactly four keys:

```text
code
stage
resource_role
mismatch_category
```

`mismatch_category` is one of the fixed categories above or `null`. Non-
application failures always use `null`. The existing v1 D1 and D2 receipt
schemas and files are not parsed as, rewritten as, or migrated to v2.

### 4.2 Internal error propagation

`DeployedReleaseDiagnosticInvalid` gains an optional, locally validated
category. Construction with a non-allowlisted category collapses to the
existing generic safe package-invalid tuple; no caller can inject arbitrary
text into a receipt. The runner copies only the validated category from this
exception into a D3 v2 receipt.

### 4.3 Package and execution

D3 gets fresh package, receipt, and observation paths, a fresh authorization
ID, new control hashes, and a separate expiry. Its package continues to allow
only the exact existing ARM `GET` allowlist, API version, byte/request bounds,
and retry limit zero.

The runner creates a mode-`0600` `started` receipt before its first ARM read.
An existing D3 receipt or observation consumes the D3 package. On any failure,
no observation is written; a single mode-`0600` failed receipt is retained.
A D3 execution still requires a later explicit approval of its exact package
SHA-256.

## 5. Data flow

```text
allowlisted ARM GET response (memory only)
  -> local fixed comparison branch
  -> validated category or null
  -> DeployedReleaseDiagnosticInvalid
  -> D3 v2 owner-only receipt

raw response / expected value / actual value / hash
  -> never serialized
```

The normal successful path remains unchanged: only a fully projected,
sanitary observation may be written after all contract checks pass.

## 6. Test plan

Tests are written before code changes and cover:

1. one failing projection case for every fixed application category;
2. malformed or unclassifiable application input yields `null`, never a remote
   field name;
3. receipt v2 validation rejects extra keys and arbitrary categories;
4. application drift places the expected safe category in a failed receipt;
5. revision/job/local failures retain `mismatch_category: null`;
6. literals resembling image digests, URLs, secret values, environment values,
   stdout, and stderr never occur in receipt or observation output;
7. D3 keeps D2's terminal-page compatibility, exact scope, receipt-before-read,
   owner-only mode, no-retry, and no-replay behavior.

The full focused diagnostic suite and the repository's changed-path/local
release gates run before a D3 package is generated. Passing local tests mean
only that the D3 tool is locally ready for separate authorization; they do not
prove a hosted state.

## 7. Acceptance criteria

D3 is ready for package generation only when all of the following are true:

- every emitted category is in the closed allowlist;
- no raw or hashed remote value reaches a receipt or observation;
- D1 and D2 artifacts remain untouched and D2 cannot be replayed;
- a v2 D3 receipt is mode `0600`, exclusive, and fail-closed;
- all D3 mapping, safety, runner, authority, and changed-path tests pass from
  one clean committed D3 branch;
- generation creates no Azure request and execution remains blocked pending a
  new exact-SHA approval.
