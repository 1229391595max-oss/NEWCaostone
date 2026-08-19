# BizPulse Deployed Release Recovery V6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Retire the approved-but-failed V5 attempt, correct its authority records, accept Azure-owned scale defaults without weakening the `1/1` replica contract, and generate one locally verified AI-disabled V6 package that stops for a new exact-SHA approval.

**Architecture:** Preserve the immutable deployed continuation and all V5 security boundaries. Change only the deployed-state verifier's scale comparison from whole-object equality to exact typed checks of the two BizPulse-owned bounds, record the V5 pre-receipt failure before any successor generation, and rotate the package title/control hashes to V6. V6 keeps the same eight pending stages and one-shot runner; it cannot reuse V5's approval.

**Tech Stack:** Python 3.12, pytest, Ruff, Azure CLI argument arrays, JSON/Markdown authority records, macOS owner-only files, Git.

## Global Constraints

- Work only in `/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift`; `/Users/maxli/Desktop/CAPTSONE` remains read-only.
- Begin from approved V6 design commit `bc0e6cf2825d68d0be3465322d80072d555c4d43` on branch `codex/integrated-viewer-ai-anti-drift`.
- Keep development anchor `3e4cc229245cf32a13623da23eaa9685e176a82b`, deployed compare-only anchor `537effe3036f77f83225beef12589bd447205a8b`, changed-path base `16f5220`, and handoff tag target `db3defce15daf5d92d91e41a8062cbbb23053b3a` distinct.
- V5 SHA-256 `656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab` was approved and invoked once. Retire it; do not rerun it or manually resume a V5 child command.
- V5 stopped after one successful `containerapp show`, before revision, Job, registry, Keychain, health, browser, capacity, expiry, restart or rollback work. Its execution receipt remains absent.
- Do not update `release/current_authority.json` in this narrow repair. Its observation is expired; docs-mode contract success is not fresh Azure evidence.
- During Tasks 1–5, do not access Azure, registry, Keychain, the public URL, OpenAI or any paid provider. Do not deploy, start/bind a Job, migrate, seed, restart or roll back.
- Keep AI disabled. V6 contains no OpenAI Key, AI enablement, model qualification or paid-provider command.
- Use `apply_patch` for edits, TDD red-green for code behavior, small local commits and no push, PR, CI or deployment.
- Package generation grants no execution authority. Stop and request approval of the exact V6 SHA-256; never execute V6 in the generation turn.

---

### Task 1: Correct V5 incident and authority records before code changes

**Files:**
- Create: `bizpulse/docs/operations/2026-08-16-recovery-v5-readonly-preflight-failure.md`
- Modify: `bizpulse/docs/operations/2026-08-16-recovery-v5-package.md`
- Modify: `CURRENT_STATUS.md`
- Modify: `NEXT_AI_HANDOFF.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`

**Interfaces:**
- Consumes: V5 package SHA, controller output `deployed_execution_readonly_stage_failed`, Azure command log boundary, sanitized scale readback and absent V5 receipt.
- Produces: one tracked non-authorizing failure record and current handoffs that uniformly retire V5 before V6 code/package work.

- [ ] **Step 1: Re-run the local authority and identity preflight**

Run from `bizpulse/`:

```bash
git status --short
git branch --show-current
git rev-parse HEAD
git rev-parse 3e4cc229245cf32a13623da23eaa9685e176a82b
git rev-parse 537effe3036f77f83225beef12589bd447205a8b
git rev-parse handoff/integrated-viewer-ai-anti-drift-v1^{}
.venv/bin/python scripts/check_authority_contract.py --mode docs
.venv/bin/python scripts/check_authority_contract.py --mode release
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md
test ! -e .tmp/RECOVERY_V5_EXECUTION_RECEIPT.json
```

Expected:

- worktree clean, branch and four Git identities exact;
- docs mode prints `authority_contract=ok`;
- release mode fails only with `authority_observation_stale` because
  `release/current_authority.json` is an expired observation;
- V5 SHA matches the approved value and the V5 receipt is absent.

- [ ] **Step 2: Write the immutable V5 pre-receipt failure record**

Create the file with this exact evidence boundary:

```markdown
# Recovery V5 Read-Only Preflight Failure — 2026-08-16

Status: V5 approved once, invoked once, stopped before receipt and retired.

## Bound package

- Package: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md`
- SHA-256: `656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab`
- Authorization ID: `75bbbbb4-69e9-4b38-921e-08f64b0bd6cf`
- Controller result: `deployed_execution_readonly_stage_failed`
- V5 execution receipt: absent

## Exact stop boundary

The first Azure `containerapp show` returned exit code `0`. The local
deployed-state verifier then stopped before revision, Job, registry, Keychain,
health, browser, capacity, expiry, restart or rollback work.

