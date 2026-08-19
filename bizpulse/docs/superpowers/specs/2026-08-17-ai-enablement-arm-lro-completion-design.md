# AI Enablement ARM Long-Running Operation Completion

**Date:** 2026-08-17  
**Status:** user-approved local design  
**Execution boundary:** this document authorizes neither Azure writes nor API-key
input, Key Vault Secret access, paid OpenAI calls, push, or deployment.

## Observed fault

R8's Container Apps budget-rehearsal transition reached the expected healthy
revision, but the next, required AI-disabled recovery PATCH was rejected with
`ContainerAppOperationInProgress` / HTTP 409.  Azure activity records show the
recovery PATCH was attempted while the preceding provisioning operation was
still active.  The runner treated a successful ARM PATCH response as a complete
operation; ARM permits `202 Accepted`, for which completion must be tracked via
the response's `Azure-AsyncOperation` or `Location` URL.

At the time of this design, the public app's single-revision traffic is 100% on
the R8 budget-rehearsal revision.  That revision has
`BIZPULSE_AI_CHAT_ENABLED=true` and
`BIZPULSE_AI_BUDGET_FAILURE_REHEARSAL=true`.  The rehearsal rejects before any
provider call, but it is not the intended AI-disabled public baseline.

## Chosen design

The action adapter will replace the Azure CLI's opaque `az rest` PATCH with a
small ARM request boundary that obtains an ARM token through `AzureCliCredential`
without logging it, submits exactly one PATCH, and retains only allowlisted
response metadata in memory.  It never persists or returns the bearer token,
response body, or response headers.

When the PATCH returns 202, the adapter validates the ARM operation URL and
polls it with GET only.  It honors a bounded retry-after delay, stops at a
terminal `Succeeded`, and fails closed on `Failed`, `Canceled`, malformed
responses, untrusted URLs, read errors, or the fixed operation deadline.  A
200/201 response is accepted only after validating the expected Container App
resource identity.  No path resends the PATCH.

Only after the ARM operation reaches `Succeeded` may the existing exact
Container App and revision reconciliation begin.  Thus the existing
predecessor/target profile and healthy-revision checks remain a second,
independent confirmation rather than a substitute for ARM operation completion.

## Recovery package sequence

The next package will be a narrow R9 recovery rather than a new AI-enable
attempt.  It will first re-read the exact current R8 budget-rehearsal state,
then perform exactly one app PATCH to a prescribed AI-disabled revision, wait
for the ARM operation, reconcile the exact disabled target, and run the
existing disabled browser gate.  It must preserve the task-owned Vault, UAMI,
and RBAC objects, but remove the AI UAMI and Vault bindings from the Container
App revision.

R9 has no Key Vault Secret read or write, no API-key prompt, no paid provider
request, and no old-vault or old-credential operation.  A fresh owner-only
package, receipt, and observation are required; the consumed R8 package cannot
be replayed.  Only after R9 has a confirmed disabled result may a later,
separate full AI-enablement package be generated.

## Alternatives rejected

1. Fixed sleep followed by a new PATCH: time is not proof that ARM released the
   provisioning lock and the second write might conflict again.
2. Retry the recovery PATCH after a 409: the first patch may already have been
   accepted, making the retry non-idempotent and obscuring evidence.
3. Route dynamic app patches through a general ARM deployment: this broadens
   the write surface and does not improve certainty over tracking the exact
   operation returned by the PATCH.

## Test and security contract

Tests first prove that an accepted 202 blocks subsequent state transitions
until its operation reports `Succeeded`; they cover `Azure-AsyncOperation` and
`Location`, retry-after bounds, malformed or cross-host URLs, operation failure,
timeout, and the invariant that exactly one PATCH was issued.  Existing
reconciliation, rehearsal, secret-boundary, preset-audit, and browser tests
must remain green.

The implementation may use only the already-pinned Azure Identity and Requests
runtime dependencies.  Azure bearer tokens, OpenAI keys, Key Vault Secret
values, raw prompts, user data, raw ARM JSON, and raw errors must not enter
logs, receipts, observations, test fixtures, command arguments, or browser
artifacts.
