# AI Enablement Asynchronous Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace immediate Container App PATCH-body verification with one-shot PATCH acknowledgement plus bounded state reconciliation, preserve safe failure recovery, and generate a fresh exact-SHA AI Enablement package only after a live Azure-and-workspace gate.

**Architecture:** A new pure reconciliation module classifies only complete predecessor and target profiles, polls sanitized Container App and revision-list projections, and returns closed, non-secret evidence. The existing action adapter owns the single PATCH and supplies Azure readers; the runner owns receipt/observation persistence and post-Key recovery. Package generation becomes schema v2 and performs the same live read-only authority check immediately before the exclusive package write.

**Tech Stack:** Python 3.12, pytest, Azure CLI and ARM `2025-01-01`, Azure Container Apps, Azure Key Vault RBAC, dedicated UAMI, Bicep, Node.js test runner, Playwright-compatible browser gate, Docker buildx, owner-only JSON evidence.

## Global Constraints

- Implementation baseline is commit `58d73f59901468a9060753ccdfa3d2f1cff0507c` on branch `codex/ai-enable-preset-buttons` in the existing isolated worktree. Use that SHA for changed-path verification.
- The current safe hosted baseline must be re-read before package creation. Its last verified values are revision `newcaostone-demo-app--ai-off-ba92c00d-d4eb6e4`, image `sellernorthbpacr.azurecr.io/bizpulse@sha256:d4eb6e41e7643caf01ce6f615ef5d7a4333f6ab416e5a0ad7e0925cdc9d7958b`, `BIZPULSE_AI_CHAT_ENABLED=false`, and only the original registry UAMI.
- R1 package `77d3d2747df21f79d27f7cd700080fc710653cda425c9c3e48a0c865efdd0180` and receipt `bd6bc07e071c26f0ce91051cbf2e607ff7fe4d5cb641482ffbedac1b1ed9ae20` are immutable and consumed.
- R2 package `71ce801f0a007327c1a35424306bbe0d987cb5303e1a2d7e613237c2c419e0a4` and receipt `83ce72f7adf7152b29e2123df84a770e05bd378c0c9b3dbdfe50539678ff3bd2` are immutable and consumed.
- R3 package `ba92c00d154e47944d909ed5ea3204262b335487690252810eda9c669ea599b0` and receipt `260c5d24e960198af4598b441f88ab4444a604718b60197569b0446fc2b5a924` are immutable and consumed. Its ACR tag `ai-5a6c199eacae-ba92c00d` and digest remain preserved.
- D3 package SHA `2ca7c7aa0d133b94607569af437dcf0f6a2b7aa44afc475c332dfe16e0ac8687` remains byte-identical, unexecuted, and separate from AI enablement.
- Every Container App transition permits one PATCH and zero PATCH retries. Each transition permits at most 120 seconds, polls no faster than every 5 seconds, and performs at most 25 application reads plus 25 revision-list reads.
- A complete predecessor profile and a complete target profile are the only allowed application templates during propagation. A third latest/latest-ready/active revision, a partial profile, wrong image/AI/identity/configuration, `Failed`, or `Unhealthy` is terminal.
- Budget and provider rehearsals must reach a healthy enabled revision before browser execution and a healthy disabled recovery revision before the state completes.
- After a real Key write, every failure attempts exactly one AI-disabled PATCH, bounded reconciliation, and a generated placeholder overwrite. A fully successful run remains AI-enabled for the public Azure Demo.
- Never request the OpenAI Key in chat, a file, `.env`, argv, package, log, screenshot, test, or receipt. The hidden local TTY prompt remains unreachable before exact package approval and all earlier gates.
- Existing credentials, existing Key Vaults, ACR-pull UAMI, PostgreSQL, storage, Operator credentials, session pepper, and account boundaries are untouched.
- The Demo passcode remains deferred. Do not add a passcode or a network-search/new-product preset in this plan.
- Preserve the six server-catalog bilingual presets, manual Send requirement, draft replacement confirmation, audit quartet, store/workspace filtering, disabled zero-request behavior, permissions, and budget controls.
- No task before Task 7 may issue an Azure request or create the R4 package. Task 7 permits only the package generator's bounded read-only Azure gate and local owner-only package write; it still permits no Azure mutation, registry publication, public browser request, Key prompt, or paid OpenAI request.
- Use `apply_patch` for tracked edits, make one focused commit per task, and preserve unrelated or ignored user work.

---

### Task 1: Build the pure asynchronous reconciliation state machine

**Files:**
- Create: `scripts/azure_ai_reconciliation.py`
- Create: `tests/hosted/test_azure_ai_reconciliation.py`

**Interfaces:**
- Consumes: sanitized application and revision-list mappings supplied by callbacks; no subprocess, Azure SDK, filesystem, environment, or secret access.
- Produces: `PendingAITransition`, `ReconciliationEvidence`, `AzureAIReconciliationInvalid`, and `reconcile_ai_transition(pending: PendingAITransition, *, application_reader: Callable[[], Mapping[str, object]], revisions_reader: Callable[[], Sequence[Mapping[str, object]]], monotonic: Callable[[], float], sleeper: Callable[[float], None]) -> dict[str, object]`.
- `PendingAITransition` fields are `role`, `acknowledgement`, `started_at`, `predecessor_revision`, `target_revision`, `predecessor_projection`, `target_projection`, and `target_image`.
- `reconcile_ai_transition` accepts keyword callbacks `application_reader`, `revisions_reader`, `monotonic`, and `sleeper`.

