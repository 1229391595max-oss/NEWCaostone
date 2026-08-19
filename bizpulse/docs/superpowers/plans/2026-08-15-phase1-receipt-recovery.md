# Phase 1 Receipt Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for inline, task-by-task execution. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resume the currently private no-AI release from verified Phase 1 state and prevent future launch packages from using a stale local issue-time anchor.

**Architecture:** A receipt collector reads Azure only and records the exact private Phase 1 boundary. A narrow resume-authority generator binds that receipt, the original approved package, and the immutable release. The resume runner accepts only the generated SHA and executes the remaining hosted gates. Future Phase 1 package commands emit the same receipt so activation authority is always based on Azure observation rather than package creation time.

**Tech Stack:** Python 3.12, pytest, Azure CLI JSON read projections, existing `verify_phase1_fence.py`, existing launch authorization verifier.

## File Structure

- `scripts/phase1_receipt.py` owns canonical receipt construction, Azure read projections, receipt comparison, and mode-600 persistence.
- `tests/hosted/test_phase1_receipt.py` owns the legacy-boundary and receipt-persistence regressions.
- `scripts/generate_phase1_receipt_resume.py` owns exact source-and-receipt command derivation.
- `tests/hosted/test_phase1_receipt_resume.py` owns hash, release, no-AI, and forbidden-stage regressions.
- `docs/operations/PHASE1_RECEIPT_RELEASE.md` owns the future two-package operating sequence and the prohibition on continuing a static v3 source package past Phase 1.
- `.tmp/run_approved_phase1_receipt_resume.py` owns exact-SHA validation and sequential remote execution after fresh user approval.

## Global Constraints

- Do not mutate Azure while implementing or running local tests.
- Preserve candidate `537effe3036f77f83225beef12589bd447205a8b` and its existing image/attestation for the immediate recovery.
- All Azure reads use `--only-show-errors --output json` with a 30-second timeout.
- A receipt never contains a password, connection string, token, or raw Azure secret.
- Recovery stays no-AI: disabled AI, no OpenAI secret, no paid-AI command, and `openai_smoke_cap=0.00`.
- A new resume package SHA must be approved before any Azure command that writes state.

---

### Task 1: Collect and validate an Azure Phase 1 receipt

**Files:**

- Create: `scripts/phase1_receipt.py`
- Create: `tests/hosted/test_phase1_receipt.py`

**Interfaces:**

- Consumes: source release identity, Phase 1 ARM deployment projection, current app projection, revision list, four Job projections, and four execution-list projections.
- Produces:

```python
def collect_legacy_receipt(
    *,
    source_authority: dict[str, object],
    source_sha256: str,
    deployment: dict[str, object],
    app: dict[str, object],
    revisions: list[dict[str, object]],
    jobs: dict[str, dict[str, object]],
    executions: dict[str, list[dict[str, object]]],
    observed_at: datetime,
) -> dict[str, object]:
    pass


def write_receipt(path: Path, receipt: dict[str, object]) -> None:
    pass
```

- [ ] **Step 1: Write failing legacy-boundary tests**

```python
def test_collect_legacy_receipt_accepts_maintenance_before_phase1_boundary():
    receipt = collect_legacy_receipt(
        source_authority=SOURCE,
        source_sha256="a" * 64,
        deployment=phase1_deployment("2026-08-15T22:20:24Z"),
        app=private_candidate_app(),
        revisions=drained_revisions(),
        jobs=manual_candidate_jobs(),
        executions=executions(
            prepare=success("22:25:27Z"),
            seed=success("22:26:07Z"),
            sessions=success("22:15:00Z"),
            storage=success("22:00:00Z"),
        ),
        observed_at=datetime(2026, 8, 15, 22, 27, tzinfo=UTC),
    )
    assert receipt["phase1_anchor_at"] == "2026-08-15T22:20:24Z"


def test_collect_legacy_receipt_rejects_maintenance_after_phase1_boundary():
    execution_history = executions(
        prepare=success("22:25:27Z"),
        seed=success("22:26:07Z"),
        sessions=success("22:21:00Z"),
        storage=success("22:00:00Z"),
    )
    with pytest.raises(Phase1ReceiptInvalid, match="maintenance_after_anchor"):
        collect_legacy_receipt(
            source_authority=SOURCE,
            source_sha256="a" * 64,
            deployment=phase1_deployment("2026-08-15T22:20:24Z"),
            app=private_candidate_app(),
            revisions=drained_revisions(),
            jobs=manual_candidate_jobs(),
            executions=execution_history,
            observed_at=datetime(2026, 8, 15, 22, 27, tzinfo=UTC),
        )
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/hosted/test_phase1_receipt.py -q`
Expected: FAIL because `phase1_receipt` does not exist.

