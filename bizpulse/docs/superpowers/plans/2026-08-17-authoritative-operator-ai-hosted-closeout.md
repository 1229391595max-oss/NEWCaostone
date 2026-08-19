# Authoritative Operator, AI, and Hosted Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve `main`, unify the validated Operator and AI histories on one authoritative branch, prove the hosted Operator upload-to-publish loop, enable real AI through one fresh exact-hash package, complete hosted acceptance, and retain only evidence-bearing deliverables and worktrees.

**Architecture:** `codex/newcaostone-authoritative-v1` starts at AI control commit `8962a6b` and merges Operator control commit `16d8266`; Git history, live Azure readback, immutable ACR digest, and exclusive receipts remain separate authorities. The current AI-disabled deployment is used only for the Operator gate, then a newly named AI package builds and deploys the authoritative commit. Old AI/recovery packages are immutable evidence and are never submitted to a runner.

**Tech Stack:** Git worktrees, Python 3.12, pytest, Node.js/CDP browser gate, Docker Buildx, Azure CLI, Azure Container Apps, ACR, Key Vault, managed identity, PostgreSQL, OpenAI Responses API.

## Global Constraints

- Keep the repository `main` branch and its worktree intact.
- Do not execute, modify, copy as authority, or reuse the path or hash of any R1-R16 recovery or enablement package.
- Secrets may enter only through the existing macOS Keychain or a local hidden-input dialog owned by the runner; never place a credential in a command argument, transcript, receipt, Git file, or chat.
- Every Azure write is bound to a fresh readback and an exact branch, commit, tree, package SHA-256, image digest, and rollback revision.
- The hosted system of record remains PostgreSQL; no SQLite substitution is accepted as hosted evidence.
- One paid provider smoke is allowed only after local model qualification, AI-enabled revision health, and budget/rate controls are proved.
- A reachable URL, a local test, and a successful deployment are separate evidence states.

---

### Task 1: Establish the Single Git and Azure Authority

**Files:**
- Create: `docs/superpowers/plans/2026-08-17-authoritative-operator-ai-hosted-closeout.md`
- Merge: `codex/operator-rotation-hosted-base` at `16d8266` into `codex/newcaostone-authoritative-v1` starting at `8962a6b`
- Verify: `tests/services/test_operator_password_rotation_service.py`
- Verify: `tests/hosted/test_run_operator_rotation.py`
- Verify: `tests/hosted/test_azure_arm_lro.py`
- Verify: `tests/hosted/test_run_ai_enablement.py`

**Interfaces:**
- Consumes: two clean, already isolated feature histories and Azure subscription `fc89e7d3-5428-425e-863f-415859810c2c`.
- Produces: one clean integration history plus a sanitized baseline for `newcaostone-demo-app`.

- [x] **Step 1: Verify merge inputs and main preservation**

```bash
git status --short --branch
git merge-base HEAD codex/operator-rotation-hosted-base
git -C /Users/maxli/Desktop/NEWCaostone rev-parse main
```

Expected: the integration worktree is clean, merge base is `75e6a8e6a2baa71ed0ea196a8365f990295c152c`, and `main` remains at its pre-closeout SHA.

- [x] **Step 2: Merge the Operator history without rewriting either parent**

```bash
git merge --no-ff codex/operator-rotation-hosted-base -m "merge: unify operator and AI release authority"
```

Expected: a two-parent merge with no conflict; `git merge-tree --write-tree` precomputed tree `ffee2c8e98685989c5f7e83a5297d96bd69b5f8d` before this plan-only commit.

- [x] **Step 3: Run the cross-branch contract tests**

```bash
.venv/bin/pytest -q tests/services/test_operator_password_rotation_service.py tests/hosted/test_run_operator_rotation.py tests/hosted/test_azure_arm_lro.py tests/hosted/test_run_ai_enablement.py tests/infra/test_bicep_contract.py
```

