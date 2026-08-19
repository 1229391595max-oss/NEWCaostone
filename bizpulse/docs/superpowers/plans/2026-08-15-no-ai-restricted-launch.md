# No-AI Restricted Launch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a new exact launch package that can publish the synthetic Demo with AI disabled, no OpenAI credential, and every non-AI hosted/recovery gate preserved.

**Architecture:** Keep the authorization schema and command-field set exact. Make the two AI failure rehearsals conditional on `ai_limits.enabled`: disabled packages carry empty `budget_failure` and `provider_failure` arrays and omit both stages from `execution_order`; enabled packages retain the existing mandatory rehearsals and paid smoke. Rebuild the complete immutable release authority before generating the new package, then stop at the user's exact SHA approval gate.

**Tech Stack:** Python 3.12, pytest, Ruff, Docker BuildKit, Azure CLI package grammar, Bicep, Git manifest-only attestation.

## Global Constraints

- `ai_limits.enabled=false`.
- `secret_presence.openai_api_key=false` and no `OPENAI_API_KEY` server setting.
- `external_publication.paid_ai_smoke=false` and `limits_usd.openai_smoke_cap=0`.
- Preserve PostgreSQL, Azure Blob, operator authentication, synthetic-only data, health, core browser, capacity, expiry, restart, and rollback gates.
- Keep `EXPECTED_COMMAND_FIELDS` exact; disabled AI stages must be present as empty arrays, not omitted.
- AI-enabled packages must still require budget failure, provider failure, and paid AI smoke.
- Do not mutate Azure, publish a registry image, retry a deployment, or expose the app before the user approves the new package SHA256.

---

### Task 1: Bind failure rehearsals to AI-enabled authority

**Files:**
- Modify: `tests/hosted/test_verify_azure_demo.py`
- Modify: `tests/hosted/verify_azure_demo.py`

**Interfaces:**
- Consumes: `authority["ai_limits"]["enabled"]`, `_expected_commands(authority)`, and `_expected_execution_order(authority)`.
- Produces: exact empty AI failure command tuples and a reduced execution order only when AI is disabled.

- [ ] **Step 1: Write the failing AI-disabled fixture and boundary tests**

Change the test helper so its expected command dictionary uses:

```python
"budget_failure": (
    [failure_check("budget")]
    if payload["ai_limits"]["enabled"]
    else []
),
"provider_failure": (
    [failure_check("provider-unavailable")]
    if payload["ai_limits"]["enabled"]
    else []
),
```

Change `_execution_order(payload)` so it appends both failure stages only when
`payload["ai_limits"]["enabled"]` is true. Add assertions to the strict
AI-disabled acceptance test:

```python
assert payload["commands"]["budget_failure"] == []
assert payload["commands"]["provider_failure"] == []
assert "budget_failure" not in payload["execution_order"]
assert "provider_failure" not in payload["execution_order"]
```