- [ ] **Step 3: Implement the bounded collector**

```python
def collect_legacy_receipt(
    *,
    source_authority: dict[str, object],
    source_sha256: str,
    deployment: dict[str, object],
    app: dict[str, object],
    revisions: list[dict[str, object]],
    jobs: dict[str, dict[str, object]],
    executions: dict[str, list[dict[str, object]]],
    observed_at: datetime,
) -> dict[str, object]:
    anchor = _require_succeeded_deployment_timestamp(deployment)
    _require_private_candidate_app(source_authority, app, revisions)
    _require_manual_candidate_jobs(source_authority, jobs)
    prepare = _require_one_succeeded_after(executions["prepare"], anchor, "prepare")
    seed = _require_one_succeeded_after(executions["seed"], anchor, "seed")
    _require_terminal_maintenance_before(executions["maintain-sessions"], anchor)
    _require_terminal_maintenance_before(executions["maintain-storage"], anchor)
    return _receipt_payload(
        source_authority=source_authority,
        source_sha256=source_sha256,
        deployment=deployment,
        anchor=anchor,
        app=app,
        jobs=jobs,
        prepare=prepare,
        seed=seed,
        observed_at=observed_at,
    )
```

The implementation rejects unknown execution statuses, missing timestamps,
non-candidate images, public ingress, non-zero replicas, duplicate qualifying
prepare/seed executions, and maintenance starts at or after the anchor.

- [ ] **Step 4: Add receipt-write boundary tests**

```python
def test_write_receipt_is_mode_600_and_rejects_noncanonical_payload(tmp_path):
    path = tmp_path / "phase1-receipt.json"
    write_receipt(path, valid_receipt())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == valid_receipt()
```

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/hosted/test_phase1_receipt.py -q`
Commit: `git add scripts/phase1_receipt.py tests/hosted/test_phase1_receipt.py && git commit -m 'feat: collect phase1 receipt authority'`.

### Task 2: Generate a hash-bound narrow resume package

**Files:**

- Create: `scripts/generate_phase1_receipt_resume.py`
- Create: `tests/hosted/test_phase1_receipt_resume.py`

**Interfaces:**

- Consumes: original launch authorization path/SHA, receipt path/SHA, and an injected UTC clock.
- Produces:

```python
def replace_not_before(command: str, anchor: str) -> str:
    pass


def derive_resume_commands(
    source_commands: dict[str, object],
    *,
    anchor: str,
    receipt_verify_command: str,
) -> dict[str, list[str]]:
    pass


def generate_resume_authority(
    *,
    source_path: Path,
    source_sha256: str,
    receipt_path: Path,
    receipt_sha256: str,
    issued_at: datetime,
) -> dict[str, object]:
    pass
```

- [ ] **Step 1: Write failing command and identity tests**

```python
def test_resume_package_uses_receipt_anchor_not_issue_time():
    authority = generate_resume_authority(
        source_path=SOURCE,
        source_sha256=SOURCE_SHA,
        receipt_path=RECEIPT,
        receipt_sha256=RECEIPT_SHA,
        issued_at=datetime(2026, 8, 15, 23, tzinfo=UTC),
    )
    assert "2026-08-15T22:20:24Z" in authority["commands"]["activate_fence"][0]
    assert "2026-08-15T23:00:00Z" not in authority["commands"]["activate_fence"][0]
    assert set(authority["commands"]) == set(RESUME_STAGES)
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/hosted/test_phase1_receipt_resume.py -q`
Expected: FAIL because the generator does not exist.

- [ ] **Step 3: Implement exact derivation**

```python
RESUME_STAGES = (
    "prepared_preflight", "registry_verify", "phase1_receipt",
    "activate_fence", "deploy", "health", "browser_acceptance",
    "capacity", "expiry", "restart_readback", "rollback",
)

