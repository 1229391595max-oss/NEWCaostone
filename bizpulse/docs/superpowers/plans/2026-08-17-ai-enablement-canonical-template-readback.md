# AI Enablement Canonical Template Readback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Azure Container Apps reconciliation compare only a strict,
canonical task-controlled template projection, then create a new R6
authorization package anchored to the healthy AI-disabled R5 candidate.

**Architecture:** The revision module gains a pure normalizer that accepts the
observed Azure provider defaults only when they have their documented default
values, then retains the same template shape emitted by
`build_ai_revision_patch`. Azure action callbacks normalize both application
and revision-list readbacks before the pure reconciliation state machine sees
them. The package generator records R5 as a consumed failed attempt and binds
R6 to the current healthy, AI-disabled revision.

**Tech Stack:** Python 3.12, pytest, Ruff, Azure CLI read-only queries, Docker
linux/amd64 build, Node.js local browser gate, owner-only authorization JSON.

## Global Constraints

- Work only on `codex/ai-enable-preset-buttons` in the existing isolated worktree.
- R5 package SHA is `0cd6205790d80d9d32d50b38c5bc1d5cbc3b5efd563e85fb5c0b653c9767cc46`; its failed receipt SHA is `325679c405534a94c1656ff37a8355c32c1eb9ddc2a919b065d16cd2fd4d3906`. Both remain mode-`0600` immutable evidence and are never replayed.
- Current hosted safe baseline is revision `newcaostone-demo-app--ai-off-0cd62057-f64d78a`, image `sellernorthbpacr.azurecr.io/bizpulse@sha256:f64d78a0368f84a061e1e0f5f1ca21bededf1173eeac7df53948652962d17556`, tag `ai-04d3037846c0-0cd62057`, one running replica, and `BIZPULSE_AI_CHAT_ENABLED=false`.
- Preserve the task-owned vault/UAMI absence, existing registry UAMI, R1/R2/R3 receipts, unexecuted R4 artifact, D3 artifact, preset catalog, budget limits, Keychain boundary, and zero auto-submit behavior.
- No task may perform an Azure write, ACR push, real OpenAI Key read/write, paid OpenAI call, deployment, or push. Only the final package generator may perform its existing nine Azure read-only gates and owner-only local package write.
- A new R6 SHA must receive separate user approval before its runner can reserve a receipt or mutate Azure.

---

### Task 1: Add a strict canonical Azure-template normalizer

**Files:**
- Modify: `scripts/azure_ai_revision.py`
- Modify: `tests/hosted/test_azure_ai_revision.py`

**Interfaces:**
- Produces `canonicalize_azure_template_readback(template: object) -> dict[str, Any]`.
- Consumes an Azure Container Apps raw `properties.template` mapping.
- Returns exactly the canonical template shape used by `build_ai_revision_patch`:
  `revisionSuffix`, one container with `name`, `image`, `env`, `probes`,
  `resources`, and scale `minReplicas` / `maxReplicas`.
- Raises `AzureAIRevisionInvalid("ai_revision_projection_invalid")` for any
  retained-field drift, missing required field, unknown field, or provider
  default with a non-default value.

- [ ] **Step 1: Write the failing default-field acceptance test**

  In `tests/hosted/test_azure_ai_revision.py`, import
  `canonicalize_azure_template_readback`. Build a valid canonical patch with
  the existing fixture, then inject the values observed in Azure:

  ```python
  raw = deepcopy(patch["properties"]["template"])
  raw["customMetricsSettings"] = None
  raw["initContainers"] = None
  raw["serviceBinds"] = None
  raw["terminationGracePeriodSeconds"] = None
  raw["volumes"] = None
  raw["scale"].update(
      {"cooldownPeriod": 300, "pollingInterval": 30, "rules": None}
  )
  raw["containers"][0]["imageType"] = "ContainerImage"

  assert canonicalize_azure_template_readback(raw) == patch["properties"]["template"]
  ```

- [ ] **Step 2: Write failing safety tests for retained/default fields**

  Add a parameterized test that changes exactly one field and expects the
  closed invalid code. Cover at least `imageType="Unknown"`,
  `cooldownPeriod=301`, `pollingInterval=29`, `rules=[]`,
  `terminationGracePeriodSeconds=30`, missing `image`, and a second container:

  ```python
  with pytest.raises(AzureAIRevisionInvalid, match="ai_revision_projection_invalid"):
      canonicalize_azure_template_readback(raw)
  ```

  Add one unknown template key (`"unrecognizedProviderField": None`) and
  assert it also fails. This proves the function does not silently accept
  future/provider-controlled configuration.

