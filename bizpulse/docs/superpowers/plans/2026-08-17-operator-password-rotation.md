# Operator Password Rotation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the owner set a replacement `operator` password locally, rotate the hosted Demo credential with an exact-old-state guard, revoke all existing operator sessions, and promote the verified replacement into the current Keychain entries without ever printing or placing a plaintext password on a command line.

**Architecture:** Split the operation into three deliberately separate layers. A macOS-only controller stores a Pending password and Argon2id hash through Security.framework. A container-compatible, transactional rotation job changes only the one active synthetic-Demo operator row and revokes its sessions under a PostgreSQL advisory lock. A release controller builds an immutable, approval-bound rotation package, runs the one permitted Azure job execution, verifies the new app revision and one login/logout, then promotes Pending to Current locally. The release controller never reads a Keychain plaintext into its output or embeds a secret in an Azure CLI argument.

**Tech Stack:** Python 3.12, FastAPI project services/repositories, SQLAlchemy/PostgreSQL, Argon2id, macOS Security.framework, Azure Container Apps Jobs, Bicep, pytest, existing Azure control scripts.

## Global Constraints

- All implementation work stays in `/Users/maxli/Desktop/NEWCaostone/.worktrees/implementation/bizpulse` on `codex/newcaostone-implementation-v3`.
- Do not change `/Users/maxli/Desktop/CAPTSONE`; it is evidence/reference only.
- Do not print, log, serialize, put in a shell command line, or place in a receipt any plaintext password, Argon2 hash, session cookie, CSRF token, or Azure secret value.
- Keep the current Keychain entries untouched until hosted verification passes. Pending entries are the only pre-hosted mutation.
- The hosted job must compare the database row to a supplied SHA-256 fingerprint of the expected old Argon2 string before changing it. It must never perform an unconditional password update.
- All session revocation and ephemeral-chat cleanup occur in the same database transaction as the exact password update.
- A remote Azure/PostgreSQL mutation is prohibited until a freshly generated package, its exact source/image identity, target app/revision, expected-old fingerprint, and rollback predicate have been shown to the owner and explicitly approved.
- No user-facing reset endpoint is added. The credential remains a server-owned, single-operator Demo control.

---

## File Structure

```text
scripts/
  operator_rotation_keychain.py             # macOS Security.framework boundary and Pending/Current promotion
  generate_operator_rotation_authority.py   # read-only package generator and SHA-bound authorization input
  rotate_operator_password.py               # container-job entry point; no macOS dependency
  run_operator_rotation.py                  # controlled package executor and hosted verification orchestrator
src/
  repositories/operators.py                 # exact active-row lock/update primitive
  repositories/sessions.py                  # bulk operator-session revocation + ephemeral cleanup primitive
  services/operator_password_rotation_service.py
infra/
  main.bicep
  modules/app.bicep                          # dormant manual rotation Job and narrowly scoped env/secret contract
  environments/demo.bicepparam
tests/
  services/test_operator_password_rotation_service.py
  hosted/test_operator_rotation_keychain.py
  hosted/test_rotate_operator_password_script.py
  hosted/test_operator_rotation_authority.py
  hosted/test_run_operator_rotation.py
  infra/test_bicep_contract.py
```

## Task 1: Add a testable, macOS-only Pending credential controller

**Files:**
- Create: `scripts/operator_rotation_keychain.py`
- Create: `tests/hosted/test_operator_rotation_keychain.py`

- [ ] **Step 1: Write failing tests for metadata-only discovery and the Pending lifecycle.**

  Create an in-memory `KeychainBackend` fake so the tests never call the real Keychain. Cover these exact service/account pairs:

  ```python
  CURRENT_PASSWORD = ("NEWCaostone Azure Demo Operator Password", "operator")
  CURRENT_HASH = ("NEWCaostone Azure Demo Operator Password Hash", "operator")
  PENDING_PASSWORD = ("NEWCaostone Azure Demo Operator Password Pending", "operator")
  PENDING_HASH = ("NEWCaostone Azure Demo Operator Password Pending Hash", "operator")
  ```

  Require that `prepare_pending()` stores an Argon2id hash matching the Pending plaintext, that `status()` returns only item presence and timestamps, that `promote_pending()` copies Pending to Current only after a caller-supplied verified marker, and that `discard_pending()` does not alter Current.

