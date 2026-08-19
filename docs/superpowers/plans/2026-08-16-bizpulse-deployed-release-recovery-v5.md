# BizPulse Deployed Release Recovery V5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a locally verified, AI-disabled V5 recovery package that binds the exact V4 deployment and Job executions, omits every completed mutation, and can run only the remaining Hosted acceptance stages after a fresh exact-SHA approval.

**Architecture:** A tracked deployed-continuation record is the immutable source of V4 partial-success facts. A recovery-specific verifier proves the candidate app and four exact Job executions without weakening the generic Phase-2 fence. A V5 builder emits only pending acceptance commands, and a dedicated one-shot controller reads only the Operator credential pair and scopes the plaintext exclusively to browser acceptance.

**Tech Stack:** Python 3.12, pytest, Ruff, Azure CLI argument arrays, Argon2id verification, macOS `security`, JSON/Markdown owner-only artifacts, Git.

## Global Constraints

- Work only in `/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift`; `/Users/maxli/Desktop/CAPTSONE` remains read-only.
- Start from design commit `0ea09d615797a35abac6f8db333fa2f3f2595bd7`; keep `DEPLOYED_RELEASE_SHA=537effe3036f77f83225beef12589bd447205a8b` compare-only and use `16f5220` as the changed-path verification base.
- V4 SHA-256 `978110287eb3335bcf5537ee59e9bd887a41eee9753861148680f1a5475beae8` is consumed. Never replay V4 or manually resume one of its commands.
- Do not redeploy the application or start, bind, migrate, seed or publish anything while implementing or generating V5.
- Do not access Azure, registry, Keychain, the public URL, OpenAI or any paid provider during local implementation and package generation.
- Keep AI disabled. V5 contains no OpenAI Key action, AI enablement, model qualification or paid request.
- Use `apply_patch` for edits, TDD red-green cycles for behavior, small local commits, and no push, PR, CI or deployment.
- A generated V5 package grants no execution authority. Stop and request approval of its exact SHA-256.

---

### Task 1: Deployed-continuation schema and immutable V4 evidence

**Files:**
- Create: `bizpulse/tests/hosted/test_verify_deployed_release_state.py`
- Create: `bizpulse/scripts/verify_deployed_release_state.py`
- Create: `bizpulse/release/incidents/2026-08-16-recovery-v4-deployed-continuation.json`

**Interfaces:**
- Consumes: V4 incident receipt `bizpulse/docs/operations/2026-08-16-recovery-v4-partial-failure.md` and seeded continuation `bizpulse/release/incidents/2026-08-16-recovery-v2-seeded-continuation.json`.
- Produces: `CONTINUATION_SCHEMA`, `validate_deployed_release_continuation(value: object) -> dict[str, Any]`, and `load_deployed_release_continuation(path: Path, *, expected_sha256: str | None = None) -> dict[str, Any]`.

- [ ] **Step 1: Write failing schema and hash tests**

Add a `deployed_continuation()` fixture with the exact top-level fields below, then test valid loading, duplicate-key rejection, source/package drift, changed execution identity, false completed boundary, secret-shaped content and wrong SHA-256:

```python
EXPECTED_EXECUTIONS = {
    "prepare": {
        "job": "newcaostone-demo-prepare",
        "name": "newcaostone-demo-prepare-pc747ae",
        "status": "Succeeded",
    },
    "seed": {
        "job": "newcaostone-demo-seed",
        "name": "newcaostone-demo-seed-vhamoeo",
        "status": "Succeeded",
    },
    "session_maintenance": {
        "job": "newcaostone-demo-sessions",
        "name": "newcaostone-demo-sessions-8yiqp1m",
        "status": "Succeeded",
    },
    "storage_maintenance": {
        "job": "newcaostone-demo-storage",
        "name": "newcaostone-demo-storage-bch1i2u",
        "status": "Succeeded",
    },
}

def test_deployed_continuation_requires_exact_v4_evidence(tmp_path: Path) -> None:
    subject = _subject()
    payload = deployed_continuation()
    path = tmp_path / "continuation.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    loaded = subject.load_deployed_release_continuation(
        path, expected_sha256=digest
    )

    assert loaded["executions"] == EXPECTED_EXECUTIONS
    assert loaded["boundaries"]["application_deployed"] is True
    assert loaded["boundaries"]["hosted_health_verified"] is False
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift/bizpulse
.venv/bin/pytest -q tests/hosted/test_verify_deployed_release_state.py::test_deployed_continuation_requires_exact_v4_evidence
```

