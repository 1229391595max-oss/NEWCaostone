# Deployed Diagnostic D2 Response Compatibility and Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the Azure collection-response contract and D1 evidence defects, prove the 234-commit implementation line integrates safely with current `main`, and generate a new owner-only D2 package without executing it.

**Architecture:** Keep the bounded `az rest` observer and one-shot runner. Make response projection tolerant only where Azure requires it, carry safe stage/role context through every read, and wrap evidence persistence with explicit consumed-failure semantics. Merge into an isolated branch from `main`, resolve the two predicted authority-document conflicts in favor of the newer implementation state, then bind D2 to that exact integration HEAD.

**Tech Stack:** Python 3.12, pytest, Azure CLI core `az rest`, Bicep 0.46.1, Git worktrees, owner-only JSON evidence, `verify_changed.py`.

## Global Constraints

- Implementation baseline: `5db9c6f1a7487734167fdb8128b68665d79c4a00`; never use the deployed SHA as the changed-path baseline.
- Current `main`: `ef78397d6cc9b110c4a1f969e0c4109b0b400f47`; merge base: `15a581fab1a0f27a59e3476572fdbaf8aad7220e`.
- D1 package SHA `8b05ef98021b7111aa556d39342270425b10c35b7976bda5b065540ccf1a73af` and receipt SHA `386a7ef0d83129f01842150e466dcfc96e9d9dec42d3a3447980395109b12bc5` are consumed and immutable.
- Never invoke D1 or D2 during implementation. No Azure, registry, Keychain, public URL, AI, paid provider, push, PR, CI, DNS, or deployment action is authorized.
- Preserve HTTPS `GET`, `management.azure.com`, API `2024-03-01`, zero retries, 30 seconds/request, one MiB/page, five pages/collection, 30 requests, and eight MiB total.
- Never serialize raw ARM bodies, stdout, stderr, URLs, resource names, credentials, tokens, or exception text.
- Local completion is not Hosted verified, Azure accepted, recovery success, AI availability, or Production ready.
- Use `apply_patch` for tracked edits and preserve unrelated user work.

---

### Task 1: Accept Azure terminal collection pages

**Files:**
- Modify: `bizpulse/tests/hosted/test_observe_deployed_release_state.py`
- Modify: `bizpulse/scripts/observe_deployed_release_state.py:290`

**Interfaces:**
- Consumes: `ArmScope`, `ReadBudget`, `ArmPage`, injected subprocess runner.
- Produces: `read_arm_collection` returning `Sequence[ArmPage]` with required list `value`, optional `nextLink`, and ignored safe top-level additions.

- [ ] **Step 1: Write failing response-shape tests**

Add:

```python
@pytest.mark.parametrize(
    "payload",
    (
        {"value": []},
        {"nextLink": None, "value": []},
        {"count": 0, "value": []},
    ),
)
def test_arm_collection_accepts_azure_terminal_page_shapes(
    continuation: dict[str, object], payload: dict[str, object]
) -> None:
    arm = _arm(continuation)
    path = arm["allowed_resource_paths"][1]
    budget = ReadBudget.from_limits(arm)
    pages = read_arm_collection(
        _url(path),
        scope=_scope(continuation),
        budget=budget,
        runner=_runner([payload], []),
    )
    assert len(pages) == 1
    assert pages[0].payload["value"] == []
    assert budget.request_count == 1
```

Add a rejection test covering `{"nextLink": None}`, non-list `value`, numeric `nextLink`, and empty-string `nextLink`. Keep cross-host/path/query and budget tests unchanged. Replace the old assertion that `{"value": []}` is incomplete.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py \
  -k 'azure_terminal_page_shapes or invalid_next_link' -q
```

Expected: missing-`nextLink` and extra-field cases fail under the exact-key check.

- [ ] **Step 3: Implement the compatible projection**

Replace the exact-key block with:

```python
        if not isinstance(page.payload, Mapping) or "value" not in page.payload:
            raise _invalid("diagnostic_arm_response_invalid")
        rows = page.payload["value"]
        next_link = page.payload.get("nextLink")
        if not isinstance(rows, list) or not (
            next_link is None
            or (isinstance(next_link, str) and bool(next_link))
        ):
            raise _invalid("diagnostic_arm_response_invalid")