- [ ] **Step 2: Run the focused test and confirm it fails because the controller does not exist.**

  Run:

  ```bash
  .venv/bin/pytest tests/hosted/test_operator_rotation_keychain.py -q
  ```

  Expected: import/collection failure for `scripts.operator_rotation_keychain`.

- [ ] **Step 3: Implement the backend boundary without a `security ... -w <secret>` subprocess.**

  Define a narrow protocol and an implementation backed by Security.framework through `ctypes` (or PyObjC only if it is already available in the repository environment):

  ```python
  class KeychainBackend(Protocol):
      def read_secret(self, service: str, account: str) -> bytes | None: ...
      def upsert_secret(self, service: str, account: str, value: bytes) -> None: ...
      def delete_secret(self, service: str, account: str) -> None: ...
      def metadata(self, service: str, account: str) -> KeychainItemMetadata | None: ...
  ```

  `prepare_pending()` receives the password from a local terminal prompt using `getpass.getpass()`, retains it only in local process memory long enough to calculate an Argon2id hash, writes both Pending entries through the native API, then overwrites mutable buffers where practical. The module must never call `print()` with a secret and must reject blank passwords.

  `status()` must inspect metadata without fetching password data. `promote_pending()` must first re-check that Pending plaintext verifies against Pending hash, snapshot both Current values in process memory, and update the two Current records. If either update fails, it must restore the prior Current pair before reporting failure; Pending remains intact in either outcome. `discard_pending()` must require an explicit `--confirmed` flag in its CLI wrapper.

- [ ] **Step 4: Add a narrow CLI with safe modes.**

  Implement only these commands:

  ```text
  python scripts/operator_rotation_keychain.py status
  python scripts/operator_rotation_keychain.py prepare-pending
  python scripts/operator_rotation_keychain.py promote-pending --verified-rotation-id <sha256>
  python scripts/operator_rotation_keychain.py discard-pending --confirmed
  ```

  The `status` output may state `current_pair=present|missing`, `pending_pair=present|missing`, account, services, and metadata timestamps. It must never expose record values, hashes, password length, or a hash-derived fingerprint.

- [ ] **Step 5: Re-run focused tests.**

  Run:

  ```bash
  .venv/bin/pytest tests/hosted/test_operator_rotation_keychain.py -q
  ```

  Expected: all tests pass without accessing the real Keychain.

- [ ] **Step 6: Commit the isolated unit.**

  ```bash
  git add scripts/operator_rotation_keychain.py tests/hosted/test_operator_rotation_keychain.py
  git commit -m "feat: stage operator credential rotation safely"
  ```

## Task 2: Add exact-row password rotation and bulk session revocation primitives

**Files:**
- Modify: `src/repositories/operators.py`
- Modify: `src/repositories/sessions.py`
- Create: `src/services/operator_password_rotation_service.py`
- Create: `tests/services/test_operator_password_rotation_service.py`

- [ ] **Step 1: Write service tests for success, idempotence, conflict, and session effects.**

  Seed one active `operator` account, two active sessions, one already revoked session, and both referenced and unreferenced ephemeral operator chat records. Test the following return states:

  ```python
  RotationResult(status="rotated", revoked_session_count=2, deleted_ephemeral_chat_count=1)
  RotationResult(status="already_rotated", revoked_session_count=0, deleted_ephemeral_chat_count=0)
  ```

  A different stored password-hash fingerprint must raise `OperatorPasswordRotationConflict`; an inactive/missing operator must raise `OperatorPasswordRotationAuthorityError`. Verify no session is revoked on either failure.

- [ ] **Step 2: Run the focused test and confirm failure.**

  ```bash
  .venv/bin/pytest tests/services/test_operator_password_rotation_service.py -q
  ```

  Expected: collection failure because the rotation service is absent.