Expected: all selected tests pass with no warning or collection error.

- [x] **Step 4: Capture a fresh sanitized Azure baseline**

```bash
az containerapp show --subscription fc89e7d3-5428-425e-863f-415859810c2c --resource-group rg-bizpulse-centralus --name newcaostone-demo-app --only-show-errors --output json
az containerapp revision list --subscription fc89e7d3-5428-425e-863f-415859810c2c --resource-group rg-bizpulse-centralus --name newcaostone-demo-app --only-show-errors --output json
```

Expected: Single mode, one healthy active ready revision, 100% latest traffic, exact ACR digest, `BIZPULSE_AI_CHAT_ENABLED=false`, and only the intended registry identity before AI enablement.

### Task 2: Allocate a Fresh AI Authority Namespace with TDD

**Files:**
- Modify: `tests/hosted/test_create_ai_enablement_package.py`
- Modify: `scripts/create_ai_enablement_package.py`
- Verify: `tests/hosted/test_run_ai_enablement.py`

**Interfaces:**
- Consumes: clean authoritative branch and the existing v1 AI package schema.
- Produces: branch authority `codex/newcaostone-authoritative-v1` and exclusive R11 paths; it does not change model, budget, runtime, or Azure action semantics.

- [x] **Step 1: Change only the test expectation to the fresh authority**

Set the expected branch to `codex/newcaostone-authoritative-v1`, set `ARTIFACTS` to `LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R11_2026-08-17.json`, `AI_ENABLEMENT_RECEIPT_R11_2026-08-17.json`, and `AI_ENABLEMENT_OBSERVATION_R11_2026-08-17.json`, and require R8 to remain in the consumed-artifact registry.

- [x] **Step 2: Run the exact test and observe the intended RED failure**

```bash
.venv/bin/pytest -q tests/hosted/test_create_ai_enablement_package.py::test_authoritative_closeout_uses_fresh_r11_paths_and_consumed_r8
```

Expected: FAIL because production constants still name the old branch and R8 paths.

- [x] **Step 3: Apply the minimal production constant update**

Update only `AUTHORIZED_BRANCH`, the three `ARTIFACTS` values, the replacement-path test name, and the consumed R8 registry entry. Do not change Azure operations, D3 diagnostic behavior, limits, model, retry, or secret handling.

- [x] **Step 4: Prove GREEN and commit the authority namespace**

```bash
.venv/bin/pytest -q tests/hosted/test_create_ai_enablement_package.py tests/hosted/test_run_ai_enablement.py
git add scripts/create_ai_enablement_package.py tests/hosted/test_create_ai_enablement_package.py docs/superpowers/plans/2026-08-17-authoritative-operator-ai-hosted-closeout.md
git commit -m "chore: allocate authoritative AI enablement package"
```

Expected: all selected tests pass and Git is clean.

### Task 3: Prove the Hosted Operator Upload Closure Before AI Enablement

**Files:**
- Read: `tests/fixtures/synthetic/v1/operator_import.xlsx`
- Execute: `scripts/browser_release_gate.mjs`
- Execute: `scripts/run_hosted_check.py`
- Preserve: `deliverables/closeout/operator-upload-receipt.json`

**Interfaces:**
- Consumes: the exact current AI-disabled image, live revision suffix, and current Operator password read only inside the Keychain process boundary.
- Produces: a sanitized receipt with uploaded content authority, immutable dataset version, completed calculations, public-release switch, viewer pinning, and zero external browser requests.

- [x] **Step 1: Run health against the exact current revision and digest**

Use `run_hosted_check.py --check health` with the read-back `--image`, `--expected-url`, and `--expected-revision-suffix`; reject any drift before login.

- [x] **Step 2: Run the core real-browser gate with a memory-only Keychain credential**

