# BizPulse AI Enablement Runbook

Status: package-bound Course Demo procedure. This file grants no independent
Azure, registry, provider, browser, push, PR, CI, or deployment authority.

## Closed R19 and Task 12 successor boundary

R1-R19 and all existing receipts are immutable consumed evidence. Never replay,
rename, overwrite, or continue one of those packages. R11-R14 are additionally
fenced by the required absence of their receipt and observation paths.

R19 stopped with `ai_enablement_emergency_disable_failed` after proving one
healthy AI-disabled transition at revision
`newcaostone-demo-app--ai-off-9c35ae6a-2bf7086`, image digest
`sha256:2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425`,
and immutable tag `ai-962a4fa43804-9c35ae6a`. Its package and failed receipt
are mandatory consumed provenance for a successor, not current hosted-state
proof. The Task 12 generator requires a new read-only observation to match that
expected AI-disabled target before it can create a fresh package; any drift
stops before publication or mutation. The observed R19 application identity
state was `registry_plus_ai`.

## Identity and ARM completion rules

An enabled revision attaches the exact task AI UAMI using an empty identity
object. A disabled revision whose predecessor contains that UAMI sends the exact
identity resource ID with a JSON `null` value. The controller separately tracks
the canonical target without the deletion marker and accepts readback only when
the App contains the registry UAMI alone.

Every Container Apps transition issues exactly one PATCH. For `202 Accepted`, the
controller ignores service-supplied status URLs and polls only the exact original
Container App resource URL with GET. It requires the exact App resource ID and
`properties.provisioningState=Succeeded`. Failed, cancelled, malformed,
foreign-resource, transport, or the 300-second timeout are terminal. Exact revision,
image, identity, template, health, and single-revision traffic reconciliation
then runs as an independent gate. There are zero PATCH retries.

## Credential prompts

Two different prompts can appear:

1. A macOS Keychain prompt requests the Mac login password so the runner can
   read the existing Demo Operator browser credential. Never enter an OpenAI key
   there.
2. A topmost dialog titled `BizPulse AI Enablement` requests the OpenAI Platform
   API key. Enter the provider key only there. The value is masked, kept in the
   current process, and never placed in chat, argv, a file, `.env`, Git, logs,
   screenshots, package JSON, receipts, or browser state.

Cancel either prompt to fail closed. An Azure OpenAI key is not interchangeable
with an OpenAI Platform key.

## Fixed target contract

- OpenAI Platform Responses API
- model `gpt-5.4-nano-2026-03-17`, reasoning `low`
- 120 daily attempts and 150,000 monthly total tokens
- 3 session attempts/minute and 20 global attempts/minute
- 15 concurrent turns and 2,800 maximum output tokens
- 30-second provider timeout, zero provider retries, and no tools
- 12 paid synthetic qualification cases plus one hosted manual-send smoke
- conservative estimated execution maximum `$0.19`; package cap `$1.00`
- task-owned Standard Key Vault with RBAC, purge protection, 90-day soft delete,
  audit diagnostics, and a dedicated UAMI with `Key Vault Secrets User`

Deterministic calculations and stored evidence remain authoritative. AI explains
and prioritizes; it does not replace deterministic records or human approval.

## Package creation

Before package creation, require all of the following:

- clean `codex/newcaostone-authoritative-v1` HEAD and tree;
- exact committed control hashes and consumed-attempt hashes;
- exact local `linux/amd64` image, runtime user `bizpulse`, and matching source
  revision/image-input labels;
- the unconsumed owner-only D3 read-only package with no receipt or observation;
- twelve sanitized Azure reads matching the package's revision, image, tag,
  replica, identity, Vault, UAMI, role, diagnostics, ACR, and workspace anchors;
- current official provider price evidence and the fixed cost cap.

Do not run the fixed R19 generator or runner again. Fresh Task 12 successor
generation is documented only in `docs/operations/AZURE_LAUNCH_RUNBOOK.md`; it
uses a UUID-addressed owner-only artifact set and includes the exact R19
package/receipt hashes in its replay fence.

The following R19 paths are retained only as immutable consumed provenance:

```text
.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R19_2026-08-17.json
.tmp/AI_ENABLEMENT_RECEIPT_R19_2026-08-17.json
.tmp/AI_ENABLEMENT_OBSERVATION_R19_2026-08-17.json
```

## Execution

R19 is terminal and has no executable SHA. Do not invoke
`scripts/run_ai_enablement.py` with any R19 artifact.

The historical intended R19 order was:

1. read-only authority and price revalidation;
2. publish the package-bound candidate image;
3. activate and verify an AI-disabled candidate with only the registry UAMI;
4. reconcile the task Vault, AI UAMI, role assignment, and diagnostics;
5. run the zero-provider budget failure rehearsal and mandatory disabled recovery;
6. write one generated invalid placeholder and run the one-failed-call provider
   rehearsal plus mandatory disabled recovery;
7. collect the OpenAI key in the local hidden dialog;
8. run 12 zero-retry paid qualification cases;
9. write the real key once through the secure Key Vault deployment boundary;
10. activate and verify the final AI-enabled revision;
11. run exactly one paid hosted manual-send smoke;
12. write a sanitized owner-only observation and completed receipt.

The failed R19 receipt consumes R19 permanently. Do not retry it;
perform fresh read-only reconciliation and design a differently named package.

## Hosted acceptance remains separate

A completed enablement receipt is necessary but not sufficient for hosted
acceptance. Bind health, Viewer/Operator browser flows, paid AI, capacity,
exact-session, restart-readback, PostgreSQL persistence, and rollback-readiness
checks to the exact final revision and immutable image digest. Keep local tests,
synthetic qualification, reachable URL, hosted acceptance, and Production
readiness as distinct evidence states.
