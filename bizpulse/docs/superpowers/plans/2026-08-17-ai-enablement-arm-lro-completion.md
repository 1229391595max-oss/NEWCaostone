# AI Enablement ARM LRO Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` for the
> user-selected Inline Execution path.  Steps use checkbox syntax for tracking.

**Goal:** Ensure every authorized Container App PATCH waits for its Azure ARM
long-running operation to complete before revision reconciliation or a later
PATCH can begin, then provide a narrow no-Key R9 disabled-state recovery path.

**Architecture:** Add a small, injectable ARM request/LRO boundary that uses the
active Azure CLI identity without logging its bearer token.  The action adapter
submits one PATCH, waits through the allowlisted ARM operation URL, then invokes
the existing exact app/revision reconciliation.  A separate recovery package
will use the same boundary to make one AI-disabled revision transition and will
not execute the normal AI-enable state sequence.

**Tech stack:** Python 3.12, `azure-identity`, `requests`, pytest, Azure ARM,
Azure Container Apps, Node/browser release gate.

## Global constraints

- Work only in `/Users/maxli/Desktop/NEWCaostone/.worktrees/ai-enable-preset-buttons/bizpulse` on `codex/ai-enable-preset-buttons`.
- Do not call Azure, Key Vault, OpenAI, ACR, browser hosted routes, push, or deploy while implementing and testing this plan.
- A transition performs exactly one PATCH. ARM operation polling uses GET only;
  no `409` retry or fixed-sleep workaround is permitted.
- ARM LRO waits at most 300 seconds, polls no faster than every five seconds,
  honors only integer `Retry-After` values from 1 through 15 seconds, and
  fails closed on malformed, foreign-host, failed, cancelled, or timed-out
  operations.
- Azure bearer tokens, OpenAI keys, Key Vault values, raw ARM payloads, raw
  error text, prompts, and user data must not be logged, persisted, accepted
  through argv, or stored in tests/receipts/observations.
- Preserve the R8 receipt and task-owned Vault/UAMI/RBAC resources.  R9 must
  not touch an existing Vault, credential, or Secret value.

---

### Task 1: Add a pure, fail-closed ARM LRO boundary

**Files:**

- Create: `scripts/azure_arm_lro.py`
- Create: `tests/hosted/test_azure_arm_lro.py`

**Interfaces:**

- Produces `ARMResponse(status_code, headers, payload)` with a copied,
  non-persisted mapping payload.
- Produces `wait_for_arm_patch(*, app_resource_id, request, monotonic,
  sleeper) -> None`.
- `request(method: str, url: str, body: Mapping[str, object] | None) -> ARMResponse`
  is injectable and is the sole external boundary under test.
- Raises `ARMOperationInvalid` with only one of
  `ai_enablement_patch_unconfirmed` or `ai_enablement_arm_operation_failed`.

- [ ] **Step 1: Write a 202-success failing test**

```python
def test_wait_for_arm_patch_polls_async_operation_before_returning() -> None:
    calls: list[tuple[str, str]] = []
    responses = iter((
        ARMResponse(202, {"Azure-AsyncOperation": OPERATION_URL}, {}),
        ARMResponse(200, {}, {"status": "InProgress"}),
        ARMResponse(200, {}, {"status": "Succeeded"}),
    ))
    clock = FakeClock()

    wait_for_arm_patch(
        app_resource_id=APP_RESOURCE_ID,
        request=lambda method, url, body: calls.append((method, url)) or next(responses),
        monotonic=clock.monotonic,
        sleeper=clock.sleep,
    )

    assert calls == [("PATCH", APP_URL), ("GET", OPERATION_URL), ("GET", OPERATION_URL)]
    assert clock.sleeps == [5]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest tests/hosted/test_azure_arm_lro.py::test_wait_for_arm_patch_polls_async_operation_before_returning -q
```

Expected: import failure because `azure_arm_lro` and `wait_for_arm_patch` do
not exist.

- [ ] **Step 3: Add terminal-safety failing tests**

Add parameterized cases for an untrusted operation URL, missing operation URL
on a 202, `Failed`, `Canceled`, HTTP 500, non-mapping JSON, invalid
`Retry-After`, and deadline exhaustion.  Each asserts one PATCH, at most the
allowed GET calls, no second PATCH, and the closed error code.

- [ ] **Step 4: Implement the minimal LRO classifier**

