# Observed Current Release Authority Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` for inline, task-by-task execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permit a safe Azure update when the image currently serving differs from the candidate's attested rollback baseline, while making that distinction machine-verifiable.

**Architecture:** The attestation owns immutable candidate and rollback identity. A new update-only observation owns the currently serving image and is checked before mutation. Package commands carry both facts only where each is meaningful.

**Tech Stack:** Python 3.12, pytest, Azure CLI read-only probes, existing authorization verifier.

## Global Constraints

- No Azure mutation during implementation or local tests.
- `release.rollback_*` is derived only from the candidate attestation.
- `recovery.observed_current_image_digest` is a lower-case `sha256:<64 hex>` value only for update mode.
- No-AI packages retain disabled AI, no OpenAI secret, no paid-AI command, and `openai_smoke_cap=0.00`.
- Tests must be RED before production code is changed.

---

### Task 1: Separate observed and rollback images in preflight

**Files:**

- Modify: `scripts/azure_recovery_preflight.py`
- Modify: `tests/hosted/test_azure_preflight.py`

**Interfaces:**

- Consumes: `run_recovery_preflight(..., observed_current_image_digest: str | None, ...)`.
- Produces: update preflight matching the live app to the observed image, prepared preflight matching the staged candidate image.

- [ ] **Step 1: Write the failing update test**

```python
CURRENT = "sha256:" + "e" * 64

def test_update_preflight_accepts_observed_current_image_distinct_from_rollback():
    outputs = _prepared_outputs()
    outputs[16]["properties"]["configuration"]["ingress"]["external"] = True
    outputs[16]["properties"]["template"]["containers"][0]["image"] = (
        "bpapprovedregistry.azurecr.io/bizpulse@" + CURRENT
    )
    _run_update(outputs, observed_current_image_digest=CURRENT)
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/hosted/test_azure_preflight.py::test_update_preflight_accepts_observed_current_image_distinct_from_rollback -q`
Expected: FAIL because the function lacks the new field or still expects the rollback image.

- [ ] **Step 3: Implement the narrow contract**

```python
expected_current_digest = (
    image_digest if target_mode == "prepared" else observed_current_image_digest
)
```

Require the field exactly for update mode; reject it for fresh/prepared mode. Add CLI flag `--observed-current-image-digest` and pass it through `main()`.

- [ ] **Step 4: Add mismatch/non-update tests**

```python
with pytest.raises(AzurePreflightFailed, match="azure_preflight_current_release_invalid"):
    _run_update(outputs, observed_current_image_digest=CURRENT)

with pytest.raises(AzurePreflightFailed, match="azure_preflight_authority_invalid"):
    _run_prepared(_prepared_outputs(), observed_current_image_digest=CURRENT)
```

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/hosted/test_azure_preflight.py -q`
Expected: PASS.

Commit: `git add scripts/azure_recovery_preflight.py tests/hosted/test_azure_preflight.py && git commit -m 'fix: separate observed and rollback images in preflight'`.

### Task 2: Bind the observation into exact package commands

**Files:**

- Modify: `tests/hosted/verify_azure_demo.py`
- Modify: `tests/hosted/test_verify_azure_demo.py`

**Interfaces:**

- Consumes: `authority["recovery"]["observed_current_image_digest"]`.
- Produces: exact update/pre-publication commands carrying the observed value; prepared commands without it.

- [ ] **Step 1: Write failing schema/command tests**

```python
def test_update_authorization_binds_observed_current_image_to_preflight():
    payload = _valid_authorization()
    payload["recovery"]["observed_current_image_digest"] = "sha256:" + "e" * 64
    assert "--observed-current-image-digest" in _expected_commands(payload)["preflight"][0]
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/hosted/test_verify_azure_demo.py -k observed_current -q`
Expected: FAIL because the exact recovery schema does not contain the field.

- [ ] **Step 3: Implement command derivation**

Add the field to the exact recovery schema. Validate it as a digest only for update mode. Add the argument to update preflight and post-publication registry preflight. When converting preflight to prepared activation, remove the flag and value.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/hosted/test_verify_azure_demo.py -q`
Expected: PASS.

Commit: `git add tests/hosted/verify_azure_demo.py tests/hosted/test_verify_azure_demo.py && git commit -m 'feat: bind observed current image in update packages'`.

### Task 3: Derive repair-package identities instead of copying them

**Files:**

- Modify: `.tmp/generate_no_ai_chat_update_package.py`
- Create: `.tmp/test_generate_no_ai_chat_update_package.py`

**Interfaces:**

- Consumes: candidate attestation, local image inspect result, bounded Azure `containerapp show` projection.
- Produces: a package with attested rollback fields and an Azure-observed current image.

- [ ] **Step 1: Write a failing generator test**

```python
def test_generator_derives_rollback_from_attestation_and_current_from_azure(monkeypatch):
    authority = generate(now=NOW, az_runner=fake_current_image(CURRENT))
    assert authority["release"]["rollback_git_sha"] == ATTESTED_ROLLBACK_SHA
    assert authority["recovery"]["observed_current_image_digest"] == CURRENT
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest .tmp/test_generate_no_ai_chat_update_package.py -q`
Expected: FAIL because the generator still holds copied identity literals.

- [ ] **Step 3: Implement minimal derivation**

Read the candidate attestation via `attestation_path(candidate)` for rollback Git/input authority. Use one 30-second Azure CLI JSON read to obtain the current Container App's exact `@sha256:` image. Do not print Azure output or secrets.

- [ ] **Step 4: Verify boundary tests**

Run: `.venv/bin/pytest .tmp/test_generate_no_ai_chat_update_package.py tests/hosted/test_verify_azure_demo.py tests/hosted/test_azure_preflight.py -q`
Expected: PASS.

- [ ] **Step 5: Build a new immutable candidate**

Run the release gate and detached attestation on a clean tree. Build Linux/amd64 with candidate and input labels. Generate a mode-600 package, validate it with `verify_azure_demo.py`, then stop for a new full SHA-256 approval before Azure mutation.

## Plan Self-Review

- Spec coverage: Tasks 1–2 implement separate identities and package binding; Task 3 removes copied package authority.
- Placeholder scan: no deferred behavior or unbounded retry is included.
- Type consistency: `observed_current_image_digest` is `str | None` at preflight and a required update-only digest in the authorization contract.
