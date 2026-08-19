# BizPulse Key Vault AI Enablement and Prompt Preset Restoration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. The user selected Inline Execution, so execute this plan in the current task with review checkpoints and without creating a separate task.

**Goal:** Keep the restored six bilingual Ask BizPulse prompt presets, replace process-environment OpenAI key loading with a task-owned Azure Key Vault public endpoint plus RBAC and a dedicated user-assigned managed identity, verify the disabled and failure-safe paths locally, and create a fresh exact-SHA 24-hour approval package that contains no key and performs no cloud or paid action.

**Architecture:** The browser receives only server-owned prompt catalog metadata and never receives a key. The FastAPI process receives a vault URL, exact secret name, and dedicated managed-identity client ID; an application-owned provider lazily retrieves the key immediately before the OpenAI call, keeps it only in memory for at most 60 seconds, creates a short-lived SDK client, and fails closed without a stale-key fallback. One inert Bicep deployment creates only the new vault, identity, diagnostic settings, and least-privilege Key Vault Secrets User assignment; a second inert template contains exactly the one secret write so the approved runner can deliver its `@secure()` value over child stdin without granting the local operator Key Vault data-plane access. A hosted runner later uses narrow resource projections and exact checkpoints so it never reads or rewrites the existing Container Apps secrets, existing Key Vault, or unrelated credentials.

**Implementation status:** Tasks 1–5 are committed locally. Task 6 code is locally implemented and under final verification; the exact 24-hour package has not yet been created. No Azure mutation, provider call, public Demo access, image publication, push, PR, or CI has occurred.

**Tech Stack:** Python 3.12, FastAPI, OpenAI Python SDK 2.52.0, Azure Identity 1.25.3, Azure Key Vault Secrets 4.11.0, PostgreSQL, Node test runner, Azure Bicep/ARM, Azure CLI, Playwright browser verification.

**Working directory:** Run repository commands from `bizpulse/` unless a command explicitly starts at the worktree root.

**Batch/worktree anchors:** `BATCH_BASE_SHA=afd3a2f0a9311aafaca35ad4a412c911aadf1e32`, branch `codex/ai-enable-preset-buttons`, isolated worktree `/Users/maxli/Desktop/NEWCaostone/.worktrees/ai-enable-preset-buttons`. Revalidate all three before generating the final package.

## Global Constraints

- Preserve the D3 package, branch, attestation absence, receipt absence, and observation absence byte-for-byte. CAPTSONE remains read-only.
- Do not access macOS Keychain, ask for or handle a real key, open the public Demo URL, call OpenAI, publish an image, mutate Azure, push, create a PR, or start CI while implementing this plan.
- No direct Container Apps OpenAI secret and no reuse of the existing `sellernorthbp-kv`, registry identity, PostgreSQL secret, Operator secret, session secret, or Blob credentials.
- The selected network posture is a new task-owned Key Vault Standard public endpoint with Azure RBAC. Private endpoint, firewall allowlisting, and the proposed Demo passcode are explicitly outside this batch.
- The Demo passcode would protect only Demo admission/abuse; it would not make a public Key Vault endpoint private and is not a substitute for RBAC.
- The provider endpoint is exactly `https://api.openai.com/v1`; proxy, alternate, Azure OpenAI, loopback, and browser-provided endpoints remain rejected.
- Preserve one fixed provider/budget contract everywhere: OpenAI Platform Responses API, model `gpt-5.4-nano-2026-03-17`, reasoning `low`, 120 daily provider attempts, 150,000 monthly total tokens, 3 session attempts/minute, 20 global attempts/minute, 15 concurrent turns, 2,800 maximum output tokens, 30-second provider timeout, zero retries, and no tools.
- A Key Vault lookup failure makes the AI turn unavailable, makes zero OpenAI request, exposes no secret detail, and conservatively retains the already-created budget reservation under the existing failure semantics.
- Write a failing focused test before each production behavior change. Record the RED reason, then implement the minimum GREEN change.
- Keep deterministic calculations and stored evidence authoritative. Prompt presets only populate the editor; they do not import, upload, calculate, write data, simulate actions, or auto-submit.
- Every completion statement must separate local implementation, local verification, package generation, approval, Azure execution, hosted verification, and Production readiness.

