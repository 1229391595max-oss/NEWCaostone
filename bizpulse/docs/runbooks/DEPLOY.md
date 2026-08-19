# NEWCaostone Azure Demo Deploy Runbook

Status: local template only. No Azure, registry, GitHub, DNS, secret, migration, deployment, or paid-provider action is authorized by this file.

## Required authorities

1. A clean, locally attested candidate and manifest-only child.
2. Separately authorized Azure read-only preflight for the intended tenant/subscription.
3. A single value-complete `LAUNCH_AUTHORIZATION.md` containing the exact subscription, region, resource group, generated names, SKUs, costs and hard cap, Git SHA, image digest, migration head, synthetic manifest hash, prior compatible digest, commands, retry limits, and stop conditions. For a fresh Container Apps environment, the package authorizes only the exact server-issued FQDN read from that declared app resource after phase 1; it does not guess a URL or require a second approval.
4. One explicit user approval of that exact package.

The checked-in `infra/environments/demo.bicepparam` is deliberately inert. Never change `deploymentEnabled` to `true` in source control and never place a secret value in a file, command transcript, log, or chat.

The Container Apps image pull authority is a task-owned user-assigned managed identity with the exact `AcrPull` role on the declared existing ACR. Do not enable the ACR admin account and do not place a registry password in parameters or environment variables. The approved package must register `Microsoft.App` before the first Container Apps deployment when the read-only preflight reports it unregistered, and must independently read back the managed identity, role assignment, app registry binding, and ACR ARM-audience authentication.

The approved launch package must preserve a two-phase rollout. Phase 1 uses the
exact image digest with `deploymentEnabled=true` and `applicationEnabled=false`.
This creates the private authorities, an application fenced with external
ingress disabled and zero minimum replicas, and four manual Jobs. Phase 2 may
set `applicationEnabled=true` and schedule maintenance only after every app
revision has drained to zero replicas, the `prepare` and `seed` Jobs each have
exactly one success in the authorization window, neither maintenance Job ran,
and all Job image/command/argument authorities match the package.

Phase 1 runs only `python scripts/phase1_fence_server.py`; the application container has no PostgreSQL, Blob, operator, session, or OpenAI secret authority.
Migration and seed may start only after the exact Phase 1 command/env/secret projection is verified and every application revision reports zero replicas.
Phase 2 removes the command override, restores the normal Uvicorn application authority, and must pass the exact phase2 fence before hosted acceptance begins.

The superseded rollout started the normal API before migration and stopped when
the missing `analysis_runs` authority prevented the prep revision from becoming
healthy and draining. A fence mismatch, nonzero replica, ambiguous Job,
migration failure, seed failure, or Phase 2 authority mismatch is a stop
condition; do not retry an old command or weaken the readback.

## Local preflight allowed before launch authority

```text
verify clean Git state and local release manifest
compile infra/main.bicep locally without Azure Resource Manager
build the exact local image from a clean commit
inspect non-root user, OCI revision label, command, and image contents
run local PostgreSQL/Azurite smoke with fake AI provider only
```

These checks do not prove a hosted state.

## Fixed AI qualification gate

The only approved provider snapshot is `gpt-5.4-nano-2026-03-17` with low
reasoning effort and a 2,800-token output ceiling. Runtime budgets are fixed at
120 provider attempts per day, 150,000 total tokens per month, 3 attempts per
Viewer session per minute, 20 global attempts per minute, and 15 concurrent
turns. Configuration drift fails closed.

The model qualification matrix is synthetic-only and contains exactly 12 cases:
English/Chinese x all/main/launch store scope x monthly sales report/inventory
risk. Ordinary local tests inject a fake provider and make no network calls.
The real qualification remains inert unless both the explicit
`--execute-paid-qualification` flag and a process-only `OPENAI_API_KEY` are
present. Its receipt contains hashes, token counts, case IDs, and pass/fail
checks only; it contains no key, prompt, or response text. Running that paid
gate belongs to the separately authorized AI release stage, never to local
development or the data-only release stage.

## Authorized release order

When `ai_limits.enabled=false`, both AI failure command groups are exact empty arrays and are omitted from `execution_order`.
When `ai_limits.enabled=true`, both AI failure rehearsals and the paid AI smoke remain mandatory.
Restricted no-AI launch packages still require canonical phase 2, strict health,
core browser acceptance, exact-15 capacity, natural session expiry, restart
readback, and rollback/forward recovery.
For an update target, the package's rollback source and digest must equal the
exact current private app image before any new image publication or activation.

Execute only the exact commands copied into the approved launch package:

```text
read-only recovery/configuration preflight
-> confirm cost cap and stop conditions
-> register Microsoft.App only if the exact package records it as unregistered
-> publish the immutable image digest if explicitly included
-> pull and inspect both current and rollback digests; require exact OCI source SHA and image-input hash labels
-> provision/update only declared resources in phase 1 with applicationEnabled=false
-> verify PostgreSQL backup/restore and Blob retention prerequisites
-> verify the prep revision, external=false, minReplicas=0, all revisions drained, and all four Jobs manual/idle
-> start/wait the same-VNet prepare Job (migrate forward to 0008_ai_budget_ledger and idempotently bootstrap the exact workspace/operator)
-> start/wait the same-VNet seed Job for the tests/fixtures/synthetic/v1 bundle directory
-> verify the prepared PostgreSQL/Blob authorities and this authorization window's exact Job successes
-> if AI is enabled, run the budget failure rehearsal; independently recover and verify private/minReplicas=0
-> if AI is enabled, run the provider-transport failure rehearsal with AI still enabled; independently recover and verify private/minReplicas=0
-> deploy phase 2 with the same digest and applicationEnabled=true
-> run both maintenance Jobs once, then verify their exact schedule/image/args and the complete phase-2 app configuration
-> resolve the exact Azure-issued app FQDN from the declared resource and verify /health/live and /health/ready without redirects
-> run operator/public core browser/API smoke, including synthetic export/outcome and explicit End Session
-> run the non-provider exact-15 session/read capacity check
-> admit one viewer, wait the real 25-35 minute idle TTL, run session maintenance, require the old cookie to fail, and admit a distinct replacement session
-> restart and compare the same pinned viewer's release, analysis, Action, Chat boundary, PostgreSQL, and Blob-backed projections
-> run the fixed two-turn paid AI smoke only if explicitly included, with AI enabled and exact token/cost limits
-> rehearse rollback to the prior compatible digest and forward again
-> compare the same pinned viewer authority after rollback and forward recovery
-> record hosted evidence without secret values
```

Every approved package carries its mode-specific `execution_order` as an exact
array. Do not execute command groups alphabetically or ad hoc. In an AI-enabled
package, both failure rehearsals intentionally finish with the application
private and at zero minimum replicas; executing either rehearsal after
canonical phase 2 would take the accepted URL offline and is a stop condition.
Restricted no-AI packages contain neither rehearsal command.

Stop immediately if a target, SKU, cost, digest, migration, URL, retry allowance, secret-presence flag, recovery prerequisite, or rollback path differs from the approved package. Do not substitute SQLite, local disk, a mutable image tag, an Alembic downgrade, or an undeclared service.

The phase-1 application must exist only in its fenced prep revision; ingress is
internal, minimum replicas are zero, and all four Jobs are manual. A failed,
stopped, duplicate, or ambiguous prepare/seed execution is a stop condition:
inspect the exact Job execution read-only, then require fresh authorization
before any retry not already present in the approved package.