- [ ] **Step 3: Add repository methods with row locking, not a broad account update.**

  Add an `OperatorRepository` method that selects the one active operator row with `FOR UPDATE`, verifies its SHA-256 fingerprint, and changes only `password_hash` plus `updated_at`. Keep the raw stored Argon2 string inside the transaction; do not emit it in exceptions.

  Add a `SessionRepository.revoke_active_for_operator(operator_id, now)` method that locks matching sessions, sets `revoked_at` only where null, and invokes the existing `_delete_ephemeral_chat("operator", session_ids)` path for those sessions. It returns counts only.

- [ ] **Step 4: Implement the transactional service.**

  The public contract is:

  ```python
  class OperatorPasswordRotationService:
      def rotate(
          self,
          *,
          expected_hash_fingerprint: str,
          replacement_password_hash: str,
          now: datetime,
      ) -> RotationResult: ...
  ```

  Within one `session.begin()` transaction, acquire PostgreSQL advisory lock key `operator/credential-rotation/synthetic-demo`, lock the active account, then:

  1. Return `already_rotated` if the stored hash equals the proposed replacement hash.
  2. Reject if the stored-hash fingerprint differs from the expected fingerprint.
  3. Update the exact row, revoke sessions, clean eligible ephemeral chat, and return counts.

  Validate the proposed hash with a public configuration validator that enforces the existing Argon2id policy. Do not re-use `FoundationBootstrapService`, which deliberately rejects changes to the foundation authority.

- [ ] **Step 5: Re-run focused tests.**

  ```bash
  .venv/bin/pytest tests/services/test_operator_password_rotation_service.py -q
  ```

  Expected: success, already-rotated, mismatch, inactive-account, session-revocation, and cleanup tests pass.

- [ ] **Step 6: Commit the transactional unit.**

  ```bash
  git add src/repositories/operators.py src/repositories/sessions.py src/services/operator_password_rotation_service.py tests/services/test_operator_password_rotation_service.py
  git commit -m "feat: rotate operator credential transactionally"
  ```

## Task 3: Add a container-job entry point that accepts only scoped environment inputs

**Files:**
- Create: `scripts/rotate_operator_password.py`
- Create: `tests/hosted/test_rotate_operator_password_script.py`
- Modify: `src/config.py`

- [ ] **Step 1: Write failing entry-point tests.**

  Test that the script:

  - requires `BIZPULSE_OPERATOR_PASSWORD_HASH` and validates it as the existing cloud Argon2id policy;
  - requires a 64-character lower-case hexadecimal `BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256` fingerprint;
  - requires `BIZPULSE_OPERATOR_ROTATION_ID` as a SHA-256 identifier;
  - writes a JSON result containing only `rotation_id`, `status`, and count fields;
  - exits non-zero for configuration, authority, or conflict errors;
  - never imports the macOS Keychain controller.

- [ ] **Step 2: Run the focused test and confirm failure.**

  ```bash
  .venv/bin/pytest tests/hosted/test_rotate_operator_password_script.py -q
  ```

- [ ] **Step 3: Expose a public hash-validation helper and implement the entry point.**

  In `src/config.py`, extract the existing cloud password-hash validation into a public function such as:

  ```python
  def validate_operator_password_hash(value: str, *, source: str) -> str: ...
  ```

  Keep `BizPulseSettings.from_env()` behavior unchanged by calling that helper. In the new script, instantiate the existing database/session infrastructure, call `OperatorPasswordRotationService.rotate()`, and serialize only non-sensitive fields. The script has no CLI argument for either password/hash/fingerprint: all values come from its process environment.

- [ ] **Step 4: Re-run the focused test.**

  ```bash
  .venv/bin/pytest tests/hosted/test_rotate_operator_password_script.py -q
  ```

- [ ] **Step 5: Commit the job entry point.**

  ```bash
  git add src/config.py scripts/rotate_operator_password.py tests/hosted/test_rotate_operator_password_script.py
  git commit -m "feat: add guarded operator rotation job"
  ```

## Task 4: Define the Bicep contract for a dormant, manual rotation job

**Files:**
- Modify: `infra/main.bicep`
- Modify: `infra/modules/app.bicep`
- Modify: `infra/environments/demo.bicepparam`
- Modify: `tests/infra/test_bicep_contract.py`