- [ ] **Step 1: Write failing wait/success tests**

Create deterministic helpers that return a predecessor app at clock `0`, a target app with old latest-ready at clock `5`, a target with `healthState=None` at clock `10`, and a healthy/provisioned target at clock `15`. Assert:

```python
evidence = reconcile_ai_transition(
    pending,
    application_reader=application_reader,
    revisions_reader=revisions_reader,
    monotonic=clock.monotonic,
    sleeper=clock.sleep,
)
assert evidence == {
    "role": "ai_disabled_candidate",
    "acknowledgement": "accepted",
    "predecessor_revision": PREDECESSOR,
    "target_revision": TARGET,
    "target_image_digest": "sha256:" + ("c" * 64),
    "final_state": "healthy_target",
    "application_read_count": 4,
    "revision_read_count": 3,
    "elapsed_milliseconds": 15000,
}
```

The first cycle must not call `revisions_reader` because the application has not announced the target. Assert the exact sleep sequence is `[5.0, 5.0, 5.0]`.

- [ ] **Step 2: Write failing terminal and budget tests**

Parameterize the terminal cases and expected safe code:

```python
@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("third_latest", "ai_reconciliation_drift"),
        ("third_active", "ai_reconciliation_drift"),
        ("wrong_image", "ai_reconciliation_drift"),
        ("partial_identity", "ai_reconciliation_drift"),
        ("failed", "ai_reconciliation_failed"),
        ("unhealthy", "ai_reconciliation_failed"),
    ],
)
def test_terminal_profiles_stop_without_sleep_or_extra_read(mutation, code):
    with pytest.raises(AzureAIReconciliationInvalid, match=code) as raised:
        reconcile_ai_transition(
            pending,
            application_reader=lambda: mutated_application,
            revisions_reader=lambda: mutated_revisions,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )
    assert raised.value.evidence["application_read_count"] == 1
    assert raised.value.evidence["elapsed_milliseconds"] == 0
```

Add a fake clock test where no target becomes ready. It must stop with `ai_reconciliation_timeout`, exactly 25 application reads, no more than 25 revision reads, 24 sleeps of five seconds, and elapsed time exactly 120000 milliseconds. Add application-reader and revision-reader exceptions and assert `ai_reconciliation_read_failed` without serializing exception text.

- [ ] **Step 3: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_azure_ai_reconciliation.py -q
```

Expected: collection fails because `scripts.azure_ai_reconciliation` does not exist.

- [ ] **Step 4: Implement the closed state machine**

Use frozen dataclasses and these exact limits/allowlists:

```python
MAX_RECONCILIATION_SECONDS = 120.0
POLL_INTERVAL_SECONDS = 5.0
MAX_APPLICATION_READS = 25
MAX_REVISION_READS = 25
ALLOWED_ROLES = frozenset({
    "ai_disabled_candidate",
    "budget_enabled",
    "budget_recovery",
    "provider_enabled",
    "provider_recovery",
    "ai_enabled",
    "emergency_disabled",
})
FINAL_STATES = frozenset({
    "healthy_target", "drift", "failed", "read_failed", "timeout"
})
```

Before comparing profiles, project the application to exactly `location`, `identity`, and `properties.template`; require that projection to equal the complete predecessor or target projection. Require `latestRevisionName` and `latestReadyRevisionName` to be members of `{predecessor_revision, target_revision}`. From the revision list, reject every active name outside that set. Success requires target latest, target latest-ready, app provisioning `Succeeded`, target active, target health `Healthy`, target provisioning `Provisioned`, and target template equal to the target template.

Use `for cycle in range(MAX_APPLICATION_READS)` so a 26th application read is structurally impossible. Query revisions only after the app names the target. Check the monotonic deadline after each classification; sleep only if another cycle is allowed. Construct error evidence from closed codes and counters only.

- [ ] **Step 5: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_azure_ai_reconciliation.py -q
.venv/bin/ruff check scripts/azure_ai_reconciliation.py \
  tests/hosted/test_azure_ai_reconciliation.py
git add scripts/azure_ai_reconciliation.py \
  tests/hosted/test_azure_ai_reconciliation.py
git commit -m "feat: reconcile async AI revisions"
```

### Task 2: Integrate one-shot acknowledgement and ordered readiness into Azure actions

**Files:**
- Modify: `scripts/azure_ai_enablement_actions.py:530-1451`
- Modify: `tests/hosted/test_azure_ai_enablement_actions.py`
- Modify: `tests/hosted/test_azure_ai_revision.py`

