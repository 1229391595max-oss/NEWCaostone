# Azure Readback Readiness Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline, task-by-task execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Azure rollback/forward readback wait for the exact ready revision and safely forward the currently healthy rollback revision without replaying completed launch work.

**Architecture:** `run_azure_readback.py` owns a bounded exact-readiness poll and a dedicated recovery operation.  A narrow authority generator and runner bind only the already-observed receipt, the current rollback revision, immutable images, and the updated control scripts.  The runner does not replay Phase 1 or already-passed acceptance gates.

**Tech Stack:** Python 3.12, pytest, Azure CLI JSON projections, existing Container Apps exact-authority verifier.

## Global Constraints

- All new Azure reads use the existing bounded CLI runner; only the final approved recovery package may mutate Azure.
- Recovery is no-AI: `aiChatEnabled=false`, no OpenAI secret, and no paid-AI command.
- Poll only the exact expected image/revision, at five-second intervals, with one 300-second monotonic deadline.
- A timeout must not issue another rollback or forward update.
- A new package SHA-256 requires explicit user approval before execution.

---

### Task 1: Prove and implement exact revision readiness polling

**Files:**

- Modify: `tests/hosted/test_run_azure_readback.py`
- Modify: `scripts/run_azure_readback.py`

**Interfaces:**

- Produces `wait_for_hosted_authority(resolve, image, suffix, role, sleeper, monotonic) -> str`.
- `run_azure_readback()` accepts injectable `sleeper` and `monotonic` for deterministic deadline tests.

- [ ] **Step 1: Write the failing readiness regression**

```python
def test_rollback_waits_for_exact_latest_ready_revision_before_snapshot():
    attempts = {"rollback": 0}
    sleeps = []

    def resolver(**kwargs):
        if kwargs["image"] == ROLLBACK:
            attempts["rollback"] += 1
            if attempts["rollback"] < 3:
                raise HostedCheckInvalid("hosted_check_resource_invalid")
        return "https://bp-approved-app.synthetic.azurecontainerapps.io"

    run_azure_readback(..., resolver=resolver, sleeper=sleeps.append,
                       monotonic=clock)
    assert attempts["rollback"] == 3
    assert sleeps == [5, 5]
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/hosted/test_run_azure_readback.py -q`

Expected: FAIL because `run_azure_readback()` has no bounded readiness polling
and the first `HostedCheckInvalid` aborts the readback.

- [ ] **Step 3: Add minimal polling helper and wire it after every update**

```python
READINESS_TIMEOUT_SECONDS = 300
READINESS_POLL_SECONDS = 5

def _wait_for_hosted_authority(resolve, image, *, suffix=None, role=None,
                                sleeper=time.sleep, monotonic=time.monotonic):
    deadline = monotonic() + READINESS_TIMEOUT_SECONDS
    while True:
        try:
            return resolve(image, suffix=suffix, recovery_role=role)
        except HostedCheckInvalid:
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AzureReadbackInvalid("azure_readback_revision_not_ready")
            sleeper(min(READINESS_POLL_SECONDS, remaining))
```

Use the helper after the rollback, forward, and rollback-state recovery-forward
mutations.  Do not change mutation count or add any retrying update.

- [ ] **Step 4: Add timeout safety regression**

```python
def test_unready_rollback_stops_before_forward_update():
    commands = []
    with pytest.raises(AzureReadbackInvalid, match="revision_not_ready"):
        run_azure_readback(..., resolver=always_unready_after_rollback,
                           mutation_runner=recording_mutator,
                           monotonic=advancing_clock, sleeper=lambda _: None)
    assert only_rollback_update(commands)
```

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/hosted/test_run_azure_readback.py -q`

Commit: `git add scripts/run_azure_readback.py tests/hosted/test_run_azure_readback.py && git commit -m 'fix: wait for exact Azure readback revision'`.

### Task 2: Add a direct, one-way recovery operation

**Files:**

- Modify: `tests/hosted/test_run_azure_readback.py`
- Modify: `scripts/run_azure_readback.py`

**Interfaces:**

- `operation` accepts `"recover"` in addition to `"restart"` and `"rollback"`.
- `recover` requires `rollback_image` and emits one candidate update with
  `recover-<authorization-prefix>-<candidate-digest-prefix>`.

- [ ] **Step 1: Write the failing direct-recover regression**

```python
def test_recover_forwards_healthy_rollback_without_second_rollback_update():
    state = {"image": ROLLBACK, "revision": "rollback-22222222-ddddddd"}
    commands = []
    run_azure_readback(..., operation="recover", rollback_image=ROLLBACK,
                       resolver=stateful_resolver, mutation_runner=record_mutation)
    assert len(commands) == 1
    assert commands[0][commands[0].index("--image") + 1] == CURRENT
    assert "rollback-" not in commands[0][commands[0].index("--revision-suffix") + 1]
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/hosted/test_run_azure_readback.py::test_recover_forwards_healthy_rollback_without_second_rollback_update -q`

Expected: FAIL because `recover` is not an accepted operation.

- [ ] **Step 3: Implement direct recover**

Require the current app to resolve through `recovery_role="rollback"`, create
one candidate `recover-*` revision, wait for exact readiness, and run the
existing `compare_after_change()` over the same viewer.  Reject any initial
candidate, unknown, or mismatched rollback state.  Do not issue a rollback
mutation in this operation.

- [ ] **Step 4: Add initial-state rejection regression**

```python
def test_recover_rejects_when_current_state_is_not_exact_rollback():
    with pytest.raises(AzureReadbackInvalid, match="azure_readback_failed"):
        run_azure_readback(..., operation="recover", rollback_image=ROLLBACK,
                           resolver=lambda **_: (_ for _ in ()).throw(HostedCheckInvalid("x")))