- [ ] **Step 1: Write/extend the Bicep contract tests first.**

  Assert that the generated template contains a manual `operator-rotation` Container Apps Job whose command is exactly:

  ```text
  python scripts/rotate_operator_password.py
  ```

  Assert that the Job, and only the Job, can receive:

  ```text
  BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256
  BIZPULSE_OPERATOR_ROTATION_ID
  ```

  Assert that app containers never receive the expected-old fingerprint and that no Bicep parameter or environment variable carries plaintext password material.

- [ ] **Step 2: Run the contract test and confirm failure.**

  ```bash
  .venv/bin/pytest tests/infra/test_bicep_contract.py -q
  ```

- [ ] **Step 3: Implement a two-phase, secret-minimizing contract.**

  Add non-secret Bicep parameters for the expected fingerprint and rotation ID,
  plus a secure `operatorRotationPasswordHash` used only by the manual Job.
  Keep the serving application bound to `operatorPasswordHash` during Job
  staging; only the Job receives the target hash. The release package performs
  these deployments in order:

  1. Deploy the manual Job with Current as the application hash and Pending as
     the Job target hash; the serving app does not switch credentials yet.
  2. Start exactly one forward Job execution. It receives the target hash
     through its scoped secret and the expected-old fingerprint through its
     scoped environment.
  3. Deploy the inspected app revision with Pending after a successful Job,
     verify health and login/logout, then redeploy an inert Job configuration
     with the rotation-only hash and expected fingerprint cleared.

  An inverse is never automatic. It is a new mode-`0600` package, generated
  from the forward package, with the hashes swapped and a new owner approval.
  It never restores revoked sessions.

- [ ] **Step 4: Compile and test the template locally.**

  ```bash
  az bicep build --file infra/main.bicep
  .venv/bin/pytest tests/infra/test_bicep_contract.py -q
  ```

  Expected: Bicep compiles and contract tests prove the secret scope.

- [ ] **Step 5: Commit the infrastructure contract.**

  ```bash
  git add infra/main.bicep infra/modules/app.bicep infra/environments/demo.bicepparam tests/infra/test_bicep_contract.py
  git commit -m "feat: add scoped operator rotation job infrastructure"
  ```

## Task 5: Generate a read-only, SHA-bound rotation authority package

**Files:**
- Create: `scripts/generate_operator_rotation_authority.py`
- Create: `tests/hosted/test_operator_rotation_authority.py`
- Reuse: `scripts/run_hosted_check.py`, `scripts/azure_recovery_preflight.py`, `scripts/phase1_receipt.py`

- [ ] **Step 1: Write failing tests for package contents and redaction.**

  Given faked Azure/app metadata, current and Pending Keychain hashes supplied only as in-memory fixtures, assert the generator creates a mode-`0600` JSON package containing:

  ```json
  {
    "schema_version": 1,
    "operation": "operator-password-rotation",
    "rotation_id": "<sha256>",
    "target": {"subscription_id": "...", "resource_group": "...", "container_app": "..."},
    "source": {"git_sha": "...", "image_digest": "..."},
    "expected": {"active_image": "...", "active_revision": "...", "old_hash_sha256": "...", "new_hash_sha256": "..."},
    "preconditions": ["single_revision_mode", "ready_healthy", "pending_pair_matches"],
    "rollback": {"allowed_until_cleanup": true, "predicate": "new_hash_sha256"}
  }
  ```

  Assert serialized text does not contain either Argon2 string, any plaintext credential, or Keychain record value.

- [ ] **Step 2: Run the focused test and confirm failure.**

  ```bash
  .venv/bin/pytest tests/hosted/test_operator_rotation_authority.py -q
  ```