**Interfaces:**
- Consumes: Task 1 `PendingAITransition` and `reconcile_ai_transition`.
- Produces: `_apply_patch_azure(patch: Mapping[str, object], *, revision_suffix: str) -> str` returning only `"accepted"`; `_verify_revision(*, enabled: bool, image: str, revision: str, context: Mapping[str, object]) -> dict[str, object]`; `emergency_recovery(*, context: Mapping[str, object], real_secret_write_attempted: bool) -> dict[str, object]`.
- `AzureAIEnablementActions.__init__` gains injected `monotonic: Callable[[], float] = time.monotonic` and `sleeper: Callable[[float], None] = time.sleep`.

- [ ] **Step 1: Write failing acknowledgement tests**

Add subprocess cases for an acknowledged update with an empty JSON body and with the exact app `id`. Require one `az rest --method patch`, `@/dev/stdin`, no secret-bearing body, and return `"accepted"`. A nonzero exit, oversized stdout, malformed nonempty JSON, or a different app ID must raise `ai_enablement_patch_unconfirmed`; calls remain exactly one.

```python
acknowledgement = actions._apply_patch_azure(
    patch,
    revision_suffix="ai-off-12345678-ccccccc",
)
assert acknowledgement == "accepted"
assert len([call for call in calls if call[0][0:3] == ("az", "rest", "--method")]) == 1
```

- [ ] **Step 2: Write failing ordering and recovery tests**

Replace injected no-op revision verifiers with a verifier that returns fixed safe evidence. Assert each rehearsal order is:

```python
assert events == [
    "patch:budget",
    "reconcile:budget_enabled",
    "browser:budget",
    "patch:recover-b",
    "reconcile:budget_recovery",
]
```

Do the same for provider failure. Add an emergency case where reconciliation raises: the sequence must contain one disable PATCH, one reconciliation attempt, and one emergency placeholder write; the placeholder write runs from `finally` and the returned recovery projection sets `ai_disabled_confirmed=False` and `placeholder_overwrite_succeeded=True`. Assert no second PATCH.

- [ ] **Step 3: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_revision.py \
  -k 'acknowledgement or ordering or recovery or asynchronous' -q
```

Expected: the PATCH body is still treated as final state, browser precedes enabled reconciliation, and placeholder overwrite precedes disabled verification.

- [ ] **Step 4: Store exact pending transitions**

In `_apply_revision`, capture `started_at = self._monotonic()` immediately before `_patch_applier`, keep a deep copy of the predecessor projection, build the target patch, and store:

```python
self._pending_transitions[expected_revision] = PendingAITransition(
    role=role,
    acknowledgement=acknowledgement,
    started_at=started_at,
    predecessor_revision=self._current_revision,
    target_revision=expected_revision,
    predecessor_projection=predecessor_projection,
    target_projection=deepcopy(patch),
    target_image=self._candidate_image(context),
)
```

Make `role` an explicit keyword on `_apply_revision`; update `_current_revision` and `current_projection` only after the acknowledgement validates. The initial read-only revalidation sets `_current_revision` from the package rollback revision.

- [ ] **Step 5: Replace single-read verification with bounded callbacks**

The application callback uses one sanitized `az containerapp show`. The revision callback uses one sanitized `az containerapp revision list` and returns only name, active, health state, provisioning state, and template. Both keep the one-MiB stdout cap and never query secrets, environment values outside the already allowlisted application template, replicas' logs, or raw responses.

Call:

```python
evidence = reconcile_ai_transition(
    self._pending_transitions.pop(revision),
    application_reader=application_reader,
    revisions_reader=revisions_reader,
    monotonic=self._monotonic,
    sleeper=self._sleeper,
)
```

Do not catch and retry a PATCH. Convert reconciliation errors to `AzureAIEnablementActionInvalid` using only their closed code and attach the already-sanitized evidence for the runner.

- [ ] **Step 6: Enforce rehearsal and recovery order**

For budget/provider enabled patches, call `_revision_verifier` before `_browser_checker`. In `_recover_disabled`, issue one disabled PATCH, reconcile it, then run the placeholder overwrite in `finally` when requested. Return:

```python
{
    "ai_disabled_confirmed": reconciliation_error is None,
    "placeholder_overwrite_succeeded": placeholder_error is None,
    "reconciliation": reconciliation_evidence,
}
```

If disabled reconciliation or placeholder overwrite fails, raise only after both were attempted. Successful rehearsal output contains both enabled and recovery reconciliation mappings. Successful final enablement does not call `_recover_disabled`.

- [ ] **Step 7: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_azure_ai_reconciliation.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_revision.py -q
.venv/bin/ruff check scripts/azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_revision.py
git add scripts/azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_revision.py
git commit -m "fix: await healthy AI revisions"
```

### Task 3: Version the execution contract and persist sanitized transition evidence

**Files:**
- Modify: `scripts/ai_enablement_contract.py`
- Modify: `scripts/run_ai_enablement.py`
- Modify: `tests/hosted/test_ai_enablement_contract.py`
- Modify: `tests/hosted/test_run_ai_enablement.py`
- Modify: `tests/hosted/test_azure_ai_enablement_actions.py`