Expected: FAIL because `scripts.verify_deployed_release_state` does not exist.

- [ ] **Step 3: Implement strict continuation parsing**

Use the same duplicate-key, timestamp, UUID, SHA-256, Git SHA, image digest,
name and reference patterns as the seeded verifier. Define these exact
constants and reject extra or missing keys at every level:

```python
CONTINUATION_SCHEMA = "newcaostone.deployed-release-continuation.v1"
COMPLETED_OPERATIONS = (
    "registry_publish",
    "postgres_migrate",
    "seed_job_bind",
    "prepare",
    "synthetic_seed",
    "application_deploy",
    "session_maintenance",
    "storage_maintenance",
)
EXECUTION_ROLES = (
    "prepare",
    "seed",
    "session_maintenance",
    "storage_maintenance",
)
BOUNDARY_KEYS = {
    "application_deployed",
    "traffic_switched",
    "ai_enabled",
    "hosted_health_verified",
    "browser_verified",
    "capacity_verified",
    "expiry_verified",
    "restart_verified",
    "rollback_verified",
    "openai_key_accessed",
    "paid_ai_called",
}
```

The loader must read at most 1 MiB, compare the optional SHA-256 with
`hmac.compare_digest`, reject duplicate JSON keys, scan the serialized object
with the existing `SECRET_PATTERN`, and return the validated mapping only.

- [ ] **Step 4: Add the exact tracked continuation record**

Record `schema_version`, `recorded_at=2026-08-16T22:18:28Z`, V4 authorization
ID/package SHA/failed receipt, source seeded-continuation reference and SHA
`dd5b39ee23d7e053f5454a4c8500cc748c74a3d6cec7717b9ae3a19e96e40cdc`, the
candidate/rollback release object, target names, `application_revision` equal to
`newcaostone-demo-app--713a6984d4a0`, the four `EXPECTED_EXECUTIONS`, the exact
`COMPLETED_OPERATIONS`, and boundaries where only application deployment and
traffic switch are true. Set AI and every remaining acceptance boundary false.

- [ ] **Step 5: Run schema tests, Ruff and compilation**

Run:

```bash
.venv/bin/pytest -q tests/hosted/test_verify_deployed_release_state.py -k continuation
.venv/bin/ruff check scripts/verify_deployed_release_state.py tests/hosted/test_verify_deployed_release_state.py
.venv/bin/python -m compileall -q scripts/verify_deployed_release_state.py
```

Expected: all selected tests pass, Ruff exits `0`, compilation emits no output.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_deployed_release_state.py tests/hosted/test_verify_deployed_release_state.py release/incidents/2026-08-16-recovery-v4-deployed-continuation.json
git commit -m "feat: record deployed recovery continuation"
```

---

### Task 2: Exact deployed-state Azure verifier

**Files:**
- Modify: `bizpulse/scripts/verify_deployed_release_state.py`
- Modify: `bizpulse/tests/hosted/test_verify_deployed_release_state.py`

**Interfaces:**
- Consumes: validated deployed continuation from Task 1.
- Produces: `verify_deployed_release_state(continuation: dict[str, Any], *, reader: Callable[[tuple[str, ...]], Any] = _read_json) -> dict[str, str]` and CLI arguments `--continuation`, `--continuation-sha256`.

- [ ] **Step 1: Write failing live-state tests**

Build a deterministic reader for `containerapp show`, `containerapp revision
list`, four `containerapp job show` calls and four execution-list calls. Cover
the success state, missing bound execution, substituted later success, later
`Failed` execution, allowed later `Running` execution, candidate image/revision/
traffic drift, AI enabled, and Job command/schedule drift:

```python
def test_exact_bound_executions_cannot_be_substituted() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    reader.responses[("executions", "prepare")] = [
        {
            "name": "newcaostone-demo-prepare-later123",
            "properties": {"status": "Succeeded"},
        }
    ]

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_bound_execution_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)
```

- [ ] **Step 2: Run one test and confirm RED**

Run:

```bash
.venv/bin/pytest -q tests/hosted/test_verify_deployed_release_state.py::test_exact_bound_executions_cannot_be_substituted
```

Expected: FAIL because `verify_deployed_release_state` is absent or incomplete.

- [ ] **Step 3: Implement exact app, Job and execution verification**

Use argument arrays and the existing `_command`/`_read_json` Azure reader
pattern. Return only this success value:

```python
ALLOWED_ADDITIONAL_EXECUTION_STATES = frozenset(
    {
        "Succeeded",
        "Pending",
        "Processing",
        "Queued",
        "Running",
        "Starting",
        "Deactivating",
    }
)

