# Deployed Release Read-Only Diagnostic D1 Design

## Status

Approved design choice: split diagnosis from recovery. D1 is a new,
single-use, Azure-read-only observation package. It is not Recovery V7, does
not inherit V6 authority, and cannot continue into hosted acceptance or any
mutation. A later Recovery V7 requires a separate design, package,
authorization ID, SHA-256 approval, and receipt after D1 evidence is reviewed.

## Goal

Produce one bounded, replay-resistant and secret-free observation of the
currently deployed candidate application, revision, four Container Apps Jobs,
and their execution histories. The observation must distinguish desired-state
contract drift from harmless Azure-owned fields and historical executions,
while preserving enough safe evidence to design Recovery V7 without another
guess-driven package.

## Evidence Baseline

The implementation starts from the isolated clean worktree on branch
`codex/integrated-viewer-ai-anti-drift`. At design time its HEAD is
`5142170acb97edc5a3a6c19d7ee1c526eb845967`; this is an observation, not a
future package identity. Package generation must bind the then-current clean
HEAD and tree again.

The deployed compare-only anchor remains
`537effe3036f77f83225beef12589bd447205a8b`. It is not a changed-path baseline
and is not a source from which to rebuild D1. The V4 deployed continuation at
`release/incidents/2026-08-16-recovery-v4-deployed-continuation.json` remains
historical input and must be accepted only at its exact SHA-256. The generated
authority block in `release/current_authority.json` is stale and must not be
promoted into a new hosted claim.

Recovery V6 is retired. Its four completed Azure calls stopped at the first
prepare Job/execution validation. D1 must not replay V6 or resume any V6 child
command.

## Confirmed Defects D1 Must Address

1. `infra/modules/app.bicep` includes `BIZPULSE_ALLOWED_ORIGIN` and
   `BIZPULSE_OPERATOR_PASSWORD_HASH` in every Job, while the V6 verifier and
   its duplicate test fixture omit them.
2. The current prepare/seed execution rule rejects every additional history
   row, including an older failed seed execution that legitimately predates
   the bound successful seed.
3. The V6 runner reduces a safe verifier subcode to a generic stage error and
   creates no receipt when a pre-receipt read, registry check or Keychain check
   fails.
4. V6 binds only three control files although its runtime imports and commands
   use substantially more source files.
5. V6 relies on Azure CLI Container Apps output while the installed
   `containerapp` extension is a beta release whose API and response behavior
   can change independently.
6. Existing focused tests pass against a hand-built fixture and do not prove
   parity with the Bicep producer.

## Authority Boundary

### Allowed

- local package, Git, file-hash, dependency-lock and tool-version validation;
- local `az bicep build --file infra/modules/app.bicep --stdout`;
- Azure Resource Manager `GET` requests through core `az rest`;
- owner-only local attempt-receipt and sanitized-observation writes;
- bounded pagination over the exact revision and Job-execution collections.

### Forbidden

- every Azure `PUT`, `PATCH`, `POST`, `DELETE` or action endpoint;
- `az containerapp` and the Container Apps extension as an observation data
  source;
- registry login, ACR token retrieval, Docker pull or image publication;
- Keychain access or credential validation;
- public Demo, health, browser, capacity or natural-expiry requests;
- restart, rollback, deploy, Job start or Job template update;
- OpenAI Key access, AI enablement or paid-provider requests;
- push, PR, CI, DNS or authority-owner changes;
- modification of `release/current_authority.json` or a Hosted/Production
  claim.

The package must contain `allowed_http_methods=["GET"]` and a complete
allowlist of ARM resource paths. The runner rejects any command or `nextLink`
outside that method, host, subscription, resource group, provider, resource
name and API-version boundary.

## Component Design

### 1. Desired-state projection

`scripts/deployed_release_diagnostic_contract.py` owns the D1 schemas,
canonical JSON hashing, strict timestamp parsing, execution-state policy and
safe projection builders. It must not import test modules.

`scripts/build_deployed_release_desired_projection.py` runs Bicep build locally
and converts the compiled ARM template into one normalized desired projection.
It extracts, for the application and all four Jobs:

- resource role and container name;
- command and arguments;
- environment-variable names and binding kinds (`value` or `secretRef`);
- secret-reference names, never secret values;
- trigger type, timeout, retry limit, schedule/manual configuration;
- CPU and memory;
- application scale, probe, ingress and no-AI configuration names.

Dynamic safe expectations such as resource IDs, public hostname, image digest,
blob endpoint and dataset identifiers come from the exact continuation. Their
values are checked in memory but environment-variable values are not persisted
in the observation. The generated package contains only the canonical desired
projection SHA-256, not Bicep secrets or ARM parameter values.

Package load recomputes this projection from the same Bicep source and exact
continuation. Any compile failure or projection-hash change invalidates the
package before an Azure read.

This makes the compiled infrastructure producer part of the verifier contract.
Tests may still use compact synthetic payloads, but those payloads are built
from the same projection function rather than a second manually maintained Job
environment list.

### 2. Exact repository and toolchain binding

The package binds:

- exact Git branch, HEAD commit and tree SHA;
- a requirement that tracked index and worktree changes are empty;
- SHA-256 values for every D1 entrypoint, its local import closure,
  `infra/modules/app.bicep`, the continuation, `requirements.txt`,
  `requirements-dev.txt`, `package.json` and `package-lock.json`;
- Python, Azure CLI and Bicep versions observed at generation;
- the installed Container Apps extension version for evidence only.

Execution rejects a changed HEAD, tree, tracked file, control hash, dependency
lock or required tool version. Untracked files are permitted only because the
approved package, attempt receipt and observation live under ignored `.tmp`;
they are addressed by exact path and SHA instead of Git cleanliness.

D1 uses core `az rest`, so the Container Apps extension must not appear in an
executed command. Its observed version is recorded only to explain the local
toolchain and prevent accidental reintroduction.

### 3. ARM observation client

`scripts/observe_deployed_release_state.py` performs only exact
`https://management.azure.com` GET requests with API version `2024-03-01`.
The initial request set is:

1. one Container App resource;
2. the application's revision collection;
3. four exact Job resources;
4. four exact Job execution collections.

Collection `nextLink` values are followed only after strict URL validation.
Limits are:

- 30 seconds per request;
- zero request retries;
- 1,000,000 response bytes per page;
- five pages per collection;
- 8,000,000 response bytes for the entire observation;
- at most 30 Azure GET requests including pagination.

Timeout, malformed JSON, duplicate JSON keys, an unexpected response shape,
an invalid `nextLink`, an incomplete collection or any limit breach fails
closed. Raw response bodies, Azure tokens, stdout and stderr are never written
to a receipt or observation. A canonical SHA-256 of each raw response page is
retained as non-reversible provenance.

### 4. Projection comparison

Azure-owned fields such as `systemData`, provisioning metadata, default scale
fields and other unapproved response additions are ignored unless D1 explicitly
projects them. Security- and behavior-bearing fields are compared exactly to
the desired projection.

The sanitized observation stores:

- target resource IDs, names, revision identity and candidate image digest;
- environment-variable names and binding kinds only;
- configured secret names and secret-reference names only;
- Job trigger, timeout, retry, schedule/manual configuration, command,
  arguments and resource limits;
- execution name, official status, `startTime` and `endTime`;
- response-page hashes, pagination counts and completeness booleans;
- named check results and safe mismatch field names;
- exact package, continuation, desired-projection, Git-tree and toolchain
  identities.

It never stores environment values, secret values, access tokens, registry
credentials, connection strings, passwords, raw Azure JSON or child output.

### 5. Execution-history policy

D1 accepts only the `2024-03-01` documented states:

- `Running`
- `Processing`
- `Stopped`
- `Degraded`
- `Failed`
- `Unknown`
- `Succeeded`

The exact continuation-bound execution for each role must exist once, be
`Succeeded`, have valid UTC `startTime` and `endTime`, and satisfy
`startTime <= endTime <= continuation.recorded_at`.

For manual prepare and seed Jobs:

- an additional execution is historical only when it has an end time no later
  than the bound execution's start time;
- historical `Succeeded`, `Failed`, `Stopped` or `Degraded` rows are retained
  and reported but do not represent current drift;