**Interfaces:**
- Consumes: Task 2 reconciliation mappings and recovery result.
- Produces: `validate_reconciliation_evidence`, success/failure receipt v2 sanitizers, owner-only observation v1 writer, and runner context key `reconciliations`.
- Successful receipt schema is `newcaostone.ai-enablement-receipt.v2`; started/failed schema is `newcaostone.ai-enablement-attempt.v2`; observation schema is `newcaostone.ai-enablement-observation.v1`.

- [ ] **Step 1: Write failing contract tests**

Add exact runtime bounds:

```python
assert contract_template()["runtime_limits"] | {
    "reconciliation_timeout_seconds": 120,
    "reconciliation_poll_interval_seconds": 5,
    "reconciliation_application_read_max": 25,
    "reconciliation_revision_read_max": 25,
    "containerapp_patch_retries": 0,
} == contract_template()["runtime_limits"]
```

Change read operation declarations from an exact two reads to per-transition maxima. For one verification state use `azure.read.containerapp.max=25` and `azure.read.revisions.max=25`; for a two-transition rehearsal use `50` and `50`. Add validation tests rejecting a role outside the seven-role allowlist, count `26`, elapsed `120001`, extra keys, Key-shaped strings, prompt text, user data, raw stdout, and exception text.

- [ ] **Step 2: Write failing runner receipt and observation tests**

On success, require six ordered reconciliation entries and an exclusive mode-`0600` observation. Require the completed receipt to bind the observation SHA-256. On a failure after real write, inject one recovery result and assert a failed receipt contains only the safe failure code, completed-state prefix, reconciliation entries, and:

```python
"recovery": {
    "ai_disabled_confirmed": True,
    "placeholder_overwrite_succeeded": True,
    "reconciliation": emergency_evidence,
}
```

Add failure cases before Key input, observation creation failure, terminal receipt finalization failure, and recovery failure. The sentinel Key must be absent from package, receipt, observation, return value, stdout, stderr, and `repr` of raised exceptions. Receipt-finalization failure leaves the original `started` replay fence and still invokes emergency recovery once.

- [ ] **Step 3: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_ai_enablement_contract.py \
  tests/hosted/test_run_ai_enablement.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  -k 'reconciliation or receipt_v2 or observation or recovery' -q
```

- [ ] **Step 4: Implement closed evidence validation**

`validate_reconciliation_evidence` requires exactly these keys and bounds:

```python
RECONCILIATION_KEYS = frozenset({
    "role", "acknowledgement", "predecessor_revision", "target_revision",
    "target_image_digest", "final_state", "application_read_count",
    "revision_read_count", "elapsed_milliseconds",
})
```

Require `acknowledgement == "accepted"`, allowed role/final state, canonical revision and digest patterns, reads in `0..25`, and elapsed in `0..120000`. Scan the complete serialized value for Key/Bearer/database/connection/prompt/user-data markers and reject unknown fields.

- [ ] **Step 5: Carry evidence through operation results**

Extend `_exact_result` so:

- `verify_ai_disabled_candidate` and `verify_ai_enabled_revision` each return one `reconciliation`;
- `budget_failure_rehearsal` and `provider_failure_rehearsal` each return exactly two `reconciliations`;
- `activate_*` states still return only revision/image anchors;
- browser states cannot begin unless their corresponding reconciliation is already appended to context.

Append validated mappings to `context["reconciliations"]`. On normal success require roles in this exact order:

```python
[
    "ai_disabled_candidate",
    "budget_enabled", "budget_recovery",
    "provider_enabled", "provider_recovery",
    "ai_enabled",
]
```

- [ ] **Step 6: Finalize safe receipts and observation**

Reserve attempt v2 before the first mutation. On success, exclusively write the mode-`0600` observation first with `acceptance_requires_completed_receipt=True`, final revision/image, `ai_enabled=True`, paid call count `13`, and six sanitized reconciliation entries. Hash it, then finalize the reserved receipt with the observation hash.

If any later step fails after `real_secret_write_attempted=True`, call emergency recovery exactly once, append its safe evidence, and finalize a failed receipt when persistence remains available. Never place `str(error)`, traceback, stdout, stderr, raw HTTP/Azure data, Key, prompt, or user content into either artifact. If receipt finalization itself fails, keep `started` unchanged and do not retry package execution.

- [ ] **Step 7: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_ai_enablement_contract.py \
  tests/hosted/test_run_ai_enablement.py \
  tests/hosted/test_azure_ai_enablement_actions.py -q
.venv/bin/ruff check scripts/ai_enablement_contract.py \
  scripts/run_ai_enablement.py tests/hosted/test_ai_enablement_contract.py \
  tests/hosted/test_run_ai_enablement.py
git add scripts/ai_enablement_contract.py scripts/run_ai_enablement.py \
  tests/hosted/test_ai_enablement_contract.py \
  tests/hosted/test_run_ai_enablement.py \
  tests/hosted/test_azure_ai_enablement_actions.py
git commit -m "feat: record bounded AI reconciliation"
```

### Task 4: Make package schema v2 depend on a live pre-write Azure gate

