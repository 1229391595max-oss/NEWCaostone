# Hosted Failure Dummy Credential Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the paid-AI-disabled Azure failure rehearsals deploy their isolated AI-enabled revision with a disposable non-provider credential, without exposing or using a real OpenAI key.

**Architecture:** `run_failure_check` generates one bounded random placeholder for the transient revision only. `_deployment` passes it to Bicep through a copied child-process environment, never through command arguments or output; the recovery deployment receives the original environment. The provider-unavailable scenario remains pinned to `https://127.0.0.1:1`, and the budget scenario still rejects before provider transmission.

**Tech Stack:** Python 3.12, pytest, Azure CLI subprocess orchestration, Bicep environment-backed secure parameters.

## Global Constraints

- Do not enable or call paid AI.
- Do not place the placeholder in argv, logs, authorization JSON, Git, or persisted handoff files.
- Keep normal hosted configuration `BIZPULSE_AI_CHAT_ENABLED=false` and `openai_api_key=false`.
- Preserve exact target, `Standard_B1ms`, Central US, immutable image, and USD 30 hard cap.
- No Azure mutation resumes until a new candidate, image digest, attestation, launch package, and cleanup package receive exact SHA approval.

---

### Task 1: Isolated failure-rehearsal placeholder

**Files:**
- Modify: `scripts/run_hosted_failure_check.py`
- Test: `tests/hosted/test_run_hosted_failure_check.py`

**Interfaces:**
- Consumes: `run_failure_check(..., runner, browser_checker)` and the environment-backed `openaiApiKey` Bicep parameter.
- Produces: optional `placeholder_factory: Callable[[], str]` injection for deterministic tests; `_deployment(..., environment)` passes an explicit child environment to the Azure CLI runner.

- [x] **Step 1: Write the failing test**

Add a test that supplies `placeholder_factory=lambda: "rehearsal-placeholder-fixed"`, records each runner call and its `env`, and asserts:

```python
assert "rehearsal-placeholder-fixed" not in " ".join(transient_command)
assert transient_env["BIZPULSE_DEPLOY_OPENAI_API_KEY"] == "rehearsal-placeholder-fixed"
assert recovery_env.get("BIZPULSE_DEPLOY_OPENAI_API_KEY") != "rehearsal-placeholder-fixed"
```

Also assert an empty or overlong placeholder fails before any Azure runner call.

- [x] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/pytest tests/hosted/test_run_hosted_failure_check.py -q
```

Expected: the new test fails because `run_failure_check` does not accept `placeholder_factory` and deployments do not pass an explicit `env`.

- [x] **Step 3: Implement the minimal environment boundary**

Add:

```python
import os
import secrets

def _placeholder() -> str:
    return f"rehearsal-placeholder-{secrets.token_hex(24)}"
```

Extend `_deployment` with `environment: dict[str, str]` and call the runner with `env=environment`. In `run_failure_check`, copy `os.environ` once, validate the generated placeholder as nonempty and at most 128 characters, override `BIZPULSE_DEPLOY_OPENAI_API_KEY` only in a second copied environment for the transient deployment, and pass the untouched original copy to recovery.

- [x] **Step 4: Verify focused GREEN and regressions**

Run:

```bash
.venv/bin/pytest tests/hosted/test_run_hosted_failure_check.py tests/hosted/test_verify_azure_demo.py tests/infra/test_bicep_contract.py -q
.venv/bin/ruff check scripts/run_hosted_failure_check.py tests/hosted/test_run_hosted_failure_check.py
```

Expected: all tests pass and Ruff reports no errors.

- [ ] **Step 5: Rebuild exact release authority**

Run the existing release gates, commit the candidate, build a `linux/amd64` image labeled with the exact candidate SHA and image-input hash, generate a manifest-only direct child attestation, and fresh-verify the detached candidate. Generate a value-complete cleanup package for the current private resources and a launch package using the new candidate/digest.

- [ ] **Step 6: External approval gate**

Report both exact SHA256 values. Do not execute cleanup, registry publication, deployment, provider rehearsal, public activation, or hosted acceptance until the user approves those exact hashes.

---

### Task 2: ARM outcome fence and secret-removal authority

**Files:**
- Modify: `scripts/run_hosted_failure_check.py`
- Modify: `infra/main.bicep`
- Modify: `infra/modules/app.bicep`
- Test: `tests/hosted/test_run_hosted_failure_check.py`
- Test: `tests/infra/test_bicep_contract.py`

**Authority:** Microsoft documents that resource-group deployments may be cancelled only while `Accepted` or `Running`; a successful cancellation ends in `Canceled`. Recovery therefore cannot be published until a failed/acknowledgement-lost transient deployment is independently observed as absent or terminal (`Succeeded`, `Failed`, or `Canceled`).

- [x] **Step 1: Write the failing outcome-ambiguity tests**

Simulate a transient deployment that raises `TimeoutExpired` after Azure records it as `Running`. Assert that the service issues `az deployment group cancel`, observes a terminal state, and only then starts recovery. Also assert that an unknown/non-terminal state prevents recovery.

- [x] **Step 2: Write the failing secret-removal tests**

Assert that `openaiApiKey` is decorated `@secure()` in both Bicep scopes. Add recovery payload variants containing `configuration.secrets[].name == openai-api-key` or an `OPENAI_API_KEY` `secretRef`, and require fail-closed rejection.

- [x] **Step 3: Implement the terminal deployment fence**

On a transient deployment exception, query the exact deployment authority. If it is `Accepted` or `Running`, request cancellation and poll with a bounded deadline until the state is `Succeeded`, `Failed`, or `Canceled`. Treat exact `DeploymentNotFound` as no accepted deployment only after 12 consecutive observations over a 55-second stability window; if the deployment appears during that window, return to the same terminal/cancellation state machine. All state and absence observations share one 60-attempt/295-second maximum budget so alternating visibility cannot multiply the deadline. Reject unknown states or unverifiable authority. Do not begin recovery until this fence succeeds.

- [x] **Step 4: Implement secure parameter and cleanup verification**

Decorate both `openaiApiKey` parameters with `@secure()`. During recovery readback, require that neither the app secret list nor container environment retains the transient OpenAI secret name/reference.

- [x] **Step 5: Re-run all Task 1 and Task 2 gates**

Run focused tests, Bicep compilation with zero warnings, the hosted/infra/release suite, Ruff, compileall, and diff checks before candidate commit and release reconstruction.