The app retained the approved candidate image/revision, 100% traffic,
single-revision mode, external ingress, AI-disabled environment and replica
bounds `minReplicas=1`, `maxReplicas=1`. Azure also returned platform-owned
defaults `cooldownPeriod=300`, `pollingInterval=30` and `rules=null`. V5
incorrectly compared the whole scale mapping with only the two approved bounds.

No Keychain item or OpenAI Key was read. No paid request or Azure mutation was
made. V5 is retired and must not be replayed or manually resumed.
```

- [ ] **Step 3: Correct every current V5 statement**

Use `apply_patch` so all four current records say:

```markdown
V5 was separately approved and invoked once. It stopped during
`deployed_preflight` after a successful application read and before revision,
Job, registry, Keychain or hosted-acceptance work. The V5 receipt is absent,
but V5 is retired and grants no replay or manual-resume authority. The failure
was caused by whole-object comparison against Azure-owned scale defaults; the
approved `minReplicas=1` and `maxReplicas=1` values did not drift.
```

Update the V5 package operation record's status from `not approved or executed`
to `approved and invoked once; retired after read-only preflight failure`, and
replace its future execution command with a no-replay pointer to the new
failure record.

- [ ] **Step 4: Prove the authority correction is internally coherent**

Run:

```bash
rg -n "not approved|not executed|approval pending" \
  ../CURRENT_STATUS.md ../NEXT_AI_HANDOFF.md \
  ../docs/handoffs/CURRENT_HANDOFF.md \
  docs/operations/2026-08-16-recovery-v5-package.md
.venv/bin/python scripts/check_authority_contract.py --mode docs
git diff --check
```

Expected: `rg` has no match, docs mode prints `authority_contract=ok`, and
`git diff --check` emits no output. Do not require release mode to pass because
the machine observation remains deliberately stale.

- [ ] **Step 5: Commit the V5 incident correction**

```bash
git add docs/operations/2026-08-16-recovery-v5-readonly-preflight-failure.md \
  docs/operations/2026-08-16-recovery-v5-package.md \
  ../CURRENT_STATUS.md ../NEXT_AI_HANDOFF.md \
  ../docs/handoffs/CURRENT_HANDOFF.md
git commit -m "docs: retire failed recovery v5 preflight"
```

---

### Task 2: Accept Azure-owned scale defaults while preserving exact bounds

**Files:**
- Modify: `bizpulse/tests/hosted/test_verify_deployed_release_state.py`
- Modify: `bizpulse/scripts/verify_deployed_release_state.py`

**Interfaces:**
- Consumes: Azure scale mapping with platform-added keys.
- Produces: `_verify_candidate_app(payload: object, continuation: dict[str, Any]) -> None` that requires an object scale and exact integer `minReplicas=1`, `maxReplicas=1`, while ignoring additional keys.

- [ ] **Step 1: Add the Azure-default regression test first**

Add:

```python
def test_deployed_state_accepts_azure_owned_scale_defaults() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    app = reader.responses[("app", continuation["target"]["application"])]
    app["properties"]["template"]["scale"].update(
        {
            "cooldownPeriod": 300,
            "pollingInterval": 30,
            "rules": None,
        }
    )

    result = subject.verify_deployed_release_state(
        continuation,
        reader=reader,
    )

    assert result == {"state": "deployed_awaiting_hosted_acceptance"}
```

- [ ] **Step 2: Run the regression test and confirm RED**

```bash
.venv/bin/pytest -q \
  tests/hosted/test_verify_deployed_release_state.py::test_deployed_state_accepts_azure_owned_scale_defaults
```

Expected: FAIL with `deployed_release_application_invalid` because V5 compares
the whole scale mapping.

- [ ] **Step 3: Add typed negative scale cases before implementation**

Add:

```python
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("minReplicas", 0),
        ("maxReplicas", 2),
        ("minReplicas", True),
        ("maxReplicas", "1"),
    ],
)
def test_deployed_state_rejects_replica_bound_drift(
    field: str,
    value: object,
) -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    app = reader.responses[("app", continuation["target"]["application"])]
    app["properties"]["template"]["scale"][field] = value

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_application_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)


def test_deployed_state_rejects_missing_scale_mapping() -> None:
    subject = _subject()
    continuation = deployed_continuation()
    reader = deployed_reader(continuation)
    app = reader.responses[("app", continuation["target"]["application"])]
    del app["properties"]["template"]["scale"]

    with pytest.raises(
        subject.DeployedReleaseStateInvalid,
        match="deployed_release_application_invalid",
    ):
        subject.verify_deployed_release_state(continuation, reader=reader)
