# Deployed Release Read-Only Diagnostic D1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-use, Azure-read-only D1 package that records a sanitized exact deployed-state observation without reading Keychain, calling the public Demo, touching the registry or mutating Azure.

**Architecture:** A compiled-Bicep desired projection and the exact V4 deployed continuation define expected state. A core-CLI `az rest` reader collects bounded `2024-03-01` ARM projections, a policy layer evaluates resources and time-aware execution history, and a one-shot runner writes its mode-0600 attempt receipt before the first Azure GET. Package generation and execution are separate; this plan stops after generating the local D1 package until the user approves its exact SHA-256.

**Tech Stack:** Python 3.12, pytest, Azure CLI core `az rest`, Bicep CLI 0.46.1-compatible build output, Git, JSON, existing release verification policy.

## Global Constraints

- Design authority: `docs/superpowers/specs/2026-08-16-deployed-release-readonly-diagnostic-d1-design.md` at commit `4b0df293f57583f2cd884208a233830e1f67aed2`.
- Implementation changed-path base: `D1_BATCH_BASE_SHA=4b0df293f57583f2cd884208a233830e1f67aed2`; never use deployed SHA `537effe3036f77f83225beef12589bd447205a8b` as a changed-path base.
- D1 may execute only local validation, `az bicep build`, ARM `GET`, and owner-only local receipt/observation writes.
- Do not run `az containerapp`, access ACR/Docker, read Keychain, request the public URL, start a Job, restart, roll back, deploy or call AI.
- ARM host is exactly `management.azure.com`; API version is exactly `2024-03-01`; methods are exactly `GET`; request retry limit is `0`.
- Limits are 30 seconds per request, 1,000,000 bytes per page, five pages per collection, 8,000,000 total response bytes and 30 total GETs.
- Package, receipt and observation modes are exactly `0600`; duplicate JSON keys, path traversal, raw Azure response persistence and arbitrary exception text are forbidden.
- A D1 package expires no later than 24 hours after issue and is consumed by any existing attempt receipt, including `started` or `failed`.
- D1 does not update `release/current_authority.json` and cannot produce a Hosted verified, Azure accepted or Production ready claim.
- Every production-code task follows RED, minimal GREEN, focused verification and a small local commit.

---

## File Structure

### New runtime files

- `scripts/secret_boundary.py`: shared secret-pattern check so D1 runtime never imports a test module.
- `scripts/deployed_release_diagnostic_contract.py`: strict D1 schemas, safe enums, canonical hashes, timestamps, URL/path checks and atomic owner-only JSON writes.
- `scripts/build_deployed_release_desired_projection.py`: compile Bicep and normalize the desired application/Job contract.
- `scripts/create_deployed_release_diagnostic_package.py`: bind Git, continuation, toolchain, controls, limits and desired-projection SHA into one owner-only package.
- `scripts/observe_deployed_release_state.py`: execute bounded ARM GETs, validate pagination, compare resources/history and return a sanitized observation.
- `scripts/run_deployed_release_diagnostic.py`: validate approved SHA, write the attempt receipt before Azure, invoke observation and atomically finalize evidence.

### New tests

- `tests/infra/test_deployed_release_bicep_projection.py`: real compiled-Bicep parity and projection tamper tests.
- `tests/release/test_deployed_release_diagnostic_package.py`: package schema, repository/toolchain/control and mode tests.
- `tests/hosted/test_observe_deployed_release_state.py`: REST scope, projection, pagination and execution-history tests.
- `tests/hosted/test_run_deployed_release_diagnostic.py`: one-shot ordering, safe receipt and non-leakage tests.

### Modified compatibility/policy files

- `scripts/verify_deployed_release_state.py`: import the shared secret pattern; retain V6 behavior for evidence compatibility, but V6 remains retired.
- `tests/hosted/verify_azure_demo.py`: import the same shared secret pattern.
- `release/verification-policy.json`: map every D1 runtime/test path to `release_static`.
- `tests/release/test_select_required_checks.py`: prove D1 paths select the static release gate.
- `docs/operations/DEPLOYED_RELEASE_DIAGNOSTIC_D1.md`: operator boundary and package/receipt/observation commands.

---

### Task 1: Remove the runtime dependency on test code

**Files:**

- Create: `scripts/secret_boundary.py`
- Modify: `scripts/verify_deployed_release_state.py:36`
- Modify: `tests/hosted/verify_azure_demo.py:318`
- Test: `tests/hosted/test_verify_deployed_release_state.py`
- Test: `tests/hosted/test_verify_azure_demo.py`

**Interfaces:**

- Produces: `scripts.secret_boundary.SECRET_PATTERN: re.Pattern[str]`.
- Existing V6 modules retain the same serialized-secret rejection behavior.
- D1 modules may import `SECRET_PATTERN` without importing `tests.*`.

- [ ] **Step 1: Write the failing import-boundary test**

Add to `tests/hosted/test_verify_deployed_release_state.py`:

```python
def test_deployed_verifier_runtime_does_not_import_test_modules() -> None:
    source = (PROJECT_ROOT / "scripts/verify_deployed_release_state.py").read_text()
    assert "from tests." not in source
    assert "import tests." not in source
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
.venv/bin/pytest tests/hosted/test_verify_deployed_release_state.py::test_deployed_verifier_runtime_does_not_import_test_modules -q
```

Expected: FAIL because `verify_deployed_release_state.py` imports
`SECRET_PATTERN` from `tests.hosted.verify_azure_demo`.

- [ ] **Step 3: Add the shared production-safe pattern**

Create `scripts/secret_boundary.py`:

```python
"""Shared value-leak detector for release and diagnostic documents."""

from __future__ import annotations

import re


SECRET_PATTERN = re.compile(
    r"(?:"
    r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}"
    r"|AccountKey\s*="
    r"|Authorization\s*:\s*Bearer\s+\S+"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----"
    r"|\b(?:password|api[_-]?key|client[_-]?secret)\s*[:=]\s*\S+"
    r"|[A-Za-z][A-Za-z0-9+.-]*://[^/@\s:]+:[^/@\s]+@"
    r")",
    re.IGNORECASE,
)
```

Import this symbol from both affected files and delete the duplicate test
definition. Do not alter any other release schema or V6 comparison rule.

- [ ] **Step 4: Prove behavior and direct entrypoints**

Run:

```bash
.venv/bin/pytest tests/hosted/test_verify_deployed_release_state.py tests/hosted/test_verify_azure_demo.py -q
.venv/bin/python scripts/verify_deployed_release_state.py --help >/dev/null
```

Expected: both commands exit `0`; the pytest count is at least the pre-change
count and the new import-boundary test passes.

- [ ] **Step 5: Commit**

```bash
git add scripts/secret_boundary.py scripts/verify_deployed_release_state.py tests/hosted/verify_azure_demo.py tests/hosted/test_verify_deployed_release_state.py
git commit -m "refactor: remove release runtime test import"
```

### Task 2: Build the desired projection from compiled Bicep

**Files:**

- Create: `scripts/deployed_release_diagnostic_contract.py`
- Create: `scripts/build_deployed_release_desired_projection.py`
- Create: `tests/infra/test_deployed_release_bicep_projection.py`

**Interfaces:**

- Consumes: a continuation returned by
  `load_deployed_release_continuation(path, expected_sha256=continuation_sha256)`.
- Produces: `canonical_sha256(value: object) -> str`.
- Produces: `compile_desired_projection(bicep_path: Path, continuation: Mapping[str, Any], *, continuation_sha256: str, runner=subprocess.run) -> dict[str, Any]`.
- Produces: `DeployedReleaseDiagnosticInvalid(code: str, stage: str, resource_role: str)` with enum-validated public attributes.

- [ ] **Step 1: Write the compiled-Bicep regression**

Create `tests/infra/test_deployed_release_bicep_projection.py` with this core
assertion:

```python
from pathlib import Path

from scripts.build_deployed_release_desired_projection import (
    compile_desired_projection,
)
from scripts.verify_deployed_release_state import (
    load_deployed_release_continuation,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTINUATION = PROJECT_ROOT / "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json"
CONTINUATION_SHA256 = "d355c9215ee9dec22adb93392705107dfd8f06db37ca8d03b240c519278af4af"


def test_compiled_bicep_projection_includes_complete_job_environment() -> None:
    continuation = load_deployed_release_continuation(
        CONTINUATION,
        expected_sha256=CONTINUATION_SHA256,
    )
    projection = compile_desired_projection(
        PROJECT_ROOT / "infra/modules/app.bicep",
        continuation,
        continuation_sha256=CONTINUATION_SHA256,
    )
    for role in (
        "prepare",
        "seed",
        "session_maintenance",
        "storage_maintenance",
    ):
        bindings = projection["jobs"][role]["environment_bindings"]
        assert bindings["BIZPULSE_ALLOWED_ORIGIN"] == "value"
        assert bindings["BIZPULSE_OPERATOR_PASSWORD_HASH"] == (
            "secretRef:operator-password-hash"
        )
```

- [ ] **Step 2: Run the test to verify RED**

Run:

```bash
.venv/bin/pytest tests/infra/test_deployed_release_bicep_projection.py -q
```

Expected: collection ERROR because the two D1 modules do not exist.

- [ ] **Step 3: Implement strict shared primitives**

In `deployed_release_diagnostic_contract.py`, implement exact-key JSON loading,
canonical hashing, UTC parsing, safe enums and atomic owner-only writes. The
public surface must be:

```python
SAFE_CODES = frozenset(
    {
        "diagnostic_package_hash_mismatch",
        "diagnostic_package_invalid",
        "diagnostic_package_expired",
        "diagnostic_package_consumed",
        "diagnostic_repository_drift",
        "diagnostic_toolchain_drift",
        "diagnostic_control_drift",
        "diagnostic_bicep_projection_invalid",
        "diagnostic_arm_request_failed",
        "diagnostic_arm_response_invalid",
        "diagnostic_arm_scope_invalid",
        "diagnostic_pagination_invalid",
        "diagnostic_pagination_limit_exceeded",
        "diagnostic_application_drift",
        "diagnostic_revision_drift",
        "diagnostic_job_drift",
        "diagnostic_bound_execution_invalid",
        "diagnostic_execution_history_invalid",
        "diagnostic_observation_write_failed",
        "diagnostic_execution_failed",
    }
)
SAFE_STAGES = frozenset({"local", "application", "revision", "job", "execution", "observation"})
SAFE_ROLES = frozenset({"local", "application", "revision", "prepare", "seed", "session_maintenance", "storage_maintenance"})


class DeployedReleaseDiagnosticInvalid(RuntimeError):
    def __init__(self, code: str, stage: str, resource_role: str):
        if (
            code not in SAFE_CODES
            or stage not in SAFE_STAGES
            or resource_role not in SAFE_ROLES
        ):
            code, stage, resource_role = (
                "diagnostic_package_invalid",
                "local",
                "local",
            )
        super().__init__(code)
        self.code = code
        self.stage = stage
        self.resource_role = resource_role


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
```

`write_owner_json_exclusive()` must use
`os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)` and
`json.dump(payload, stream, indent=2, sort_keys=True)`. The replacement helper
must use the same exclusive mode for a sibling temporary path followed by
`os.replace(temporary, path)`. Both helpers perform a post-write mode assertion.

- [ ] **Step 4: Implement Bicep compilation and normalization**

`compile_desired_projection()` must execute exactly:

```python
completed = runner(
    [
        "az",
        "bicep",
        "build",
        "--file",
        str(bicep_path),
        "--stdout",
    ],
    check=False,
    capture_output=True,
    text=True,
    timeout=60,
)
```

Reject nonzero exit, output above 2,000,000 bytes, duplicate JSON keys, resource
counts other than one app and four Jobs, unknown container roles, duplicate env
names, secret values, or missing required structures. Normalize each env row to
`"value"` or `"secretRef:<name>"`; materialize safe expected values from the
continuation only in an in-memory `expected_value_env` mapping. Return exact
top-level keys `schema_version`, `application`, `jobs`, and
`continuation_sha256`, with schema
`newcaostone.deployed-release-desired-projection.v1`.

- [ ] **Step 5: Add tamper and completeness tests**

Add tests that inject a fake compiler response with each of these changes and
expect `diagnostic_bicep_projection_invalid`:

```python
@pytest.mark.parametrize(
    "mutation",
    (
        "remove_allowed_origin",
        "change_operator_hash_binding",
        "duplicate_env_name",
        "add_secret_value",
        "remove_seed_job",
    ),
)
def test_bicep_projection_rejects_contract_drift(mutation: str) -> None:
    compiled = compiled_template_fixture()
    mutate_compiled_template(compiled, mutation)
    with pytest.raises(
        DeployedReleaseDiagnosticInvalid,
        match="diagnostic_bicep_projection_invalid",
    ):
        compile_desired_projection(
            BICEP,
            continuation_fixture(),
            continuation_sha256=CONTINUATION_SHA256,
            runner=fake_bicep(compiled),
        )
```

The local fixture helper must derive live payload builders from the returned
projection; it must not contain a second handwritten Job environment list.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest tests/infra/test_deployed_release_bicep_projection.py -q
az bicep build --file infra/modules/app.bicep --stdout >/dev/null
git add scripts/deployed_release_diagnostic_contract.py scripts/build_deployed_release_desired_projection.py tests/infra/test_deployed_release_bicep_projection.py
git commit -m "feat: derive deployed contract from Bicep"
```

Expected: tests PASS and Bicep build exits `0` without writing an ARM file.

### Task 3: Bind the D1 package to repository, controls and toolchain

**Files:**

- Create: `scripts/create_deployed_release_diagnostic_package.py`
- Create: `tests/release/test_deployed_release_diagnostic_package.py`

**Interfaces:**

- Produces: `build_deployed_release_diagnostic_package(*, continuation: Mapping[str, Any], continuation_reference: str, continuation_sha256: str, desired_projection: Mapping[str, Any], authorization_id: str, issued_at: str, expires_at: str, git_runner: Callable, command_runner: Callable) -> dict[str, Any]`.
- Produces: `write_deployed_release_diagnostic_package(path: Path, package: Mapping[str, Any]) -> str`, returning the document SHA-256.
- Produces: `load_deployed_release_diagnostic_package(path: Path, *, continuation_path: Path, now: datetime | None = None) -> dict[str, Any]`.
- Package schema: `newcaostone.deployed-release-diagnostic-package.v1`.

- [ ] **Step 1: Write failing exact-shape and tamper tests**

Create tests that build with injected Git/tool runners and assert:

```python
def test_package_binds_clean_repository_projection_controls_and_limits(tmp_path: Path) -> None:
    package = build_package_fixture(tmp_path)
    assert package["schema_version"] == (
        "newcaostone.deployed-release-diagnostic-package.v1"
    )
    assert package["repository"]["tracked_clean_required"] is True
    assert package["arm"] == {
        "allowed_http_methods": ["GET"],
        "allowed_resource_paths": expected_arm_paths(continuation_fixture()),
        "api_version": "2024-03-01",
        "host": "management.azure.com",
        "max_page_bytes": 1_000_000,
        "max_pages_per_collection": 5,
        "max_total_requests": 30,
        "max_total_response_bytes": 8_000_000,
        "request_retry_limit": 0,
        "request_timeout_seconds": 30,
    }
    assert package["forbidden_operations"] == [
        "azure_mutation",
        "registry_access",
        "keychain_access",
        "public_url_access",
        "ai_access",
    ]
