# AI Enablement: Asynchronous Container App Reconciliation

**Date:** 2026-08-17

**Status:** approved architecture; written specification awaiting user review

**Execution boundary:** local design only; no Azure write, real Key read/write,
paid OpenAI request, push, or deployment is authorized by this document

## 1. Background and evidence

The AI enablement runner currently treats the Azure Container Apps update
response as if it were the final hosted state. Azure may instead return
`202 Accepted` while the update continues asynchronously. Requiring the PATCH
response to contain the final revision, image, identity, and environment state
therefore produces a false failure even when Azure subsequently provisions the
requested revision.

R1, R2, and R3 each stopped fail-closed and retained their mode-`0600`
`started` receipts. They are consumed attempts and must never be deleted,
rewritten, or replayed. R3 provides the decisive evidence: its runner reported
failure after the Container App PATCH, but later read-only Azure inspection
showed that the requested AI-disabled revision had become healthy.

Microsoft's Container Apps update contract explicitly permits `202 Accepted`
for an in-progress operation and exposes asynchronous operation information:

<https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps/update?view=rest-resource-manager-containerapps-2025-01-01>

The defect is consequently in local completion detection, not proof that
Azure rejected the R3 update. Local tests, a successful PATCH acknowledgement,
and a healthy hosted revision remain separate evidence states.

## 2. Current safe baseline

The next package must use a fresh read-only Azure observation immediately
before package creation. Until that observation is performed, the last
verified safe baseline is:

| Field | Verified R3 value |
| --- | --- |
| Container App | `newcaostone-demo-app` |
| latest revision | `newcaostone-demo-app--ai-off-ba92c00d-d4eb6e4` |
| latest-ready revision | `newcaostone-demo-app--ai-off-ba92c00d-d4eb6e4` |
| revision state | `Healthy` / `Provisioned`, one replica |
| immutable image | `sellernorthbpacr.azurecr.io/bizpulse@sha256:d4eb6e41e7643caf01ce6f615ef5d7a4333f6ab416e5a0ad7e0925cdc9d7958b` |
| application AI flag | `BIZPULSE_AI_CHAT_ENABLED=false` |
| managed identities | original registry UAMI only |
| task-owned AI UAMI | absent |
| task-owned Key Vault | absent |
| task-owned Key Vault RBAC | absent |
| real OpenAI Key | not requested, read, or written |

The public Azure Demo is running the new application image with AI disabled.
The R3 package's browser gate did not run because the old runner stopped at the
asynchronous PATCH acknowledgement. This baseline is safe but is not AI
enablement acceptance evidence.

## 3. Scope and non-goals

This design changes the authorized runner's handling of Container App state
transitions and the evidence recorded around those transitions. It covers:

- one PATCH per intended Container App transition;
- bounded, condition-based read-only reconciliation after the PATCH;
- readiness ordering for enabled rehearsals, browser checks, and recovery;
- mandatory removal of the real provider Key after any post-Key outcome;
- a live Azure-and-workspace gate immediately before a new authorization
  package is written;
- sanitized attempt evidence with exact read counts and elapsed duration.

This design does not authorize an Azure write or package execution. It does
not add the deferred Demo passcode, alter the six-preset product contract,
touch an existing Key Vault or existing credential, retry R1/R2/R3, weaken
budgets or permissions, or claim Production readiness.

## 4. Chosen architecture

### 4.1 Separate acknowledgement from convergence

The runner treats an allowed successful PATCH response, including
`202 Accepted`, only as acknowledgement that Azure accepted the update. It
does not use the response body as final proof. The runner captures only the
allowlisted asynchronous metadata needed in memory, then begins reconciliation
against fresh Container App and revision GET responses.

The PATCH is issued exactly once for that transition. A timeout, transient
Azure delay, malformed response, or later drift never causes another PATCH.
Only the bounded GET loop may repeat.

### 4.2 Exact reconciliation budget

Each transition has these immutable limits:

| Control | Limit |
| --- | --- |
| wall-clock duration | 120 seconds |
| poll interval | 5 seconds |
| Container App reads | at most 25 |
| revision reads | at most 25 |
| PATCH retries | zero |

The first application read occurs immediately after acknowledgement. A later
cycle begins no more frequently than every five seconds and never after the
120-second deadline. Each cycle performs at most one application GET and at
most one target-revision GET. The target revision is not queried until the
application projection makes that read meaningful. The runner stops as soon
as success or a terminal condition is observed, so actual counts may be lower
than the maxima.

The monotonic clock begins immediately before the PATCH and the receipt stores
the final elapsed milliseconds, application-read count, and revision-read
count. The elapsed value includes PATCH acknowledgement time and all polling.

### 4.3 Closed transition profiles

Every package defines two complete, immutable, non-secret profiles:

1. the observed predecessor profile captured by the pre-package live gate;
2. the intended target profile, including the prescribed revision name,
   immutable image digest, AI flag, UAMI set, ingress/traffic contract,
   environment-reference names, probes, scale, and resource limits.

