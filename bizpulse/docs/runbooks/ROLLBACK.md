# NEWCaostone Azure Demo Rollback Runbook

Status: procedural template only. Rollback is an external mutation and requires inclusion in the approved launch package or a new exact authorization.

## Preconditions

- Stop new operator writes if integrity or migration compatibility is uncertain.
- Identify the exact current and prior immutable image digests.
- Confirm the prior application is forward-schema compatible with migration head `0008_ai_budget_ledger`.
- Record current public release pointer, dataset version, PostgreSQL backup identity, and Blob storage account/container identifiers without credentials.
- Confirm the approved retry count and cost/availability impact.

## Application rollback

1. Deploy only the authorized prior compatible digest; never use a mutable tag.
2. Do not run `alembic downgrade` on retained data.
3. Verify liveness/readiness, migration head, PostgreSQL/Blob configuration, fixed public version, operator authentication, and session reads.
4. If the issue is a bad public dataset release rather than code, atomically repoint to the prior immutable version through the operator service; do not delete either version.
5. Run restart readback and the bounded acceptance subset named in the authorization package.

If any persisted record or Blob reference is incompatible, stop writes and follow `RECOVERY.md`; do not improvise deletion or repair.
