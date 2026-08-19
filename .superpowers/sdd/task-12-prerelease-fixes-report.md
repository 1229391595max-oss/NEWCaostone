# Task 12A Pre-release Fix Report

## Result

Task 12A is implemented and locally verified from reviewed base
`ba3c9a6d5485c5a83bb471c56fa323b17baab134`.

- Initial implementation commit: `8eee45b0394e55247944ba1b28e3551b9cac0515`
- Nested bootstrap object-path fix:
  `09949e198085aa0386fdb76a3cc5282820cc5872`
- Fail-closed bootstrap pipeline fix:
  `94ca7b30f90c9db34d94bfa0892e6c33b2749b3d`
- Canonical exact-runtime path fix:
  `9da84894140d7e649ca8779ded46508ae5987447`
- Current-authority refresh design:
  `41a8ec601a70f3034c683f41c16164b296875ee1`
- Exact read-only current-authority refresh implementation:
  `d506a5a1d103c49fdd3be604bf7e5dc982e5c765`
- Owner-private authority-bundle staging review fix:
  `1edc8b14899643fb1c52947239cdc89a05a09a94`
- Post-R19 recovery-adoption design and plan:
  `b674918db68c95993c7cc855032f1b0fd5beb7bb`
- Exact recovery-adoption implementation:
  `310ae240e9d72ccb79172870754519c88c4bb145`
- Supplied-authority admission review fix:
  `17f92d929ab5e0ff86b06163ed7fd5d10e63535f`
- Final independent review: **CLEAN — 0 Critical, 0 Important, 0 Minor**
- Evidence state: local implementation and local acceptance only
- External actions: none. No live image build/push, authorization-package
  generation/execution, Azure/OpenAI/Key Vault call, deploy, replay, cleanup,
  or `main` mutation was performed.

## Original findings: RED to GREEN

### Critical 1 — exact build-context provenance

RED coverage rejected untracked Docker-context source in `api`, `src`,
`frontend`, and `alembic`, plus mismatched context, image-label, OCI, and
package bindings.

GREEN builds only a private read-only `git archive` of one exact commit,
derives the build-context/image-input manifests from those bytes, exports one
OCI archive, validates every descriptor/blob/label, and binds the manifest and
archive hashes through package, publisher, controller, and receipt. The exact
OCI layout is published without a mutable Docker tag or rebuild.

### Critical 2 — committed live operations adapter

RED coverage proved the documented factory was absent and the controller's
real state/RBAC ordering was not executable.

GREEN adds the committed `scripts.admin_ai_release_operations:create_operations`
adapter and integrates the exact read-only preflight, OCI publication, Task 10
RBAC action, forward-compatible candidate deployment, atomic migration Job
execution override, authenticated Operator/Admin HTTP flow, Demo flow,
immutable evidence, secret scanning, and fail-closed no-retry ordering.

### Critical 3 — immutable per-turn shared binding

RED PostgreSQL/service/hosted tests demonstrated that equal display
fingerprints could not prove two turns used the same exact credential version,
and that a concurrent replay could continue with a different selected binding.

GREEN migration `0017_ai_turn_credential_binding` persists an immutable
non-secret binding ID, control revision, and request ID. Operator-only audit
projection and hosted verification require exact Operator/Demo binding
equality. Recovered replays cannot continue provider work unless exact binding,
revision, and request ownership match.

### Important 1 — ambiguous Key Vault compensation

RED fakes committed the candidate as latest and then raised, including the
no-prior-value case.

GREEN marks the write attempted before dispatch, performs exactly one prior
value restoration after an ambiguous outcome, never retries candidate
validation/activation, and preserves both channels disabled with explicit
reconciliation-required evidence when no prior value exists.

### Important 2 — Admin document cache policy

RED tests covered authenticated, anonymous, Demo, child, redirect, and unknown
`/admin/*` responses.