## Completed Prerequisites (Do Not Reimplement)

- Commit `a66958b` restored the six exact EN/ZH server-owned catalog entries, disabled-visible behavior, exact template validation, editor fill/focus/no-auto-submit behavior, draft replacement dialog, and preset audit quartet.
- Commit `18e9d16` locked the provider to the official OpenAI base URL and removed the obsolete Bicep endpoint override.
- Commit `9761e80` made the budget failure rehearsal preserve the exact 150,000-token monthly limit with zero provider call and zero ledger mutation.
- Commit `256ea7f` recorded the approved task-owned Key Vault, dedicated UAMI, public endpoint, and RBAC design while excluding the Demo passcode.
- Re-run the relevant regression suites after the implementation below; change completed prerequisite code only if a new RED test proves a real regression.

## Task 1: Add Fail-Closed Key Vault Configuration and Reproducible Dependencies

**Files:**

- Modify: `bizpulse/src/config.py`
- Create temporarily (ignored, do not commit): `.tmp/requirements-runtime.in`
- Create temporarily (ignored, do not commit): `.tmp/requirements-dev.in`
- Modify: `bizpulse/requirements.txt`
- Modify: `bizpulse/requirements-dev.txt`
- Test: `bizpulse/tests/unit/test_config.py`
- Test: `bizpulse/tests/release/test_container_contract.py`

**Interface:** Extend `BizPulseSettings` with:

```python
openai_key_vault_url: str | None
openai_key_vault_secret_name: str | None
openai_managed_identity_client_id: str | None
```

Use only these environment names:

```text
BIZPULSE_OPENAI_KEY_VAULT_URL
BIZPULSE_OPENAI_KEY_VAULT_SECRET_NAME
BIZPULSE_OPENAI_MANAGED_IDENTITY_CLIENT_ID
```

The enabled production configuration requires HTTPS Azure Key Vault host syntax, exact secret name `openai-api-key`, and a UUID client ID. Disabled configuration rejects stale values. `OPENAI_API_KEY` is not an application configuration input and must not appear in Container Apps environment variables.

- [ ] Add focused RED tests for missing, partial, malformed, non-HTTPS, non-Azure-host, wrong-secret-name, and invalid-client-ID bindings when AI is enabled.
- [ ] Add focused RED tests showing AI-disabled settings reject all three stale Key Vault bindings and reject a direct `OPENAI_API_KEY` application path.
- [ ] Preserve an explicit test-only construction path for unit tests that inject a fixed fake client without reading process environment secrets.
- [ ] Run RED:

  ```bash
  .venv/bin/python -m pytest tests/unit/test_config.py tests/release/test_container_contract.py -q
  ```

- [ ] Implement parsing and validation in `src/config.py`; error messages name only the invalid field and never echo values.
- [ ] Reconstruct `.tmp/requirements-runtime.in` from the lock's direct packages and add `azure-identity==1.25.3` plus `azure-keyvault-secrets==4.11.0`. Reconstruct `.tmp/requirements-dev.in` with the existing runtime constraint and direct dev packages; do not infer or upgrade any unrelated direct version.
- [ ] Create `bizpulse/.venv`, install `pip-tools==7.5.2`, and regenerate both hashed lock files from the worktree root without changing the D3 environment:

  ```bash
  bizpulse/.venv/bin/pip-compile --generate-hashes --strip-extras \
    --output-file=bizpulse/requirements.txt .tmp/requirements-runtime.in
  bizpulse/.venv/bin/pip-compile --generate-hashes --strip-extras \
    --output-file=bizpulse/requirements-dev.txt .tmp/requirements-dev.in
  ```