```

Also test dirty tracked state, wrong HEAD/tree, changed Bicep/control/lock hash,
wrong tool version, duplicate key, mode `0644`, expiry above 24 hours and
continuation-path traversal.

- [ ] **Step 2: Run the tests to verify RED**

```bash
.venv/bin/pytest tests/release/test_deployed_release_diagnostic_package.py -q
```

Expected: collection ERROR because the package module does not exist.

- [ ] **Step 3: Implement deterministic local import-closure discovery**

Walk `ast.Import` and `ast.ImportFrom` recursively for repository-local
`scripts.*` and `src.*` modules, starting from all four D1 entrypoints. Add the
following data inputs explicitly:

```python
BOUND_DATA_PATHS = (
    "infra/modules/app.bicep",
    "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json",
    "requirements.txt",
    "requirements-dev.txt",
    "package.json",
    "package-lock.json",
)
```

Reject dynamic relative imports, a discovered path outside `PROJECT_ROOT`, an
unreadable file or an empty control set. Store sorted relative paths and
SHA-256 values.

- [ ] **Step 4: Implement repository and toolchain binding**

Use non-interactive subprocess calls with `shell=False` to capture:

```text
git branch --show-current
git rev-parse HEAD
git rev-parse HEAD^{tree}
git status --porcelain=v1 --untracked-files=no
.venv/bin/python --version
az version --output json
az bicep version
```

Require the branch to be `codex/integrated-viewer-ai-anti-drift`, full lower
case Git SHAs, and empty tracked status. Record the Container Apps extension
version but do not include any `az containerapp` command.

- [ ] **Step 5: Implement strict build/write/load**

Build the package with exact key sets from the design, a UUID authorization ID,
timezone-aware timestamps, desired-projection SHA, continuation SHA and the
four allowed operations. `load_*` must rebuild the expected package from the
stored authority and current local facts, compare with `hmac.compare_digest`
where hashes are involved, and reject drift before returning.

The Markdown wrapper is exactly:

```python
HEADER = "# NEWCaostone Deployed Release Diagnostic D1 Authorization"
document = HEADER + "\n\n```json\n" + json.dumps(
    package,
    indent=2,
    sort_keys=True,
) + "\n```\n"
```

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest tests/release/test_deployed_release_diagnostic_package.py tests/infra/test_deployed_release_bicep_projection.py -q
.venv/bin/python scripts/create_deployed_release_diagnostic_package.py --help >/dev/null
git add scripts/create_deployed_release_diagnostic_package.py tests/release/test_deployed_release_diagnostic_package.py
git commit -m "feat: bind read-only diagnostic package"
```

### Task 4: Implement the bounded ARM GET client

**Files:**

- Create: `scripts/observe_deployed_release_state.py`
- Create: `tests/hosted/test_observe_deployed_release_state.py`

**Interfaces:**

- Produces: `read_arm_page(url: str, *, limits: Mapping[str, int], runner=subprocess.run) -> ArmPage`.
- Produces: `read_arm_collection(url: str, *, scope: ArmScope, budget: ReadBudget, runner=subprocess.run) -> Sequence[ArmPage]`.
- Produces: `collect_arm_payloads(package: Mapping[str, Any], continuation: Mapping[str, Any], *, runner=subprocess.run) -> dict[str, Any]`.
- `ArmPage` contains only parsed `payload`, `sha256` and `byte_count`; raw text is released after parsing.

- [ ] **Step 1: Write failing request-scope tests**

Add a fake runner that records argv and returns one JSON page. Assert the first
command is exactly:

```python
assert calls[0] == [
    "az",
    "rest",
    "--method",
    "get",
    "--url",
    expected_app_url,
    "--only-show-errors",
    "--output",
    "json",
]
```

Add rejection tests for method `post`, non-HTTPS URL, another host,
subscription, resource group, provider, resource name, API version, embedded
credentials, fragment and non-allowlisted query parameter. For `nextLink`,
normalize query-key case and permit only `api-version=2024-03-01` plus one of
`$skiptoken` or `skiptoken`; reject duplicate query keys and an empty token.

- [ ] **Step 2: Run tests to verify RED**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py -k "arm or scope" -q
```

Expected: collection ERROR because the observer module does not exist.

- [ ] **Step 3: Implement sanitized `az rest` execution**

Use only `AZURE_CONFIG_DIR`, `HOME`, `LANG`, `LC_ALL`, `PATH`,
`REQUESTS_CA_BUNDLE`, `SSL_CERT_FILE` and `TMPDIR` from the parent environment.
Invoke with `check=False`, `capture_output=True`, `text=False`, `timeout=30`,
`cwd=PROJECT_ROOT` and `shell=False`. Convert nonzero return, timeout or OS
error to `diagnostic_arm_request_failed` without propagating output.

Parse with a duplicate-key hook:

```python
def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("diagnostic_json_duplicate_key")
        result[key] = value
    return result