```python
ARM_HOST = "management.azure.com"
MAX_ARM_OPERATION_SECONDS = 300.0
DEFAULT_POLL_SECONDS = 5.0
MAX_RETRY_AFTER_SECONDS = 15

def _operation_url(value: str, subscription_id: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or parsed.hostname != ARM_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not parsed.path.startswith(f"/subscriptions/{subscription_id}/")
    ):
        raise ARMOperationInvalid("ai_enablement_patch_unconfirmed")
    return value
```

Accept only PATCH 200, 201, or 202.  On 202, prefer
`Azure-AsyncOperation`, otherwise use `Location`; poll GET until `status` is
`Succeeded`.  For a `Location` response, an HTTP 200/204 without an explicit
status is terminal success.  Validate the optional initial response `id`
against the exact app resource ID.  Do not serialize a payload or header.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/hosted/test_azure_arm_lro.py -q
.venv/bin/ruff check scripts/azure_arm_lro.py tests/hosted/test_azure_arm_lro.py
```

Expected: all LRO tests pass and Ruff reports no findings.

### Task 2: Bind the action adapter to the LRO boundary

**Files:**

- Modify: `scripts/azure_ai_enablement_actions.py:1-40, 677-715, 1097-1170`
- Modify: `tests/hosted/test_azure_ai_enablement_actions.py`

**Interfaces:**

- Consumes `wait_for_arm_patch` and `ARMResponse` from Task 1.
- Adds optional constructor argument
  `arm_requester: Callable[[str, str, Mapping[str, object] | None], ARMResponse] | None`.
- Default requester obtains an ARM token with `AzureCliCredential`, makes one
  `requests.request` call with a 300-second request timeout, and returns only
  status, headers, and parsed JSON mapping/empty mapping.  The token exists in
  local memory only and is never included in an exception.

- [ ] **Step 1: Write an integration failing test**

```python
def test_apply_patch_waits_for_lro_before_acknowledgement() -> None:
    events: list[str] = []
    responses = iter((
        ARMResponse(202, {"Azure-AsyncOperation": OPERATION_URL}, {}),
        ARMResponse(200, {}, {"status": "Succeeded"}),
    ))
    actions = AzureAIEnablementActions(
        package=_package(),
        package_sha256=PACKAGE_SHA256,
        arm_requester=lambda method, url, body: events.append(method) or next(responses),
    )

    assert actions._apply_patch_azure(PATCH, revision_suffix=SUFFIX) == "accepted"
    assert events == ["PATCH", "GET"]
```

- [ ] **Step 2: Verify RED**

Run:

```bash
.venv/bin/pytest tests/hosted/test_azure_ai_enablement_actions.py::test_apply_patch_waits_for_lro_before_acknowledgement -q
```

Expected: constructor rejects `arm_requester` or the action returns without a
GET, demonstrating the former unsafe behavior.

- [ ] **Step 3: Implement the smallest adapter change**

Replace the `az rest` subprocess in `_apply_patch_azure` with a call to
`wait_for_arm_patch`.  The method must return `"accepted"` only after the LRO
helper succeeds.  Keep `_apply_revision` and the existing 120-second
app/revision reconciliation unchanged: it begins only after this return.

The production requester must be limited to this shape:

```python
token = self._arm_credential.get_token("https://management.azure.com/.default").token
try:
    response = requests.request(method, url, json=body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }, timeout=300)
finally:
    token = ""
```

Map all HTTP, token, transport, and JSON failures to the helper's closed code;
do not propagate response text.  Set `self._arm_credential` lazily so local
unit tests do not require an Azure login.

- [ ] **Step 4: Verify GREEN and regressions**

Run:

```bash
.venv/bin/pytest tests/hosted/test_azure_arm_lro.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_reconciliation.py -q
.venv/bin/ruff check scripts/azure_arm_lro.py \
  scripts/azure_ai_enablement_actions.py \
  tests/hosted/test_azure_arm_lro.py \
  tests/hosted/test_azure_ai_enablement_actions.py
