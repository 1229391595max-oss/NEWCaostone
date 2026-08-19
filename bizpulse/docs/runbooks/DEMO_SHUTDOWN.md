# NEWCaostone Azure Demo Shutdown Runbook

Status: cleanup template only. Resource stop/delete, database destruction, Blob deletion, registry cleanup, remote branch/worktree deletion, and Key operations require a value-complete `CLEANUP_AUTHORIZATION.md`.

## Before requesting cleanup approval

- Inventory every exact Azure resource ID, image digest, registry artifact, PostgreSQL server/database, storage account/container, monitoring resource, secret-setting name, remote ref, and retained evidence object.
- Classify each target as stop, retain, export, revoke, soft-delete, or permanently delete.
- State recoverability, retention period, monthly cost effect, and user-owned exclusions.
- Preserve the local release manifest, hosted acceptance identifiers, migration head, synthetic manifest hash, and rollback evidence without credentials.

## Authorized order

1. Disable new public/operator sessions if approved.
2. Revoke the dedicated OpenAI Key through `AI_KEY_REVOCATION.md`.
3. Remove the server Key setting.
4. Preserve the approved evidence/retention set.
5. Stop or delete only exact named application, monitoring, PostgreSQL, Blob, network, registry, and resource-group targets in the approved order.
6. Verify billing/resource inventory and record only safe identifiers/status.

Never infer cleanup authority from plan approval, launch approval, a failed deployment, a reachable URL, or the age of a resource.