GREEN applies `Cache-Control: private, no-store` and `Vary: Cookie` to the
entire `/admin` document prefix and Admin API boundary.

### Minor — localized workspace entry

RED frontend tests showed the Administrator entry remained English after a
Chinese language switch.

GREEN adds matching English/Chinese catalog copy and localized accessible
name/title behavior.

## Final-review repair rounds

Every Critical/Important finding from repeated independent review received a
focused RED before its fix. The final coherent implementation also closes:

- exact committed runtime-tool and Bicep provenance, recursive import-shadow
  rejection, private isolated source/dependency materialization, trusted
  installed-dependency file hashes, and one captured source SHA/tree;
- OCI runtime-user validation and safe extraction of the approved archive into
  the layout consumed by ORAS;
- strict real Task 10 contract validation, package-time validation before the
  first Azure read, exact R19 consumed package/receipt provenance, and the
  post-R19 healthy AI-disabled revision/digest/tag successor boundary;
- exact fresh `/health/ready` database-head binding and pre-publication
  revalidation; candidate readiness now permits only additive `0014`, `0015`,
  `0016`, and `0017`, while package creation accepts only pre-migration
  `0014`–`0016`;
- capability-first migration ordering, exact `0017` post-migration gate, and
  candidate-only safe-stop semantics because the old image is not ready on
  `0017`;
- complete migration Job resource/template authority, secret-free projection,
  no retry, and a package-bound full execution override rather than a mutable
  read-then-start template;
- immediate exact/generic response and header secret rejection, bounded
  revision/request-scoped log queries with ingestion watermark and settling
  poll, bounded Admin audit-row validation/scanning, and real response request
  IDs only;
- exact audit actor/status/request/turn/binding validation and authenticated
  Demo denial of `/admin`;
- a validated controlling TTY attached only to the isolated release child, so
  committed bootstrap source can remain on stdin while no-TTY execution stops
  before preflight or mutation.

## Post-review bootstrap path follow-up

A no-action live-preparation attempt exposed that the repository top level is
the worktree parent while every supported command runs from its `bizpulse`
subdirectory. Git therefore rejected the documented
`<sha>:scripts/admin_ai_exact_runtime.py` operand; from that required working
directory the exact committed object is
`<sha>:./scripts/admin_ai_exact_runtime.py`.

The first RED covered all three documented build/package/release lookups with
real Git from the actual nested project, required equality with the same
captured root-qualified object, rejected the old root-relative and moved
paths, and reproduced the same defect in the non-snapshot operations-factory
binding. GREEN changes all three runbook commands, the exact-runtime help, and
the factory Git read to cwd-relative object syntax. The audit found no other
bad executable assumption: the remaining `create_release_manifest.py` reads
deliberately run from the repository root with `bizpulse/...` paths.

Independent review then found that plain Bash pipeline status could mask a
failed `git show`: Python accepted empty stdin and exited zero. A second RED
parsed and ran each complete documented pipeline, proving a moved path must
make the aggregate command nonzero. GREEN enables `set -o pipefail` in each
block and documents the requirement in launcher help. Exact implementation
commit `94ca7b30f90c9db34d94bfa0892e6c33b2749b3d` received a fresh independent
assessment of **CLEAN — 0 Critical, 0 Important, 0 Minor**.

## Current-authority refresh follow-up

A fifth no-action preparation attempt stopped before choosing an Admin AI
attempt UUID because `release/current_authority.json` had expired. Package
generation was ordered to perform fresh hosted reads before its later
authority capture, so invoking it would have reached the stale-authority stop
only after unnecessary reads. The attempt therefore stopped earlier; the
runbook described a separately authorized refresh without providing an
executable path. No Azure/public read, UUID, Docker build, request, package,
receipt, or controller action occurred in that stopped preparation attempt.