**Files:**
- Modify: `scripts/create_ai_enablement_package.py`
- Modify: `scripts/azure_ai_enablement_actions.py:184-495`
- Modify: `scripts/run_ai_enablement.py:470-537`
- Modify: `tests/hosted/test_create_ai_enablement_package.py`
- Modify: `tests/hosted/test_azure_ai_enablement_actions.py`
- Modify: `tests/hosted/test_run_ai_enablement.py`

**Interfaces:**
- Consumes: clean Git state, control hashes, exact R1/R2/R3 local artifacts, D3 invariant, and a nine-read sanitized Azure projection.
- Produces: package schema `newcaostone.ai-enablement-package.v2`, `capture_prior_ai_attempts(project_root: Path = PROJECT_ROOT) -> dict[str, object]`, and `generate_ai_enablement_package(*, output_path: Path, receipt_path: Path, observation_path: Path, generated_at: Callable[[], datetime], repository_reader: Callable[[], object], control_reader: Callable[[], object], prior_attempts_reader: Callable[[], object], azure_reader: Callable[[Mapping[str, object]], object]) -> dict[str, object]` that writes only after all live/local checks pass.
- Adds CLI arguments `--receipt`, `--observation`, and `--rollback-registry-tag`.

- [ ] **Step 1: Write failing prior-attempt and artifact-path tests**

Bind these exact relative paths and SHA-256 values:

```python
PRIOR_AI_ATTEMPTS = {
    "r1": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_2026-08-17.json",
        "package_sha256": "77d3d2747df21f79d27f7cd700080fc710653cda425c9c3e48a0c865efdd0180",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_2026-08-17.json",
        "receipt_sha256": "bd6bc07e071c26f0ce91051cbf2e607ff7fe4d5cb641482ffbedac1b1ed9ae20",
    },
    "r2": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R2_2026-08-17.json",
        "package_sha256": "71ce801f0a007327c1a35424306bbe0d987cb5303e1a2d7e613237c2c419e0a4",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R2_2026-08-17.json",
        "receipt_sha256": "83ce72f7adf7152b29e2123df84a770e05bd378c0c9b3dbdfe50539678ff3bd2",
    },
    "r3": {
        "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R3_2026-08-17.json",
        "package_sha256": "ba92c00d154e47944d909ed5ea3204262b335487690252810eda9c669ea599b0",
        "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R3_2026-08-17.json",
        "receipt_sha256": "260c5d24e960198af4598b441f88ab4444a604718b60197569b0446fc2b5a924",
    },
}
```

Each file must be regular, non-symlink, mode `0600`; each receipt must have attempt v1, its matching package SHA, and `state="started"`. Mutation, removal, replacement, mode drift, or content drift must reject package creation and later execution.

Package artifacts are exactly:

```python
{
    "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R4_2026-08-17.json",
    "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R4_2026-08-17.json",
    "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_R4_2026-08-17.json",
}
```

All three paths must be absent before generation; the runner must reject CLI paths that differ from the package.

- [ ] **Step 2: Write failing nine-read Azure gate tests**

Extend the current seven-read fake Azure runner with:

1. `az containerapp replica list` for the R3 rollback revision, returning exactly one running replica name projection;
2. `az acr manifest show-metadata --name bizpulse@sha256:d4eb6e41e7643caf01ce6f615ef5d7a4333f6ab416e5a0ad7e0925cdc9d7958b` returning the exact digest and tags containing `ai-5a6c199eacae-ba92c00d`.

Require all nine reads, equal latest/latest-ready, healthy/provisioned revision, one replica, exact R3 digest/tag, AI false, original registry identity only, target vault name available, target UAMI absent, matching account/ACR/workspace, Single revision mode, and unchanged ingress/traffic/probes/scale/resources. Every drift case must fail before `write_ai_enablement_package` is called.

- [ ] **Step 3: Write failing generation-order tests**

Inject event callbacks and assert:

```python
assert events == [
    "repository:before",
    "controls:before",
    "prior_attempts:before",
    "azure:read_only",
    "repository:after",
    "controls:after",
    "prior_attempts:after",
    "package:exclusive_write",
]
```

If Azure reading fails, or either after-snapshot differs, assert the output package, receipt, and observation paths are absent and no mutation callback exists. The final `issued_at` is captured only after the live read and expiry remains exactly 24 hours.

- [ ] **Step 4: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_create_ai_enablement_package.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_run_ai_enablement.py \
  -k 'prior_attempt or nine_read or prepackage or artifact_path' -q