```

Do not change URL restrictions, budgets, duplicate-key rejection, full response secret scanning, or sanitized output.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py \
  -k 'arm_collection or arm_pagination' -q
git add tests/hosted/test_observe_deployed_release_state.py \
  scripts/observe_deployed_release_state.py
git commit -m "fix: accept azure terminal collection pages"
```

### Task 2: Preserve safe read provenance

**Files:**
- Modify: `bizpulse/tests/hosted/test_observe_deployed_release_state.py`
- Modify: `bizpulse/tests/hosted/test_run_deployed_release_diagnostic.py`
- Modify: `bizpulse/scripts/observe_deployed_release_state.py`

**Interfaces:**
- Consumes: Task 1 behavior and existing safe enums.
- Produces: keyword-only `stage: str = "local"` and `role: str = "local"` on request/collection helpers and accurate receipt provenance.

- [ ] **Step 1: Write failing helper and receipt tests**

Add a revisions helper test that supplies `stage="revision"` and `role="revision"` to `read_arm_collection` with `{"nextLink": 7, "value": []}` and asserts code `diagnostic_arm_response_invalid`, stage `revision`, role `revision`. Add flow tests where the prepare Job resource and executions return invalid JSON; assert `job/prepare` and `execution/prepare`.

Add a runner test that succeeds on application, fails on malformed revisions, then asserts:

```python
assert receipt["failure"] == {
    "code": "diagnostic_arm_response_invalid",
    "resource_role": "revision",
    "stage": "revision",
}
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py \
  -k 'provenance or safe_context' -q
```

Expected: helpers reject new keywords or record `local/local`.

- [ ] **Step 3: Add context to every read boundary**

Change `read_arm_page` to accept keyword-only `stage: str = "local"` and
`role: str = "local"` after `runner`. Change `read_arm_collection` to accept
the same two keyword-only parameters after `limits`.

Extend `ArmScope.validate_request`, `ReadBudget.reserve_request`, `ReadBudget.record_bytes`, and `_resource_page` with the same context. In `collect_arm_payloads` map application to `application/application`, revisions to `revision/revision`, each Job to `job/<role>`, and executions to `execution/<role>`.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py -q
git add tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py \
  scripts/observe_deployed_release_state.py
git commit -m "fix: preserve deployed read failure context"
```

### Task 3: Finalize evidence safely and record real completion time

**Files:**
- Modify: `bizpulse/tests/hosted/test_run_deployed_release_diagnostic.py`
- Modify: `bizpulse/scripts/run_deployed_release_diagnostic.py`

**Interfaces:**
- Consumes: Task 2 contextual errors.
- Produces: an executor with `completion_clock: Callable[[], datetime] = _utc_now` and safe persistence wrappers.

- [ ] **Step 1: Write failing lifecycle tests**

Pass `completion_clock=lambda: parse_utc("2026-08-16T23:30:08Z")` to success and assert start `23:30:00Z` and completion `23:30:08Z`. Do the same for failure at `23:30:03Z` and add a naïve-clock rejection.

Add tests that initial receipt creation `OSError` makes zero ARM calls; observation creation/readback `OSError` leaves a safe failed receipt; final receipt replacement failure remains consumed. Assert injected bearer/password strings are absent.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_run_deployed_release_diagnostic.py \
  -k 'completion_time or persistence or observation_write' -q
```

- [ ] **Step 3: Implement clock and persistence wrappers**

Add:

```python
def _utc_now() -> datetime:
    return datetime.now(UTC)

def _finished_at(
    clock: Callable[[], datetime], *, started_at: datetime
) -> datetime:
    value = clock()
    if value.tzinfo is None:
        raise _invalid("diagnostic_execution_failed", stage="execution", role="local")
    value = value.astimezone(UTC)
    if value < started_at:
        raise _invalid("diagnostic_execution_failed", stage="execution", role="local")
    return value

def _write_evidence_exclusive(path: Path, payload: object) -> None:
    try:
        write_owner_json_exclusive(path, payload)
    except OSError as error:
        raise _invalid(
            "diagnostic_observation_write_failed",
            stage="observation",
            role="local",
        ) from error
```