RED hermetic coverage required one exact committed-source entrypoint, exact
owner-only R19 package/failed-receipt provenance without reuse, a newly
generated strict Task 10 successor held only in memory, and a fixed read
contract of twelve existing sanitized Azure reads plus one bounded public
readiness GET. It rejected any source/document drift, R18/R19 mismatch,
revision/digest/tag/topology/traffic/RBAC/AI-disabled/readiness/schema/channel
change, malformed freshness window, or partial bundle replacement. A further
RED proved that the canonical evidence hash must include the public
readiness/schema projection as well as the twelve-read result and projection.

GREEN adds the committed-bootstrap `authority-refresh` mode and dedicated
refresh entrypoint. The bootstrap uses the same exact clean SHA/tree, private
read-only source snapshot, trusted dependency manifest, canonical path,
import-shadow, and safe-environment controls as package/release execution. It
copies the two retired R19 inputs as `0400` files only after exact mode and
SHA-256 validation. The child verifies the exact R19 predecessor and terminal
receipt, creates a fresh successor request only in memory, and accepts only the
R19 terminal revision/digest/derived tag at one healthy revision and 100%
traffic, `officer_only` RBAC, process AI disabled, and public readiness at
`0014_import_base_lineage`. Because 0014 predates the database AI-control
tables, that exact schema plus the disabled process state proves both channels
false without a database credential or mutation.

Only after the complete 12+1 read and a post-read HEAD/tree/status/document
fence does the entrypoint render the authority and all policy documents. It
preserves `attested_rollback` and `prepared_candidate`, replaces only observed
deployment/freshness, derives development migration `0017` and AI capability
from the exact snapshot, and applies an all-or-restored local bundle. Every
forward and rollback stage remains `0600` through replacement; the final mode
is restored on the exact no-follow file descriptor and both the file and
parent directory are synced. Output contains only bounded safe counts,
identifiers, timestamps, and hashes. The command performs no Azure mutation,
Docker/registry action, secret read, paid call, or release-package generation.

The exact committed-object `authority-refresh --help` command was run from the
required `bizpulse` subdirectory. It validated private snapshot, R19 input, and
dependency wiring, returned zero, and exited before the refresh entrypoint
could perform any public or Azure read. Exact follow-up commit
`1edc8b14899643fb1c52947239cdc89a05a09a94` received a fresh independent
assessment of **CLEAN — 0 Critical, 0 Important, 0 Minor**.

## macOS canonical runtime-path follow-up

A later no-action preparation attempt stopped before Docker because macOS
reported the new private temporary directory lexically as `/var/folders/...`,
while the child entrypoint's `Path(__file__).resolve()` reported the same
directory as `/private/var/folders/...`. The strict runtime guard correctly
rejected those unequal strings, but the parent had failed to establish one
canonical representation before exporting the binding. The consumed attempt
UUID and its absent artifact paths remain retired and were not reused.

RED integration coverage reproduced the macOS-style alias and the real child
guard, showed package artifact argv carried the noncanonical spelling, retained
rejection of a genuinely different target, and demonstrated that swapping a
temporary-root symlink could redirect both execution and cleanup to a decoy.
GREEN now resolves the existing project and OS temporary roots once, creates
the owner-private temporary directory under the canonical root, validates its
containment and mode, and derives the snapshot, environment variable, child
argv/import context, dependency root, entrypoint, copied inputs, and cleanup
path from that single real location. Artifact, Task 10 request, and release
package inputs use strict canonical resolution before copying; manifest
artifact identity remains project-relative and hash-bound; outputs remain
outside the snapshot under the canonical original-project cwd.

The real committed Git-object command was exercised safely with `build --help`:
it reached builder help, returned zero, did not invoke Docker, and left no
private-runtime directory behind. Exact implementation commit
`9da84894140d7e649ca8779ded46508ae5987447` received a fresh independent
assessment of **CLEAN — 0 Critical, 0 Important, 0 Minor**.

## Post-R19 recovery-adoption addendum