- [ ] Run GREEN with the same command, then install the two locks into the task-local environment and re-run the focused tests.
- [ ] Verify no direct secret surface:

  ```bash
  rg -n 'OPENAI_API_KEY|openaiApiKey|openai-api-key' src api frontend infra scripts tests \
    -g '!tests/unit/test_config.py' -g '!tests/infra/test_ai_enablement_bicep.py'
  ```

- [ ] Commit: `feat: add fail-closed Key Vault AI settings`

## Task 2: Implement Lazy In-Memory Key Retrieval and Gateway Integration

**Files:**

- Create: `bizpulse/src/secrets/__init__.py`
- Create: `bizpulse/src/secrets/azure_openai.py`
- Modify: `bizpulse/src/ai/openai_gateway.py`
- Test: `bizpulse/tests/unit/secrets/test_azure_openai.py`
- Test: `bizpulse/tests/services/test_ai_chat_service.py`
- Test: `bizpulse/tests/security/test_ai_chat_boundary.py`

**Interfaces:**

```python
class OpenAIClientProvider(Protocol):
    @contextmanager
    def acquire(self) -> Iterator[OpenAIClientProtocol]: ...
    def close(self) -> None: ...

class FixedOpenAIClientProvider:
    def __init__(self, client: OpenAIClientProtocol) -> None: ...

class AzureOpenAIClientProvider:
    def __init__(
        self,
        *,
        vault_url: str,
        secret_name: str,
        managed_identity_client_id: str,
        cache_ttl_seconds: float = 60.0,
        credential: TokenCredential | None = None,
        secret_client: SecretClient | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None: ...
```

`AzureOpenAIClientProvider.acquire()` calls a `SecretClient` configured with SDK retries disabled, uses `ManagedIdentityCredential(client_id=...)`, sets 5-second connect/read transport timeouts, validates a nonblank secret, keeps only an in-memory value plus monotonic expiry, constructs `OpenAI(api_key=..., base_url="https://api.openai.com/v1")`, and never returns or logs the key. `close()` clears cached references and closes SDK resources. `repr()`/exceptions contain no secret value.

- [ ] Add RED tests for lazy retrieval, exact vault/name/client ID, one fetch inside 60 seconds, refresh after expiry, no stale fallback after an expired refresh failure, blank-secret rejection, retry count zero, timeout configuration, safe `repr`, safe mapped error, and idempotent close.
- [ ] Add RED tests that `OpenAIGateway` acquires a client only at the provider stage, uses the existing model/timeout/retry controls, and releases it after success or failure.
- [ ] Add RED tests that Key Vault authentication, authorization, timeout, not-found, disabled-secret, and transport failures make zero OpenAI call and expose only `AI currently unavailable` through the API boundary.
- [ ] Run RED:

  ```bash
  .venv/bin/python -m pytest \
    tests/unit/secrets/test_azure_openai.py \
    tests/services/test_ai_chat_service.py \
    tests/security/test_ai_chat_boundary.py -q
  ```

- [ ] Implement the provider without module-level credential/client creation and without environment fallback.
- [ ] Change `OpenAIGateway` to depend on `OpenAIClientProvider`, retaining `FixedOpenAIClientProvider` for fake-client tests.
- [ ] Ensure the gateway never retries a secret failure or an OpenAI failure and never places secret/provider exception text in logs, metrics, API payloads, or persisted chat messages.
- [ ] Run GREEN with the same command.
- [ ] Run gateway/service regressions:

  ```bash
  .venv/bin/python -m pytest tests/services/test_ai_chat_container.py tests/api/v1/test_ai_chat.py -q
  ```

- [ ] Commit: `feat: load OpenAI key lazily from Key Vault`

## Task 3: Wire Application Construction and Deterministic Shutdown

**Files:**

- Modify: `bizpulse/api/container.py`
- Modify: `bizpulse/api/main.py`
- Test: `bizpulse/tests/services/test_ai_chat_container.py`
- Test: `bizpulse/tests/api/test_application_shell.py`
- Test: `bizpulse/tests/api/v1/test_ai_chat.py`