- `Unknown`, missing/invalid timestamps, overlap with the bound run, or any
  execution starting after the bound execution fails the diagnostic.

For scheduled session/storage maintenance Jobs:

- historical terminal rows before the bound run are retained;
- later `Succeeded` rows are accepted;
- later `Running` or `Processing` rows are accepted only while their age is no
  greater than `replicaTimeout + 120 seconds` at the D1 observation time;
- later `Failed`, `Stopped`, `Degraded`, `Unknown`, over-age active rows or
  missing timestamps fail the diagnostic.

Names must be unique across the complete paginated collection. D1 does not
infer absence from an incomplete or truncated history.

### 6. One-shot runner and safe error channel

`scripts/create_deployed_release_diagnostic_package.py` creates the owner-only
package at
`.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md`. The document
uses schema `newcaostone.deployed-release-diagnostic-package.v1`, mode `0600`,
an independent authorization UUID, and an expiry no more than 24 hours after
issue. Package generation performs no Azure or Keychain access.

`scripts/run_deployed_release_diagnostic.py` validates the exact user-approved
package SHA-256, package mode, expiry, Git/toolchain/control bindings,
continuation and desired projection. Before the first `az rest` call it creates
`.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json` with `O_EXCL` and
mode `0600`. Any existing receipt consumes the package regardless of receipt
status.

The receipt schema is
`newcaostone.deployed-release-diagnostic-attempt.v1` and contains only:

- authorization and package identities;
- start/completion timestamps;
- status (`started`, `failed` or `completed`);
- count and safe role names of completed reads;
- failure stage, resource role and allowlisted error code;
- completed observation path and SHA-256 when successful.

The runner and observer exchange typed Python results and
`DeployedReleaseDiagnosticInvalid(code, stage, resource_role)`. Safe codes and
roles are enums. Arbitrary exception text, stdout and stderr are discarded.
Receipt replacement is atomic and preserves mode `0600`. A crash leaves a
`started` receipt and therefore consumes the package.

On success the runner creates
`.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_OBSERVATION.json` with `O_EXCL` and mode
`0600`, records its SHA-256 in the receipt and clears temporary in-memory
response objects.

### 7. Failure taxonomy

At minimum, tests and schemas cover these safe codes:

- `diagnostic_package_hash_mismatch`
- `diagnostic_package_invalid`
- `diagnostic_package_expired`
- `diagnostic_package_consumed`
- `diagnostic_repository_drift`
- `diagnostic_toolchain_drift`
- `diagnostic_control_drift`
- `diagnostic_bicep_projection_invalid`
- `diagnostic_arm_request_failed`
- `diagnostic_arm_response_invalid`
- `diagnostic_arm_scope_invalid`
- `diagnostic_pagination_invalid`
- `diagnostic_pagination_limit_exceeded`
- `diagnostic_application_drift`
- `diagnostic_revision_drift`
- `diagnostic_job_drift`
- `diagnostic_bound_execution_invalid`
- `diagnostic_execution_history_invalid`
- `diagnostic_observation_write_failed`

No safe error payload contains a resource value beyond an allowlisted role such
as `application`, `revision`, `prepare`, `seed`, `session_maintenance` or
`storage_maintenance`.

## Package Schema Outline