Invoke `node scripts/browser_release_gate.mjs <exact-url> core` from a Python wrapper that reads `OperatorRotationKeychain.current_pair().password`, passes it only as `BIZPULSE_BROWSER_OPERATOR_PASSWORD` to the child, clears the child environment afterward, and prints only the gate's sanitized JSON.

Expected JSON: `operatorImport=true`, `operatorPublish=true`, `operatorExport=true`, `operatorOutcome=true`, `pinnedRefresh=true`, `consoleErrors=0`, and `externalRequests=0`.

- [x] **Step 3: Save a sanitized Operator receipt**

Record the observed revision, image digest, gate result, UTC time, fixture SHA-256, and resulting dataset version identifier. Exclude cookies, CSRF values, Keychain metadata, and the Operator password.

### Task 4: Create and Execute One Fresh Exact-Hash AI Enablement

**Files:**
- Read: `docs/superpowers/specs/2026-08-17-authoritative-ai-resource-reconciliation-design.md`
- Execute: `scripts/create_ai_enablement_package.py`
- Execute: `scripts/run_ai_enablement.py`
- Preserve: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R11_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_RECEIPT_R11_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_OBSERVATION_R11_2026-08-17.json`
- Preserve: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R12_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_RECEIPT_R12_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_OBSERVATION_R12_2026-08-17.json`
- Preserve: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R13_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_RECEIPT_R13_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_OBSERVATION_R13_2026-08-17.json`
- Preserve: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R14_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_RECEIPT_R14_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_OBSERVATION_R14_2026-08-17.json`
- Preserve: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R15_2026-08-17.json`
- Preserve: `.tmp/AI_ENABLEMENT_RECEIPT_R15_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_OBSERVATION_R15_2026-08-17.json`
- Preserve: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R16_2026-08-17.json`
- Preserve: `.tmp/AI_ENABLEMENT_RECEIPT_R16_2026-08-17.json`
- Preserve as absent: `.tmp/AI_ENABLEMENT_OBSERVATION_R16_2026-08-17.json`
- Preserve: `.tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R17_2026-08-17.json`
- Preserve: `.tmp/AI_ENABLEMENT_RECEIPT_R17_2026-08-17.json`
- Preserve: `.tmp/AI_ENABLEMENT_OBSERVATION_R17_2026-08-17.json`

**Interfaces:**
- Consumes: authoritative clean Git tree, exact current revision/image rollback pair, ACR, Key Vault, managed identity, and one API key entered only in the runner's local hidden-input dialog.
- Produces: immutable R11-R14 fences plus consumed R15/R16 failure receipts, then an immutable ACR digest, healthy AI-enabled Container App revision, successful single paid smoke, and bounded R17 receipts.

- [x] **Step 1: Run local model qualification and release-control tests**

```bash
.venv/bin/pytest -q tests/unit/ai/test_model_qualification.py tests/hosted/test_ai_enablement_contract.py tests/hosted/test_azure_ai_enablement_actions.py tests/hosted/test_azure_ai_reconciliation.py tests/hosted/test_azure_ai_revision.py tests/hosted/test_azure_arm_lro.py
```

Expected: qualification contract fixes `gpt-5.4-nano-2026-03-17`, low reasoning, no tools, no retry, 2,800 maximum output tokens, and a 30-second timeout.

- [x] **Step 2: Generate R11 after a fresh source and Azure readback**

Run `create_ai_enablement_package.py` with the exact subscription, tenant, resource group, app, registry, log workspace, registry identity, rollback revision/image/tag, vault, and AI identity read from Azure. The 11-read gate must prove the preserved task Vault, UAMI, deterministic RBAC, and diagnostics are `existing_exact` without a Key Vault Secret command. Write only the three exclusive R11 paths.

- [x] **Step 3: Stop and fence the pre-receipt R11 failure**

R11 returned failure before its exclusive receipt was reserved. A fresh readback proved the exact Operator revision/image remained AI-disabled and no R11 receipt or observation existed. Record the exact R11 package hash plus the required absence of both outputs in `PRIOR_AI_ATTEMPTS`; any later R11 output is drift. Do not submit R11 again.

