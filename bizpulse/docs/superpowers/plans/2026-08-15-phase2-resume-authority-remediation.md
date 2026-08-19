# Phase 2 Resume Authority Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the no-AI Azure launch safely resumable by binding the Phase 2 verifier to Azure's exact Blob root endpoint and reusing one verified Operator Argon2 hash across process restarts.

**Architecture:** The committed release change is a one-line authority correction plus its regression: Phase 2 expects the Microsoft-projected `https://<account>.blob.core.windows.net/` value. The local execution controller separately stores one strong Argon2id hash in macOS Keychain, verifies it against the already stored plaintext, and injects the same value into every deployment phase. The partial synthetic environment is cleaned and rebuilt rather than modified with ad-hoc SQL.

**Tech Stack:** Python 3.12, pytest, Argon2id, macOS Security.framework/Keychain, Azure CLI, Azure Bicep/ARM, Docker BuildKit, PostgreSQL/Azure Blob hosted gates, Git manifest-only attestation.

## Global Constraints

- Keep AI disabled and do not introduce an OpenAI key, provider request, paid smoke, budget rehearsal, or provider-failure rehearsal.
- Do not weaken foundation, migration, Blob, revision, traffic, replica, Job, session, or rollback checks.
- Do not log, print, serialize, commit, or place any credential or credential hash in argv.
- Do not repair the current PostgreSQL authority with direct SQL.
- Do not mutate Azure again until a new exact cleanup package and launch package are generated and their SHA256 values are explicitly approved.
- Treat local tests, image builds, attestations, and package validation as local evidence only.

---

### Task 1: Accept Azure's exact Blob root projection

**Files:**
- Modify: `tests/hosted/test_azure_preflight.py`
- Modify: `scripts/verify_phase1_fence.py`

**Interfaces:**
- Phase 2 expected value: `BIZPULSE_BLOB_ENDPOINT=https://<storage-account>.blob.core.windows.net/`.
- Stable rejection for any other app projection: `phase1_app_not_fenced`.

- [ ] **Step 1: Write the failing regression**

Change the valid Phase 2 Azure fixture's `BIZPULSE_BLOB_ENDPOINT` value to:

```python
{"name": "BIZPULSE_BLOB_ENDPOINT", "value": "https://bpapprovedstorage.blob.core.windows.net/"}
```

Keep explicit negative cases for a different hostname, non-root path, query,
fragment, and non-HTTPS endpoint.

- [ ] **Step 2: Run the exact regression and verify RED**

```bash
.venv/bin/pytest tests/hosted/test_azure_preflight.py -k phase2 -q
```

Expected: the valid Microsoft-shaped fixture fails with
`phase1_app_not_fenced` because the verifier currently expects no trailing
slash.

- [ ] **Step 3: Implement the minimal exact expectation**

Change only the expected Phase 2 Blob value:

```python
"BIZPULSE_BLOB_ENDPOINT": (
    f"https://{storage_account_name}.blob.core.windows.net/"
),
```

Do not normalize arbitrary input and do not change any other expected env,
secret, hostname, container, revision, traffic, probe, scale, or Job value.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_azure_preflight.py -q
.venv/bin/ruff check scripts/verify_phase1_fence.py tests/hosted/test_azure_preflight.py
git diff --check
git add scripts/verify_phase1_fence.py tests/hosted/test_azure_preflight.py
git commit -m "fix: accept Azure blob root authority"
```

Expected: focused tests and Ruff pass and diff check is silent.

---

### Task 2: Make the local Operator hash a persistent Keychain authority

**Files:**
- Modify: `.tmp/run_approved_no_ai_launch.py` after the new package is generated
- Create: `.tmp/test_persistent_operator_hash.py`

**Interfaces:**
- Keychain service: `NEWCaostone Azure Demo Operator Password Hash`.
- Keychain account: `operator`.
- Input plaintext authority: existing service `NEWCaostone Azure Demo Operator Password`, account `operator`.
- Output environment: `BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH` only in the child process environment.

- [ ] **Step 1: Write RED controller tests**

Use an in-memory fake Keychain and assert:

```python
first = resolve_operator_hash(password, existing=None, persist=fake.persist)
second = resolve_operator_hash(password, existing=first, persist=fake.persist)
assert first == second
assert fake.persist_calls == 1
assert PasswordHasher().verify(second, password)
```

Also require malformed hash, valid hash for another plaintext, duplicate-item
ambiguity, and write failure to stop before any mocked Azure command. Capture
stdout/stderr and assert neither plaintext nor hash appears.

- [ ] **Step 2: Run the controller test and verify RED**

```bash
.venv/bin/pytest .tmp/test_persistent_operator_hash.py -q
```

Expected: failure because the controller currently generates a fresh Argon2
hash on every process start.

- [ ] **Step 3: Implement create-once/reuse**

Add a pure resolver that validates an existing hash with
`src.config._validate_cloud_operator_password_hash`, verifies it with
`PasswordHasher().verify`, and returns it unchanged. When the exact Keychain
item is absent, generate one hash, add it through Security.framework without
putting the value in argv, reread it, validate it, and compare it with the
generated value. Any other Keychain status fails closed with a value-free
error.

Use the returned value for every stage and remove the direct call:

```python
operator_password_hash = PasswordHasher().hash(operator_password)
```

- [ ] **Step 4: Verify the controller locally**

```bash
.venv/bin/pytest .tmp/test_persistent_operator_hash.py -q
.venv/bin/python -m py_compile .tmp/run_approved_no_ai_launch.py
```

Expected: tests pass, no secret is printed, and two dry controller loads return
the same in-memory hash authority without invoking Azure.

---

### Task 3: Rebuild release authority and stop at the external gate

**Files:**
- Modify: `CURRENT_STATUS.md`
- Modify: `AUTHORIZATION_LEDGER.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`
- Create: new manifest-only Task 15 attestation under `release/`
- Create: ignored `.tmp` cleanup and restricted no-AI launch packages

**Interfaces:**
- Candidate image: exact `linux/amd64`, non-root `bizpulse`, immutable digest,
  exact Git revision and image-input OCI labels, and `--no-access-log` Uvicorn
  command.
- Cleanup: exact current pure-synthetic Demo resources only; preserve ACR and
  unrelated resources.
- Launch: no-AI execution order and zero paid/provider commands.

- [ ] **Step 1: Run focused and full local gates**

```bash
.venv/bin/pytest tests/hosted/test_azure_preflight.py tests/infra tests/release -q
.venv/bin/ruff check scripts tests
git diff --check
.venv/bin/python scripts/verify_release.py
```

Expected: all tests and eight release gates pass.

- [ ] **Step 2: Commit the clean candidate and build/inspect the image**

Commit only the reviewed remediation and current evidence docs. Build the exact
candidate as `linux/amd64`, inspect non-root user, command, labels, contents,
and local PostgreSQL/Azurite behavior, then resolve its immutable digest.

- [ ] **Step 3: Create and verify the manifest-only child**

Require the child commit to add exactly one Task 15 manifest and independently
verify candidate SHA/tree, migration `0008_ai_budget_ledger`, current and
rollback image-input labels, fixture/generator hashes, and conservative claims.
Run detached attestation verification and require exit 0.

- [ ] **Step 4: Generate packages and stop**

Generate mode-0600 cleanup and restricted no-AI launch packages, validate exact
scope/order/hash/expiry, and report both SHA256 values for explicit user
approval. Do not execute either package in this task.