- [ ] **Step 3: Implement read-only preflight and package generation.**

  The generator must:

  1. Obtain current/Pending hashes through the Keychain module only in process memory and verify both password/hash pairs locally.
  2. Read Azure app mode, FQDN, latest ready revision, and serving-image digest without an Azure write; bind that observed image separately from the candidate image that will be deployed.
  3. Request the app `/health/ready` endpoint and require `200` plus all named checks `ok`.
  4. Calculate `rotation_id = sha256(canonical_json_without_secrets)` and write only package metadata to `deliverables/operator-password-rotation/<rotation_id>.json` with `0600` permissions.
  5. Fail closed if current/Pending records are missing, Pending equals Current, any app identity differs from the approved target, or health is not ready.

  It must report package path, rotation ID, source SHA, target FQDN, and the two non-secret fingerprints for human review. It must not execute a deployment or job.

- [ ] **Step 4: Re-run focused tests.**

  ```bash
  .venv/bin/pytest tests/hosted/test_operator_rotation_authority.py -q
  ```

- [ ] **Step 5: Commit the package generator.**

  ```bash
  git add scripts/generate_operator_rotation_authority.py tests/hosted/test_operator_rotation_authority.py
  git commit -m "feat: generate operator rotation authority package"
  ```

## Task 6: Implement the controlled executor and hosted verifier

**Files:**
- Create: `scripts/run_operator_rotation.py`
- Create: `tests/hosted/test_run_operator_rotation.py`
- Reuse: `scripts/run_azure_job.py`

- [ ] **Step 1: Write failing orchestration tests with faked subprocesses/HTTP.**

  Cover:

  - refusal without `--approved-rotation-id <id>` exactly matching the package;
  - refusal when package source SHA, image digest, revision, app mode, FQDN, or expected-old fingerprint drift;
  - exactly one forward Azure Job start through `run_azure_job.py`;
  - a healthy target revision plus one API login/logout smoke using the Pending plaintext in process memory only;
  - a failed health/login after a committed forward job stops before Keychain promotion and emits an inverse-job instruction, rather than silently retrying;
  - success removes rollback material, writes a redacted receipt, and returns the verified `rotation_id`.

- [ ] **Step 2: Run the focused test and confirm failure.**

  ```bash
  .venv/bin/pytest tests/hosted/test_run_operator_rotation.py -q
  ```

- [ ] **Step 3: Implement the executor with explicit phase boundaries.**

  Implement these states:

  ```text
  PRECHECKED -> INFRASTRUCTURE_APPLIED -> FORWARD_JOB_COMMITTED
             -> APP_READY -> NEW_CREDENTIAL_SMOKED -> ROLLBACK_SECRET_REMOVED
             -> PENDING_PROMOTED -> RECEIPT_WRITTEN
  ```

  Details:

  - Re-run the read-only preflight immediately before the first Azure write and compare it byte-for-byte to the approved package fields.
  - Read new/current hashes and the Pending plaintext through Keychain only in memory. Do not call shell commands that include their values.
  - Feed secure Bicep values only through a minimal child environment consumed
    by `readEnvironmentVariable()`; do not put secret values in
    `--parameters`, command arguments, output, or temporary files.
  - Use the existing `run_azure_job.py` once for forward execution. Do not retry on an ambiguous result.
  - Use origin-bearing API login/logout smoke equivalent to the previously accepted API contract. Store neither cookie nor CSRF token; immediately revoke via logout.
  - Only after successful health and smoke: redeploy inert job configuration, call `promote_pending()`, and write a receipt containing IDs/status/counts/fingerprints but no secret values.
  - If forward job returns `already_rotated`, require database/app state to match the package target before proceeding. If not, fail closed.
  - If the forward commit succeeds but readiness/smoke fails, do not promote Pending and do not attempt rollback automatically. Print the precise package-bound inverse command requiring a separate explicit approval.

- [ ] **Step 4: Re-run focused tests.**

  ```bash
  .venv/bin/pytest tests/hosted/test_run_operator_rotation.py -q
  ```

- [ ] **Step 5: Commit the executor.**

  ```bash
  git add scripts/run_operator_rotation.py tests/hosted/test_run_operator_rotation.py
  git commit -m "feat: add controlled operator rotation executor"
  ```

## Task 7: Run layered local verification and review the release boundary

**Files:** all files changed above.