def verify_deployed_release_state(
    continuation: dict[str, Any],
    *,
    reader: Callable[[tuple[str, ...]], Any] = _read_json,
) -> dict[str, str]:
    app = reader(_command(continuation, "containerapp", "show"))
    _verify_candidate_app(app, continuation)
    revisions = reader(_command(continuation, "containerapp", "revision", "list"))
    _verify_candidate_revision(revisions, continuation)
    for role in EXECUTION_ROLES:
        job = reader(_command(continuation, "containerapp", "job", "show", role=role))
        executions = reader(
            _command(continuation, "containerapp", "job", "execution", "list", role=role)
        )
        _verify_job_and_bound_execution(role, job, executions, continuation)
    return {"state": "deployed_awaiting_hosted_acceptance"}
```

Implement `_verify_candidate_app`, `_verify_candidate_revision` and
`_verify_job_and_bound_execution` in the same module. Import
`EXPECTED_APP_PROBES`, `PHASE2_SECRET_REFS` and `PHASE2_SECRET_NAMES` from the
Phase-2 verifier without changing `verify_phase1_fence.py`. Do not request or
print secret values. The CLI prints only `deployed_release_state=verified` or a
value-free error code.

- [ ] **Step 4: Add a direct-entrypoint regression test**

Run the direct file with `PYTHONPATH` removed and `--help`; assert exit `0` and
presence of `--continuation-sha256`.

- [ ] **Step 5: Run the full verifier file**

```bash
.venv/bin/pytest -q tests/hosted/test_verify_deployed_release_state.py
.venv/bin/ruff check scripts/verify_deployed_release_state.py tests/hosted/test_verify_deployed_release_state.py
```

Expected: all tests pass and Ruff reports `All checks passed!`.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_deployed_release_state.py tests/hosted/test_verify_deployed_release_state.py
git commit -m "feat: verify exact deployed recovery state"
```

---

### Task 3: V5 owner-only package builder

**Files:**
- Create: `bizpulse/scripts/create_deployed_release_recovery_package.py`
- Create: `bizpulse/tests/release/test_deployed_release_recovery_package.py`

**Interfaces:**
- Consumes: Task 1 continuation, candidate attestation `release/attestations/82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3.json`, and attestation Git SHA `c573f2be9d8d6414143fbeab2fa2af788caf4f19`.
- Produces: `build_deployed_release_recovery_package(*, authority: dict[str, Any], continuation: dict[str, Any], continuation_reference: str, continuation_sha256: str, authorization_id: str, issued_at: str, expires_at: str) -> dict[str, Any]`, `write_deployed_release_recovery_package(path: Path, package: dict[str, Any]) -> str`, and `load_deployed_release_recovery_package(path: Path, *, continuation_path: Path, now: str | datetime | None = None) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing package contract test**

Assert these exact constants and descriptors:

```python
EXPECTED_ORDER = [
    "deployed_preflight",
    "registry_verify",
    "health",
    "browser_acceptance",
    "capacity",
    "expiry",
    "restart_readback",
    "rollback",
]
EXPECTED_KEYCHAIN = [
    {
        "account": "operator",
        "environment": "BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK",
        "scope": "credential_pair_validation",
        "service": "NEWCaostone Azure Demo Operator Password Hash",
    },
    {
        "account": "operator",
        "environment": "BIZPULSE_BROWSER_OPERATOR_PASSWORD",
        "scope": "browser_acceptance",
        "service": "NEWCaostone Azure Demo Operator Password",
    },
]