- [ ] **Step 3: Verify RED**

  Run:

  ```bash
  .venv/bin/pytest tests/hosted/test_azure_ai_revision.py -k canonicalize -q
  ```

  Expected: collection/import fails because
  `canonicalize_azure_template_readback` does not exist.

- [ ] **Step 4: Implement the minimal pure normalizer**

  In `scripts/azure_ai_revision.py`, introduce these exact provider-default
  contracts near the existing `_EXPECTED_*` constants:

  ```python
  _AZURE_TEMPLATE_DEFAULTS = {
      "customMetricsSettings": None,
      "initContainers": None,
      "serviceBinds": None,
      "terminationGracePeriodSeconds": None,
      "volumes": None,
  }
  _AZURE_SCALE_DEFAULTS = {
      "cooldownPeriod": 300,
      "pollingInterval": 30,
      "rules": None,
  }
  _AZURE_CONTAINER_DEFAULTS = {"imageType": "ContainerImage"}
  ```

  Implement `canonicalize_azure_template_readback` by requiring the exact
  union of canonical and provider-default keys at every level, checking the
  default mappings exactly, copying only the canonical subset, and validating
  it with the existing canonical template/environment validation. Extract a
  small internal `_validate_template(template: object) -> dict[str, Any]` from
  `_validate_projection` so the emitted patch and the readback use the same
  validation path. Do not loosen `_validate_environment`, image pinning,
  probes, resources, identity validation, or scale min/max validation.

- [ ] **Step 5: Verify GREEN and commit**

  Run:

  ```bash
  .venv/bin/pytest tests/hosted/test_azure_ai_revision.py -q
  .venv/bin/ruff check scripts/azure_ai_revision.py tests/hosted/test_azure_ai_revision.py
  git add scripts/azure_ai_revision.py tests/hosted/test_azure_ai_revision.py
  git commit -m "fix: canonicalize Azure revision template readback"
  ```

  Expected: all focused tests pass; the commit contains only the normalizer
  and its tests.

### Task 2: Normalize both reconciliation readbacks before comparison

**Files:**
- Modify: `scripts/azure_ai_enablement_actions.py`
- Modify: `tests/hosted/test_azure_ai_enablement_actions.py`
- Modify: `tests/hosted/test_azure_ai_reconciliation.py`

**Interfaces:**
- Consumes `canonicalize_azure_template_readback` from
  `scripts.azure_ai_revision`.
- The `application_reader` in `_verify_revision` returns a canonical
  application mapping. The `revisions_reader` returns each row with a canonical
  `properties.template`.
- `reconcile_ai_transition` remains a pure state machine and compares only
  canonical projections.