```

- [ ] **Step 5: Implement package v2 and the live gate**

Add `artifacts`, `prior_attempts`, and `prepackage_gate` to `_PACKAGE_KEYS`. `prepackage_gate` binds:

```python
{
    "required_azure_reads": 9,
    "rollback_revision": "newcaostone-demo-app--ai-off-ba92c00d-d4eb6e4",
    "rollback_image": "sellernorthbpacr.azurecr.io/bizpulse@sha256:d4eb6e41e7643caf01ce6f615ef5d7a4333f6ab416e5a0ad7e0925cdc9d7958b",
    "rollback_registry_tag": "ai-5a6c199eacae-ba92c00d",
    "replica_count": 1,
    "ai_enabled": False,
    "vault_absent": True,
    "identity_absent": True,
}
```

Add `scripts/azure_ai_reconciliation.py` to `CONTROL_PATHS`. `generate_ai_enablement_package` builds a provisional in-memory package, performs the nine reads, repeats Git/control/prior snapshots, requires equality, rebuilds with `generated_at` captured after the reads, and exclusively writes the package. It never rewrites a live expectation from observed Azure data.

- [ ] **Step 6: Recheck the same gates at execution**

Before reserving the R4 receipt, require package hash/expiry, exact package-bound CLI artifact paths, clean repository, exact control hashes, exact prior-attempt hashes/states, exact D3 state, nine-read Azure authority, and current provider price/cap. The Key provider remains untouched until after failure rehearsals.

- [ ] **Step 7: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_create_ai_enablement_package.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_run_ai_enablement.py -q
.venv/bin/ruff check scripts/create_ai_enablement_package.py \
  scripts/azure_ai_enablement_actions.py scripts/run_ai_enablement.py \
  tests/hosted/test_create_ai_enablement_package.py
git add scripts/create_ai_enablement_package.py \
  scripts/azure_ai_enablement_actions.py scripts/run_ai_enablement.py \
  tests/hosted/test_create_ai_enablement_package.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_run_ai_enablement.py
git commit -m "feat: gate AI package on live Azure state"
```

### Task 5: Update the operator runbook and verify the focused AI contract

**Files:**
- Modify: `docs/runbooks/AI_ENABLEMENT.md`
- Modify: `tests/hosted/test_ai_enablement_contract.py`
- Verify unchanged: `infra/ai_enablement.bicep`
- Verify unchanged: `infra/ai_secret_write.bicep`
- Verify unchanged: `src/ai/prompt_catalog.py`
- Verify unchanged: `frontend/assets/features/ask-bizpulse/view.mjs`

**Interfaces:**
- Consumes: Tasks 1-4 schemas, state sequence, and R4 paths.
- Produces: an exact local runbook that does not grant execution authority.

- [ ] **Step 1: Write failing runbook contract assertions**

Add source assertions for the phrases and values that must not drift: `202 Accepted`, `120 seconds`, `5 seconds`, `25 application`, `25 revision`, `zero PATCH retries`, `R4`, `nine sanitized Azure reads`, `success remains AI-enabled`, `failure recovery`, `hidden local TTY`, and the exact new package/receipt/observation paths. Reject the old claim that every verification uses exactly two reads.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_ai_enablement_contract.py \
  -k 'runbook or reconciliation' -q
```

- [ ] **Step 3: Update the runbook**

Document acknowledgement versus convergence, waiting/terminal states, the six normal PATCHes, at most one emergency PATCH, enabled-before-browser ordering, disabled-before-recovery-complete ordering, provisional observation plus completed receipt, public-Demo success remaining enabled, and separate future disable/revoke authorization. Replace the package command with R4 paths and `--rollback-registry-tag ai-5a6c199eacae-ba92c00d`.

Keep the explicit warning that Key Vault public network access plus RBAC does not make the passcode a Key Vault control. Keep the known shared-budget abuse risk while the passcode is deferred.

- [ ] **Step 4: Run focused AI, secret, preset, and Bicep tests**

```bash
.venv/bin/pytest tests/hosted/test_azure_ai_reconciliation.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_run_ai_enablement.py \
  tests/hosted/test_create_ai_enablement_package.py \
  tests/hosted/test_ai_enablement_contract.py \
  tests/infra/test_ai_enablement_bicep.py \
  tests/unit/secrets/test_azure_openai.py \
  tests/unit/ai/test_prompt_catalog.py \
  tests/api/v1/test_ai_chat.py \
  tests/security/test_ai_chat_boundary.py -q
node --test --test-name-pattern='preset|Ask BizPulse|recommended question|AI' \
  tests/frontend/ask-bizpulse-state.test.mjs \
  tests/frontend/ask-bizpulse-view-model.test.mjs \
  tests/frontend/ask-bizpulse-view.test.mjs \
  tests/frontend/ask-bizpulse-effects.test.mjs
az bicep build --file infra/ai_enablement.bicep --stdout >/dev/null
az bicep build --file infra/ai_secret_write.bicep --stdout >/dev/null
```

Expected: PASS, six English and six Chinese preset labels, fill/focus/no-auto-send, draft confirmation, complete audit quartet, disabled zero request, enabled server validation/budgets, and no secret/prompt/user-data leak.

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/AI_ENABLEMENT.md \
  tests/hosted/test_ai_enablement_contract.py
git commit -m "docs: explain async AI enablement gate"
```

### Task 6: Run full local verification and preserve browser evidence

**Files:**
- Verify: all changed files since `58d73f59901468a9060753ccdfa3d2f1cff0507c`
- Preserve ignored: `.tmp/ai-enablement-browser-evidence/01-six-preset-buttons-visible.png`
- Preserve ignored: `.tmp/ai-enablement-browser-evidence/02-preset-filled-no-auto-submit.png`
- Preserve ignored: `.tmp/ai-enablement-browser-evidence/03-result-after-manual-send.png`