```

- [ ] **Step 4: Implement pagination and global budgets**

The app and four Job GETs accept mapping payloads. Revision and execution
collections require exact keys `value` and `nextLink`, a list `value`, and
`nextLink` of string or null. Validate every next URL against `ArmScope` before
issuing it. Increment request and byte budgets before following the next page;
raise `diagnostic_pagination_limit_exceeded` at the configured boundary rather
than returning a partial collection.

- [ ] **Step 5: Test pagination, size, count and non-leakage**

Cover two-page success and each exact limit. Include a response containing
`Authorization: Bearer do-not-record` and assert that neither the exception nor
the returned page metadata contains it. Confirm stderr is discarded.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py -k "arm or scope or pagination or limit" -q
git add scripts/observe_deployed_release_state.py tests/hosted/test_observe_deployed_release_state.py
git commit -m "feat: add bounded ARM diagnostic reader"
```

### Task 5: Compare app and Job resources without Azure-owned-field drift

**Files:**

- Modify: `scripts/observe_deployed_release_state.py`
- Modify: `tests/hosted/test_observe_deployed_release_state.py`

**Interfaces:**

- Produces: `project_deployed_resources(raw: Mapping[str, Any], desired: Mapping[str, Any], continuation: Mapping[str, Any]) -> dict[str, Any]`.
- The return value is sanitized and contains no environment values or raw ARM objects.

- [ ] **Step 1: Write the V6 regression as a failing test**

Build live Job payloads from the Task 2 desired projection and assert all four
roles are accepted with both corrected bindings:

```python
def test_resource_projection_accepts_the_compiled_bicep_job_contract() -> None:
    desired = desired_projection_fixture()
    raw = live_payloads_from_desired(desired)
    result = project_deployed_resources(raw, desired, continuation_fixture())
    for role in desired["jobs"]:
        bindings = result["jobs"][role]["environment_bindings"]
        assert "BIZPULSE_ALLOWED_ORIGIN" in bindings
        assert "BIZPULSE_OPERATOR_PASSWORD_HASH" in bindings
        assert "expected_value_env" not in result["jobs"][role]
```

Add Azure-owned fields `systemData`, `eventStreamEndpoint`,
`outboundIpAddresses`, scale defaults and null optional fields and assert the
same sanitized result.

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py -k resource_projection -q
```

Expected: FAIL because `project_deployed_resources` is absent.

- [ ] **Step 3: Implement strict security-bearing projections**

For the app, compare exact name/ID/environment, candidate image, ready/latest
revision, single mode, external ingress, FQDN, 100% latest traffic, min/max
replicas, probes, container, no-AI values, env bindings and secret names. For
Jobs, compare exact name/ID/environment, image, command, args, env bindings,
secret names, trigger, retry, timeout, manual/schedule config and resources.

Ignore fields outside the explicit projection. Reject extra or missing env
names, different binding kinds, non-empty returned secret values and duplicate
names. Store only:

```python
{
    "checks": {"desired_contract_match": True},
    "container": {"image": candidate_image, "name": container_name},
    "environment_bindings": sorted(binding_names),
    "resource_id": canonical_resource_id,
    "resource_name": resource_name,
}
```

Job output additionally includes safe trigger/timeout/retry/schedule/resource
settings; app output additionally includes safe revision, traffic, scale and
FQDN fields.

- [ ] **Step 4: Add exact drift tests**

Parameterize image, env name, secretRef, command, schedule, timeout, resources,
revision and traffic changes. Expect `diagnostic_application_drift`,
`diagnostic_revision_drift` or `diagnostic_job_drift` with only the safe role.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py -k "resource_projection or resource_drift" -q
git add scripts/observe_deployed_release_state.py tests/hosted/test_observe_deployed_release_state.py
git commit -m "fix: compare deployed state to Bicep projection"
```

### Task 6: Add time-aware execution history and sanitized observation

**Files:**

- Modify: `scripts/deployed_release_diagnostic_contract.py`
- Modify: `scripts/observe_deployed_release_state.py`
- Modify: `tests/hosted/test_observe_deployed_release_state.py`

**Interfaces:**

- Produces: `evaluate_execution_history(role: str, rows: Sequence[Mapping[str, Any]], bound: Mapping[str, str], *, continuation_recorded_at: datetime, observed_at: datetime, replica_timeout: int) -> dict[str, Any]`.
- Produces: `observe_deployed_release_state(package, continuation, desired, *, observed_at, runner) -> dict[str, Any]` with schema `newcaostone.deployed-release-diagnostic-observation.v1`.

- [ ] **Step 1: Write the historical failed-seed regression**