- [ ] **Step 1: Write the failing integration test using Azure-shaped responses**

  Add a helper in `tests/hosted/test_azure_ai_enablement_actions.py` that
  decorates `_app()["properties"]["template"]` with the observed provider
  defaults. Configure the injected runner so the `containerapp show` and
  `revision list` commands return that raw template, while the expected pending
  patch remains canonical. Drive `_verify_revision` for an
  `ai_disabled_candidate` pending transition and assert closed success evidence:

  ```python
  assert evidence["role"] == "ai_disabled_candidate"
  assert evidence["final_state"] == "healthy_target"
  assert evidence["application_read_count"] == 1
  assert evidence["revision_read_count"] == 1
  ```

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  .venv/bin/pytest tests/hosted/test_azure_ai_enablement_actions.py \
    -k azure_default_template_readback -q
  ```

  Expected: FAIL with `ai_enablement_revision_unverified` or
  `ai_reconciliation_drift`, proving raw Azure defaults are still being passed
  through.

- [ ] **Step 3: Normalize application and revision callbacks**

  Import the normalizer into `scripts/azure_ai_enablement_actions.py`. In
  `_verify_revision`, preserve the current Azure CLI commands and one-MiB
  output limits, but replace raw template copies with:

  ```python
  canonical_template = canonicalize_azure_template_readback(
      properties.get("template")
  )
  ```

  Use that `canonical_template` in the application projection and map every
  revision row through the same function. Convert an invalid normalization to
  the existing closed `ai_enablement_revision_unverified` path; do not expose
  Azure output, error text, environment values, or credentials.

- [ ] **Step 4: Add regression rejection tests**

  In the same integration fixture, alter one retained task-controlled field
  (`BIZPULSE_AI_CHAT_ENABLED`, digest image, `minReplicas`, probe path, or
  secret reference name) and assert `_verify_revision` fails closed. Alter one
  provider default to a non-default value and assert the same. Keep the pure
  reconciliation tests canonical so they continue to demonstrate that the
  state machine is independent of Azure transport shapes.

- [ ] **Step 5: Verify GREEN and commit**

  Run:

  ```bash
  .venv/bin/pytest tests/hosted/test_azure_ai_reconciliation.py \
    tests/hosted/test_azure_ai_enablement_actions.py \
    tests/hosted/test_azure_ai_revision.py -q
  .venv/bin/ruff check scripts/azure_ai_enablement_actions.py \
    scripts/azure_ai_revision.py \
    tests/hosted/test_azure_ai_enablement_actions.py \
    tests/hosted/test_azure_ai_reconciliation.py \
    tests/hosted/test_azure_ai_revision.py
  git add scripts/azure_ai_enablement_actions.py \
    tests/hosted/test_azure_ai_enablement_actions.py \
    tests/hosted/test_azure_ai_reconciliation.py
  git commit -m "fix: reconcile canonical Azure templates"
  ```

  Expected: existing transition drift/timeout tests remain green, and only
  Azure-injected defaults are ignored.

### Task 3: Advance package controls from consumed R5 to fresh R6

**Files:**
- Modify: `scripts/create_ai_enablement_package.py`
- Modify: `tests/hosted/test_create_ai_enablement_package.py`
- Modify: `docs/runbooks/AI_ENABLEMENT.md`

**Interfaces:**
- `ARTIFACTS` becomes the exclusive R6 package, receipt, and observation paths.
- `PRIOR_AI_ATTEMPTS` retains R1/R2/R3 started receipts and adds the exact R5
  failed receipt contract.
- `capture_prior_ai_attempts()` verifies both the file SHA-256 and the exact
  safe receipt shape appropriate to each attempt.

- [ ] **Step 1: Write failing R6 prior-attempt and path tests**

  Update `tests/hosted/test_create_ai_enablement_package.py` with assertions:

  ```python
  assert ARTIFACTS == {
      "package_path": ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R6_2026-08-17.json",
      "receipt_path": ".tmp/AI_ENABLEMENT_RECEIPT_R6_2026-08-17.json",
      "observation_path": ".tmp/AI_ENABLEMENT_OBSERVATION_R6_2026-08-17.json",
  }
  assert PRIOR_AI_ATTEMPTS["r5"]["package_sha256"] == (
      "0cd6205790d80d9d32d50b38c5bc1d5cbc3b5efd563e85fb5c0b653c9767cc46"
  )
  assert PRIOR_AI_ATTEMPTS["r5"]["receipt_sha256"] == (
      "325679c405534a94c1656ff37a8355c32c1eb9ddc2a919b065d16cd2fd4d3906"
  )
  ```

  Add a temporary-owner-only R5-style failed receipt fixture and assert
  `capture_prior_ai_attempts` accepts only the full safe v2 shape:

  ```python
  {
      "schema_version": "newcaostone.ai-enablement-attempt.v2",
      "package_sha256": r5_package_sha,
      "state": "failed",
      "failure_code": "ai_enablement_operation_failed",
      "completed_states": [
          "readonly_revalidation",
          "publish_candidate_image",
          "activate_ai_disabled_candidate",
      ],
      "reconciliations": [],
      "recovery": None,
  }
  ```

- [ ] **Step 2: Verify RED**

  Run:

  ```bash
  .venv/bin/pytest tests/hosted/test_create_ai_enablement_package.py \
    -k 'r5 or r6 or prior_attempts' -q
  ```

  Expected: the R6 path assertion fails and the R5 failed receipt is rejected
  by the old started-v1-only parser.

- [ ] **Step 3: Implement strict R6 constants and receipt variants**

  Update the generator constants to:

  ```python
  ROLLBACK_REVISION = "newcaostone-demo-app--ai-off-0cd62057-f64d78a"
  ROLLBACK_DIGEST = "f64d78a0368f84a061e1e0f5f1ca21bededf1173eeac7df53948652962d17556"
  ROLLBACK_REGISTRY_TAG = "ai-04d3037846c0-0cd62057"
  ```

  Change `ARTIFACTS` to R6 paths. Add R5 to `PRIOR_AI_ATTEMPTS` with a
  `receipt_contract` mapping containing the exact v2 failed shape above.
  Give each existing attempt its exact v1 started `receipt_contract` too, then
  have `capture_prior_ai_attempts` compare the parsed receipt to that mapping
  after verifying owner-only mode and SHA-256. This preserves every historical
  receipt without interpreting arbitrary remote content.

- [ ] **Step 4: Update the runbook and test all package controls**

  Replace R5 package/receipt/observation command paths and rollback anchors in
  `docs/runbooks/AI_ENABLEMENT.md` with R6 values. State that R5 is a consumed
  partial attempt: candidate publication and AI-disabled activation happened,
  but its v2 failed receipt prevents replay. Keep the real Key prompt boundary
  unchanged.

- [ ] **Step 5: Verify GREEN and commit**

  Run:

  ```bash
  .venv/bin/pytest tests/hosted/test_create_ai_enablement_package.py \
    tests/hosted/test_run_ai_enablement.py \
    tests/hosted/test_ai_enablement_contract.py -q
  .venv/bin/ruff check scripts/create_ai_enablement_package.py \
    tests/hosted/test_create_ai_enablement_package.py
  git add scripts/create_ai_enablement_package.py \
    tests/hosted/test_create_ai_enablement_package.py \
    docs/runbooks/AI_ENABLEMENT.md
  git commit -m "chore: prepare fresh R6 AI authorization"
  ```

### Task 4: Verify locally and generate the approval-only R6 artifact

**Files:**
- Local ignored artifact: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R6_2026-08-17.json`
- Local ignored paths that must remain absent before generation:
  `.tmp/AI_ENABLEMENT_RECEIPT_R6_2026-08-17.json` and
  `.tmp/AI_ENABLEMENT_OBSERVATION_R6_2026-08-17.json`