Add:

```python
def _replace_evidence_atomic(path: Path, payload: object) -> None:
    try:
        replace_owner_json_atomic(path, payload)
    except OSError as error:
        raise _invalid(
            "diagnostic_observation_write_failed",
            stage="observation",
            role="local",
        ) from error
```

Use both wrappers for receipt progress, observation creation, and finalization. Convert observation read/hash `OSError` to `diagnostic_observation_write_failed`. Capture `_finished_at` independently on success and handled failure.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_run_deployed_release_diagnostic.py -q
git add tests/hosted/test_run_deployed_release_diagnostic.py \
  scripts/run_deployed_release_diagnostic.py
git commit -m "fix: finalize diagnostic evidence safely"
```

### Task 4: Bind successor tooling to D2 integration

**Files:**
- Modify: `bizpulse/tests/release/test_deployed_release_diagnostic_package.py`
- Modify: `bizpulse/scripts/create_deployed_release_diagnostic_package.py`
- Create: `bizpulse/docs/operations/DEPLOYED_RELEASE_DIAGNOSTIC_D2.md`

**Interfaces:**
- Consumes: repaired control closure.
- Produces: schema-v1 D2 package bound only to `codex/integrated-viewer-ai-anti-drift-d2-integration`.

- [ ] **Step 1: Write failing identity tests**

Set the repository fixture branch to the integration branch, rename writer output to `D2.md`, assert the D2 header and `D2_ENTRYPOINTS`, and prove the old implementation branch is rejected.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/release/test_deployed_release_diagnostic_package.py -q
```

- [ ] **Step 3: Implement exact D2 identity**

```python
HEADER = "# NEWCaostone Deployed Release Diagnostic D2 Authorization"
PACKAGE_SCHEMA = "newcaostone.deployed-release-diagnostic-package.v1"
AUTHORIZED_BRANCH = "codex/integrated-viewer-ai-anti-drift-d2-integration"
D2_ENTRYPOINTS = (
    "scripts/build_deployed_release_desired_projection.py",
    "scripts/create_deployed_release_diagnostic_package.py",
    "scripts/observe_deployed_release_state.py",
    "scripts/run_deployed_release_diagnostic.py",
)
```

Use `AUTHORIZED_BRANCH` in repository collection/loading and `D2_ENTRYPOINTS` for control discovery. Accept no fallback branch.

- [ ] **Step 4: Write runbook, verify, and commit**

Document D2 package/receipt/observation/continuation paths, local generation, exact-SHA approval, zero retry, any-receipt-consumes, and claim boundary. Preserve the D1 runbook.

```bash
.venv/bin/pytest tests/release/test_deployed_release_diagnostic_package.py \
  tests/hosted/test_run_deployed_release_diagnostic.py -q
.venv/bin/python scripts/create_deployed_release_diagnostic_package.py --help >/dev/null
git add tests/release/test_deployed_release_diagnostic_package.py \
  scripts/create_deployed_release_diagnostic_package.py \
  docs/operations/DEPLOYED_RELEASE_DIAGNOSTIC_D2.md
git commit -m "docs: bind deployed diagnostic d2 package"
```

### Task 5: Close D1 and verify implementation branch

**Files:**
- Create: `bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d1-failure.md`
- Modify: `CURRENT_STATUS.md`, `NEXT_AI_HANDOFF.md`, `docs/handoffs/CURRENT_HANDOFF.md`

**Interfaces:**
- Consumes: immutable D1 receipt and Tasks 1-4.
- Produces: current no-replay authority and verified implementation candidate.

- [ ] **Step 1: Revalidate D1 locally**

```bash
stat -f '%Lp %z %N' .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json
shasum -a 256 .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json
jq '{status,completed_reads,completed_resource_roles,failure,observation}' \
  .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_OBSERVATION.json
```

Expected: mode `600`, exact receipt SHA, failed after application, no observation.

- [ ] **Step 2: Record safe closeout**