def derive_resume_commands(
    source_commands: dict[str, object],
    *,
    anchor: str,
    receipt_verify_command: str,
) -> dict[str, list[str]]:
    activate = _commands(source_commands, "activate", 2)
    deploy = _commands(source_commands, "deploy", 4)
    return {
        "prepared_preflight": [activate[0]],
        "registry_verify": _commands(source_commands, "registry_verify", 2),
        "phase1_receipt": [receipt_verify_command],
        "activate_fence": [replace_not_before(activate[1], anchor)],
        "deploy": [deploy[0], deploy[1], deploy[2], replace_not_before(deploy[3], anchor)],
        "health": _commands(source_commands, "health", 1),
        "browser_acceptance": _commands(source_commands, "browser_acceptance", 1),
        "capacity": _commands(source_commands, "capacity", 1),
        "expiry": _commands(source_commands, "expiry", 1),
        "restart_readback": _commands(source_commands, "restart_readback", 1),
        "rollback": _commands(source_commands, "rollback", 1),
    }
```

Validate the source at its own issue time, require its no-AI declarations and
the source release to exactly equal the receipt release. The output records
source and receipt SHA-256 values, receipt ID, copied release authority,
receipt anchor, 24-hour expiry, exact derived commands, and a
`control_sha256` object that binds `scripts/phase1_receipt.py`,
`scripts/generate_phase1_receipt_resume.py`, and the ignored
`.tmp/run_approved_phase1_receipt_resume.py`. It excludes
registry publish, provision, migrate, and seed.

- [ ] **Step 4: Add rejection tests**

```python
@pytest.mark.parametrize("field", ["source_sha256", "receipt_sha256", "release"])
def test_resume_generator_rejects_identity_mismatch(field):
    with pytest.raises(ResumeAuthorityInvalid):
        generate_resume_authority(**tampered(field))
```

Also cover an AI-enabled source, a receipt after expiry, and a source command
set that includes a forbidden phase in the resume authority.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/hosted/test_phase1_receipt_resume.py -q`
Commit: `git add scripts/generate_phase1_receipt_resume.py tests/hosted/test_phase1_receipt_resume.py && git commit -m 'feat: derive phase1 receipt resume authority'`.

### Task 3: Lock the future two-package workflow without invalidating v3 authorities

**Files:**

- Create: `docs/operations/PHASE1_RECEIPT_RELEASE.md`
- Modify: `tests/hosted/test_phase1_receipt_resume.py`

**Interfaces:**

The existing `newcaostone.azure-demo-authorization.v3` schema and
`tests/hosted/verify_azure_demo.py` remain byte-compatible so the approved
source package can still be independently validated. The new receipt-resume
schema is a second authorization document produced only after Phase 1.

- [ ] **Step 1: Add a failing backward-compatibility regression**

```python
def test_receipt_resume_accepts_a_valid_v3_source_without_rewriting_it(tmp_path):
    source = write_valid_v3_source(tmp_path)
    before = source.read_bytes()

    authority = generate_resume_authority(
        source_path=source,
        source_sha256=hashlib.sha256(before).hexdigest(),
        receipt_path=write_valid_receipt(tmp_path),
        receipt_sha256=receipt_sha256(tmp_path),
        issued_at=datetime(2026, 8, 15, 23, 0, tzinfo=UTC),
    )

    assert source.read_bytes() == before
    assert authority["schema_version"] == "newcaostone.phase1-receipt-resume-authorization.v1"
    assert "--not-before 2026-08-15T22:20:24Z" in authority["commands"]["activate_fence"][0]
```

- [ ] **Step 2: Verify RED, then keep the v3 verifier unchanged**

Run: `.venv/bin/pytest tests/hosted/test_phase1_receipt_resume.py -k v3_source -q`

Expected: FAIL until Task 2's generator exists. The implementation must not
modify `tests/hosted/verify_azure_demo.py`, its expected command fields, or
the source authority document.