- [x] **Step 4: Generate R12 from the new clean committed authority**

Allocate only the three exclusive R12 paths. The package must consume the exact R11 package hash and its `pre_receipt_no_azure_write` absence fence, repeat the fresh Git/control/Azure readback, and bind the new commit and tree.

- [x] **Step 5: Stop and fence R12 at the Keychain authorization boundary**

R12 returned `ai_enablement_browser_credential_unavailable` before its exclusive receipt was reserved. The exact Keychain item and current pair remained present, while the 60-second secret-read process did not receive macOS login-Keychain approval. Fresh Azure readback remained on the same healthy AI-disabled Operator revision and digest. Record the exact R12 package hash, safe failure code, and required absence of both R12 outputs; never submit R12 again.

- [x] **Step 6: Generate and fence R13 at the Keychain authorization boundary**

R13 consumed both earlier fences and repeated the clean Git/control/Azure readback, but the separate `/usr/bin/security` process again timed out before receipt reservation. Preserve its exact package hash, safe failure code, absent outputs, and unchanged live AI-disabled readback; never submit R13 again.

- [x] **Step 7: Generate R14 with the already-proven native Security.framework reader**

Replace only the browser credential adapter with `OperatorRotationKeychain.current_pair()` backed by `MacOSKeychainBackend`, the same native boundary used by the successful Operator browser gate. Prove the current pair is available without printing it, allocate only the three exclusive R14 paths, consume all prior fences, and repeat the clean Git/control/Azure readback.

- [x] **Step 8: Fence R14 without submitting it**

The background controller PTY is not a user-accessible Terminal, and Computer Use correctly prohibits automated Terminal control. Preserve the exact R14 package and required absence of both outputs as `never_submitted_superseded_before_execution`; no R14 runner process or Azure write occurred.

- [x] **Step 9: Generate R15 with a local hidden-input dialog**

Collect the OpenAI key through a topmost Tk secure dialog using `show="*"`. The dialog returns the value only to the current runner process; it is not printed, stored in argv or ambient environment, or sent through chat. Cancel maps to the existing missing-key fail-closed path.

- [x] **Step 10: Execute R15 once and stop before key input**

R15 wrote its exclusive failed receipt after `readonly_revalidation` and returned `ai_enablement_image_publish_failed`. Exact Docker inspection proved `newcaostone-local:03bebfd72a12` was absent; the live app remained on the healthy AI-disabled Operator revision. The key dialog never opened, no provider call ran, and no Secret write or Container App write occurred.

- [x] **Step 11: Consume and diagnose the R15 receipt**

Retain the exact R15 package and receipt hashes in `PRIOR_AI_ATTEMPTS`. Never retry R15.

- [x] **Step 12: Build and hard-gate the exact R16 local image before package write**

Build `linux/amd64` from the clean committed R16 authority using the exact `SOURCE_REVISION` and `IMAGE_INPUT_SHA256` build arguments. Require local tag `newcaostone-local:<sha12>`, user `bizpulse`, and exact revision/image-input labels. The package generator must inspect and accept that image before creating any R16 path.

- [x] **Step 13: Generate and execute the exact R16 SHA once**

After the local-image gate and fresh 11-read Azure baseline passed, R16 published its exact image and submitted the first AI-disabled Container App PATCH. The controller rejected the returned asynchronous-operation URL before key input and wrote `ai_enablement_patch_unconfirmed`.

- [x] **Step 14: Reconcile and consume R16**

Fresh readback proved the PATCH actually created healthy revision `newcaostone-demo-app--ai-off-a42dd26e-6ae74ab`, serving digest `sha256:6ae74aba8cb81dd1393012fdcb4f702675a0546850780e934a31e60ec39fb046` at 100% with AI disabled and exact health passing. Retain the R16 package/receipt hashes and never retry it.