State: D1 executed once and is consumed; both `az rest` commands exited 0; revisions parsing failed locally; no observation exists; deployed health is not disproved; D2 grants no Azure authority. Include both D1 SHAs and remove no historical evidence.

- [ ] **Step 3: Run all implementation gates**

```bash
.venv/bin/pytest tests/infra/test_deployed_release_bicep_projection.py \
  tests/release/test_deployed_release_diagnostic_package.py \
  tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py -q
.venv/bin/ruff check scripts/observe_deployed_release_state.py \
  scripts/run_deployed_release_diagnostic.py \
  scripts/create_deployed_release_diagnostic_package.py \
  tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py \
  tests/release/test_deployed_release_diagnostic_package.py
.venv/bin/python -m compileall -q scripts tests/hosted tests/release
az bicep build --file infra/modules/app.bicep --stdout >/dev/null
.venv/bin/python scripts/check_authority_contract.py --mode docs
.venv/bin/python scripts/verify_changed.py \
  --base 5db9c6f1a7487734167fdb8128b68665d79c4a00 --no-reuse
git diff --check "$(git merge-base 5db9c6f1a7487734167fdb8128b68665d79c4a00 HEAD)" HEAD
```

Run the exact checked-in `release_static` command without copying or drifting its argv:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
import subprocess

from scripts.select_required_checks import load_verification_policy

policy = load_verification_policy(Path("release/verification-policy.json"))
raise SystemExit(subprocess.run(policy.check("release_static").argv).returncode)
PY
```

Expected: PASS and `verification_changed=passed`.

- [ ] **Step 4: Commit closeout**

```bash
git add docs/operations/2026-08-16-deployed-diagnostic-d1-failure.md \
  ../CURRENT_STATUS.md ../NEXT_AI_HANDOFF.md \
  ../docs/handoffs/CURRENT_HANDOFF.md
git commit -m "docs: close failed deployed diagnostic d1"
test -z "$(git status --short)"
```

### Task 6: Build authority-aware integration candidate

**Files:**
- Create branch/worktree: `codex/integrated-viewer-ai-anti-drift-d2-integration`
- Resolve: `NEXT_AI_HANDOFF.md` and `docs/superpowers/specs/2026-08-15-bizpulse-integrated-viewer-ai-experience-design.md`
- Create: `bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d2-integration.md`
- Modify: three current authority files.

**Interfaces:**
- Consumes: clean `main` and Task 5 HEAD.
- Produces: clean verified integration HEAD/tree.

- [ ] **Step 1: Verify/classify Git graph**

```bash
git -C /Users/maxli/Desktop/NEWCaostone status --short
git status --short
git rev-parse main
git merge-base main HEAD
git rev-list --left-right --count main...HEAD
git cherry -v HEAD main
```

Expected: five `-` patch-equivalent commits (`f1b32d8`, `d311852`, `55d9a4f`, `669ed7a`, `db3defc`) and one `+` `ef78397`, superseded by newer recovery/D1/D2 handoff.

- [ ] **Step 2: Create worktree and runtime links**

```bash
git worktree add -b codex/integrated-viewer-ai-anti-drift-d2-integration \
  /Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift-d2-integration main
ln -s /Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift/bizpulse/.venv \
  /Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift-d2-integration/bizpulse/.venv
ln -s /Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift/bizpulse/node_modules \
  /Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift-d2-integration/bizpulse/node_modules
```

- [ ] **Step 3: Merge and resolve exactly two conflicts**

```bash
git merge --no-ff codex/integrated-viewer-ai-anti-drift \
  -m "merge: integrate viewer AI and diagnostic D2"
git checkout --theirs NEXT_AI_HANDOFF.md
git checkout --theirs \
  docs/superpowers/specs/2026-08-15-bizpulse-integrated-viewer-ai-experience-design.md
git add NEXT_AI_HANDOFF.md \
  docs/superpowers/specs/2026-08-15-bizpulse-integrated-viewer-ai-experience-design.md
git commit --no-edit
```

Expected: exactly those add/add conflicts. Stop on any other path. “Theirs” is the newer implementation handoff and v1.1 design.

- [ ] **Step 4: Verify integration**

Run the integration gates explicitly:

```bash
.venv/bin/pytest tests/infra/test_deployed_release_bicep_projection.py \
  tests/release/test_deployed_release_diagnostic_package.py \
  tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py -q