- [ ] **Step 3: Write the operating contract**

The document states this exact order:

1. Run the approved v3 package only through `provision`, `migrate`, and `seed`.
2. Stop before its static `activate` command.
3. Collect a Phase 1 receipt using the approved source SHA and Azure deployment completion time.
4. Generate a second, mode-600 receipt-resume document.
5. Obtain explicit approval for that document's exact SHA-256.
6. Execute only its remaining stages.

It also states that a v3 package `issued_at` is never a valid cloud fence,
that migration and seed must not be replayed after a valid receipt, and that
any receipt/source/current-state mismatch is a fail-closed stop.

- [ ] **Step 4: Verify and commit**

Run: `.venv/bin/pytest tests/hosted/test_phase1_receipt_resume.py tests/hosted/test_verify_azure_demo.py -q`

```bash
git add docs/operations/PHASE1_RECEIPT_RELEASE.md \
  tests/hosted/test_phase1_receipt_resume.py
git commit -m 'docs: require phase1 receipt activation packages'
```

### Task 4: Validate and run the approved recovery authority

**Files:**

- Create: `.tmp/run_approved_phase1_receipt_resume.py`
- Create: `.tmp/test_run_approved_phase1_receipt_resume.py`

**Interfaces:**

```python
def validate_resume_authority(
    *,
    authorization_path: Path,
    approved_sha256: str,
    source_path: Path,
    receipt_path: Path,
    now: datetime,
) -> dict[str, object]:
    pass


def environment_for_stage(
    stage: str,
    *,
    base_environment: dict[str, str],
    credential_loader: Callable[[], dict[str, str]],
) -> dict[str, str]:
    pass


def execute_resume(
    authority: dict[str, object],
    *,
    base_environment: dict[str, str],
    credential_loader: Callable[[], dict[str, str]],
    command_runner: Callable,
) -> None:
    pass
```

The runner consumes the exact approved resume SHA, source authorization,
receipt, and existing Keychain-only credential loader. It produces one
sequential execution of the resume-stage commands.

- [ ] **Step 1: Write failing runner validation and secret-scope tests**

```python
def test_runner_rejects_wrong_approved_hash_before_loading_keychain(monkeypatch, tmp_path):
    keychain_calls: list[str] = []
    monkeypatch.setattr(
        module,
        "load_deployment_credentials",
        lambda: keychain_calls.append("loaded") or {},
    )

    status = module.main([
        "--authorization", str(write_valid_resume_authority(tmp_path)),
        "--source-authorization", str(write_valid_source_authority(tmp_path)),
        "--receipt", str(write_valid_receipt(tmp_path)),
        "--approved-sha256", "0" * 64,
        "--validate-only",
    ])

    assert status == 1
    assert keychain_calls == []


def test_execute_resume_loads_deployment_values_only_for_deploy_and_browser():
    loaded: list[str] = []
    calls: list[tuple[str, dict[str, str]]] = []

    execute_resume(
        valid_resume_authority(),
        base_environment={"PATH": "/usr/bin"},
        credential_loader=lambda: loaded.append("loaded") or {
            "BIZPULSE_DEPLOY_POSTGRES_PASSWORD": "redacted",
            "BIZPULSE_BROWSER_OPERATOR_PASSWORD": "redacted",
        },
        command_runner=lambda command, **kwargs: calls.append((command[-1], kwargs["env"])) or completed(),
    )

    assert loaded == ["loaded"]
    assert any("BIZPULSE_DEPLOY_POSTGRES_PASSWORD" in env for name, env in calls if name == "deploy")
    assert all("BIZPULSE_DEPLOY_POSTGRES_PASSWORD" not in env for name, env in calls if name != "deploy")
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest .tmp/test_run_approved_phase1_receipt_resume.py -q`
Expected: FAIL because no receipt-resume runner exists.

- [ ] **Step 3: Implement stage-scoped execution**