assert package["execution_order"] == EXPECTED_ORDER
assert package["keychain_sources"] == EXPECTED_KEYCHAIN
assert package["no_ai"] is True
```

Also assert the serialized commands omit `az deployment group create`,
`containerapp job start`, `run_azure_job.py`, `update_azure_job_binding.py`,
`prepare_cloud.py`, `seed_demo.py`, `publish_registry_image.py`,
`qualify_openai_model.py`, `openai-api-key` and `aiChatEnabled=true`.

- [ ] **Step 2: Run and confirm RED**

```bash
.venv/bin/pytest -q tests/release/test_deployed_release_recovery_package.py
```

Expected: FAIL because the package builder does not exist.

- [ ] **Step 3: Implement package construction and reconstruction**

Define:

```python
HEADER = "# NEWCaostone Deployed Release Recovery V5 Authorization"
SCHEMA = "newcaostone.deployed-release-recovery.v1"
STAGES = (
    "deployed_preflight",
    "registry_verify",
    "health",
    "browser_acceptance",
    "capacity",
    "expiry",
    "restart_readback",
    "rollback",
)
CONTROL_HASH_PATHS = (
    "scripts/create_deployed_release_recovery_package.py",
    "scripts/run_deployed_release_recovery.py",
    "scripts/verify_deployed_release_state.py",
)
```

Add `_build_authority_from_continuation(*, continuation: dict[str, Any],
attestation_path: Path, attestation_git_sha: str, authorization_id: str,
issued_at: str, expires_at: str) -> dict[str, Any]`. It passes the continuation's
subscription, region, resource group, public URL, name prefix, registry,
repository, storage account, PostgreSQL server/login, candidate and rollback
digests to `build_data_stage_authority`, uses cost bounds `100.00`, `0.00` and
`80.00`, and sets `registry_publish=False`. Require exact equality between the
resulting authority and continuation candidate, rollback, target, URL and
limits.
Select only the existing authority commands for stages 2-8 and prepend the new
deployed-preflight command. Store `COMPLETED_OPERATIONS`, `no_ai=True`, the two
Keychain descriptors, zero deploy/paid retries and control hashes. Write with
`O_CREAT|O_EXCL` and mode `0600`; the loader must reconstruct the entire package
and reject drift.

- [ ] **Step 4: Add CLI and direct-entrypoint tests**

The CLI accepts the same attestation/continuation arguments as the V4 builder,
plus output and expiry hours. A direct `--help` invocation without `PYTHONPATH`
must exit `0`.

Task 4 creates the runner named in `CONTROL_HASH_PATHS`. Until then, package
tests must monkeypatch only the private `_control_sha256()` helper to return
this exact synthetic mapping; do not add a production hash-override argument:

```python
SYNTHETIC_CONTROL_HASHES = {
    "scripts/create_deployed_release_recovery_package.py": "1" * 64,
    "scripts/run_deployed_release_recovery.py": "2" * 64,
    "scripts/verify_deployed_release_state.py": "3" * 64,
}
monkeypatch.setattr(subject, "_control_sha256", lambda: SYNTHETIC_CONTROL_HASHES)
```

Use the same patch for build and load reconstruction tests. Task 4 must add an
unpatched integration test proving all real control files exist and reconstruct.

- [ ] **Step 5: Run package tests and static checks**

```bash
.venv/bin/pytest -q tests/release/test_deployed_release_recovery_package.py
.venv/bin/ruff check scripts/create_deployed_release_recovery_package.py tests/release/test_deployed_release_recovery_package.py
.venv/bin/python -m compileall -q scripts/create_deployed_release_recovery_package.py
```

- [ ] **Step 6: Commit**

```bash
git add scripts/create_deployed_release_recovery_package.py tests/release/test_deployed_release_recovery_package.py
git commit -m "feat: add deployed recovery v5 package"
```

---

### Task 4: V5 one-shot execution controller

**Files:**
- Create: `bizpulse/scripts/run_deployed_release_recovery.py`
- Create: `bizpulse/tests/hosted/test_run_deployed_release_recovery.py`

**Interfaces:**
- Consumes: V5 package loader from Task 3 and exact Operator Keychain descriptors.
- Produces: `execute_deployed_release_recovery(*, package_path: Path, expected_package_sha256: str, continuation_path: Path, receipt_path: Path, now: str | datetime | None = None, keychain_reader: Callable[[str, str], str | None] = read_keychain_secret, command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run, base_environment: Mapping[str, str] = os.environ) -> dict[str, str]`, owner-only atomic receipt schema `newcaostone.deployed-release-execution-receipt.v1`, and CLI `--package`, `--approved-sha256`, `--continuation`, `--receipt`.

- [ ] **Step 1: Write wrong-hash, replay and credential-boundary tests**

Use injected Keychain and subprocess functions. The first test must prove a
wrong package hash makes zero Keychain and command calls. The success test must
prove only two items are read, the hash is never passed to a child, and the
plaintext appears only in the browser child's environment:

```python
assert keychain_calls == [
    ("NEWCaostone Azure Demo Operator Password Hash", "operator"),
    ("NEWCaostone Azure Demo Operator Password", "operator"),
]
browser = next(
    call for call in calls if "scripts/run_hosted_check.py" in call["command"]
    and "browser" in call["command"]
)
assert browser["kwargs"]["env"]["BIZPULSE_BROWSER_OPERATOR_PASSWORD"] == (
    "operator-secret"
)
assert all(
    "BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK" not in call["kwargs"]["env"]
    for call in calls
)
```

- [ ] **Step 2: Run one test and confirm RED**

```bash
.venv/bin/pytest -q tests/hosted/test_run_deployed_release_recovery.py::test_wrong_hash_stops_before_keychain_or_commands
```

Expected: FAIL because the runner is absent.

- [ ] **Step 3: Implement hash-first staged execution**

Define:

```python
READ_ONLY_PRE_RECEIPT_STAGES = ("deployed_preflight", "registry_verify")
POST_RECEIPT_STAGES = (
    "health",
    "browser_acceptance",
    "capacity",
    "expiry",
    "restart_readback",
    "rollback",
)
BROWSER_ENVIRONMENT = "BIZPULSE_BROWSER_OPERATOR_PASSWORD"
HASH_CHECK_ENVIRONMENT = "BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK"
```

Verify package bytes with `hmac.compare_digest`, load/reconstruct the package,
reject an existing receipt, and run the two pre-receipt stages with a clean
allowlisted environment. Read the two exact Keychain values once, validate the
Argon2id hash with `_validate_cloud_operator_password_hash`, then verify the
plaintext with `PasswordHasher().verify`. Create the `0600` receipt atomically,
run POST_RECEIPT_STAGES with `shell=False`, update completed/failed stages by
atomic replacement, and blank both in-memory values in `finally`.

- [ ] **Step 4: Add failure receipt and direct-entrypoint coverage**

Test that health failure records `failed_stage=health`, browser failure never
runs capacity or later stages, an existing receipt blocks every call, no secret
appears in stdout/stderr/receipt, and direct `--help` works without
`PYTHONPATH`.

Also add this unpatched package integration test after the runner file exists;
the runner tests' `_package` fixture then exercises the unpatched loader:

```python
def test_real_control_hashes_cover_all_v5_entrypoints() -> None:
    assert package_builder._control_sha256() == {
        path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
        for path in (
            "scripts/create_deployed_release_recovery_package.py",
            "scripts/run_deployed_release_recovery.py",
            "scripts/verify_deployed_release_state.py",
        )
    }