The bounded diagnosis report records that R19's last accepted reconciliation
remains historical revision
`newcaostone-demo-app--ai-off-9c35ae6a-2bf7086`, while the legitimate later
disabled recovery revision is
`newcaostone-demo-app--recover-b-9c35ae6a-2bf7086`. This implementation does
not rewrite, replay, delete, or reinterpret the owner-only R19 package or failed
receipt. A separate successor contract deterministically derives the recovery
suffix from the exact R19 package-hash prefix `9c35ae6a`, terminal image-digest
prefix `2bf7086`, failed terminal contract, and absence of an accepted recovery
record.

RED coverage rejected the historical R18/R19 revisions, arbitrary recovery
labels, digest/tag drift, `registry_plus_ai` at the adoption boundary, changed
R19 provenance, malformed failure contracts, and non-Task12 artifact paths.
GREEN binds the sole current read-only adoption profile to the exact recovery
revision, digest
`sha256:2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425`,
tag `ai-962a4fa43804-9c35ae6a`, `registry_only` identity, process AI disabled,
no AI bindings, exact one-revision/100%-traffic health, `officer_only` RBAC,
and readiness schema `0014_import_base_lineage` with both database channels
inferred false.

The lower historical Task 10 validator still accepts the exact immutable R19
contract with its original `ai-off` target and `registry_plus_ai` prepackage
gate. Only UUID-addressed Task12 artifacts select the new successor. Both
generated and supplied Admin observation requests must use that exact profile,
and the package CLI revalidates the owner-only prior artifacts before the first
Azure read. Final Admin package validation independently rejects a historical
profile even if its baseline is internally consistent.

The existing twelve sanitized Azure reads are parameterized by the already
validated identity profile. Future mutation remains separately package-bound:
the disabled recovery begins registry-only, and only the enabled capability
transition may attach the exact AI identity and Key Vault locator values after
Task 10 RBAC reconciliation. Disabled recovery continues to remove the AI
identity and bindings fail-closed.

The implementation performed no Azure/public readiness read, Docker or
registry operation, package generation, UUID creation, deploy, secret access,
cleanup, or R19 file mutation. It updates only local source, tests, policy, and
wording; therefore it does not prove hosted acceptance or current live state.
Exact fix commit `17f92d929ab5e0ff86b06163ed7fd5d10e63535f`
received a fresh independent assessment of
**CLEAN — 0 Critical, 0 Important, 0 Minor**.

## Verification evidence

All commands ran locally in `bizpulse`; no hosted service was contacted.

- Full Python after the canonical runtime-path repair:
  `1309 passed, 314 skipped` in 114.74s.
- Full Python after the current-authority refresh and review fixes:
  `1332 passed, 314 skipped` in 108.58s.
- Full Python after the post-R19 recovery-adoption review fix:
  `1350 passed, 314 skipped` in 104.21s.
- Frontend: `220 passed`.
- Focused post-R19 successor/Task 10/Admin release/policy suite:
  `321 passed` in 6.50s.
- Focused current-authority/Task 10/bootstrap/release contract:
  `347 passed` in 18.38s before the private-stage review fix; focused
  post-fix authority/bootstrap coverage `177 passed` in 14.59s.
- Focused exact-runtime/OCI/release provenance:
  `153 passed` in 14.04s.
- Full hosted authority/controller/action focus: `195 passed`.
- Bicep/release/security/provenance/secret focus: `293 passed, 25 skipped`.
- Guarded real PostgreSQL migration/trigger suite:
  `29 passed` in 11.89s after the canonical path repair.
- Guarded real PostgreSQL cloud application-shell suite:
  `20 passed` in 4.79s.
- Guarded real PostgreSQL AI/rotation service suite:
  `65 passed` in 271.45s.
- Exact `0014 -> one migration invocation -> 0017` guarded PostgreSQL test:
  `1 passed` (also included in the 29-test migration suite).
- Proportionate guarded PostgreSQL 0014 lineage and full migration chain after
  the authority-refresh change: `9 passed` in 2.86s; after the recovery
  adoption change the same real PostgreSQL set passed `9` tests in 2.28s.