**Interfaces:**
- Consumes the committed R6 controls, clean Git snapshot, canonical template
  tests, local linux/amd64 image label, existing D3 artifacts, and nine
  sanitized Azure reads.
- Produces one mode-`0600`, 24-hour R6 package and its SHA-256 only. It does
  not reserve a receipt, push an image, mutate Azure, read a real Key, or make
  a paid call.

- [ ] **Step 1: Run the complete local verification suite**

  Run:

  ```bash
  .venv/bin/python scripts/verify_changed.py --base 80ae274
  .venv/bin/pytest tests/hosted/test_azure_ai_reconciliation.py \
    tests/hosted/test_azure_ai_revision.py \
    tests/hosted/test_azure_ai_enablement_actions.py \
    tests/hosted/test_create_ai_enablement_package.py \
    tests/hosted/test_run_ai_enablement.py \
    tests/hosted/test_ai_enablement_contract.py -q
  npm test
  ```

  Expected: all local tests pass. If any command fails, stop before Docker or
  Azure package generation and repair only the diagnosed local defect.

- [ ] **Step 2: Rebuild and inspect the local-only deployment image**

  Run the existing repository image-build command with a local tag derived
  from the final commit. Inspect its Linux/amd64 platform, non-root user,
  revision label, and `org.newcaostone.bizpulse.image-input-sha256` label.
  Require the image-input label to equal
  `committed_image_input_sha256(HEAD)`. Do not log in to ACR or push.

- [ ] **Step 3: Verify fresh R6 read-only authority and generate package**

  Ensure the three R6 artifact paths are absent. Run the existing package
  command using the R6 paths, current safe rollback revision/image/tag, and
  existing target identifiers:

  ```bash
  .venv/bin/python scripts/create_ai_enablement_package.py \
    --output .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R6_2026-08-17.json \
    --receipt .tmp/AI_ENABLEMENT_RECEIPT_R6_2026-08-17.json \
    --observation .tmp/AI_ENABLEMENT_OBSERVATION_R6_2026-08-17.json \
    --subscription fc89e7d3-5428-425e-863f-415859810c2c \
    --tenant 13d04c38-d91c-4f9f-8b65-6af2b515dd63 \
    --resource-group rg-bizpulse-centralus \
    --location centralus \
    --app newcaostone-demo-app \
    --registry sellernorthbpacr \
    --log-workspace newcaostone-demo-logs \
    --registry-identity newcaostone-demo-registry \
    --rollback-revision newcaostone-demo-app--ai-off-0cd62057-f64d78a \
    --rollback-image sellernorthbpacr.azurecr.io/bizpulse@sha256:f64d78a0368f84a061e1e0f5f1ca21bededf1173eeac7df53948652962d17556 \
    --rollback-registry-tag ai-04d3037846c0-0cd62057 \
    --vault newcaostone-ai-kv \
    --identity newcaostone-ai-identity
  ```

  Expected: exactly nine sanitized Azure reads, one exclusive local package
  write with mode `0600`, and R6 receipt/observation paths still absent.

- [ ] **Step 4: Validate and hand off the package**

  Run:

  ```bash
  shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R6_2026-08-17.json
  stat -f '%N %Lp %z' .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R6_2026-08-17.json
  .venv/bin/python -c 'from pathlib import Path; from scripts.create_ai_enablement_package import load_ai_enablement_package; load_ai_enablement_package(Path(".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R6_2026-08-17.json")); print("r6_package=validated")'
  ```

  Report the exact R6 SHA, expiry, safe rollback anchor, local test evidence,
  and the fact that no Azure mutation/ACR push/real Key/paid call occurred.
  Stop for a new exact user approval; do not run `run_ai_enablement.py`.