```python
credential_cache: dict[str, dict[str, str]] = {}


def load_once() -> dict[str, str]:
    if "values" not in credential_cache:
        credential_cache["values"] = credential_loader()
    return credential_cache["values"]


for stage in RESUME_STAGES:
    authority = validate_resume_authority(
        authorization_path=authorization_path,
        approved_sha256=approved_sha256,
        source_path=source_path,
        receipt_path=receipt_path,
        now=datetime.now(UTC),
    )
    environment = environment_for_stage(
        stage,
        base_environment=base_environment,
        credential_loader=load_once,
    )
    for command in authority["commands"][stage]:
        command_runner(shlex.split(command), cwd=ROOT, env=environment, check=True)
```

The runner revalidates source SHA, receipt SHA, expiration, no-AI scope, and
exact commands before each stage. It has no registry publish, provision,
migrate, or seed branch.

- [ ] **Step 4: Verify local recovery artifacts**

Run:

```bash
.venv/bin/pytest .tmp/test_run_approved_phase1_receipt_resume.py \
  tests/hosted/test_phase1_receipt.py \
  tests/hosted/test_phase1_receipt_resume.py \
  tests/hosted/test_azure_preflight.py -q
.venv/bin/python -m ruff check scripts/phase1_receipt.py scripts/generate_phase1_receipt_resume.py
git diff --check
```

Expected: all listed tests pass, Ruff exits 0, and `git diff --check` has no output.

- [ ] **Step 5: Commit reusable implementation while keeping live artifacts local**

```bash
git add scripts/phase1_receipt.py scripts/generate_phase1_receipt_resume.py \
  tests/hosted/test_phase1_receipt.py \
  tests/hosted/test_phase1_receipt_resume.py \
  docs/operations/PHASE1_RECEIPT_RELEASE.md
git commit -m 'fix: resume launches from phase1 receipts'
```

Keep `.tmp/run_approved_phase1_receipt_resume.py` and its focused test under
the existing ignored `.tmp/` boundary. Bind their SHA-256 values inside the
generated resume authority and revalidate those hashes before every stage.
Never add either file to Git.

- [ ] **Step 6: Generate and validate the actual resume package**

Run a read-only Azure receipt collection against the current private Phase 1
state, generate the mode-600 resume document, validate its SHA and command
set locally, then stop for a new explicit approval. No Azure write occurs in
this step.

```bash
.venv/bin/python scripts/phase1_receipt.py collect \
  --source-authorization .tmp/LAUNCH_AUTHORIZATION_OBSERVED_CURRENT_V1.md \
  --source-sha256 e5ff124b8fc65481af3dbb7f8f7cf6188c36bcad9e7da3ee6b499897987bcb1e \
  --phase1-deployment newcaostone-demo-phase1 \
  --subscription fc89e7d3-5428-425e-863f-415859810c2c \
  --resource-group rg-bizpulse-centralus \
  --app newcaostone-demo-app \
  --prepare-job newcaostone-demo-prepare \
  --seed-job newcaostone-demo-seed \
  --session-job newcaostone-demo-sessions \
  --storage-job newcaostone-demo-storage \
  --output .tmp/phase1-receipt-78eaaf31.json
.venv/bin/python scripts/generate_phase1_receipt_resume.py \
  --source-authorization .tmp/LAUNCH_AUTHORIZATION_OBSERVED_CURRENT_V1.md \
  --source-sha256 e5ff124b8fc65481af3dbb7f8f7cf6188c36bcad9e7da3ee6b499897987bcb1e \
  --receipt .tmp/phase1-receipt-78eaaf31.json \
  --output .tmp/LAUNCH_AUTHORIZATION_PHASE1_RECEIPT_RESUME_V1.md
```

The script reports the new resume package SHA-256, expiry, source SHA,
receipt SHA, control-script SHA values, and stage names, then stops. It does
not call the recovery runner in this step. Never commit the generated receipt,
generated resume authority, deployment credential files, or Azure response
data.

## Plan Self-Review

- Spec coverage: Tasks 1–2 implement the current legacy recovery; Task 3
  prevents future issue-time anchors without changing v3 source authority;
  Task 4 preserves exact approval and
  stage-scoped secrets while executing the new package.
- Completeness scan: all stages, authority fields, tests, and command behavior
  are named explicitly; no deferred safety behavior is included.
- Type consistency: receipt collection produces the SHA-bound receipt consumed
  by the resume generator, and the runner validates that same document before
  every stage.