- [x] **Step 15: Accept the exact Container Apps operationStatuses path and build R17**

Allow both the existing `operations/<uuid>` and the observed official `operationStatuses/<uuid>` paths under the same subscription, Microsoft.App provider, location, HTTPS host, and single API-version query. Reject all other paths. Promote the healthy R16 AI-disabled revision/digest/tag to the R17 rollback anchor, build the new exact local image, and require the local-image gate before package creation.

- [x] **Step 16: Generate and execute the exact R17 SHA once**

After fresh Git, image, prior-attempt, D3, price, and 11-read Azure gates pass, generate only the R17 namespace and execute its exact hash once. Enter the OpenAI key only in the local hidden-input dialog. Do not submit any R1-R16 enablement or recovery package.

R17 passed the local-image and fresh Azure gates, published its exact image, and submitted one AI-disabled PATCH. It wrote `ai_enablement_patch_unconfirmed` before key input because the service-supplied operation-status endpoint did not provide a confirmable result to this identity. Fresh readback proved the exact R17 revision subsequently became healthy, ready, and 100% serving with AI disabled.

- [x] **Step 17: Stop on the R17 receipt failure**

Retain the exact R17 package and failed receipt, capture the healthy AI-disabled readback, and never retry R17.

- [x] **Step 18: Poll the exact Container App resource and build R18**

For a 202 PATCH, ignore service-supplied polling URLs and issue only GET requests to the exact original Container App resource URL. Require the exact resource ID and `properties.provisioningState=Succeeded`; wait on the bounded known in-progress states and fail closed on failed, cancelled, malformed, foreign-resource, transport, or timeout outcomes. Existing exact revision reconciliation remains mandatory after this ARM acknowledgement. Promote the healthy R17 AI-disabled revision/digest/tag to the R18 rollback anchor, consume the exact R17 package and receipt hashes, build the exact new local image, and generate only the fresh R18 namespace.

- [x] **Step 19: Execute the exact R18 SHA once**

After fresh Git, image, prior-attempt, D3, price, and 11-read Azure gates pass, execute R18 exactly once. Enter the OpenAI key only in the clearly labelled local hidden-input dialog. Do not submit any R1-R17 enablement or recovery package.

R18 proved the exact-resource ARM completion path, published its candidate image, verified the initial AI-disabled revision, and reconciled the preserved AI resources. The budget rehearsal recovery then failed closed because omitting the AI UAMI from a PATCH does not remove it. Fresh readback proved the recovery revision healthy and AI disabled, but the App still had both registry and AI UAMIs. No key prompt, paid call, placeholder/real Secret write, or observation occurred. Preserve the exact failed receipt and never retry R18.

- [ ] **Step 20: Use explicit UAMI deletion semantics and build R19**

For every disabled revision whose predecessor has the AI UAMI, send the exact AI UAMI resource ID with a JSON `null` value, matching Azure Container Apps identity-removal semantics. Track and reconcile the desired target projection without that deletion marker. Bind the healthy R18 recovery revision/digest/tag and its exact `registry_plus_ai` identity state, consume the exact R18 package/receipt hashes, build a new exact local image, and generate only R19.

- [ ] **Step 21: Execute the exact R19 SHA once**

The first R19 disabled transition must prove the explicit deletion leaves only the registry UAMI before any failure rehearsal. Then complete the budget recovery, placeholder-provider recovery, local hidden key input, 12 paid qualification calls, real Secret write, final enabled revision, and one hosted paid application smoke. Any terminal R19 receipt is consumed and never retried.

### Task 5: Complete Hosted Acceptance and Delivery Evidence