```

- [ ] **Step 5: Run runner and combined V5 tests**

```bash
.venv/bin/pytest -q \
  tests/hosted/test_verify_deployed_release_state.py \
  tests/release/test_deployed_release_recovery_package.py \
  tests/hosted/test_run_deployed_release_recovery.py
.venv/bin/ruff check \
  scripts/verify_deployed_release_state.py \
  scripts/create_deployed_release_recovery_package.py \
  scripts/run_deployed_release_recovery.py \
  tests/hosted/test_verify_deployed_release_state.py \
  tests/release/test_deployed_release_recovery_package.py \
  tests/hosted/test_run_deployed_release_recovery.py
```

- [ ] **Step 6: Commit**

```bash
git add scripts/run_deployed_release_recovery.py tests/hosted/test_run_deployed_release_recovery.py
git commit -m "feat: add one-shot deployed recovery runner"
```

---

### Task 5: Release-policy and changed-path coverage

**Files:**
- Modify: `bizpulse/release/verification-policy.json`
- Modify: `bizpulse/tests/release/test_select_required_checks.py`

**Interfaces:**
- Consumes: the three V5 scripts and three V5 test files.
- Produces: deterministic `release_static` selection for every V5 code, test and continuation path.

- [ ] **Step 1: Extend the selector parametrization first**

Add these exact paths to
`test_two_stage_release_tooling_is_mapped_to_static_release_gate`:

```python
"bizpulse/scripts/create_deployed_release_recovery_package.py",
"bizpulse/scripts/run_deployed_release_recovery.py",
"bizpulse/scripts/verify_deployed_release_state.py",
"bizpulse/tests/release/test_deployed_release_recovery_package.py",
"bizpulse/tests/hosted/test_verify_deployed_release_state.py",
"bizpulse/tests/hosted/test_run_deployed_release_recovery.py",
"bizpulse/release/incidents/2026-08-16-recovery-v4-deployed-continuation.json",
```

- [ ] **Step 2: Run and confirm RED**

```bash
.venv/bin/pytest -q tests/release/test_select_required_checks.py
```

Expected: the new V5 script/test paths fail selection until policy is updated.

- [ ] **Step 3: Extend release-static argv and release-tooling includes**

Add the three V5 test files to `checks.release_static.argv` before `-q`. Add the
three V5 scripts and test files to the `release_tooling.include` list. The
incident is already covered by `bizpulse/release/**`; retain that broad mapping.

- [ ] **Step 4: Run policy tests**

```bash
.venv/bin/pytest -q tests/release/test_select_required_checks.py
```

Expected: all selector tests pass.

- [ ] **Step 5: Commit**

```bash
git add release/verification-policy.json tests/release/test_select_required_checks.py
git commit -m "test: cover deployed recovery release tooling"
```

---

### Task 6: Full local verification before package generation

**Files:**
- Modify only if a verification failure identifies a real local defect; use a new TDD cycle and separate commit for any such fix.

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: fresh evidence that the exact V5 control files are locally valid before their hashes are embedded.

- [ ] **Step 1: Run focused V5 tests and static checks**

```bash
.venv/bin/pytest -q \
  tests/hosted/test_verify_deployed_release_state.py \
  tests/release/test_deployed_release_recovery_package.py \
  tests/hosted/test_run_deployed_release_recovery.py
.venv/bin/ruff check \
  scripts/verify_deployed_release_state.py \
  scripts/create_deployed_release_recovery_package.py \
  scripts/run_deployed_release_recovery.py \
  tests/hosted/test_verify_deployed_release_state.py \
  tests/release/test_deployed_release_recovery_package.py \
  tests/hosted/test_run_deployed_release_recovery.py
.venv/bin/python -m compileall -q \
  scripts/verify_deployed_release_state.py \
  scripts/create_deployed_release_recovery_package.py \
  scripts/run_deployed_release_recovery.py
```

- [ ] **Step 2: Run the release-static suite from policy**

Run the exact `checks.release_static.argv` array from
`release/verification-policy.json`; do not hand-select a smaller list. Expected:
zero failures, with only the policy's known skips.

- [ ] **Step 3: Run selector and changed-path gates**

```bash
.venv/bin/pytest -q tests/release/test_select_required_checks.py
.venv/bin/python scripts/check_authority_contract.py --mode docs
.venv/bin/python scripts/verify_changed.py --base 16f5220 --no-reuse
git diff --check
git status --short
```

Expected: `authority_contract=ok`, `verification_changed=passed`, no diff-check
output, and only deliberate tracked implementation/document changes already
committed.

---

### Task 7: Generate V5 once, document it and stop at exact-SHA approval

**Files:**
- Create outside Git: `bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md`
- Reserve outside Git: `bizpulse/.tmp/RECOVERY_V5_EXECUTION_RECEIPT.json`
- Create: `bizpulse/docs/operations/2026-08-16-recovery-v5-package.md`
- Modify: `CURRENT_STATUS.md`
- Modify: `NEXT_AI_HANDOFF.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`

**Interfaces:**
- Consumes: verified V5 controls, exact continuation and existing candidate attestation.
- Produces: one owner-only V5 package, immutable local package receipt, updated authority handoff and a user-facing exact SHA-256 approval request.

- [ ] **Step 1: Prove clean generation preconditions**

```bash
git status --short
stat .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md
stat .tmp/RECOVERY_V5_EXECUTION_RECEIPT.json
```

Expected: Git output is empty; both `stat` commands report that the files do not
exist. If either file exists, stop without overwriting it.

- [ ] **Step 2: Generate exactly once without Azure or Keychain**

```bash
.venv/bin/python scripts/create_deployed_release_recovery_package.py \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --continuation-reference release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --release-attestation release/attestations/82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3.json \
  --attestation-git-sha c573f2be9d8d6414143fbeab2fa2af788caf4f19 \
  --expires-hours 24 \
  --output .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md
```

Expected: `deployed_recovery_package=ok`, an output path and one SHA-256. This
command must not read Keychain, execute a package command or access Azure.

- [ ] **Step 3: Independently validate identity and boundaries**

```bash
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md
stat -f '%Sp %Lp %Su:%Sg %z' .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md
.venv/bin/python -c "from pathlib import Path; from scripts.create_deployed_release_recovery_package import load_deployed_release_recovery_package; p=load_deployed_release_recovery_package(Path('.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md'), continuation_path=Path('release/incidents/2026-08-16-recovery-v4-deployed-continuation.json')); assert p['no_ai'] is True; assert p['execution_order']==['deployed_preflight','registry_verify','health','browser_acceptance','capacity','expiry','restart_readback','rollback']; assert len(p['keychain_sources'])==2; print('v5_package_loader=passed')"
stat .tmp/RECOVERY_V5_EXECUTION_RECEIPT.json
```

Expected: independent SHA matches generator output, mode is `600`, loader
passes, and the execution receipt remains absent.

- [ ] **Step 4: Write immutable package receipt and update handoffs**

Use `apply_patch`. Copy the generator's exact authorization ID, issue time,
expiry and independent SHA-256 into
`docs/operations/2026-08-16-recovery-v5-package.md`. Record the exact eight
stages, completed V4 operations, two credential descriptors, AI-disabled
boundary, test counts and the future one-shot command. Update all three current
handoff files to say V4 is consumed, V5 is generated but not approved or
executed, and Hosted/Production acceptance remains pending.

- [ ] **Step 5: Run final verification and commit documentation**

```bash
.venv/bin/python scripts/verify_changed.py --base 16f5220 --no-reuse
git diff --check
git add docs/operations/2026-08-16-recovery-v5-package.md \
  ../CURRENT_STATUS.md ../NEXT_AI_HANDOFF.md ../docs/handoffs/CURRENT_HANDOFF.md
git commit -m "docs: prepare deployed recovery v5 handoff"
git status --short
```

Expected: `verification_changed=passed`, commit succeeds, and worktree is clean.

- [ ] **Step 6: Stop and request exact approval**

Report the package path, authorization ID, expiry, SHA-256, verification counts,
AI-disabled state and absent receipt. Ask the user to reply exactly:

Construct one line by concatenating the literal prefix
`批准执行 V5 SHA256：` and the exact 64-character digest printed and independently
verified in Steps 2-3. Do not abbreviate, reformat or substitute that digest.

Do not execute V5 in the same turn that generates it.