**Construction rule:** `ApiContainer.build(settings, openai_client=None)` must no longer call `OpenAI()` directly. When enabled and no test client is injected, it constructs one `AzureOpenAIClientProvider` from validated settings and supplies it to `OpenAIGateway`. When disabled, it constructs neither Azure credential nor SecretClient nor OpenAI client. The FastAPI lifespan closes the container/provider once.

- [ ] Add RED tests proving disabled construction creates zero Azure/OpenAI objects, enabled construction uses only the three validated Key Vault settings, injected fake clients remain supported, and no process environment key is read.
- [ ] Add RED lifespan tests for one close on normal shutdown and one close after startup/request failure.
- [ ] Run RED:

  ```bash
  .venv/bin/python -m pytest \
    tests/services/test_ai_chat_container.py tests/api/test_application_shell.py tests/api/v1/test_ai_chat.py -q
  ```

- [ ] Implement container ownership and a synchronous or asynchronous `close()` matching the existing lifespan style.
- [ ] Preserve the always-present prompt catalog and AI-disabled list route from the completed prerequisite.
- [ ] Run GREEN with the same command.
- [ ] Run the guarded PostgreSQL prompt audit regressions:

  ```bash
  .venv/bin/python scripts/test_postgres.py \
    tests/postgres/test_0008_ai_budget_ledger.py \
    tests/postgres/test_0009_prompt_preset_audit.py -q
  ```

- [ ] Commit: `feat: wire managed identity AI client lifecycle`

## Task 4: Create an Isolated, Inert Key Vault/UAMI Deployment and Safe App Projection

**Files:**

- Create: `bizpulse/infra/ai_enablement.bicep`
- Create: `bizpulse/infra/ai_secret_write.bicep`
- Create: `bizpulse/infra/environments/ai_enablement.bicepparam`
- Create: `bizpulse/infra/environments/ai_secret_write.bicepparam`
- Create: `bizpulse/scripts/azure_ai_revision.py`
- Modify: `bizpulse/infra/main.bicep`
- Modify: `bizpulse/infra/modules/app.bicep`
- Test: `bizpulse/tests/infra/test_ai_enablement_bicep.py`
- Test: `bizpulse/tests/infra/test_bicep_contract.py`
- Test: `bizpulse/tests/hosted/test_azure_ai_revision.py`

**Bicep boundary:** The separate template is inert unless `deploymentEnabled=true`. It creates exactly:

- one new task-owned Standard Key Vault with `enableRbacAuthorization: true`, public network access enabled, soft delete, and purge protection;
- one dedicated user-assigned managed identity;
- one Key Vault Secrets User role assignment using role definition ID `4633458b-17de-408a-b874-0445c86b69e6`, scoped only to that vault;
- diagnostic settings that emit audit/resource logs to the already-approved destination without granting data access.

The second template references only the new vault and writes exactly one
`openai-api-key` child resource from an `@secure()` parameter. The runner sends
that parameter document over child stdin. It never appears in argv or a file.

Use stable API versions where available: Key Vault and secret `2025-05-01`, UAMI `2023-01-31`, role assignment `2022-04-01`, diagnostics `2021-05-01-preview`. Do not read existing Key Vault resources or existing Container Apps secrets.

**Revision interface:** `scripts/azure_ai_revision.py` accepts a sanitized current Container App projection and creates enabled/disabled JSON Merge Patch bodies containing only `location`, the dedicated UAMI identity map, and `properties.template`. It rejects inline secret values, unknown environment names, an `OPENAI_API_KEY` variable, a non-official endpoint, and any attempt to include `properties.configuration.secrets`.