During propagation, the application may match the complete predecessor or the
complete target profile. A partial mixture or any third profile is terminal
drift. Revision names may only be the prescribed predecessor or target. A
third `latestRevisionName`, `latestReadyRevisionName`, or active revision is
terminal drift.

### 4.4 State classification

Each fresh projection is classified using this closed table:

| Observation | Classification |
| --- | --- |
| complete predecessor profile remains latest and/or latest-ready | wait |
| complete target profile exists but predecessor is still latest-ready | wait |
| target revision has not yet been announced by the application | wait |
| application announces target and its revision is temporarily unavailable or has `healthState=null` | wait |
| target provisioning is in progress without an unhealthy/failed state | wait |
| target is both latest and latest-ready, exactly matches the target profile, and is `Healthy` plus `Provisioned` | success |
| any third revision or third application profile | terminal drift |
| wrong image, AI flag, identity set, ingress/traffic, probes, scale, resources, or environment reference | terminal drift |
| target or application reports `Failed`, `Unhealthy`, or another explicit terminal failure | terminal failure |
| an Azure response cannot be safely validated, or an unexpected non-success response occurs | terminal read failure |
| read limit or 120-second deadline is reached before success | terminal timeout |

A temporarily absent target-revision response is a waiting state only after
the application has named the prescribed target and only within the fixed
budget. It does not permit a PATCH retry. Explicit authorization, subscription,
resource, or schema errors remain terminal immediately.

## 5. Phase ordering

### 5.1 Normal enabled transition

After task-owned infrastructure and Key material pass their own checks, the
runner issues the single AI-enabled Container App PATCH and reconciles it to
the exact healthy target. Budget, daily/monthly/session/concurrency, permission,
provider-failure, and browser rehearsals may begin only after reconciliation
success. A PATCH acknowledgement or a merely visible revision is insufficient.

### 5.2 Rehearsals

Every enabled rehearsal uses the already reconciled healthy enabled revision.
It must continue through the existing server-side session, permission, global,
daily, monthly, concurrency, prompt-preset validation, and failure-display
paths. Rehearsals do not add a second PATCH and cannot bypass the official
preset catalog or turn preset selection into automatic submission.

### 5.3 Failure recovery and successful hosted state

Once a real Key has been written, every failure path enters a non-optional
recovery block:

1. issue exactly one AI-disabled Container App PATCH;
2. reconcile the prescribed AI-disabled target with the same 120-second,
   five-second, and 25-plus-25 bounds;
3. overwrite the task-owned vault secret with a non-provider placeholder;
4. retain a sanitized receipt that distinguishes confirmed AI-disabled health
   from disable-not-confirmed recovery.

The placeholder overwrite is attempted even if disabled reconciliation ends
in timeout or terminal failure, because removing usable provider material has
priority over preserving it for diagnosis. The runner never issues a second
disable PATCH. If disabled health cannot be confirmed, the execution ends
fail-closed and makes no hosted-success claim.

A fully successful run does not enter this recovery block. It leaves the exact
healthy AI-enabled revision and task-owned Key Vault secret available to the
public Azure Demo under the approved session, permission, budget, concurrency,
and audit controls. Disabling that successful hosted state later requires its
own exact authorized disable/revoke package; it is never performed as an
unrecorded cleanup side effect.

## 6. Real Key and Azure security boundary

The implementation continues to use a task-specific Key Vault public endpoint
with Azure RBAC and a dedicated task-specific UAMI. Existing credentials,
existing Key Vaults, and the original ACR-pull UAMI remain untouched.

The user is asked for the OpenAI API Key only after a separately approved
exact package reaches the Key-input stage. Input occurs in a hidden local TTY
prompt; it is never requested in chat, echoed, logged, placed in a package,
receipt, environment dump, command-line argument, test fixture, browser
artifact, or source file. The Key is used only in the in-memory Key Vault
request body and references are discarded on a best-effort basis immediately
after the request.

The Container App receives only a Key Vault secret reference through the
dedicated UAMI. Client code, HTML, JavaScript, API responses, logs, and preset
audit fields never contain the Key. Public network reachability of the vault
does not grant access: Azure RBAC, the dedicated identity, exact secret scope,
and immediate placeholder recovery remain the authorization boundary.

## 7. Receipt and evidence contract

The fresh package uses fresh package, receipt, and observation paths and a new
authorization ID. The mode-`0600` `started` receipt is created exclusively
before the first authorized Azure write. It is retained on every outcome and
consumes the package.

For each transition the receipt records only allowlisted evidence:

- transition role: enabled, disabled recovery, or safe baseline;
- acknowledgement class without response body;
- predecessor and target revision identifiers and immutable image digests;
- final safe state code;
- application-read count, revision-read count, and elapsed milliseconds;
- whether AI-disabled healthy recovery was confirmed;
- whether the task-owned secret placeholder overwrite succeeded.