```

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/hosted/test_run_azure_readback.py -q`

Commit: `git add scripts/run_azure_readback.py tests/hosted/test_run_azure_readback.py && git commit -m 'feat: recover exact Azure rollback revision'`.

### Task 3: Generate and validate a narrow forward-only recovery authority

**Files:**

- Create: `scripts/generate_rollback_forward_resume.py`
- Create: `.tmp/run_approved_rollback_forward_resume.py`
- Create: `tests/hosted/test_rollback_forward_resume.py`
- Modify: `tests/hosted/verify_azure_demo.py`
- Modify: `docs/operations/PHASE1_RECEIPT_RELEASE.md`

**Interfaces:**

- `generate_rollback_forward_resume.py` takes the original receipt-resume
  authority, its SHA-256, a current rollback read projection, and an injected
  UTC clock; it emits one value-safe JSON authority.
- The ignored runner validates the approved SHA before each stage.

- [ ] **Step 1: Write failing authority-shape regression**

```python
def test_forward_resume_authorizes_only_preflight_registry_recover_and_health(tmp_path):
    authority = generate_forward_resume(...)
    assert tuple(authority["stage_order"]) == (
        "rollback_preflight", "registry_verify", "recover", "health",
    )
    assert "--operation recover" in authority["commands"]["recover"][0]
    assert authority["release"]["ai_limits"]["enabled"] is False
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/hosted/test_rollback_forward_resume.py -q`

Expected: FAIL because the forward-resume generator does not exist.

- [ ] **Step 3: Implement exact authority derivation**

Bind source package SHA, receipt SHA/ID, candidate and rollback images,
expected rollback revision, app/resource group/subscription, control-script
hashes, no-AI declarations, a 24-hour expiry, and four exact stages.  Reject
any source package that contains AI, Phase 1, migration, seed, registry publish,
or an image mismatch.

- [ ] **Step 4: Add tamper/rejection regressions**

```python
@pytest.mark.parametrize("field", ["rollback_revision", "candidate_image", "receipt_sha256"])
def test_forward_resume_rejects_tampered_identity(field):
    with pytest.raises(ForwardResumeInvalid):
        generate_forward_resume(**tampered_input(field))
```

Also prove that the runner refuses an incorrect approved SHA before any
subprocess command.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/hosted/test_rollback_forward_resume.py tests/hosted/test_run_azure_readback.py -q`

Commit: `git add scripts/generate_rollback_forward_resume.py tests/hosted/test_rollback_forward_resume.py tests/hosted/verify_azure_demo.py docs/operations/PHASE1_RECEIPT_RELEASE.md && git commit -m 'feat: bind rollback forward recovery authority'`.

### Task 4: Package, approve, and execute the forward recovery

**Files:**

- Create: `.tmp/LAUNCH_AUTHORIZATION_ROLLBACK_FORWARD_RESUME_V1.md`
- Create: `.tmp/rollback-forward-state.json`

- [ ] **Step 1: Collect read-only rollback-state authority**

Read the exact app, revision, registry, and health projections.  Require the
expected rollback revision to be latest-ready and healthy before packaging.

- [ ] **Step 2: Generate and validate the package locally**

Run the generator and runner in `--validate-only` mode.  Record only the
package SHA-256, authorization ID, expiry, and no-AI status in user-visible
status.

- [ ] **Step 3: Request explicit user SHA approval**

Do not run the package until the user approves the exact printed SHA-256.

- [ ] **Step 4: Execute and verify hosted result**

After approval, run one package executor.  Independently read the exact final
candidate revision, health endpoint, and public URL before reporting hosted
acceptance.