- [ ] Add RED static and compiled-template tests for the exact resource allowlist, public endpoint/RBAC posture, dedicated UAMI, one-secret vault, secure parameter, role scope, purge protection, diagnostics, deterministic names/outputs, inert default, and absence of existing vault/secret/identity names.
- [ ] Add RED tests proving `infra/main.bicep` and `infra/modules/app.bicep` contain no direct OpenAI key parameter, secret, or environment binding.
- [ ] Add RED transformer tests for enabled and disabled revisions plus rejection of secret `value`, unrelated identity mutation, unrelated environment mutation, configuration secret projection, and missing current revision anchors.
- [ ] Run RED:

  ```bash
  .venv/bin/python -m pytest \
    tests/infra/test_ai_enablement_bicep.py tests/infra/test_bicep_contract.py \
    tests/hosted/test_azure_ai_revision.py -q
  ```

- [ ] Implement the isolated Bicep template and an inert parameter file where `deploymentEnabled=false` and the secure key parameter defaults from `BIZPULSE_DEPLOY_OPENAI_API_KEY` only for the separately approved child process.
- [ ] Remove obsolete direct Container Apps OpenAI secret wiring from the existing templates.
- [ ] Implement the revision transformer with pure functions and deterministic JSON so all behavior is locally testable.
- [ ] Compile templates without deployment:

  ```bash
  az bicep build --file infra/ai_enablement.bicep --stdout >/dev/null
  az bicep build-params --file infra/environments/ai_enablement.bicepparam --stdout >/dev/null
  az bicep build --file infra/main.bicep --stdout >/dev/null
  ```

- [ ] Run GREEN with the same focused test command.
- [ ] Commit: `infra: isolate Key Vault AI enablement`

## Task 5: Replace Broad Hosted Failure Deployment with Bounded Rehearsals

**Files:**

- Modify: `bizpulse/scripts/run_hosted_failure_check.py`
- Create: `bizpulse/scripts/ai_enablement_contract.py`
- Test: `bizpulse/tests/hosted/test_run_hosted_failure_check.py`
- Create: `bizpulse/tests/hosted/test_ai_enablement_contract.py`
- Modify only if required by a RED regression: `bizpulse/scripts/qualify_openai_model.py`

**Contract states:**

```text
readonly_revalidation
publish_candidate_image
activate_ai_disabled_candidate
verify_ai_disabled_candidate
create_ai_vault_identity_role_diagnostics
budget_failure_rehearsal
provider_failure_placeholder_write
provider_failure_rehearsal
paid_model_qualification
real_secret_write
activate_ai_enabled_revision
verify_ai_enabled_revision
paid_hosted_manual_send_smoke
sanitize_receipt
```

Every state has exact preconditions, allowed Azure operation classes, maximum counts, expected safe evidence, a stop-on-drift rule, and a resume token bound to package SHA, candidate image digest, revision, subscription, tenant, resource group, app, vault, identity, model, and expiry.

- [ ] Add RED tests proving `run_hosted_failure_check.py` does not perform a full resource-group deployment, does not pass or enumerate existing secrets, and uses only the sanitized revision patch.
- [ ] Add RED contract tests for strict state order, the fixed 12-case paid model qualification followed by exactly one hosted manual-send smoke, exact 150,000 monthly budget, all fixed session/global/daily/monthly/concurrency/output/timeout/retry/tool limits, zero-ledger budget rehearsal, conservative reservation on provider failure, placeholder overwrite before real secret write, and terminal receipt sanitization.
- [ ] Add RED tests that a first mismatch stops immediately without retry, cleanup, fallback deployment, secret read, owner change, or next-state action.
- [ ] Run RED:

  ```bash
  .venv/bin/python -m pytest \
    tests/hosted/test_run_hosted_failure_check.py \
    tests/hosted/test_ai_enablement_contract.py -q
  ```

- [ ] Refactor failure rehearsal to generate and apply only an allowlisted app revision patch after later approval; keep the current implementation dry-run-only in local tests.
- [ ] Implement the pure contract validator/state transition model. It must never accept a raw key in arguments, JSON, package files, receipts, or logs.
- [ ] Preserve model qualification's exact model allowlist, exactly 12 synthetic qualification calls, and one hosted manual-send smoke.
- [ ] Run GREEN with the same command.
- [ ] Commit: `fix: bound hosted AI failure rehearsals`