```

Run the new negative tests and confirm they pass under the existing strict
comparison; the positive Azure-default test must remain red.

- [ ] **Step 4: Implement the minimal scale contract fix**

In `_verify_candidate_app`, derive and validate scale separately:

```python
    scale = template.get("scale")
    if not isinstance(scale, Mapping):
        raise DeployedReleaseStateInvalid(code)
```

Then replace only this old predicate inside the existing application condition:

```python
template.get("scale") != {"minReplicas": 1, "maxReplicas": 1}
```

with these exact predicates:

```python
type(scale.get("minReplicas")) is not int
or scale.get("minReplicas") != 1
or type(scale.get("maxReplicas")) is not int
or scale.get("maxReplicas") != 1
```

Do not change any other deployed app, revision, traffic, AI, Job or execution
validation.

- [ ] **Step 5: Run verifier tests and static checks**

```bash
.venv/bin/pytest -q tests/hosted/test_verify_deployed_release_state.py
.venv/bin/ruff check \
  scripts/verify_deployed_release_state.py \
  tests/hosted/test_verify_deployed_release_state.py
.venv/bin/python -m compileall -q scripts/verify_deployed_release_state.py
git diff --check
```

Expected: all tests pass, Ruff prints `All checks passed!`, compilation is
silent and diff check is clean.

- [ ] **Step 6: Commit the narrow verifier fix**

```bash
git add scripts/verify_deployed_release_state.py \
  tests/hosted/test_verify_deployed_release_state.py
git commit -m "fix: accept azure scale defaults in deployed verifier"
```

---

### Task 3: Rotate the generated recovery identity from V5 to V6

**Files:**
- Modify: `bizpulse/tests/release/test_deployed_release_recovery_package.py`
- Modify: `bizpulse/scripts/create_deployed_release_recovery_package.py`
- Modify: `bizpulse/scripts/run_deployed_release_recovery.py`

**Interfaces:**
- Consumes: corrected deployed verifier and unchanged deployed continuation.
- Produces: V6-titled owner-only package with the same schema, commands, one-shot runner interface and fresh hashes of all three control files.

- [ ] **Step 1: Change package expectations to V6 and confirm RED**

Rename V5-specific package test names to V6 and change the header assertion to:

```python
assert output.read_text().startswith(
    "# NEWCaostone Deployed Release Recovery V6 Authorization\n"
)
```

Run:

```bash
.venv/bin/pytest -q \
  tests/release/test_deployed_release_recovery_package.py::test_v6_package_contains_only_pending_stages_and_keychain_descriptors
```

Expected: FAIL because the builder still emits the V5 header.

- [ ] **Step 2: Rotate the header and controller descriptions only**

Change:

```python
HEADER = "# NEWCaostone Deployed Release Recovery V6 Authorization"
```

Update the builder module docstring to
`Create the owner-only V6 package for pending hosted acceptance only.` and the
runner docstring to
`Execute one approved V6 hosted-acceptance recovery without secret leakage.`

Keep these interfaces and values unchanged:

```python
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
```

Do not add a V5 compatibility loader or hash override.

- [ ] **Step 3: Run combined V6 control tests**

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

Expected: zero failures. The real-control-hash test must prove that the changed
builder, runner and verifier hashes reconstruct without monkeypatching.

- [ ] **Step 4: Commit the V6 identity rotation**

```bash
git add scripts/create_deployed_release_recovery_package.py \
  scripts/run_deployed_release_recovery.py \
  tests/release/test_deployed_release_recovery_package.py