.venv/bin/python - <<'PY'
from pathlib import Path
import subprocess

from scripts.select_required_checks import load_verification_policy

policy = load_verification_policy(Path("release/verification-policy.json"))
raise SystemExit(subprocess.run(policy.check("release_static").argv).returncode)
PY
.venv/bin/ruff check scripts/observe_deployed_release_state.py \
  scripts/run_deployed_release_diagnostic.py \
  scripts/create_deployed_release_diagnostic_package.py \
  tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py \
  tests/release/test_deployed_release_diagnostic_package.py
.venv/bin/python -m compileall -q scripts tests/hosted tests/release
az bicep build --file infra/modules/app.bicep --stdout >/dev/null
.venv/bin/python scripts/check_authority_contract.py --mode docs
```

Then run:

```bash
.venv/bin/python scripts/verify_changed.py \
  --base ef78397d6cc9b110c4a1f969e0c4109b0b400f47 --no-reuse
git diff --check "$(git merge-base ef78397d6cc9b110c4a1f969e0c4109b0b400f47 HEAD)" HEAD
```

- [ ] **Step 5: Record and commit exact integration evidence**

Capture literal HEAD/tree/parents, left-right count, cherry classification, commands, and results. Record them in the integration report and authority files with “D2 not generated or executed”.

```bash
git add bizpulse/docs/operations/2026-08-16-deployed-diagnostic-d2-integration.md \
  CURRENT_STATUS.md NEXT_AI_HANDOFF.md docs/handoffs/CURRENT_HANDOFF.md
git commit -m "docs: record deployed diagnostic d2 integration"
cd bizpulse
.venv/bin/python scripts/check_authority_contract.py --mode docs
.venv/bin/python scripts/verify_changed.py \
  --base ef78397d6cc9b110c4a1f969e0c4109b0b400f47 --no-reuse
test -z "$(git status --short)"
```

### Task 7: Generate D2 locally and stop

**Files:**
- Create ignored: `bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md`
- Keep absent: D2 receipt and observation.

**Interfaces:**
- Consumes: clean verified Task 6 HEAD.
- Produces: owner-only D2 identity, no Azure request.

- [ ] **Step 1: Final preflight**

```bash
test "$(git branch --show-current)" = codex/integrated-viewer-ai-anti-drift-d2-integration
test -z "$(git status --short)"
test ! -e .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_ATTEMPT_RECEIPT.json
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_OBSERVATION.json
git rev-parse HEAD
git rev-parse HEAD^{tree}
.venv/bin/python scripts/check_authority_contract.py --mode docs
```

- [ ] **Step 2: Generate and validate D2**

```bash
.venv/bin/python scripts/create_deployed_release_diagnostic_package.py \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --continuation-reference release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --output .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md \
  --expires-hours 24
stat -f '%Lp %z %N' .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_ATTEMPT_RECEIPT.json
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_OBSERVATION.json
git status --short
```

Expected: mode `600`, matching SHA, absent receipt/observation, clean tracked status. Report exact branch, HEAD, tree, package path, authorization ID, expiry, SHA, tests, D1 no-replay boundary, and D2 unexecuted. Do not invoke `run_deployed_release_diagnostic.py` or `az rest`.

## Final Self-Review Checklist

- [ ] Every behavior starts with a failing test.
- [ ] Missing/null `nextLink` terminate; malformed values and malicious links fail closed.
- [ ] Unknown fields never reach observation.
- [ ] Failures carry safe stage/role.
- [ ] Initial write failure makes zero ARM calls; later failures remain consumed.
- [ ] Completion time is later than start.
- [ ] D1 remains immutable and is never replayed.
- [ ] Five main commits are patch-equivalent; `ef78397` is reconciled against newer authority.
- [ ] Integration uses only the new branch; `main` is not moved.
- [ ] Only two predicted conflicts resolve to newer implementation content.
- [ ] Both branches pass no-reuse verification with non-deployed baselines.
- [ ] D2 is generated from clean integration and remains unexecuted.