## Task 6: Build the 24-Hour Exact-SHA Approval Package and Runner

**Files:**

- Create: `bizpulse/scripts/create_ai_enablement_package.py`
- Create: `bizpulse/scripts/run_ai_enablement.py`
- Create: `bizpulse/tests/hosted/test_create_ai_enablement_package.py`
- Create: `bizpulse/tests/hosted/test_run_ai_enablement.py`
- Create: `bizpulse/docs/runbooks/AI_ENABLEMENT.md`
- Create: `docs/handoffs/AI_ENABLEMENT_2026-08-17.md`

**Package contents:** sanitized manifest, exact Git SHA/tree, dirty-state assertion, candidate image source plus an explicitly unset digest field at creation, Azure authority anchors, resource allowlist, operation sequence/counts, Bicep/template hashes, runner hash, expected safe observations, expiry exactly 24 hours after creation, abort conditions, and an approval field that is empty at creation. It contains no key, Keychain locator, public Demo URL, existing secret names/values, access token, refresh token, cookie, database URL, or operator/session credential.

**Runner secret boundary:** Only after a separate user message approves the fresh package's exact SHA-256 does the runner show a local hidden-input prompt. The qualification child alone receives the value in `BIZPULSE_DEPLOY_OPENAI_API_KEY`; the one-secret Bicep deployment receives it only in an ARM secure-parameter document over child stdin. It never enters argv, file, Git, shell trace, log, receipt, browser, Container Apps configuration secret, or the inherited parent environment. The runner clears each child scope, performs the exact local, D3, Azure and price preflight, and reserves a durable `0600` started receipt before mutation. It requests the key only after both zero-paid rehearsals have returned to a freshly verified AI-disabled revision.

- [ ] Add RED package tests for deterministic serialization, mode `0600`, exact 24-hour expiry, complete allowlist/counts, current clean SHA/tree, blank approval, D3 invariants, and prohibited-field scans.
- [ ] Add RED runner tests for package hash/expiry/approval mismatch, authority drift, dirty tree, image digest drift, state mismatch, missing key, key-shaped argv/file/output content, non-TTY execution, interrupted execution, and first-failure immediate stop.
- [ ] Add RED runner tests with a sentinel fake key proving it exists only in the mocked child environment/in-memory secret request and is absent from subprocess argv, filesystem snapshots, captured stdout/stderr, manifest, receipt, and environment after child exit.
- [ ] Run RED:

  ```bash
  .venv/bin/python -m pytest \
    tests/hosted/test_create_ai_enablement_package.py \
    tests/hosted/test_run_ai_enablement.py -q
  ```

- [ ] Implement package creation as a local read-only operation and runner execution as locked until exact package authorization is present.
- [ ] Write the runbook with preparation, approval syntax, per-state expected evidence, failure recovery, placeholder-overwrite lifecycle, paid-call boundaries, rollback, sanitization, and explicit evidence-state language.
- [ ] Run GREEN with the same command.
- [ ] Run prohibited-source verification against the package fixtures and scripts.
- [ ] Commit: `feat: package gated AI enablement`

## Task 7: Full Local Verification, Browser Evidence, and Final Stop Gate

**Files:**

- Modify only when a test proves a gap: existing prompt/frontend/API files
- Create: `bizpulse/tests/browser/ask-bizpulse-presets.spec.mjs` if no equivalent browser test exists
- Create local evidence under an ignored task directory; do not commit screenshots containing user data or URLs
- Create one fresh package under the approved private package directory with mode `0600`

- [ ] Run all Python tests with the task-local locked environment and record exact pass/fail counts.
- [ ] Run guarded PostgreSQL tests and record exact pass/fail counts separately.
- [ ] Run all Node frontend tests:

  ```bash
  node --test tests/frontend/*.test.mjs
  ```