git commit -m "chore: rotate deployed recovery package to v6"
```

---

### Task 4: Run the complete local V6 verification gates

**Files:**
- Modify only if a fresh failing test identifies a real local defect; use a new TDD cycle and separate commit.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: fresh local evidence that the exact V6 controls are valid before their hashes enter a package.

- [ ] **Step 1: Run focused V6 tests, Ruff and compilation**

Run the complete command block from Task 3 Step 3 again from a clean worktree.
Expected: zero failures and zero lint/compile errors.

- [ ] **Step 2: Run the exact release-static argv from policy**

```bash
.venv/bin/python -c 'import json, subprocess; from pathlib import Path; policy=json.loads(Path("release/verification-policy.json").read_text()); argv=policy["checks"]["release_static"]["argv"]; print("release_static_argv=" + json.dumps(argv)); raise SystemExit(subprocess.run(argv, check=False).returncode)'
```

Expected: the exact policy suite exits `0`, with only its declared skips.

- [ ] **Step 3: Run authority, selector and changed-path gates**

```bash
.venv/bin/pytest -q tests/release/test_select_required_checks.py
.venv/bin/python scripts/check_authority_contract.py --mode docs
.venv/bin/python scripts/verify_changed.py --base 16f5220 --no-reuse
git diff --check
git status --short
```

Expected: selector passes, `authority_contract=ok`,
`verification_changed=passed`, no diff-check output and a clean worktree.
Do not run release-mode authority as a success gate; its observation is known
expired and was deliberately not rewritten in this repair.

---

### Task 5: Generate V6 once, document it and stop at exact-SHA approval

**Files:**
- Create outside Git: `bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md`
- Reserve outside Git: `bizpulse/.tmp/RECOVERY_V6_EXECUTION_RECEIPT.json`
- Create: `bizpulse/docs/operations/2026-08-16-recovery-v6-package.md`
- Modify: `CURRENT_STATUS.md`
- Modify: `NEXT_AI_HANDOFF.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`

**Interfaces:**
- Consumes: verified V6 controls, the immutable deployed continuation and candidate attestation.
- Produces: one owner-only V6 package, updated non-authorizing handoffs and an exact user approval request. It does not execute V6.

- [ ] **Step 1: Prove clean one-time generation preconditions**

```bash
git status --short
test ! -e .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md
test ! -e .tmp/RECOVERY_V6_EXECUTION_RECEIPT.json
```

Expected: no Git output and both tests exit `0`. If either V6 file exists,
stop without overwriting or deleting it.

- [ ] **Step 2: Generate V6 exactly once without Azure or Keychain**

```bash
.venv/bin/python scripts/create_deployed_release_recovery_package.py \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --continuation-reference release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --release-attestation release/attestations/82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3.json \
  --attestation-git-sha c573f2be9d8d6414143fbeab2fa2af788caf4f19 \
  --expires-hours 24 \
  --output .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md
```

Expected: `deployed_recovery_package=ok`, one output path and one SHA-256. Do
not run this command a second time.

- [ ] **Step 3: Independently validate V6 identity and boundaries**

```bash
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md
stat -f '%Sp %Lp %Su:%Sg %z' \
  .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md
.venv/bin/python -c "from pathlib import Path; from scripts.create_deployed_release_recovery_package import load_deployed_release_recovery_package; p=load_deployed_release_recovery_package(Path('.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md'), continuation_path=Path('release/incidents/2026-08-16-recovery-v4-deployed-continuation.json')); assert p['no_ai'] is True; assert p['execution_order']==['deployed_preflight','registry_verify','health','browser_acceptance','capacity','expiry','restart_readback','rollback']; assert len(p['keychain_sources'])==2; print('v6_package_loader=passed'); print('authorization_id='+p['authorization_id']); print('issued_at='+p['issued_at']); print('expires_at='+p['expires_at'])"
test ! -e .tmp/RECOVERY_V6_EXECUTION_RECEIPT.json
```

Expected: independent SHA matches the generator, mode is `0600`, loader and
stage/credential assertions pass, and the V6 execution receipt remains absent.

- [ ] **Step 4: Write the immutable V6 package receipt and update handoffs**

Use `apply_patch`. Record the exact generated path, SHA-256, authorization ID,
issue time, expiry, `0600` mode, eight stages, retired V5 boundary, two
credential descriptors, AI-disabled state, verification counts and absent V6
receipt in `docs/operations/2026-08-16-recovery-v6-package.md`.

All three handoffs must contain this exact status meaning:

```markdown
V5 is retired after its approved read-only preflight failure. V6 is generated
and locally verified but is not approved or executed. Its receipt is absent.
Hosted health, browser, capacity, expiry, restart and rollback acceptance remain
pending; AI remains disabled and no OpenAI Key or paid request is involved.
```

Include the future one-shot command with the generated exact SHA, V6 package
path and `.tmp/RECOVERY_V6_EXECUTION_RECEIPT.json`, clearly labelled as
non-authorized until a separate exact-hash approval.

- [ ] **Step 5: Run final local verification and commit documentation**

```bash
.venv/bin/python scripts/check_authority_contract.py --mode docs
.venv/bin/python scripts/verify_changed.py --base 16f5220 --no-reuse
git diff --check
git add docs/operations/2026-08-16-recovery-v6-package.md \
  ../CURRENT_STATUS.md ../NEXT_AI_HANDOFF.md \
  ../docs/handoffs/CURRENT_HANDOFF.md
git commit -m "docs: prepare deployed recovery v6 handoff"
git status --short
```

Expected: authority and changed-path gates pass, commit succeeds and worktree is
clean. Re-run only local SHA/mode/loader/receipt-absence checks after the docs
commit; do not access Azure, registry, Keychain or the public URL.

- [ ] **Step 6: Stop and request exact approval**

Report the V6 path, authorization ID, expiry, independent SHA-256, verification
counts, AI-disabled state and absent receipt. Ask the user to reply with one
line formed by concatenating the literal prefix
`批准执行 V6 SHA256：` and the exact generated 64-character digest.

Do not execute V6 in the same turn that generates it.
