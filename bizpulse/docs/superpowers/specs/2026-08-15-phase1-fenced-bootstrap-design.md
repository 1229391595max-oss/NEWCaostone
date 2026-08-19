# Phase 1 Fenced Bootstrap Design

**Status:** Approved by the user on 2026-08-15.

## Incident and objective

The approved restricted no-AI launch reached the first Phase 1 fence and
stopped before migration. Azure created the private resources successfully,
but the normal API process started before the schema existed. `ApiContainer`
constructed `AnalysisService`, which attempted to update `analysis_runs`; the
database returned `UndefinedTable`. Azure repeatedly restarted the container,
kept one revision replica in `Activating`, and therefore could not satisfy the
required zero-replica drain fence.

The objective is to make Phase 1 a genuinely inert application state that can
be provisioned and drained before migration. Phase 2 remains the only state in
which the normal BizPulse API, database/Blob clients, application secrets, and
public ingress are enabled.

## Selected approach

The image will contain a small standard-library-only Phase 1 fence server.
When `applicationEnabled=false`, the Container App overrides the image's normal
command and runs only this server. It binds port 8000 and returns fixed,
value-free JSON for the two probe paths. It does not import `api`, `src`,
SQLAlchemy, Azure SDKs, or the application configuration module; it does not
read environment variables, connect to PostgreSQL or Blob, emit credentials,
or perform business writes.

The private Phase 1 revision uses:

- `command: ["python"]`;
- `args: ["scripts/phase1_fence_server.py"]`;
- only the minimum non-secret environment needed to identify the fenced mode;
- no application-level database, Blob, operator, session, or OpenAI secrets;
- internal ingress, `minReplicas=0`, and `maxReplicas=1`;
- liveness and readiness probes that can be satisfied only by the fence server.

The migration and seed Jobs remain separate resources and retain their exact
secure settings because they are the only Phase 1 actors allowed to access
PostgreSQL and Blob.

When `applicationEnabled=true`, Bicep omits the command override so Docker's
normal Uvicorn command runs. The normal application environment, secure
references, `/health/live` and `/health/ready` probes, single active revision,
external HTTPS ingress, and exact scale limits are restored. In restricted
no-AI mode the Phase 2 application still contains no OpenAI secret or endpoint
override.

## Alternatives rejected

1. Omitting the Container App until Phase 2 would avoid premature startup, but
   would substantially change the approved Phase 1 authority, URL derivation,
   revision fencing, and recovery readback.
2. Allowing the normal API to tolerate a missing schema would mix deployment
   orchestration into runtime behavior and could conceal a broken or incomplete
   migration. A healthy application must continue to fail closed on schema
   authority problems.

## Authority and verification changes

`verify_phase1_fence.py` will treat command, arguments, environment, probes,
and secret exposure as part of the authoritative state:

- `initial` and `activate` require the exact fence-server command and arguments,
  no application secret references, internal ingress, and all replicas drained;
- `phase2` requires the normal application command authority, the existing
  exact server settings and secrets, the exact ready revision, one active
  replica, single-revision traffic, and external ingress;
- any unknown or mixed projection fails closed.

Tests will be written before production changes and will prove:

1. the currently compiled Phase 1 template incorrectly uses the normal image
   command and therefore fails the new contract;
2. the compiled Phase 1 ARM template contains the exact fence command, probe
   paths, minimal environment, and no application secrets;
3. the compiled Phase 2 template retains the normal Uvicorn path, exact secure
   references, and no OpenAI authority when AI is disabled;
4. the fence server returns bounded JSON only for the expected health paths,
   rejects other paths, and never imports application/database/storage modules;
5. hosted verifier and release regressions remain green.

## Recovery and authorization

The failed Phase 1 state remains private and unseeded while this fix is built.
No existing approved command will be retried. After local verification:

1. retire the superseded attestation and create a new clean candidate;
2. run the full local release gate;
3. build and inspect a new `linux/amd64` image and immutable digest;
4. create a manifest-only attestation child;
5. generate a new exact cleanup package for the current failed private Phase 1
   resources;
6. generate a new restricted no-AI launch package with all non-AI gates;
7. stop for explicit approval of both new SHA256 values.

The operator password, PostgreSQL password, and session pepper already written
to macOS Keychain may be reused by the new package only if their exact secure
authority is preserved in memory. They will not be copied into files, logs,
Git, or chat. If safe reuse cannot be proved, new random values will be created
and atomically replace the Keychain entries before the next authorized launch.

## Evidence boundary

The remediation candidate, tests, image, attestation, and packages are local
evidence only. The Demo remains not deployed, not hosted-verified, not accepted,
and not Production-ready until a newly approved cleanup and launch both finish
and every hosted non-AI gate succeeds.
