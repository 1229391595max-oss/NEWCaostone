# NEWCaostone Azure Demo Recovery Runbook

Status: procedural template only. Restore, failover, object recovery, and replacement resources require exact external authorization.

## Recovery-first preflight

- Verify PostgreSQL backup retention and the exact recoverable timestamp range.
- Verify Blob soft-delete/container retention and storage lifecycle ledger health.
- Record the exact migration head, active public release, dataset/artifact digests, storage object references, and application digest.
- Confirm a replacement PostgreSQL target and temporary recovery namespace do not collide with retained resources.

## PostgreSQL restore

1. Stop or fence writes.
2. Restore to a new authorized server or recovery database; never overwrite the only retained authority during diagnosis.
3. Verify schema head and immutable dataset/analysis/forecast/bridge/action/Chat constraints.
4. Compare sentinel counts and exact public/version/session references.

## Blob reconciliation

1. Read referenced object keys and SHA-256 digests from the restored database.
2. Verify each referenced Blob through bounded server-side reads.
3. Restore only exact missing retained objects under the authorized storage mechanism.
4. Leave unreferenced objects quarantined for lifecycle review; do not permanently delete them without `CLEANUP_AUTHORIZATION.md`.

## Return to service

Deploy the authorized compatible digest, run health and restart readback, then repeat deterministic analysis, viewer pinning, Action, Chat isolation, and browser acceptance. Record `Hosted verified` only after all required evidence passes again.