```python
def test_older_failed_seed_is_history_not_current_drift() -> None:
    result = evaluate_execution_history(
        "seed",
        [
            execution("newcaostone-demo-seed-8a8k7de", "Failed", "2026-08-16T20:00:00Z", "2026-08-16T20:01:00Z"),
            execution("newcaostone-demo-seed-vhamoeo", "Succeeded", "2026-08-16T20:10:00Z", "2026-08-16T20:11:00Z"),
        ],
        {"name": "newcaostone-demo-seed-vhamoeo", "status": "Succeeded"},
        continuation_recorded_at=parse_utc("2026-08-16T22:18:28Z"),
        observed_at=parse_utc("2026-08-16T23:30:00Z"),
        replica_timeout=1800,
    )
    assert result["bound"]["status"] == "Succeeded"
    assert result["historical"][0]["status"] == "Failed"
    assert result["later"] == []
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py -k execution_history -q
```

Expected: FAIL because the policy function does not exist.

- [ ] **Step 3: Implement the exact state/time policy**

Define:

```python
OFFICIAL_EXECUTION_STATES = frozenset(
    {"Running", "Processing", "Stopped", "Degraded", "Failed", "Unknown", "Succeeded"}
)
HISTORICAL_TERMINAL_STATES = frozenset(
    {"Succeeded", "Failed", "Stopped", "Degraded"}
)
ACTIVE_STATES = frozenset({"Running", "Processing"})
ACTIVE_GRACE_SECONDS = 120
```

Require one exact bound name, `Succeeded`, valid UTC start/end and
`start <= end <= continuation_recorded_at`. Apply all manual and scheduled
rules verbatim from the approved design. Sort output by `(startTime, name)`,
reject duplicate names, and preserve only name/status/start/end.

- [ ] **Step 4: Add all policy edge cases**

Test:

- a newer prepare and newer seed are rejected;
- an overlapping historical manual execution is rejected;
- `Unknown` history is rejected;
- a later scheduled success is accepted;
- a later scheduled failure is rejected;
- Running/Processing within timeout plus 120 seconds is accepted;
- an over-age active run is rejected;
- missing timestamps, duplicate names and an undocumented state are rejected;
- the exact bound execution missing from a complete paginated collection is rejected.

- [ ] **Step 5: Build the final observation schema**

Combine page hashes, pagination counts, resource projections and execution
results under exact keys:

```python
observation = {
    "schema_version": "newcaostone.deployed-release-diagnostic-observation.v1",
    "authorization_id": package["authorization_id"],
    "package_sha256": package_sha256,
    "observed_at": utc_text(observed_at),
    "repository": package["repository"],
    "continuation": package["continuation"],
    "desired_projection_sha256": package["desired_projection_sha256"],
    "toolchain": package["toolchain"],
    "page_evidence": page_evidence,
    "resources": resource_projection,
    "executions": execution_projection,
    "checks": {
        "pagination_complete": True,
        "desired_contract_match": True,
        "bound_executions_match": True,
        "execution_history_acceptable": True,
    },
    "claim": "read_only_deployed_state_observed",
}
```