- [ ] Run all Bicep compile/static tests and `git diff --check`.
- [ ] Run the mandated authority and release checks without package reuse:

  ```bash
  .venv/bin/python scripts/check_authority_contract.py
  .venv/bin/python scripts/verify_changed.py --no-reuse
  .venv/bin/python scripts/verify_release.py
  ```

- [ ] Reconfirm the safe Azure read-only projection against the recorded subscription, tenant, resource group, app, ready revision, traffic, image digest, identities, and AI-disabled environment-name/secret-reference set. Do not request any API shape that returns secret values.
- [ ] Start the app locally with fake/injected provider behavior only. Do not put a real or sentinel key into the browser process.
- [ ] Use browser verification to capture English and Chinese views where all six exact buttons are visible.
- [ ] Capture enabled interaction evidence: clicking a preset inserts the current-locale server template, focuses the textarea, and produces zero chat-submit request until the user manually clicks Send.
- [ ] Capture draft evidence: existing text opens the Replace / Continue editing confirmation, keyboard focus is contained, Escape keeps the draft, Replace inserts the template, and no click auto-submits.
- [ ] Capture disabled evidence: all six buttons remain visible/disabled with clear `AI currently unavailable`, keyboard/ARIA state is correct, and the browser network log shows zero preset/provider request.
- [ ] Capture one fake-provider manual-send failure/success display only as appropriate; do not label it a hosted or real OpenAI result.
- [ ] In the separately authorized hosted execution, require the public Azure Demo Viewer path to complete one real manual-send turn with Demo session/CSRF, preset audit quartet, store/workspace scope and synchronized attempt/ledger evidence. Operator-only or localhost success is insufficient.
- [ ] Scan browser artifacts, logs, screenshots metadata, built assets, Git diff, and package for keys, raw provider errors, raw user data, and unexpected prompt leakage.
- [ ] Self-review the implementation against every 5A acceptance bullet and every original key-injection constraint; list any evidence not yet available.
- [ ] Use the code-review skill and resolve actionable findings with new RED tests.
- [ ] Use the verification-before-completion skill and repeat all affected commands after the final edit.
- [ ] Create the fresh exact-SHA package only after all code commits and a clean worktree. Report its absolute path, SHA-256, mode, creation/expiry times, and prohibited-content scan result.
- [ ] Stop. Do not handle the real key, mutate Azure, call OpenAI, publish/deploy, access the public Demo, push, open a PR, or start CI until the user separately approves that exact fresh package SHA-256.

## Acceptance Trace

| Requirement | Primary proof |
|---|---|
| Six exact bilingual buttons | Existing prompt catalog tests plus Task 7 EN/ZH browser screenshots |
| Fill, focus, no auto-submit | Existing frontend tests plus Task 7 request trace |
| Draft replacement confirmation | Existing dialog tests plus Task 7 keyboard evidence |
| Preset id/locale/version/SHA-256 | Existing API/PostgreSQL audit tests |
| Disabled visible and zero requests | Existing disabled tests plus Task 7 disabled network trace |
| Enabled server validation, rate/budget/permission failures | Existing service/API tests plus Tasks 2, 3, and 5 |
| Store/workspace/period scope | Existing server-derived scope tests; no browser-provided authority |
| No XSS/key/raw data leakage | `textContent` tests, boundary tests, package/log/artifact scans |
| Public Key Vault endpoint + RBAC | Task 4 compiled Bicep contract |
| Existing vault/credentials untouched | Task 4 allowlist and Task 5/6 operation-contract tests |
| Runtime managed-identity key read | Tasks 1–3 unit/integration tests |
| Exact 24-hour approval boundary | Task 6 package/runner tests and Task 7 final stop |

## Evidence Boundary at Plan Completion

Completing Tasks 1–7 proves local implementation, local tests, local browser behavior with fake/injected AI, and creation of a fresh approval package. It does **not** prove that an Azure resource exists, that a real key was stored, that OpenAI accepted a request, that a hosted revision is healthy, that the public Demo is protected by a passcode, or that Staging/Production is ready. Those states require the separate exact-package approval and later hosted evidence.
