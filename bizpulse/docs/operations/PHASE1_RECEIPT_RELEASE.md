# Phase 1 Receipt Release Contract

This contract prevents a locally issued authorization timestamp from being
used as an Azure execution fence. It applies to the current no-AI recovery and
to future Azure Demo releases.

## Authority model

The Phase 1 ARM deployment completion timestamp reported by Azure is the only
valid Phase 1 anchor. A launch document's `issued_at` is an approval-window
timestamp; it is never evidence that the cloud application, Jobs, database, or
Blob state reached Phase 1.

The original launch authorization remains immutable. Existing v3/v4 launch
schemas and their verifier are not rewritten to make an already approved
document pass a new condition. Activation uses a second authorization document
that is generated only after Azure has produced a valid Phase 1 receipt.

## Required two-package sequence

1. Validate the first launch package by its exact user-approved SHA-256.
2. Execute that package only through Phase 1 deployment, database migration,
   and synthetic seed.
3. Stop before its static activation command.
4. Read the exact Phase 1 ARM deployment, private Container App, drained
   revisions, four Job definitions, and their execution histories from Azure.
5. Create a canonical mode-600 Phase 1 receipt. The receipt binds the original
   package SHA and authorization ID, release/image authority, Azure deployment
   completion time, private candidate revision, successful prepare/seed
   executions, and maintenance history.
6. Generate a second mode-600 receipt-resume authorization. It binds the source
   package, receipt, and the SHA-256 values of the receipt collector, resume
   generator, and ignored local runner.
7. Obtain explicit user approval for the second document's exact SHA-256.
8. Execute only its remaining stages, in order: prepared preflight, registry
   verification, receipt revalidation, activation fence, Phase 2 deployment,
   health, browser acceptance, capacity, natural expiry, restart readback, and
   rollback rehearsal.

## Fail-closed rules

- Maintenance that ended before the Azure Phase 1 anchor is historical and may
  be recorded in the receipt. A maintenance execution starting at or after the
  anchor rejects the receipt.
- Exactly one successful prepare execution and one successful seed execution
  must start at or after the anchor and finish before receipt observation.
- Once a valid receipt exists, registry publication, Phase 1 deployment,
  migration, and seed are not replayed by the resume package.
- Any source SHA, receipt SHA, release, image, command, control-file hash,
  current Azure state, expiry, or no-AI mismatch stops execution.
- The source package may be expired when its historical authority is checked at
  its own issuance time. The newly approved resume document must be current and
  expires exactly 24 hours after generation.
- Validation-only operation never reads Keychain credentials and never writes
  Azure. Execution loads deployment and browser credentials lazily and never
  imports or forwards an OpenAI API key.

Generated receipts, resume authorizations, credential material, and raw Azure
responses stay under the ignored `.tmp/` boundary and are never committed.

## Interrupted rollback-readback recovery

If the final rollback rehearsal creates a healthy rollback revision but stops
before its forward readback, do not replay the original resume package and do
not use Azure Portal to update the application.  The original rollback suffix
is immutable and a second rollback update with the same suffix is not a safe
retry.

Instead, collect a read-only proof that the exact rollback revision is latest
ready, healthy, singly routed, and still bound to the approved rollback image.
Generate a new owner-only rollback-forward authorization that binds this
revision, the original receipt-resume SHA, the candidate and rollback registry
identities, and the current readback script hash.  After a new explicit user
SHA-256 approval, it may execute only rollback preflight, registry readback,
one `recover` forward update, and final candidate health/readback.

The readback runner waits for Azure to report the exact latest-ready revision
after each update using a single bounded monotonic deadline.  A timeout is a
stop condition, not permission to submit another update.