- Release static verifier with the synthetic manifest and dirty-worktree
  allowance: `development_static_check=ok`, `checks_passed=1`.
- Required Ruff command:
  `.venv/bin/python -m ruff check api src scripts tests alembic` — passed.
- `git diff --check` — passed.
- Independent reviewer evidence on the final content snapshot: focused
  `268 passed, 12 skipped`; service/API/security `24 passed, 67 skipped`;
  frontend `220 passed`; Ruff and diff check passed. The bootstrap follow-up
  received a separate exact-commit review and final assessment CLEAN. The
  authority-refresh follow-up reviewer ran 61 focused tests on exact
  `1edc8b14899643fb1c52947239cdc89a05a09a94`, confirmed its tree and clean
  status, and reported **0 Critical, 0 Important, 0 Minor**. The post-R19
  reviewer ran 321 focused tests against exact `17f92d9`, confirmed tree
  `74aee6e`, Ruff, diff check, and clean status, and reported
  **0 Critical, 0 Important, 0 Minor**.

PostgreSQL skips in the ordinary full run are expected because those tests are
guarded. The separate `scripts/test_postgres.py` results above prove the
relevant cases executed against ephemeral real PostgreSQL.

## Changed files

### Authority, handoff, and runbooks

- `AUTHORIZATION_LEDGER.md`
- `CURRENT_STATUS.md`
- `docs/handoffs/AZURE_LAUNCH_HANDOFF_2026-08-15.md`
- `docs/handoffs/CURRENT_HANDOFF.md`
- `docs/handoffs/NEXT_AI_BOOTSTRAP_2026-08-15.md`
- `bizpulse/docs/operations/AZURE_LAUNCH_RUNBOOK.md`
- `bizpulse/docs/superpowers/plans/2026-08-18-admin-ai-post-r19-recovery-adoption.md`
- `bizpulse/docs/superpowers/specs/2026-08-18-admin-ai-post-r19-recovery-adoption-design.md`
- `bizpulse/docs/runbooks/AI_ENABLEMENT.md`
- `bizpulse/release/current_authority.json`

### Application, schema, and frontend

- `bizpulse/Dockerfile`
- `bizpulse/alembic/versions/0017_ai_turn_credential_binding.py`
- `bizpulse/api/main.py`
- `bizpulse/api/routers/health.py`
- `bizpulse/api/security_policy.py`
- `bizpulse/api/v1/routers/admin.py`
- `bizpulse/api/v1/routers/ai_chat.py`
- `bizpulse/api/v1/schemas/admin.py`
- `bizpulse/frontend/assets/app.mjs`
- `bizpulse/frontend/assets/i18n/catalog.mjs`
- `bizpulse/frontend/index.html`
- `bizpulse/src/ai/contracts.py`
- `bizpulse/src/ai/release_constants.py`
- `bizpulse/src/config.py`
- `bizpulse/src/db/readiness.py`
- `bizpulse/src/db/schema.py`
- `bizpulse/src/repositories/admin_ai.py`
- `bizpulse/src/repositories/ai_chat.py`
- `bizpulse/src/services/ai_chat_service.py`
- `bizpulse/src/services/ai_control_service.py`
- `bizpulse/src/services/openai_key_rotation_service.py`

### Release tooling

