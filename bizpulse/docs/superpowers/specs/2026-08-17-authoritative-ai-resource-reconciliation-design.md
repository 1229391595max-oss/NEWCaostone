# Authoritative AI Resource Reconciliation Design

**Date:** 2026-08-17  
**Status:** implemented reconciliation design, amended for R19 explicit UAMI deletion
**Execution boundary:** R11-R13 stopped before receipt, R14 was never submitted, R15 stopped before Azure writes, R16/R17 stopped after their first accepted AI-disabled PATCH, and R18 stopped during budget recovery. The amended design authorizes one new R19 package only. It does not make an old package reusable and does not put credential material in Git, argv, logs, receipts, or chat.

## Observed post-recovery state

Fresh Azure readback after the R10 disabled recovery and Operator rotation proved:

- `newcaostone-demo-app--rotate-11c5ef25c9fe` is the single healthy ready revision, with 100% latest traffic and image `sha256:6c41f8783f88943ff96ab5e3720af8bafc66d8b8b66f3ddf2857bd8a0517a220`;
- AI is disabled and the Container App has only the existing registry UAMI;
- the task-owned `newcaostone-ai-kv` and `newcaostone-ai-identity` remain present, as required by the approved ARM LRO recovery design;
- the Vault has RBAC, purge protection, 90-day soft delete, the exact task tags, the deterministic Key Vault Secrets User role for the task UAMI, and the `ai-vault-audit` diagnostic setting pointing to `newcaostone-demo-logs`;
- no Secret value or Secret metadata was read. The interactive Azure principal is intentionally denied Secret metadata access.

The original full-enablement prepackage gate required the Vault and UAMI to be absent. That condition is now stale and cannot be repaired by deletion: deleting the purge-protected Vault would make the name unavailable and would destroy the intended recovery provenance.

## Chosen design

R11 introduced, and R19 retained, adoption of the preserved task-owned resources only after an exact, non-secret control-plane readback. Successor packages expand that gate from eleven to twelve sanitized reads so Azure CLI descendant and ancestor enumeration semantics are both covered:

1. account;
2. Container App;
3. rollback revision;
4. rollback replica;
5. ACR manifest and rollback tag;
6. ACR configuration;
7. Log Analytics workspace;
8. task Vault configuration;
9. task UAMI configuration;
10. all subscription and descendant role assignments for the task UAMI;
11. subscription and ancestor role assignments for the task UAMI;
12. Vault diagnostic setting.

The gate requires all four task-resource states to equal `existing_exact`. It reads no Container App configuration Secret values and calls no Key Vault Secret command. The resource stage is renamed from create to reconcile; its Bicep deployment may create-or-update only the four exact task-owned resource types and must preserve the expected IDs, tenant, region, tags, RBAC, purge protection, diagnostic destination, and managed-identity client ID.

The rollback authority is now the healthy R18 budget-recovery revision `newcaostone-demo-app--recover-b-22767486-20f39c8`, digest `sha256:20f39c82b499c98ba10c68129531a46b4fb7fe3a6c4e91a87ddcdff99bfc18c1`, and immutable ACR tag `ai-790b71a7b95e-22767486`. It is AI disabled and serves 100% traffic, but its App-level identity state is exactly `registry_plus_ai`; no AI binding environment variables are present. R19 publishes a new authoritative image and must normalize that identity state in its first disabled transition.

## R11-R18 terminal boundaries and R19 fence

R11 was invoked once and returned failure before the runner reserved its exclusive receipt. Both the R11 receipt and observation paths remained absent, and immediate Container App readback remained on the same healthy AI-disabled Operator revision and digest. Therefore R11 is consumed at the `pre_receipt_no_azure_write` boundary and must never be resubmitted.

R12 bound the exact R11 package SHA-256 and required both R11 output paths to remain absent. It then stopped with `ai_enablement_browser_credential_unavailable` before receipt reservation because the exact macOS login-Keychain secret-read process did not receive user approval inside its 60-second window. The Keychain item/current pair remained present, and immediate Azure readback remained unchanged and AI-disabled.

R13 bound both exact package hashes and required all four R11/R12 output paths to remain absent. Its separate `/usr/bin/security` process likewise timed out before receipt reservation, while the current Keychain pair remained present and the live app remained AI-disabled and unchanged.

R14 bound all three exact package hashes and required all six R11-R13 output paths to remain absent. It was never submitted because the background controller PTY is not user-accessible and automated Terminal control is prohibited. R14 is therefore consumed as `never_submitted_superseded_before_execution`, with both output paths required to remain absent.