Before returning, serialize and reject `SECRET_PATTERN`; assert no keys named
`value`, `raw`, `stdout`, `stderr`, `token`, `password` or
`connection_string` occur anywhere in the observation.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest tests/hosted/test_observe_deployed_release_state.py -q
git add scripts/deployed_release_diagnostic_contract.py scripts/observe_deployed_release_state.py tests/hosted/test_observe_deployed_release_state.py
git commit -m "feat: classify deployed execution history"
```

### Task 7: Enforce receipt-before-read and one-shot execution

**Files:**

- Create: `scripts/run_deployed_release_diagnostic.py`
- Create: `tests/hosted/test_run_deployed_release_diagnostic.py`

**Interfaces:**

- Produces: `execute_deployed_release_diagnostic(*, package_path: Path, approved_sha256: str, continuation_path: Path, receipt_path: Path, observation_path: Path, now: datetime | None = None, arm_runner=subprocess.run) -> dict[str, str]`.
- Receipt schema: `newcaostone.deployed-release-diagnostic-attempt.v1`.

- [ ] **Step 1: Write the ordering regression**

```python
def test_attempt_receipt_exists_before_first_arm_read(tmp_path: Path) -> None:
    package_path, digest, continuation_path = valid_package(tmp_path)
    receipt_path = tmp_path / "attempt.json"
    observation_path = tmp_path / "observation.json"

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        assert receipt_path.exists()
        receipt = json.loads(receipt_path.read_text())
        assert receipt["status"] == "started"
        return arm_response_for(argv)

    execute_deployed_release_diagnostic(
        package_path=package_path,
        approved_sha256=digest,
        continuation_path=continuation_path,
        receipt_path=receipt_path,
        observation_path=observation_path,
        now=parse_utc("2026-08-16T23:30:00Z"),
        arm_runner=runner,
    )
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/hosted/test_run_deployed_release_diagnostic.py -q
```

Expected: collection ERROR because the runner module does not exist.

- [ ] **Step 3: Implement local validation then irreversible attempt creation**

Order the function exactly:

1. read package bytes and compare approved SHA with `hmac.compare_digest`;
2. load/rebuild package and validate continuation, Git, controls, toolchain and Bicep projection;
3. reject existing receipt or observation;
4. create the `started` receipt with `write_owner_json_exclusive`;
5. perform the first ARM read;
6. atomically update safe progress after each completed resource role;
7. exclusively write the sanitized observation;
8. atomically set receipt `completed` with observation SHA.

Wrap only `DeployedReleaseDiagnosticInvalid`. On failure, set `status=failed`
and store only its enum `code`, `stage` and `resource_role`; then re-raise a
generic `diagnostic_execution_failed`. A `BaseException` or process crash is
not converted, leaving the `started` receipt to consume the package.

- [ ] **Step 4: Prove one-shot, mode and safe failure behavior**

Tests must cover:

- wrong approved SHA creates no receipt and makes no ARM call;
- invalid local package creates no receipt and makes no ARM call;
- an ARM failure leaves one mode-0600 failed receipt;
- a crash leaves one mode-0600 started receipt;
- any existing started/failed/completed receipt blocks replay;
- observation is mode `0600`, `O_EXCL` and its SHA matches the receipt;
- arbitrary child stdout/stderr and bearer/password samples never enter either file;
- Keychain, Docker, `az containerapp` and non-GET tokens never appear in recorded argv.

- [ ] **Step 5: Add a direct-entrypoint CLI**

The CLI requires all five explicit arguments:

```text
--package
--approved-sha256
--continuation
--receipt
--observation
```

On success print only `deployed_release_diagnostic=completed`. On failure print
only the generic safe code and `deployed_release_diagnostic=failed`.

- [ ] **Step 6: Verify and commit**

```bash
.venv/bin/pytest tests/hosted/test_run_deployed_release_diagnostic.py tests/hosted/test_observe_deployed_release_state.py -q
.venv/bin/python scripts/run_deployed_release_diagnostic.py --help >/dev/null
git add scripts/run_deployed_release_diagnostic.py tests/hosted/test_run_deployed_release_diagnostic.py
git commit -m "feat: enforce one-shot deployed diagnostic"
```

### Task 8: Map D1 into release policy and write the operator boundary

**Files:**

- Modify: `release/verification-policy.json`
- Modify: `tests/release/test_select_required_checks.py`
- Create: `docs/operations/DEPLOYED_RELEASE_DIAGNOSTIC_D1.md`

**Interfaces:**

- Every D1 runtime and test path selects `release_static`; the Bicep projection
  test also retains the existing `ai_infra_boundary` selection for
  `tests/infra/**`.
- The runbook provides generation/validation paths but grants no execution authority.

- [ ] **Step 1: Write failing path-selection coverage**

Add these runtime and non-infra test paths to the existing release-tooling
parameterization:

```python
"bizpulse/scripts/deployed_release_diagnostic_contract.py",
"bizpulse/scripts/build_deployed_release_desired_projection.py",
"bizpulse/scripts/create_deployed_release_diagnostic_package.py",
"bizpulse/scripts/observe_deployed_release_state.py",
"bizpulse/scripts/run_deployed_release_diagnostic.py",
"bizpulse/tests/release/test_deployed_release_diagnostic_package.py",
"bizpulse/tests/hosted/test_observe_deployed_release_state.py",
"bizpulse/tests/hosted/test_run_deployed_release_diagnostic.py",
```

Add a separate assertion for the existing infra overlap:

```python
def test_deployed_diagnostic_bicep_projection_keeps_both_infra_gates() -> None:
    selected = select_required_checks(
        ("bizpulse/tests/infra/test_deployed_release_bicep_projection.py",),
        POLICY,
    )
    assert {item.name for item in selected} == {
        "ai_infra_boundary",
        "release_static",
    }
```

- [ ] **Step 2: Verify RED**

```bash
.venv/bin/pytest tests/release/test_select_required_checks.py -k two_stage_release_tooling -q
```

Expected: FAIL with `verification_policy_unmapped_path` for the new D1 paths.

- [ ] **Step 3: Extend the exact release-static command and domain**

Add the four new test files to `checks.release_static.argv`. Add all runtime and
test paths to the `release_tooling.include` array. Do not add D1 to
`full_release_gate`; D1 implementation is local release tooling and performs no
deployment.

- [ ] **Step 4: Write the operator runbook**

Document exact fixed paths:

```text
.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md
.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json
.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_OBSERVATION.json
release/incidents/2026-08-16-recovery-v4-deployed-continuation.json
```

The runbook must state that package generation does not access Azure, package
execution requires a separate exact SHA approval, any receipt consumes the
package, and a completed observation is not hosted acceptance. Include no
credential instructions because D1 never reads Keychain.

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/pytest tests/release/test_select_required_checks.py tests/release/test_deployed_release_diagnostic_package.py tests/hosted/test_run_deployed_release_diagnostic.py -q
git add release/verification-policy.json tests/release/test_select_required_checks.py docs/operations/DEPLOYED_RELEASE_DIAGNOSTIC_D1.md
git commit -m "docs: bind deployed diagnostic release gate"
```

### Task 9: Run the complete local gate and generate D1 for approval

**Files:**

- Create ignored: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md`
- Do not create yet: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json`
- Do not create yet: `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_OBSERVATION.json`

**Interfaces:**

- Produces one owner-only package path, authorization ID, expiry and SHA-256.
- Stops before the runner and before every Azure request.

- [ ] **Step 1: Run the focused non-cloud suite**

```bash
.venv/bin/pytest \
  tests/infra/test_deployed_release_bicep_projection.py \
  tests/release/test_deployed_release_diagnostic_package.py \
  tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py \
  -q
```

Expected: PASS with no network, Keychain, registry or public URL request.

- [ ] **Step 2: Run static release and Bicep gates**

```bash
.venv/bin/pytest \
  tests/release/test_container_contract.py \
  tests/release/test_release_scripts.py \
  tests/release/test_two_stage_release_package.py \
  tests/release/test_partial_release_recovery_package.py \
  tests/release/test_seeded_release_recovery_package.py \
  tests/hosted/test_verify_azure_demo.py \
  tests/hosted/test_verify_partial_release_state.py \
  tests/hosted/test_verify_seeded_release_state.py \
  tests/hosted/test_run_seeded_release_recovery.py \
  tests/hosted/test_verify_deployed_release_state.py \
  tests/release/test_deployed_release_recovery_package.py \
  tests/hosted/test_run_deployed_release_recovery.py \
  tests/hosted/test_update_azure_job_binding.py \
  tests/hosted/test_phase1_receipt_resume.py \
  tests/hosted/test_rollback_forward_resume.py \
  tests/hosted/test_rollback_forward_resume_runner.py \
  tests/hosted/test_azure_preflight.py \
  tests/hosted/test_run_hosted_failure_check.py \
  tests/infra/test_deployed_release_bicep_projection.py \
  tests/release/test_deployed_release_diagnostic_package.py \
  tests/hosted/test_observe_deployed_release_state.py \
  tests/hosted/test_run_deployed_release_diagnostic.py \
  -q
az bicep build --file infra/modules/app.bicep --stdout >/dev/null
```

Expected: all pytest cases PASS and Bicep build exits `0`.

- [ ] **Step 3: Run authority and changed-path verification**

```bash
.venv/bin/python scripts/check_authority_contract.py --mode docs
.venv/bin/python scripts/verify_changed.py \
  --base 4b0df293f57583f2cd884208a233830e1f67aed2 \
  --no-reuse
git diff --check "$(git merge-base 4b0df293f57583f2cd884208a233830e1f67aed2 HEAD)" HEAD
git status --short
```

Expected: docs authority passes; `verify_changed=passed`; diff check emits no
text; tracked worktree is clean after all task commits. A stale release-mode
observation remains stale and is not refreshed in this plan.

- [ ] **Step 4: Generate the package locally**

Run from the clean committed worktree:

```bash
.venv/bin/python scripts/create_deployed_release_diagnostic_package.py \
  --continuation release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --continuation-reference release/incidents/2026-08-16-recovery-v4-deployed-continuation.json \
  --output .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md \
  --expires-hours 24
```

Expected: the generator prints only the absolute package path, authorization
ID, UTC expiry and SHA-256. It performs local Git/toolchain/Bicep work only.

- [ ] **Step 5: Independently validate the generated artifact**

```bash
stat -f '%Lp %N' .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D1.md
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_ATTEMPT_RECEIPT.json
test ! -e .tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D1_OBSERVATION.json
git status --short
```

Expected: mode is `600`; the independently computed SHA equals generator
output; neither receipt nor observation exists; tracked status remains clean.

- [ ] **Step 6: Stop for exact SHA approval**

Report the package absolute path, authorization ID, expiry, SHA-256, bound Git
HEAD/tree, continuation SHA, desired-projection SHA and exact forbidden
operations. Do not invoke `run_deployed_release_diagnostic.py`, `az rest`,
Keychain, registry, Docker or the public URL in this task.

## Plan Self-Review

- Spec coverage: Tasks 1–2 remove the fixture/import drift and bind compiled
  Bicep; Task 3 binds repository/toolchain/control authority; Tasks 4–6 cover
  REST scope, projections, pagination and time-aware history; Task 7 enforces
  receipt-before-read and safe failure evidence; Tasks 8–9 provide anti-drift
  gates and the explicit approval stop.
- Scope separation: no task executes Azure, reads Keychain, touches ACR/Docker,
  calls the public Demo or designs Recovery V7.
- Type consistency: all modules use
  `DeployedReleaseDiagnosticInvalid(code, stage, resource_role)`, the exact D1
  package/attempt/observation schema names, and the same continuation and
  desired-projection SHA fields.
- Placeholder scan: all filenames, schemas, limits, commands, tests, expected
  outcomes and commit messages are explicit; no deferred implementation step
  is present.
- Evidence language: successful local implementation means only that D1 is
  locally ready for approval. A future completed D1 run may claim only
  `Read-only deployed-state observation completed`.
