# Phase 1 Receipt Recovery Design

## Goal

Recover a stopped no-AI Azure launch without replaying already-successful
Phase 1 work, and prevent future launches from confusing a package issue time
with the time at which Azure actually fenced writes.

## Observed Failure

The approved no-AI update package was issued at `2026-08-15T22:12:46Z`.
An existing scheduled session-maintenance execution started at `22:15:00Z`
and finished before the Phase 1 deployment completed at about `22:20Z`.
The Phase 1 deployment, drain fence, migration, and seed then succeeded.

The activation fence used the package issue time for both requirements:

1. the prepare and seed executions must start after the fence; and
2. no maintenance execution may start after the fence.

That caused a safe pre-Phase-1 maintenance execution to be treated as a
post-fence write. The fail-closed stop was correct; using the package issue
time as the cloud fence boundary was not.

## Scope

- Add a receipt-derived recovery authority for the currently fenced release.
- Add a durable Phase 1 receipt protocol for future launch packages.
- Preserve no-AI boundaries: AI remains disabled, no OpenAI secret is loaded,
  and no paid-AI command is authorized.
- Keep all new Azure reads bounded and all Azure writes inside a newly approved
  exact SHA-256 package.

## Non-Goals

- Do not loosen the activation fence.
- Do not recreate resources, republish images, rerun migration, or rerun seed
  during a valid recovery.
- Do not infer or expose credential values.
- Do not convert local validation into hosted acceptance evidence.

## Receipt Authority

### Future launches

The Phase 1 executor must create a mode-600 `phase1 receipt` only after all
of the following pass in one observed sequence:

1. Azure reports the expected private Phase 1 app revision and candidate
   digest, external ingress disabled, and all revisions drained to zero.
2. All four Jobs have the expected candidate image and Phase 1 trigger
   configuration, with no active or unknown execution state.
3. The executor records `phase1_fence_observed_at` immediately after the
   successful read-back.

The receipt contains only value-safe authority:

- source launch package SHA-256 and authorization ID;
- candidate Git SHA, image digest, image-input SHA-256, and rollback identity;
- Azure deployment ID and terminal timestamp;
- app name, exact private revision name, and candidate digest;
- `phase1_fence_observed_at`;
- the four job names and their terminal/no-active observation;
- receipt schema version and a fresh receipt ID.

The activation package is generated from that receipt, not from the local
clock. It requires prepare and seed executions to start at or after
`phase1_fence_observed_at`, and rejects any maintenance execution at or after
that same time.

### Current recovery

This launch predates receipts. A one-time legacy receipt may be derived only
when Azure proves all of the following:

1. the original Phase 1 deployment reached `Succeeded`;
2. the current app still exactly matches the private candidate Phase 1 state;
3. all revisions are drained and all Jobs are manual with no active or unknown
   execution;
4. exactly one successful prepare execution and one successful seed execution
   started after the Azure Phase 1 deployment terminal timestamp; and
5. no maintenance execution started at or after that timestamp.

The derived timestamp is then the recovery receipt anchor. This accepts the
known `22:15Z` maintenance execution because it completed before the Azure
Phase 1 deployment boundary, while still rejecting any maintenance execution
that could have overlapped the fenced work.

## Narrow Resume Package

The resume package must bind all of these values exactly:

- source package SHA-256 and source authorization ID;
- receipt SHA-256 and receipt ID;
- copied immutable release and rollback identity;
- no-AI declarations and zero OpenAI smoke cap;
- a 24-hour expiry window; and
- commands derived from the source package with the receipt anchor substituted
  only in the activation and Phase 2 fence commands.

It may authorize only this order:

1. prepared-state preflight;
2. candidate and rollback registry verification;
3. current private Phase 1 receipt revalidation;
4. activation fence;
5. Phase 2 deployment and maintenance-job enablement;
6. health, browser, capacity, expiry, restart-readback, and rollback-readback
   gates.

It must exclude registry publication, Phase 1 provisioning, migration, and
seed. A runner validates the new package SHA before every stage and only loads
the PostgreSQL/operator/session secrets for the Phase 2 deployment and browser
password for browser acceptance.

## Failure Rules

| Observation | Result |
| --- | --- |
| Maintenance execution before receipt anchor and already terminal | May recover. |
| Maintenance execution at or after receipt anchor | Reject recovery. |
| Prepare or seed before receipt anchor, missing, failed, or duplicated | Reject recovery. |
| Current app not private Phase 1 candidate state | Reject recovery. |
| Receipt/source/release/hash mismatch or expiry | Reject recovery. |
| Azure read failure or unknown execution state | Reject recovery. |

## Verification

The implementation must add RED/GREEN regressions for:

1. a legacy pre-Phase-1 maintenance execution being accepted;
2. a post-Phase-1 maintenance execution being rejected;
3. prepare or seed before the receipt anchor being rejected;
4. a resume package using the receipt timestamp rather than its issue time;
5. mismatched source package, receipt, candidate image, or no-AI declaration
   being rejected; and
6. the exact resume command set containing no registry publication, provision,
   migration, or seed stage.

The current recovery is complete only after receipt validation succeeds,
the new package is approved by SHA-256, and every authorized hosted gate
returns success.