**Interfaces:**
- Consumes: clean committed Tasks 1-5.
- Produces: fresh local verification evidence only; no hosted or paid claim.

- [ ] **Step 1: Verify clean branch and immutable artifacts**

```bash
test "$(git branch --show-current)" = codex/ai-enable-preset-buttons
test -z "$(git status --short)"
shasum -a 256 \
  .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_2026-08-17.json \
  .tmp/AI_ENABLEMENT_RECEIPT_2026-08-17.json \
  .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R2_2026-08-17.json \
  .tmp/AI_ENABLEMENT_RECEIPT_R2_2026-08-17.json \
  .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R3_2026-08-17.json \
  .tmp/AI_ENABLEMENT_RECEIPT_R3_2026-08-17.json
```

Expected: the six SHA values in Global Constraints; all modes remain `600` and all receipts remain `started`.

- [ ] **Step 2: Run complete relevant Python and frontend suites**

```bash
.venv/bin/pytest tests/hosted/test_azure_ai_reconciliation.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_revision.py \
  tests/hosted/test_run_ai_enablement.py \
  tests/hosted/test_create_ai_enablement_package.py \
  tests/hosted/test_ai_enablement_contract.py \
  tests/infra/test_ai_enablement_bicep.py \
  tests/unit/secrets/test_azure_openai.py \
  tests/unit/ai/test_model_qualification.py \
  tests/unit/ai/test_prompt_catalog.py \
  tests/integration/test_ai_chat_tools.py \
  tests/api/v1/test_ai_chat.py \
  tests/services/test_ai_chat_service.py \
  tests/security/test_ai_chat_boundary.py \
  tests/acceptance/test_browser_smoke.py -q
npm test
```

- [ ] **Step 3: Run static, Bicep, and changed-path gates**

```bash
.venv/bin/ruff check scripts/azure_ai_reconciliation.py \
  scripts/azure_ai_enablement_actions.py scripts/ai_enablement_contract.py \
  scripts/run_ai_enablement.py scripts/create_ai_enablement_package.py \
  tests/hosted/test_azure_ai_reconciliation.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_run_ai_enablement.py \
  tests/hosted/test_create_ai_enablement_package.py
.venv/bin/python -m compileall -q scripts tests/hosted
az bicep build --file infra/ai_enablement.bicep --stdout >/dev/null
az bicep build --file infra/ai_secret_write.bicep --stdout >/dev/null
.venv/bin/python scripts/check_authority_contract.py --mode docs
.venv/bin/python scripts/verify_changed.py \
  --base 58d73f59901468a9060753ccdfa3d2f1cff0507c --no-reuse
.venv/bin/python scripts/verify_release.py \
  --manifest tests/fixtures/synthetic/v1/manifest.json
git diff --check 58d73f59901468a9060753ccdfa3d2f1cff0507c HEAD
```

Expected: PASS and `verification_changed=passed`. If the policy requires a full release gate, run the exact checked-in `release_static` argv through `scripts.select_required_checks` and record its result; do not weaken the policy or reuse old evidence.

- [ ] **Step 4: Inspect the existing local browser screenshots**

Use the browser-control skill for a fresh local UI session if the screenshots are missing, unreadable, or no longer correspond to the current six-preset implementation. The evidence must show: six buttons visible; click fills and focuses the textarea with no request; explicit Send causes the request/result. Verify English and Chinese labels through the automated frontend tests. Do not open the public Azure URL in this task.

- [ ] **Step 5: Commit only tracked verification closeout if needed**

If no tracked closeout document changed, make no empty commit. Otherwise stage only the reviewed closeout paths, commit with `docs: record async AI local verification`, rerun `check_authority_contract.py --mode docs`, and require a clean worktree.

### Task 7: Build the local image, perform the live read-only gate, generate R4, and stop

**Files:**
- Create ignored: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R4_2026-08-17.json`
- Keep absent: `.tmp/AI_ENABLEMENT_RECEIPT_R4_2026-08-17.json`
- Keep absent: `.tmp/AI_ENABLEMENT_OBSERVATION_R4_2026-08-17.json`

**Interfaces:**
- Consumes: clean locally verified HEAD, linux/amd64 local image, exact R3 hosted baseline, exact prior attempts, and read-only Azure credentials.
- Produces: one owner-only 24-hour R4 package and its SHA-256; no Azure write or Key prompt.

- [ ] **Step 1: Final local preflight**

```bash
test "$(git branch --show-current)" = codex/ai-enable-preset-buttons
test -z "$(git status --short)"
test ! -e .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R4_2026-08-17.json
test ! -e .tmp/AI_ENABLEMENT_RECEIPT_R4_2026-08-17.json
test ! -e .tmp/AI_ENABLEMENT_OBSERVATION_R4_2026-08-17.json
git rev-parse HEAD
git rev-parse HEAD^{tree}
.venv/bin/python scripts/check_authority_contract.py --mode docs
```

Stop if any check differs. Do not remove or overwrite an existing R4 path.

- [ ] **Step 2: Build and inspect the exact local image**

```bash
CANDIDATE=$(git rev-parse HEAD)
IMAGE_INPUT=$(.venv/bin/python -c 'from scripts.create_release_manifest import committed_image_input_sha256; import subprocess; sha=subprocess.check_output(["git","rev-parse","HEAD"], text=True).strip(); print(committed_image_input_sha256(sha))')
LOCAL_IMAGE="newcaostone-local:${CANDIDATE:0:12}"
docker buildx build --platform linux/amd64 \
  --build-arg SOURCE_REVISION="$CANDIDATE" \
  --build-arg IMAGE_INPUT_SHA256="$IMAGE_INPUT" \
  --load -t "$LOCAL_IMAGE" .
