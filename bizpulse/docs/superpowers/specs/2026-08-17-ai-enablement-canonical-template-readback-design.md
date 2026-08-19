# AI Enablement: Canonical Azure Template Readback

**Date:** 2026-08-17

**Status:** user-approved design; implementation and a fresh authorization
package are still pending

**Execution boundary:** this document authorizes no Azure write, registry
publication, secret read/write, paid OpenAI request, push, or deployment.

## Background and verified failure

R5 (`0cd6205790d80d9d32d50b38c5bc1d5cbc3b5efd563e85fb5c0b653c9767cc46`)
completed its read-only revalidation, candidate-image publication, and
AI-disabled candidate activation. Its exclusive failed receipt records those
three completed states, so R5 is consumed and must never be replayed.

The current candidate revision is healthy, provisioned, running, latest, and
latest-ready with `BIZPULSE_AI_CHAT_ENABLED=false`. A targeted hosted browser
diagnostic then passed: six disabled bilingual preset buttons were visible,
with zero provider turns and zero external requests. The task-owned Key Vault,
task-owned UAMI, real Key write, and paid OpenAI qualification stages were not
reached.

The failure is a local readback-shape defect, not a rejected Azure deployment
or an operator-password failure. The preflight reader deliberately requests a
canonical template subset:

- template: `revisionSuffix`, `containers`, and `scale.minReplicas` /
  `scale.maxReplicas`;
- container: `name`, `image`, `env`, `probes`, and `resources`.

The reconciliation reader instead requests Azure's raw template. Azure adds
provider-owned defaults such as `imageType`, `cooldownPeriod`,
`pollingInterval`, `rules`, `customMetricsSettings`, `initContainers`,
`serviceBinds`, `terminationGracePeriodSeconds`, and `volumes`. The raw
template can never equal the canonical target patch, so reconciliation reports
false drift before the hosted browser gate can be accepted.

## Options considered

1. **Canonicalize every reconciliation readback (chosen).** Project both the
   application and revision template to the same allowlisted shape used by
   preflight before comparing it to the predecessor or target profile.
   Provider-owned defaults are ignored, while every task-controlled field
   remains exact.
2. **Add Azure defaults to the expected patch.** Rejected: defaults are API
   version/provider behavior and would make the desired state brittle.
3. **Insert a fixed delay or browser retry.** Rejected: it hides the false
   drift classification and neither proves nor preserves the exact deployment
   contract.

## Chosen implementation

Add one pure canonical-template projection shared by reconciliation readers.
It accepts only the exact task-controlled template structure and preserves
only:

- revision suffix;
- one container's name, digest-pinned image, allowlisted environment rows,
  probes, and resources;
- `minReplicas` and `maxReplicas`.

The projection rejects missing, malformed, duplicate, secret-valued, or
unexpected task-controlled entries. It discards only Azure-generated fields
that were not part of the submitted patch. Reconciliation still fails closed
for a wrong image, AI flag, UAMI set, secret reference name, budget setting,
probe, resource limit, scale min/max, ingress/traffic configuration, revision,
health, provisioning state, or third active revision.

The reconciliation callback normalizes raw Container App and revision-list
responses before they reach `reconcile_ai_transition`; no raw Azure response,
secret value, prompt, user data, or error body is written into receipts.

## Test-first acceptance

Before production code changes, add a failing hosted test containing a valid
target template plus the Azure-injected fields observed in R5. It must fail
under the current raw comparison. After the minimal projection change it must
pass, while paired tests continue to reject changes to each retained field.

Run the focused reconciliation/action tests, full AI contract tests, browser
tests, release static checks, and changed-path verification. The local
browser gate must still prove six visible disabled presets and zero AI/provider
requests.

## Fresh authorization boundary

After the local fix and all tests pass, run a fresh read-only Azure gate. R6
must use the current healthy AI-disabled candidate revision and its immutable
image digest as the new rollback baseline. It must record R5 as consumed,
confirm that the task-owned Key Vault and UAMI remain absent, use new exclusive
receipt/observation paths, and receive a new SHA-256 approval before any Azure
write, ACR push, real Key prompt, or paid OpenAI request.