```json
{
  "schema_version": "newcaostone.deployed-release-diagnostic-package.v1",
  "authorization_id": "uuid",
  "issued_at": "UTC timestamp",
  "expires_at": "UTC timestamp",
  "repository": {
    "branch": "codex/integrated-viewer-ai-anti-drift",
    "head_sha": "40 hex",
    "tree_sha": "40 hex",
    "tracked_clean_required": true
  },
  "continuation": {
    "reference": "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json",
    "sha256": "64 hex"
  },
  "desired_projection_sha256": "64 hex",
  "control_sha256": {"relative/path": "64 hex"},
  "toolchain": {
    "python": "exact version",
    "azure_cli": "exact version",
    "bicep": "exact version",
    "containerapp_extension_observed": "exact version"
  },
  "arm": {
    "host": "management.azure.com",
    "api_version": "2024-03-01",
    "allowed_http_methods": ["GET"],
    "allowed_resource_paths": [
      "/subscriptions/{subscription}/resourceGroups/{resource-group}/providers/Microsoft.App/containerApps/{application}",
      "/subscriptions/{subscription}/resourceGroups/{resource-group}/providers/Microsoft.App/containerApps/{application}/revisions",
      "/subscriptions/{subscription}/resourceGroups/{resource-group}/providers/Microsoft.App/jobs/{job}",
      "/subscriptions/{subscription}/resourceGroups/{resource-group}/providers/Microsoft.App/jobs/{job}/executions"
    ],
    "request_timeout_seconds": 30,
    "request_retry_limit": 0,
    "max_page_bytes": 1000000,
    "max_pages_per_collection": 5,
    "max_total_response_bytes": 8000000,
    "max_total_requests": 30
  },
  "allowed_operations": [
    "local_contract_validation",
    "azure_resource_manager_read",
    "local_attempt_receipt_write",
    "local_sanitized_observation_write"
  ],
  "forbidden_operations": [
    "azure_mutation",
    "registry_access",
    "keychain_access",
    "public_url_access",
    "ai_access"
  ]
}
```

The braces above describe values derived from the exact continuation; generated
packages contain the concrete subscription, resource-group, application and
four Job paths. Duplicate paths are rejected. A pagination `nextLink` may add
only `api-version=2024-03-01` and one opaque pagination-token query parameter;
it may not change the path or any authority component.

All mappings use exact key sets, duplicate JSON keys are rejected, path
references are relative and traversal-free, and timestamps are timezone-aware
UTC values.

## Verification Strategy

Implementation is test-first and divided into independently reviewable gates:

1. Bicep compilation and desired-projection parity for all four Jobs and the
   app, including the two fields V6 omitted.
2. Exact package schema, mode, expiry, repository, toolchain, continuation,
   control closure and tamper rejection.
3. REST request construction, method/host/path/API allowlist, pagination,
   byte/request/time limits and duplicate-key rejection.
4. Azure-owned extra-field tolerance with exact security-bearing projections.
5. Bound execution, older failed seed, newer manual execution, scheduled
   success/failure, active timeout and pagination-completeness cases.
6. Receipt-before-read ordering, crash consumption, atomic updates, safe error
   propagation and raw-output/secret non-leakage.
7. Full focused suite, release-policy/static suite, `verify_changed` from the
   implementation batch base, Bicep build and secret-pattern scan.

The existing `66 passed` focused result is only a baseline. D1 is not complete
until a regression test fails against the V6-style duplicate fixture and then
passes against the compiled-Bicep projection.

## Execution and Evidence States

Implementation and local tests authorize no Azure read. After implementation,
the generator may create the mode-`0600` D1 package locally and report its
absolute path, authorization ID, expiry and SHA-256. Execution then stops for
explicit approval of that exact SHA-256.

An approved D1 execution may claim only:

`Read-only deployed-state observation completed`

It must not claim `Hosted verified`, `Azure accepted`, `Production ready`,
healthy Demo, successful recovery or AI availability. D1 does not update the
current authority block. Its sanitized result is reviewed before a separate
Recovery V7 design begins.

## Official Basis

- Azure Container Apps Jobs and execution history:
  <https://learn.microsoft.com/en-us/azure/container-apps/jobs>
- Job execution CLI behavior:
  <https://learn.microsoft.com/en-us/cli/azure/containerapp/job/execution?view=azure-cli-latest>
- Jobs Get REST API `2024-03-01`:
  <https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/jobs/get?view=rest-resource-manager-containerapps-2024-03-01>
- Jobs Executions List REST API `2024-03-01`:
  <https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/jobs-executions/list?view=rest-resource-manager-containerapps-2024-03-01>
- Bicep build behavior:
  <https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/bicep-cli>
- ARM template test toolkit and Bicep-linter boundary:
  <https://learn.microsoft.com/en-us/azure/azure-resource-manager/templates/test-toolkit>
- Microsoft Container Apps Jobs sample:
  <https://github.com/Azure-Samples/container-apps-jobs>