docker image inspect "$LOCAL_IMAGE"
```

Require linux/amd64, user `bizpulse`, exact revision label, and exact image-input label. This is a local build only; do not login, tag for ACR, or push.

- [ ] **Step 3: Run the package generator's live gate and exclusive write**

```bash
.venv/bin/python scripts/create_ai_enablement_package.py \
  --output .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R4_2026-08-17.json \
  --receipt .tmp/AI_ENABLEMENT_RECEIPT_R4_2026-08-17.json \
  --observation .tmp/AI_ENABLEMENT_OBSERVATION_R4_2026-08-17.json \
  --subscription fc89e7d3-5428-425e-863f-415859810c2c \
  --tenant 13d04c38-d91c-4f9f-8b65-6af2b515dd63 \
  --resource-group rg-bizpulse-centralus \
  --location centralus \
  --app newcaostone-demo-app \
  --registry sellernorthbpacr \
  --log-workspace newcaostone-demo-logs \
  --registry-identity newcaostone-demo-registry \
  --rollback-revision newcaostone-demo-app--ai-off-ba92c00d-d4eb6e4 \
  --rollback-image sellernorthbpacr.azurecr.io/bizpulse@sha256:d4eb6e41e7643caf01ce6f615ef5d7a4333f6ab416e5a0ad7e0925cdc9d7958b \
  --rollback-registry-tag ai-5a6c199eacae-ba92c00d \
  --vault newcaostone-ai-kv \
  --identity newcaostone-ai-identity
```

This command must first perform the bounded nine Azure reads. It creates the package only if online latest/latest-ready/image/AI/identity/replica/ACR/workspace/vault/UAMI state and the after-read workspace snapshot all match. Any drift prints a stable failure code and leaves all three R4 paths absent.

- [ ] **Step 4: Validate the generated package and stop**

```bash
stat -f '%Lp %z %N' .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R4_2026-08-17.json
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R4_2026-08-17.json
jq '{schema_version,issued_at,expires_at,repository,azure_target,artifacts,prepackage_gate,cost_cap}' \
  .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R4_2026-08-17.json
test ! -e .tmp/AI_ENABLEMENT_RECEIPT_R4_2026-08-17.json
test ! -e .tmp/AI_ENABLEMENT_OBSERVATION_R4_2026-08-17.json
git status --short
```

Expected: package mode `600`, schema v2, 24-hour expiry, clean tracked status, and absent R4 receipt/observation. Scan the package for prohibited Key/Bearer/prompt/user/database/connection values. Report exact branch, HEAD, tree, package path, expiry, SHA-256, local test results, Azure read-only projection, budget, and failure recovery.

Stop without invoking `scripts/run_ai_enablement.py`. Do not ask for the API Key yet. The only next execution gate is:

```text
批准执行 AI Enablement R4 SHA256：<exact-sha256>
```

## Final Self-Review Checklist

- [ ] Every behavior change began with a failing test and has a focused commit.
- [ ] A PATCH is sent once; its response is acknowledgement, never hosted convergence proof.
- [ ] Every transition is bounded to 120 seconds, five-second polling, 25 app reads, 25 revision reads, and zero PATCH retries.
- [ ] Only predecessor/target profiles and revisions are tolerated; third/partial/failed/unhealthy states stop.
- [ ] Enabled rehearsals reconcile before browser execution; disabled recovery reconciles before completion.
- [ ] Emergency placeholder overwrite is attempted even when disabled reconciliation fails; no second disable PATCH occurs.
- [ ] Normal success remains AI-enabled for the public Demo; only failure triggers emergency disable.
- [ ] Receipts/observations contain counts and duration but no Key, token, raw prompt, user/store data, raw response, stdout, stderr, or exception text.
- [ ] R1/R2/R3 and D3 artifacts remain exact and replay-protected.
- [ ] Six bilingual presets, manual Send, draft confirmation, audit quartet, disabled zero-request, scope, permissions, and budget limits pass unchanged.
- [ ] Package creation performs live Azure reads immediately before its exclusive write and refuses drift without creating a file.
- [ ] R4 receipt and observation remain absent until a separately approved execution.
- [ ] No Azure mutation, registry publication, public browser request, Key prompt, paid OpenAI request, push, PR, CI, DNS, or deployment occurred during planning/local implementation/package generation.