- `bizpulse/scripts/admin_ai_current_successor.py`
- `bizpulse/scripts/admin_ai_exact_runtime.py`
- `bizpulse/scripts/admin_ai_oci_artifact.py`
- `bizpulse/scripts/admin_ai_release_operations.py`
- `bizpulse/scripts/admin_ai_runtime_dependencies.json`
- `bizpulse/scripts/ai_enablement_contract.py`
- `bizpulse/scripts/azure_ai_enablement_actions.py`
- `bizpulse/scripts/azure_ai_reconciliation.py`
- `bizpulse/scripts/build_admin_ai_candidate.py`
- `bizpulse/scripts/create_admin_ai_release_package.py`
- `bizpulse/scripts/create_ai_enablement_package.py`
- `bizpulse/scripts/publish_registry_image.py`
- `bizpulse/scripts/refresh_admin_ai_current_authority.py`
- `bizpulse/scripts/refresh_current_authority.py`
- `bizpulse/scripts/release_authority.py`
- `bizpulse/scripts/run_admin_ai_release.py`
- `bizpulse/scripts/run_azure_job.py`
- `bizpulse/scripts/verify_admin_ai_control.py`
- `bizpulse/scripts/verify_release.py`

### Tests and hosted verifier

- `bizpulse/tests/acceptance/test_rollback_compatibility.py`
- `bizpulse/tests/api/test_admin_api.py`
- `bizpulse/tests/api/test_admin_shell.py`
- `bizpulse/tests/api/test_application_shell.py`
- `bizpulse/tests/frontend/admin-overview.test.mjs`
- `bizpulse/tests/frontend/shell.test.mjs`
- `bizpulse/tests/hosted/test_admin_ai_candidate_artifact.py`
- `bizpulse/tests/hosted/test_admin_ai_exact_runtime.py`
- `bizpulse/tests/hosted/test_admin_ai_release_contract.py`
- `bizpulse/tests/hosted/test_azure_ai_enablement_actions.py`
- `bizpulse/tests/hosted/test_azure_ai_reconciliation.py`
- `bizpulse/tests/hosted/test_create_ai_enablement_package.py`
- `bizpulse/tests/hosted/test_publish_registry_image.py`
- `bizpulse/tests/hosted/test_refresh_admin_ai_current_authority.py`
- `bizpulse/tests/hosted/test_run_ai_disabled_recovery.py`
- `bizpulse/tests/hosted/test_run_azure_job.py`
- `bizpulse/tests/hosted/verify_admin_ai_control.py`
- `bizpulse/tests/postgres/test_0007_chat_session_fences.py`
- `bizpulse/tests/postgres/test_0008_ai_budget_ledger.py`
- `bizpulse/tests/postgres/test_0009_prompt_preset_audit.py`
- `bizpulse/tests/postgres/test_0010_demo_data_activation.py`
- `bizpulse/tests/postgres/test_migration_chain.py`
- `bizpulse/tests/release/test_authority_contract.py`
- `bizpulse/tests/release/test_select_required_checks.py`
- `bizpulse/tests/release/test_container_contract.py`
- `bizpulse/tests/security/test_headers.py`
- `bizpulse/tests/services/test_admin_summary_service.py`
- `bizpulse/tests/services/test_ai_chat_service.py`
- `bizpulse/tests/services/test_openai_key_rotation_service.py`

## Residual risk and next boundary

- `release/current_authority.json` remains intentionally expired/stale in this
  implementation commit. Package generation stays fail-closed until the new
  exact command is separately authorized and executed, its authority/document
  delta is reviewed, and that local-only delta is committed as a new source.
- This implementation turn did not execute the refresh, contact Azure or the
  public readiness endpoint, or create a live/transient attempt UUID. The next
  boundary is one separately authorized read-only refresh execution; success
  intentionally leaves only the tracked authority/policy-document delta dirty
  for review and commit.
- No candidate OCI archive or real authorization package was created. A future
  attempt must start from this exact clean committed source, produce new
  UUID-addressed artifacts, obtain separate approval of the complete package
  SHA-256, and preserve every retired package/receipt fence.
- Local tests and this report are not hosted, paid-AI, Staging, Production,
  browser, capacity, restart, or rollback acceptance evidence.
- Any live revision, digest, tag, RBAC, migration Job, or database-head drift
  stops during fresh package/preflight validation before publication or
  mutation. Recovery after an `0017` migration must remain forward-only on the
  candidate revision and requires new authorization.