It never records the API Key, vault secret value, raw Azure response, access
token, raw prompt template, user input, store data, workspace data, HTTP body,
stdout, stderr, or browser storage. Failure categories are selected from a
closed local allowlist; no arbitrary remote string is serialized.

R1, R2, and R3 packages, receipts, observations, ACR tags, and digests are
preserved as historical evidence. The new implementation does not migrate or
reinterpret their receipt schemas.

## 8. Mandatory live gate before package creation

After local implementation and tests, package generation must first perform a
fresh, read-only gate immediately before any package file is created. The gate
checks:

1. expected Azure tenant, subscription, resource group, and Container App;
2. `latestRevisionName` and `latestReadyRevisionName` equality;
3. healthy/provisioned latest revision and replica availability;
4. exact immutable R3 image digest and AI-disabled flag;
5. exact current identity set, ingress/traffic, probes, scale, resources, and
   managed-environment binding;
6. ACR repository/tag/digest consistency for the intended implementation
   image;
7. absence or exact expected state of the reserved task-owned UAMI, Key Vault,
   secret, and RBAC resources, without inspecting unrelated vaults or
   credentials;
8. clean expected Git branch and HEAD, exact control-file hashes, passing test
   evidence, and preservation of all R1/R2/R3 artifacts;
9. absence of a receipt or observation at the new exclusive paths;
10. a fresh expiry no more than 24 hours after package generation.

The gate compares the live observation with one complete expected baseline.
Any mismatch, ambiguity, unavailable required read, unexpected task-owned
resource, workspace drift, or third revision stops generation before the
package path exists. It does not silently rewrite expectations to match Azure.
The live observation is projected to non-secret fields and retained only as
the exact package controls required for later execution.

Only after all checks pass may the package be written atomically with mode
`0600`, hashed, and presented to the user. Execution remains blocked until the
user separately approves that new exact SHA-256. The earlier R1, R2, and R3
approvals cannot authorize it.

## 9. Test-driven implementation design

Implementation begins with failing tests and adds the smallest production
changes needed to pass them. The focused suite covers:

1. `202 Accepted` is acknowledgement, never immediate convergence proof;
2. one PATCH only, including timeout, read error, drift, and failed revision;
3. predecessor-to-target propagation through every allowed waiting state;
4. success only when latest and latest-ready equal the healthy/provisioned
   exact target;
5. terminal rejection of a third revision, partial profile, wrong image, AI
   flag, identity, ingress/traffic, probe, scale, resource, or environment
   binding;
6. `healthState=null`, old latest-ready, and prescribed target not-yet-visible
   wait within bounds;
7. exact 120-second, five-second, 25 application-read, and 25 revision-read
   ceilings using a fake monotonic clock;
8. enabled budget/provider/browser rehearsals cannot run before healthy
   reconciliation;
9. every post-Key exception enters one-shot disable reconciliation and
   placeholder overwrite;
10. placeholder overwrite still runs when disable confirmation fails;
11. receipts contain exact sanitized counters/duration and reject additional
    or secret-bearing fields;
12. pre-package live drift produces no package file and no Azure write;
13. Key input remains unreachable before exact-SHA approval and all preceding
    gates;
14. existing AI API contract, six-preset frontend/backend tests, XSS and leak
    checks, and browser acceptance remain passing.

The full relevant local test suite, changed-path release controls, package
schema tests, and secret-pattern scans run from a clean committed branch before
the live pre-package gate. Tests use only synthetic placeholders and never a
real OpenAI credential or paid request.

## 10. Alternatives rejected

### Retry the PATCH

Rejected because the first request may already be applying. A retry can create
an unintended extra revision or obscure which request produced the hosted
state.

### Trust the PATCH body or fixed sleep

Rejected because acknowledgement is not convergence, and Azure provisioning
time is variable. A fixed sleep supplies neither early success nor exact drift
evidence.

### Poll without bounds

Rejected because it weakens the authorization package's request and time
limits and can hide a terminal hosted failure.

### Accept any eventually healthy revision

Rejected because health alone does not prove the authorized image, AI flag,
identity, tenant boundary, or revision. Only the exact prescribed target can
succeed.

### Keep the provider Key for debugging

Rejected because diagnostic convenience does not justify retaining a usable
paid credential after the bounded run. Sanitized evidence and placeholder
overwrite are sufficient.

## 11. Acceptance and handoff

This design is ready for implementation planning when the user confirms the
written specification. Implementation completion will require fresh local
test evidence and self-review, followed by the mandatory live read-only Azure
gate. Only then may a new 24-hour exact-SHA authorization package be created.

The package must stop for the user's separate exact-SHA approval before any
Azure write, Key prompt, paid OpenAI request, deployment transition, or hosted
browser execution. The user will be reminded at the hidden TTY Key-input stage;
no Key is needed during design, implementation, tests, or package generation.
