# Azure Readback Readiness Recovery Design

## Goal

Finish a no-AI Azure recovery when a rollback revision has been created and is
healthy, but an immediate control-plane read reports the prior
`latestReadyRevisionName` and interrupts the forward step.

## Observed Root Cause

The receipt-bound recovery runner created
`newcaostone-demo-app--rollback-78eaaf31-9508829`.  The first read immediately
after the Azure update still reported the previous candidate as
`latestReadyRevisionName`, so `resolve_hosted_url()` rejected the state and the
runner stopped before its forward operation.  A later read showed the rollback
revision as healthy and `latestReadyRevisionName` equal to that revision; its
health endpoint returned `200` with migration `0008_ai_budget_ledger`.

The fault is a control-plane propagation race in `run_azure_readback.py`, not
a bad image, database migration, public URL, or expired authorization.

## Scope

- Wait for an exact Container Apps revision to become the latest ready
  revision after every readback mutation.
- Bound every wait with one monotonic deadline and read-only polling.
- Add a `recover` readback operation that starts only from the exact, healthy
  rollback revision and forwards directly to the candidate image.
- Generate a new, narrow, receipt-bound recovery authority that contains only
  rollback-state preflight, registry verification, the forward recovery, and
  final readback checks.

## Non-Goals

- Do not repeat Phase 1 provisioning, migration, seed, image publication,
  browser import, capacity, or natural-expiry tests that completed before the
  interrupted rollback readback.
- Do not enable AI, load an OpenAI credential, or authorize paid-AI calls.
- Do not use a blind delay, redeploy a second rollback revision, or manually
  modify Azure Portal state.

## Design

### Exact readiness wait

`run_azure_readback.py` gains one small helper that invokes the existing
`resolve_hosted_url()` until it verifies the exact image and expected revision
suffix.  It catches only `HostedCheckInvalid`, sleeps at most five seconds,
and shares a single 300-second monotonic deadline.  Timeout fails closed with
`azure_readback_revision_not_ready`; it does not submit another update.

The helper is used after a rollback update, a forward update, and the existing
rollback-state recovery-forward update.  All Azure checks remain read-only.

### Direct forward recovery

`run_azure_readback.py --operation recover` accepts the same immutable
candidate and rollback identities as rollback.  It first requires the current
application to resolve exactly as the allowed rollback recovery revision.  It
creates one authorization-bound `recover-<authorization-prefix>-<digest>`
candidate revision, waits for exact readiness, verifies health, reconnects the
same viewer cookie jar, and compares the pinned session, release, analysis,
action-overlay, and no-AI boundary projections.

It never creates another rollback revision.  If the recovery update outcome is
ambiguous, the code first reads exact candidate state; otherwise it stops.

### No-AI compatibility boundary

The approved rollback image returns the legacy exact safe error
`503 {"code":"AI_CHAT_UNAVAILABLE"}` for Chat reads.  The candidate image
returns the newer exact no-AI projection with availability `unavailable` and
the same code.  The readback normalizes only those two exact representations
to one semantic no-AI authority before comparing the pinned viewer snapshot.
It does not accept any other 5xx response, code, or payload as a substitute.

### Narrow recovery authority

The new authority is derived from the original receipt-resume package and
binds all immutable source, receipt, candidate, rollback, control-script, and
current rollback-revision identities.  Its commands are limited to:

1. rollback-state read-only preflight;
2. candidate and rollback registry verification;
3. `run_azure_readback.py --operation recover`;
4. final candidate health/readback.

It expires within 24 hours and needs a new user SHA-256 approval before the
single Azure forward mutation.

## Failure Rules

| Observation | Result |
| --- | --- |
| Exact rollback revision is not latest-ready, healthy, single-revision, and externally routed | Reject recovery before mutation. |
| Candidate revision does not become exact latest-ready before deadline | Stop without a second update. |
| Candidate/rollback digest, receipt, source SHA, or control-script hash differs | Reject authority. |
| Pinned viewer state changes after forward | Fail recovery and do not claim launch success. |
| All checks pass | Generate user-approved URL handoff as no-AI hosted acceptance. |

## Verification

The implementation must prove:

1. an initially unready exact revision is polled until ready before viewer
   comparison;
2. a never-ready revision times out without submitting a forward mutation;
3. `recover` issues exactly one candidate update and never creates another
   rollback update;
4. the recover path rejects a non-rollback initial state;
5. source/resume identity and no-AI authority remain exact; and
6. legacy and current exact no-AI Chat representations normalize to the same
   safe viewer authority; and
7. the new package excludes Phase 1, migration, seed, AI, and rollback writes.