- [ ] **Step 1: Run focused test suites.**

  ```bash
  .venv/bin/pytest \
    tests/hosted/test_operator_rotation_keychain.py \
    tests/services/test_operator_password_rotation_service.py \
    tests/hosted/test_rotate_operator_password_script.py \
    tests/infra/test_bicep_contract.py \
    tests/hosted/test_operator_rotation_authority.py \
    tests/hosted/test_run_operator_rotation.py -q
  ```

- [ ] **Step 2: Run relevant regressions.**

  ```bash
  .venv/bin/pytest \
    tests/services \
    tests/hosted/test_run_azure_job.py \
    tests/infra/test_bicep_contract.py -q
  az bicep build --file infra/main.bicep
  git diff --check
  ```

  Expected: no whitespace errors, Bicep compiles, and all local tests pass. These tests are local proof only; they do not prove a hosted rotation.

- [ ] **Step 3: Perform security-focused source review.**

  Verify by code search that no new logging, JSON serialization, CLI command construction, exception text, or receipt field contains `password`, `password_hash`, `BIZPULSE_OPERATOR_PASSWORD_HASH`, or Keychain payload values except for deliberately non-secret service names and environment-variable identifiers.

  ```bash
  rg -n --glob '*.py' --glob '*.bicep' --glob '*.bicepparam' \
    'print\(|logger\.|json\.dump|subprocess|BIZPULSE_OPERATOR_PASSWORD_HASH|password_hash' \
    scripts src infra tests
  ```

  Manually inspect all matches added by this change; do not accept a broad search result as proof by itself.

- [ ] **Step 4: Commit final implementation evidence.**

  ```bash
  git status --short
  git log --oneline --decorate -8
  ```

  Do not use `git commit -a`: it can pick up unrelated tracked work. If a final verification artifact is intentionally added, stage its exact pathname with `git add <exact-path>` and commit only that pathname. Otherwise leave the worktree clean and report the exact commit chain.

## Task 8: Owner-controlled hosted rotation handoff (not part of local implementation)

**Files:** generated package/receipt only, under the repository’s `deliverables/operator-password-rotation/` directory.

- [ ] **Step 1: Stage a new Pending password locally.**

  The owner runs the local no-echo prompt:

  ```bash
  python scripts/operator_rotation_keychain.py prepare-pending
  python scripts/operator_rotation_keychain.py status
  ```

  This is a local Keychain mutation, not an Azure or database mutation. The command output is metadata-only.

- [ ] **Step 2: Generate and inspect a fresh read-only package.**

  ```bash
  python scripts/generate_operator_rotation_authority.py \
    --subscription <subscription-id> \
    --resource-group <resource-group> \
    --app <container-app> \
    --image <immutable-image@sha256:...> \
    --deployment-profile <approved-public-profile.json>
  ```

  Review the exact package path, rotation ID, live target, source SHA/image digest, expected-old fingerprint, new fingerprint, readiness result, and rollback predicate. A previously generated package must never be reused after app/revision/source drift.

- [ ] **Step 3: Obtain a separate, narrow approval for that exact package.**

  The approval must name the `rotation_id` and authorize only the package’s Azure deployment/job steps. It does not authorize a retry, a different package, a production target, or arbitrary account changes.

- [ ] **Step 4: Execute once and inspect the redacted receipt.**

  ```bash
  python scripts/run_operator_rotation.py \
    --package deliverables/operator-password-rotation/<rotation_id>.json \
    --approved-rotation-id <rotation_id>
  ```

  Success is only when all of the following are evidenced: target job completed with `rotated` or verified `already_rotated`; hosted `/health/ready` is healthy; one Pending-password login/logout succeeds; old sessions are revoked; rollback secret is removed; Current Keychain pair equals Pending; and receipt was written without secrets.

---

## Completion Criteria

- Local test evidence proves Pending storage, exact-row transactional rotation, session revocation, secret-scoped infrastructure, package redaction, and no-retry orchestration behavior.
- No plaintext password or Argon2 hash appears in repository content, terminal output, command arguments, receipts, or logs.
- The implementation itself makes no hosted write.
- A hosted credential change occurs only after the owner separately approves a fresh SHA-bound package, and its receipt distinguishes local implementation success from hosted verification success.