Add two fail-closed tests. The first inserts the old budget command into a
disabled payload; the second inserts `budget_failure` into the disabled
execution order. Both must raise the corresponding stable authorization error.
Extend the paid-AI acceptance test to assert both failure command arrays are
nonempty and both stages precede `deploy`.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
.venv/bin/pytest tests/hosted/test_verify_azure_demo.py -q
```

Expected: the strict disabled package and new fail-closed tests fail because
production `_expected_commands` and `_expected_execution_order` still require
the two failure stages.

- [ ] **Step 3: Implement the minimal mode boundary**

In `tests/hosted/verify_azure_demo.py`, change only the two command values:

```python
"budget_failure": (
    (failure_check("budget"),) if ai_limits["enabled"] else ()
),
"provider_failure": (
    (failure_check("provider-unavailable"),)
    if ai_limits["enabled"]
    else ()
),
```

Build execution order with the common prefix through `activate`, append the
two failure stages only when AI is enabled, and then append the unchanged
non-AI tail beginning with `deploy`.

- [ ] **Step 4: Verify GREEN and authorization regressions**

Run:

```bash
.venv/bin/pytest tests/hosted/test_verify_azure_demo.py tests/hosted/test_run_hosted_failure_check.py tests/hosted/test_run_hosted_check.py -q
.venv/bin/ruff check tests/hosted/verify_azure_demo.py tests/hosted/test_verify_azure_demo.py
git diff --check
```

Expected: all tests pass, Ruff is clean, and diff check prints nothing.

- [ ] **Step 5: Commit the mode boundary**

```bash
git add tests/hosted/verify_azure_demo.py tests/hosted/test_verify_azure_demo.py
git commit -m "fix: permit restricted no-ai launch"
```

---

### Task 2: Document the conditional hosted order

**Files:**
- Modify: `docs/runbooks/DEPLOY.md`
- Test: `tests/hosted/test_verify_azure_demo.py`

**Interfaces:**
- Consumes: the exact enabled/disabled execution orders from Task 1.
- Produces: an operator-readable rule that failure rehearsals are mandatory only for AI-enabled packages and forbidden in restricted no-AI packages.

- [ ] **Step 1: Add the documentation contract test**

Add a test that reads `docs/runbooks/DEPLOY.md` and requires these exact
sentences:

```text
When `ai_limits.enabled=false`, both AI failure command groups are exact empty arrays and are omitted from `execution_order`.
When `ai_limits.enabled=true`, both AI failure rehearsals and the paid AI smoke remain mandatory.
```

- [ ] **Step 2: Run the contract test and verify RED**

Run:

```bash
.venv/bin/pytest tests/hosted/test_verify_azure_demo.py -q
```

Expected: the new runbook contract assertion fails because the current runbook
unconditionally lists both failure rehearsals.

- [ ] **Step 3: Update the runbook without weakening non-AI gates**

Add the two exact sentences immediately before the authorized release order.
Label the budget/provider steps inside the order as AI-enabled-only. State that
restricted mode still requires phase 2, health, core browser, capacity, natural
expiry, restart readback, and rollback/forward recovery.

- [ ] **Step 4: Verify GREEN and commit**

Run:

```bash
.venv/bin/pytest tests/hosted/test_verify_azure_demo.py -q
git diff --check
git add docs/runbooks/DEPLOY.md tests/hosted/test_verify_azure_demo.py
git commit -m "docs: define no-ai hosted order"
```

Expected: tests pass, diff check is empty, and the commit succeeds.

---

### Task 3: Rebuild immutable local release authority

**Files:**
- Delete in candidate: `release/task15-local-release-manifest.json`
- Create in manifest child: `release/task15-local-release-manifest.json`
- Verify: `scripts/verify_release.py`
- Verify: `scripts/create_release_manifest.py`
- Verify: `Dockerfile`

**Interfaces:**
- Consumes: the clean candidate commit from Tasks 1-2 and the exact currently deployed private candidate `8896d17d7c69c684e150b611e3066008842a240f` recorded by `scripts.create_release_manifest.DEFAULT_ROLLBACK_SHA`.
- Produces: a clean candidate SHA, `linux/amd64` image digest, image-input hash, and direct manifest-only attestation child.

- [ ] **Step 1: Retire the superseded attestation in the candidate**

If `release/task15-local-release-manifest.json` exists, delete only that file
with an explicit candidate commit:

```bash
git add release/task15-local-release-manifest.json
git commit -m "release: retire superseded no-ai attestation"
```

Expected: the commit contains only the deleted manifest. This preserves the
manifest-only direct-child invariant and prevents overwriting immutable prior
attestation evidence.

- [ ] **Step 2: Run the complete local release gate**

```bash
.venv/bin/python scripts/verify_release.py --manifest tests/fixtures/synthetic/v1/manifest.json
```

Expected: `release_verification=ok`; all required gate summaries pass and the
candidate remains clean and unchanged.

- [ ] **Step 3: Commit any final tracked verification-safe state**

If Step 1 leaves no tracked changes, use the current `HEAD` as `CANDIDATE`.
Otherwise commit only reviewed in-scope tracked files and rerun Step 1. Record:

```bash
CANDIDATE=$(git rev-parse HEAD)
CANDIDATE_TREE=$(git rev-parse 'HEAD^{tree}')
```

Expected: both values are lowercase 40-character Git hashes and `git status
--short` is empty.

- [ ] **Step 4: Compute the exact image input and build the image**

```bash
IMAGE_INPUT=$(.venv/bin/python -c 'from scripts.create_release_manifest import committed_image_input_sha256; import subprocess; sha=subprocess.check_output(["git","rev-parse","HEAD"], text=True).strip(); print(committed_image_input_sha256(sha))')
LOCAL_IMAGE="newcaostone-local:${CANDIDATE:0:12}"
docker buildx build --platform linux/amd64 --build-arg SOURCE_REVISION="$CANDIDATE" --build-arg IMAGE_INPUT_SHA256="$IMAGE_INPUT" --load -t "$LOCAL_IMAGE" .
IMAGE_DIGEST=$(docker image inspect "$LOCAL_IMAGE" --format '{{.Id}}')
```

Inspect the loaded image and require `linux/amd64`, user `bizpulse`, exact OCI
revision label, exact image-input label, and the no-access-log command. Require
`IMAGE_DIGEST` to match `sha256:<64 lowercase hex>`. The existing authorized
publisher will independently require the registry digest to equal this exact
local digest after later package approval; do not publish in this task.

- [ ] **Step 5: Create and commit the manifest-only child**

```bash
.venv/bin/python scripts/create_release_manifest.py --candidate-sha "$CANDIDATE"
git add release/task15-local-release-manifest.json
git diff --cached --name-only
git commit -m "task15: attest restricted no-ai candidate"
ATTESTATION=$(git rev-parse HEAD)
```

Expected: the staged-path check prints only
`release/task15-local-release-manifest.json`; `ATTESTATION^` equals
`CANDIDATE`.

- [ ] **Step 6: Fresh-verify the detached attestation**

```bash
.venv/bin/python scripts/create_release_manifest.py --verify-attestation
```

Expected: `release_attestation=ok` with the exact candidate and attestation
SHAs. This may rerun the full gate in a detached worktree.

---

### Task 4: Generate and validate the no-AI launch package

**Files:**
- Create outside Git: `.tmp/LAUNCH_AUTHORIZATION_NO_AI_RESTRICTED_V1.md`
- Verify: `tests/hosted/verify_azure_demo.py`

**Interfaces:**
- Consumes: the last approved package's exact Azure target/resource/cost fields, the new candidate/attestation/image authority, and read-only Azure state.
- Produces: one value-complete package whose SHA256 is the only approval target for resumed external execution.

- [ ] **Step 1: Refresh Azure state read-only**

Use the existing target subscription and resource group from the prior approved
package. Read the exact app FQDN, private ingress state, current revision,
resource SKUs, Jobs, ACR digests, PostgreSQL/Blob recovery configuration, and
deployment status. Do not change any resource. Stop if target, cost, or recovery
authority differs from the package template. For an existing private target,
set `recovery.target_mode="update"`, derive the future external URL from the
declared app plus the Azure-managed environment's exact `defaultDomain`, and
require the current app image to equal the manifest-bound rollback digest.

- [ ] **Step 2: Generate the value-complete restricted package**

Copy only the prior package's still-current Azure/resource/cost values. Generate
a fresh UUID authorization ID and a bounded expiry. Set the new candidate,
attestation, image digest, image-input hash, and local-manifest hash. Set:

```python
authority["ai_limits"]["enabled"] = False
authority["secret_presence"]["openai_api_key"] = False
authority["external_publication"]["paid_ai_smoke"] = False
authority["limits_usd"]["openai_smoke_cap"] = "0.00"
authority["commands"] = {
    stage: [shlex.join(command) for command in commands]
    for stage, commands in verifier._expected_commands(authority).items()
}
authority["execution_order"] = list(
    verifier._expected_execution_order(authority)
)
```

Write the package with mode `0600`. Do not include any secret value.

- [ ] **Step 3: Validate package and approval binding locally**

Run the verifier against the new file and its SHA. Require:

```text
launch_package=valid
approval_binding=matched
```

Also parse the JSON independently and assert empty `budget_failure`,
`provider_failure`, and `paid_ai_smoke` arrays; no corresponding execution
stages; AI disabled; zero OpenAI cap; no OpenAI secret presence or setting.

- [ ] **Step 4: Report the exact approval gate and stop**

Calculate:

```bash
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_NO_AI_RESTRICTED_V1.md
```

Report the full SHA256, candidate SHA, attestation SHA, image digest, expiry,
and the remaining hosted stages. Do not run registry publication, deployment,
health/browser/capacity/expiry, restart, or rollback until the user approves
that exact SHA.