**Files:**
- Execute: `scripts/run_hosted_check.py`
- Execute: `tests/acceptance/test_exact_15_sessions.py`
- Execute: `tests/acceptance/test_restart_readback.py`
- Execute: `tests/acceptance/test_rollback_compatibility.py`
- Preserve: `deliverables/closeout/NEWCAOSTONE_FINAL_ACCEPTANCE_2026-08-17.md`
- Preserve: `deliverables/BizPulse_Updated_Dry_Run_2026-08-16.pptx`
- Preserve: `deliverables/BizPulse_Updated_Presentation_Script_2026-08-16.docx`
- Preserve: `/Users/maxli/Desktop/NEWCaostone/newcaostone-demo-url-qr.png`

**Interfaces:**
- Consumes: exact AI-enabled revision and immutable image digest.
- Produces: health, full browser, capacity, session, restart, rollback-readiness, presentation, and provenance evidence with explicit local/hosted boundaries.

- [ ] **Step 1: Run exact hosted health, full browser, paid-AI, and capacity checks**

Bind every check to the new digest and revision suffix. The full gate must prove Viewer and Operator flows; the paid-AI result must show one provider turn and no client-side API key surface.

- [ ] **Step 2: Run persistence and rollback acceptance**

Execute exact-15 sessions, restart readback, and rollback compatibility against the hosted PostgreSQL-backed release path. Record local-only tests separately if a test harness does not target Azure.

- [ ] **Step 3: Verify deliverables and claims**

Hash the PPTX, DOCX, QR, plan, R11-R18 packages/fences/receipts, R19 receipt and observation, Operator receipt, and final acceptance report. Re-render PPTX/DOCX only if their bytes changed; do not label local render QA as hosted proof.

- [ ] **Step 4: Commit the unique final handoff**

The handoff states exact branch/SHA/tree/image/revision/URL, AI and Operator proof, remaining limitations, rollback authority, and cleanup allowlist. It must not claim Production readiness from course-Demo evidence.

### Task 6: Provenance-Checked Cleanup Without Deleting Main

**Files:**
- Inspect: `/Users/maxli/Desktop/NEWCaostone/.worktrees/*`
- Preserve: `/Users/maxli/Desktop/NEWCaostone`
- Preserve: `codex/newcaostone-authoritative-v1`
- Preserve: unique receipts and deliverables referenced by the final handoff

**Interfaces:**
- Consumes: final clean authoritative commit and an allowlist of evidence already copied to retained locations.
- Produces: no stale disposable worktree and no loss of `main`, branch history, dirty user file, unique receipt, or attestation.

- [ ] **Step 1: Inventory every worktree, branch tip, dirty path, and unique commit**

```bash
git worktree list --porcelain
git branch --format='%(refname:short) %(objectname)'
```

Expected: every deletion candidate is clean or its unique files have been copied and hashed into the retained closeout set.

- [ ] **Step 2: Remove only allowlisted obsolete worktrees**

Use `git worktree remove <exact-path>` one path at a time. Do not use recursive filesystem deletion and do not remove `/Users/maxli/Desktop/NEWCaostone` or the active authoritative worktree.

- [ ] **Step 3: Delete only fully merged obsolete `codex/*` branches**

Use `git branch --merged codex/newcaostone-authoritative-v1` to construct the allowlist, then `git branch -d <exact-branch>` individually. Never delete `main` or the authoritative branch.

- [ ] **Step 4: Re-run final state checks**

Verify `main` still resolves, the authoritative branch is clean, Azure still serves the accepted revision/image, all retained hashes match, and `git worktree list` contains only intentional worktrees.

## Self-Review

- Spec coverage: all five user-ordered outcomes and the explicit no-old-package/main-preservation constraints map to Tasks 1-6.
- Placeholder scan: the plan contains no unresolved marker, unspecified credential value, or unbounded retry.
- Type and authority consistency: source SHA, tree SHA, package SHA-256, image digest, revision, and URL remain distinct fields throughout.
- Execution choice: the user explicitly authorized immediate inline execution in this session, so superpowers:executing-plans applies without another handoff question.
