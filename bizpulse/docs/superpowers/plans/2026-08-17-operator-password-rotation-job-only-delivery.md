# Operator Password Rotation Job-Only Delivery Implementation Plan

> **For agentic workers:** Execute inline in the existing isolated worktree; no external deployment occurs until the final package execution step.

**Goal:** Repair the Demo operator-password rotation so staging and cleanup update only the manual rotation Job, then complete the owner-authorized hosted rotation once.

**Architecture:** A new standalone Bicep entry point declares the existing-resource references and the rotation Job only. The Python executor selects that entry point for stage and cleanup and selects the existing full application template only for activation. The authority package uses schema v3 to bind this delivery contract.

**Tech Stack:** Python 3.12, pytest, Azure CLI/Bicep, Azure Container Apps Jobs, macOS Keychain, Docker Linux/amd64 candidate image.

## Global Constraints

- Work only in `/Users/maxli/Desktop/NEWCaostone/.worktrees/operator-rotation-hosted-base/bizpulse` on branch `codex/operator-rotation-hosted-base`.
- Preserve the pending Keychain pair until hosted acceptance and do not print secret values.
- Do not deploy a v2 package, retry the rotation Job, or update an App revision during stage or cleanup.
- Reuse the existing immutable candidate image unless a fresh local verification proves it unusable.

### Task 1: Add the regression contracts

**Files:**
- Modify: `tests/hosted/test_run_operator_rotation.py`
- Modify: `tests/infra/test_bicep_contract.py`

- [ ] Add a failing Azure-operation test that calls `stage_rotation_job()` and
  `remove_rotation_material()` with a fake command runner, then asserts the
  command uses `infra/environments/operator-rotation-job.bicepparam`, contains
  `operatorRotationEnabled`, and contains neither `applicationEnabled`,
  `applicationRevisionSuffix`, nor `deploymentEnabled`.
- [ ] Add a failing Bicep contract test that compiles
  `infra/operator_rotation_job.bicep`, requires a
  `Microsoft.App/jobs@2024-03-01` resource, and rejects the string
  `Microsoft.App/containerApps@`.
- [ ] Run the focused tests in the candidate Linux/amd64 image and record the
  expected failures before editing production code.

### Task 2: Introduce the isolated Job template

**Files:**
- Create: `infra/operator_rotation_job.bicep`
- Create: `infra/environments/operator-rotation-job.bicepparam`

- [ ] Declare existing environment, registry identity, PostgreSQL server, and
  storage account resources; derive the scoped Job configuration from those
  identities and secure environment values.
- [ ] Declare only the manual rotation Job, preserving `replicaRetryLimit: 0`,
  its expected-hash and rotation-ID environment variables, and a disabled
  cleanup configuration.
- [ ] Compile the template locally with `az bicep build` and make the new Bicep
  contract pass.

### Task 3: Select phase-specific deployment paths

**Files:**
- Modify: `scripts/run_operator_rotation.py`
- Modify: `scripts/generate_operator_rotation_authority.py`
- Modify: `tests/hosted/test_run_operator_rotation.py`
- Modify: `tests/hosted/test_operator_rotation_authority.py`

- [ ] Change the authority schema to v3 and include the
  `job-only-stage-v1` delivery contract in canonical package data.
- [ ] Make stage and cleanup deploy the job-only parameter file with only the
  parameters it declares; make activation alone deploy `demo.bicepparam` and a
  unique `rotate-<id>` or `inverse-<id>` App revision suffix.
- [ ] Remove the active revision suffix from the stage-operation interface so a
  future caller cannot accidentally reuse it.
- [ ] Run the focused Python regression suite in the candidate Linux/amd64
  image, plus host Bicep compilation for the full App and Job-only templates.

### Task 4: Generate and execute the repaired authority package

**Files:**
- Generated: `deliverables/operator-password-rotation/<new-id>.json`
- Generated: `deliverables/operator-password-rotation/<new-id>-receipt.json`

- [ ] Commit the validated repair in the isolated branch.
- [ ] Re-run the A0 read-only preflight and registry digest verification, then
  generate a v3 package bound to the live App and current Pending pair.
- [ ] Execute that exact fresh package once: stage the Job, start one manual
  execution, activate the unique App revision, check readiness, perform one
  login/logout, clean Job rotation material, and promote Pending to Current.
- [ ] Re-read hosted App/revision/health state and Keychain metadata, then
  report only value-free evidence and the generated receipt path.