```

Expected: no action can start browser/recovery code before its ARM operation
has succeeded, and all existing reconciliation tests remain green.

### Task 3: Add R9 disabled-recovery planning and package validation

**Files:**

- Create: `scripts/create_ai_disabled_recovery_package.py`
- Create: `scripts/run_ai_disabled_recovery.py`
- Create: `tests/hosted/test_create_ai_disabled_recovery_package.py`
- Create: `tests/hosted/test_run_ai_disabled_recovery.py`
- Modify: `docs/runbooks/AI_ENABLEMENT.md`

**Interfaces:**

- The generator accepts the exact current budget revision/digest only after a
  read-only Azure projection and writes an owner-only R9 package.
- The runner accepts a separately approved package hash, reserves an attempt
  receipt before the sole app PATCH, calls the Task 2 action boundary, and
  returns only sanitized disabled-recovery evidence.

- [ ] **Step 1: Write generator failing tests**

Require the pre-write projection to match all of: single revision mode, latest
and ready budget revision, 100% latest traffic, R8 image digest, AI enabled,
budget rehearsal enabled, task UAMI plus registry UAMI, and no Secret read.
Any mismatch must create neither package nor receipt.  A generated package must
declare exactly one `azure.write.containerapp.patch`, zero Key Vault/OpenAI
writes/calls, and a 24-hour-or-less expiry.

- [ ] **Step 2: Write runner failing tests**

Require an exclusive mode-0600 started receipt before one adapter PATCH.  On
success, assert the package-targeted disabled revision is latest/ready,
healthy/provisioned, 100% traffic, has AI disabled, no budget-rehearsal flag,
and only the registry UAMI.  On all failure paths assert no secret action, no
provider request, no second PATCH, and a closed receipt code.

- [ ] **Step 3: Verify RED**

Run:

```bash
.venv/bin/pytest tests/hosted/test_create_ai_disabled_recovery_package.py \
  tests/hosted/test_run_ai_disabled_recovery.py -q
```

Expected: import failures because the dedicated R9 package/runner do not exist.

- [ ] **Step 4: Implement the narrow R9 contract**

Build the disabled patch using
`build_ai_revision_patch(current_projection, enabled=False, candidate_image=package_candidate_image, revision_suffix=target_suffix, ai_identity_resource_id=task_identity_id)`
and the exact R8 candidate image.  Reuse `AzureAIEnablementActions` only for
read-only revalidation, the Task 2 one-shot patch/LRO wait, and exact
reconciliation.  Do not call resource deployment, placeholder writes, paid
qualification, browser scenarios requiring a provider, or the full
`run_ai_enablement` state sequence.  The disabled browser gate must make zero
provider turns and no external provider requests.

- [ ] **Step 5: Verify GREEN**

Run:

```bash
.venv/bin/pytest tests/hosted/test_create_ai_disabled_recovery_package.py \
  tests/hosted/test_run_ai_disabled_recovery.py \
  tests/hosted/test_azure_arm_lro.py \
  tests/hosted/test_azure_ai_enablement_actions.py -q
.venv/bin/ruff check scripts/create_ai_disabled_recovery_package.py \
  scripts/run_ai_disabled_recovery.py \
  tests/hosted/test_create_ai_disabled_recovery_package.py \
  tests/hosted/test_run_ai_disabled_recovery.py
```

Expected: the recovery contract proves it cannot request or store an OpenAI
key and it permits one ARM PATCH only.

### Task 4: Verify, commit, then produce—not execute—R9 authorization

**Files:**

- Modify only files from Tasks 1-3 and `docs/runbooks/AI_ENABLEMENT.md`.
- Generate at execution time: `.tmp/LAUNCH_AUTHORIZATION_AI_DISABLED_RECOVERY_R9_2026-08-17.json`.

- [ ] **Step 1: Run focused and changed-path checks**

```bash
.venv/bin/pytest tests/hosted/test_azure_arm_lro.py \
  tests/hosted/test_azure_ai_enablement_actions.py \
  tests/hosted/test_azure_ai_reconciliation.py \
  tests/hosted/test_create_ai_disabled_recovery_package.py \
  tests/hosted/test_run_ai_disabled_recovery.py -q
.venv/bin/ruff check scripts tests/hosted
npm test -- --runInBand
git diff --check
```

- [ ] **Step 2: Commit local implementation**

```bash
git add scripts tests/hosted docs/runbooks/AI_ENABLEMENT.md
git commit -m "fix: await ARM AI revision operations"
```

- [ ] **Step 3: Run a fresh read-only Azure preflight**

Read only the task app, its revision/traffic projection, task Vault/UAMI/RBAC
metadata, deployment identity, and R8 candidate digest.  Never list, read, or
write a Key Vault Secret.  Stop if the budget-rehearsal state changed since the
R9 contract was prepared.

- [ ] **Step 4: Generate and hash the R9 package**

Write the exact package and exclusive receipt/observation paths with mode 0600.
Report its SHA-256, execution count (one app PATCH), preflight projection, and
the explicit no-Key/no-paid-call boundary.  Stop for a separate user approval;
do not execute the R9 runner.