R15 bound all four exact package hashes and required all eight R11-R14 output paths to remain absent. It wrote a terminal failed receipt after read-only revalidation because the exact local image tag for its commit did not exist. The live app remained unchanged and AI-disabled; the secure key dialog never opened, no paid provider call ran, and no Secret or Container App write occurred.

R16 consumed the exact R15 package and receipt hashes and passed the new local-image gate. It published the exact image, then submitted one AI-disabled PATCH. Azure returned an asynchronous-operation URL using `operationStatuses/<uuid>`; the controller allowed only `operations/<uuid>` and therefore wrote `ai_enablement_patch_unconfirmed`. Fresh reconciliation proved the resulting revision healthy, exact, AI-disabled, and serving 100% traffic. The key dialog never opened, no paid provider call ran, and no Secret write occurred.

R17 consumed the exact R16 package and receipt hashes, promoted the healthy R16 revision to rollback authority, passed its exact local-image gate, and published a new exact image. Its first AI-disabled PATCH was accepted, but confirmation through the service-supplied status URL failed closed. Fresh readback proved the resulting R17 revision healthy, ready, exact, AI-disabled, and 100% serving. The secure key dialog never opened; no paid provider call or Secret write occurred.

R18 consumed the exact R17 package and receipt hashes and proved exact-resource ARM polling works in the live service. It published a new image, reconciled its first AI-disabled candidate, and adopted the exact preserved Vault/UAMI/RBAC/diagnostic resources. The budget-enabled rehearsal and its recovery PATCH were accepted, but the recovery reconciliation rejected the remaining AI UAMI. Fresh readback showed the recovery revision healthy, ready, 100% serving, and AI disabled while the App identity still contained both UAMIs. The secure key dialog never opened; no paid provider call, placeholder Secret write, real Secret write, or observation occurred.

The R18 fault is a PATCH merge-semantic mismatch. Omitting a key from `identity.userAssignedIdentities` preserves that identity; Azure's Container Apps identity-removal implementation sends the exact identity resource ID with a JSON `null` value. R19 therefore emits `{<ai-uami-id>: null}` only when disabling from a predecessor that contains the AI UAMI. It separately canonicalizes the desired readback by removing that marker, so reconciliation still requires the final App identity to contain only the registry UAMI. The same rule applies to the initial normalization, budget recovery, provider recovery, and emergency recovery. Enabled transitions continue to attach the AI UAMI with `{}`.

For every 202 PATCH, R19 ignores service-supplied status URLs and polls only the exact original Container App resource URL. A read is accepted only when its resource ID exactly matches the package-bound App and `properties.provisioningState` is `Succeeded`; known in-progress states wait within the existing 300-second deadline, while failed, cancelled, malformed, foreign-resource, transport, and timeout results fail closed. Exact app/revision/image/health reconciliation still runs afterward as an independent gate.

## Credential and package boundary

- R1-R18 packages and existing receipts remain immutable consumed evidence. Their paths and hashes are never passed as the R19 package; R11-R14 are additionally fenced by the required absence of their receipts and observations.
- D3 remains a separately hash-bound read-only diagnostic fallback required by the v1 controller; it is not a recovery package and cannot make an Azure write.
- The provider key is accepted only by a local topmost Tk dialog after R19 is generated, hashed, and revalidated. The input is masked with `*`, never printed, and exists only in the runner's process memory until the existing wipe path completes.
- The runner performs 12 bounded synthetic model-qualification calls and one hosted manual-send smoke, each with zero retry. The hosted smoke is the single real application turn.
- The key is written once to the task Vault only after the budget and placeholder-provider rehearsals pass; the browser never receives it.

## Alternatives rejected

1. Delete and recreate the Vault/UAMI: unsafe with purge protection and unnecessary because the resources are exact.
2. Pretend the resources are absent: falsifies the prepackage evidence and can hide drift.
3. Skip the resource stage without readback: loses proof of the role and diagnostic boundary.
4. Replay R8 or either disabled-recovery package: prohibited by receipt fences and the user's explicit no-replay instruction.

## Test and acceptance contract

Tests first require the new state name, 12-read contract, current rollback anchor, exact-existing resource states, and task-only reconciliation allowlist. The pre-existing tests must then prove package determinism, transition ordering, receipt sanitization, ARM LRO one-PATCH behavior, zero Secret reads, and unchanged runtime/model/cost limits.

Before the R19 write, the branch must be clean, every control file hash must match, and the exact local image gate must pass. After execution, hosted health, full browser, paid-AI, capacity, exact-session, restart, and rollback-readiness evidence remain separate acceptance gates.
