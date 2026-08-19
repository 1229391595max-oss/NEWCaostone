# Admin AI Post-R19 Recovery Adoption Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven development for every behavior change and request an independent security/release review before completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a distinct exact successor profile that adopts the post-R19 registry-only recovery revision for read-only authority refresh and future package preflight without rewriting R18/R19 history.

**Architecture:** A new focused successor-contract module derives and validates the exact recovery target from immutable R19 provenance. Existing historical Task 10 validation remains the default; only fresh Task12 artifact identities select the strict successor profile, which parameterizes the existing twelve-read observer and authority projection.

**Tech Stack:** Python 3.12, pytest, existing Task 10 package/action contracts, exact-runtime authority refresh, Markdown runbook/status policy.

## Global Constraints

- Preserve all R18/R19 constants, package semantics, receipt contracts, files, and last accepted `ai-off` reconciliation.
- The only current target is `newcaostone-demo-app--recover-b-9c35ae6a-2bf7086` at digest `sha256:2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425`, tag `ai-962a4fa43804-9c35ae6a`, identity `registry_only`.
- Successor observation requires exact 12 sanitized Azure reads plus one bounded public readiness result at `0014_import_base_lineage`; implementation performs no live call.
- No Azure write/read, HTTP call, Docker operation, package/UUID creation, R19 replay/change/delete, deployment, cleanup, or secret access during implementation/tests.
- Every production behavior change begins with an observed focused RED.

---

### Task 1: Immutable recovery-adoption derivation

**Files:**
- Create: `scripts/admin_ai_current_successor.py`
- Modify: `tests/hosted/test_refresh_admin_ai_current_authority.py`

**Interfaces:**
- Consumes: the safe mapping returned by `validate_r19_deployment_provenance` plus the exact R19 failed receipt contract.
- Produces: `derive_current_admin_ai_successor(provenance, receipt_contract) -> dict[str, str]` with exact revision, image, digest, tag, identity state, and historical terminal revision.

- [ ] Add tests that assert the exact derived `recover-b` revision and reject changed package hash prefix, terminal digest/revision, failure code, completed states, or a non-null accepted recovery.
- [ ] Run the focused derivation tests and observe failure because the module/function is absent.
- [ ] Implement the minimal exact derivation with fixed-safe patterns and complete key validation.
- [ ] Run the derivation tests and confirm GREEN.

### Task 2: Dual historical/successor Task 10 validation

**Files:**
- Modify: `scripts/create_ai_enablement_package.py`
- Modify: `scripts/create_admin_ai_release_package.py`
- Modify: `scripts/admin_ai_current_successor.py`
- Modify: `tests/hosted/test_create_ai_enablement_package.py`
- Modify: `tests/hosted/test_admin_ai_release_contract.py`
- Modify: `tests/hosted/test_refresh_admin_ai_current_authority.py`

**Interfaces:**
- Consumes: fresh Task12 artifact paths and `CURRENT_ADMIN_AI_SUCCESSOR_TARGET`.
- Produces: a strict fresh successor request with exact recovery target and `rollback_identity_state=registry_only`; the historical validator still accepts the exact R19 package contract unchanged.

- [ ] Add tests that snapshot historical constants/receipt validation and prove the exact owner-only R19 package still validates only against its original `ai-off` target and `registry_plus_ai` gate.
- [ ] Add tests for a fresh strict successor request and rejection of fixed R19 artifacts, R18/R19 `ai-off`, arbitrary recover labels/digests/tags, and `registry_plus_ai`.
- [ ] Run both focused suites and observe failures at the old hardcoded target/identity gates.
- [ ] Add explicit successor-profile selection and validation without changing historical constants or receipt mappings.
- [ ] Run both suites and confirm GREEN.

### Task 3: Registry-only readback and authority projection

**Files:**
- Modify: `scripts/azure_ai_enablement_actions.py`
- Modify: `scripts/refresh_admin_ai_current_authority.py`
- Modify: `tests/hosted/test_azure_ai_enablement_actions.py`
- Modify: `tests/hosted/test_refresh_admin_ai_current_authority.py`

**Interfaces:**
- Consumes: a strictly validated package whose prepackage gate determines the exact allowed identity profile.
- Produces: the existing twelve-read safe result/projection and one authority observation bound to the recovery revision, digest, registry-only identity, readiness 0014, and channels false.

- [ ] Add a reader RED accepting exactly one registry-only App identity for the successor while rejecting no identity, extra AI identity, and historical/successor profile swaps.
- [ ] Add observation REDs for exact recovery acceptance and all ai-off/R18/arbitrary revision, digest, tag, topology, health, RBAC, readiness, schema, and channel drift.
- [ ] Run the focused action/refresh tests and confirm the failures occur at identity and revision validation.
- [ ] Parameterize `_safe_projection` and the observation expectation from the validated profile; keep exact disabled/no-binding canonicalization.
- [ ] Run action/refresh suites and confirm GREEN.

### Task 4: Future package-bound identity transition

**Files:**
- Modify: `scripts/admin_ai_release_operations.py`
- Modify: `tests/hosted/test_admin_ai_release_contract.py`

**Interfaces:**
- Consumes: package-bound successor baseline and exact Task 10 RBAC reconciliation.
- Produces: an enabled-capability revision that attaches only the exact AI identity after reconciliation; all disabled/recovery states remain registry-only.

- [ ] Add a composition RED proving the initial preflight is registry-only and no AI binding, the RBAC state runs once, and only the enabled candidate patch gains the exact AI identity and Key Vault binding.
- [ ] Add negatives for pre-existing `registry_plus_ai`, early identity attachment, or disabled recovery retaining AI identity.
- [ ] Run the focused release/action test and observe the existing profile mismatch.
- [ ] Bind the transition to the package-validated successor profile and keep disabled recovery fail-closed.
- [ ] Run the focused composition suite and confirm GREEN.

### Task 5: Documentation, gates, review, and report

**Files:**
- Modify: `docs/operations/AZURE_LAUNCH_RUNBOOK.md`
- Modify: `CURRENT_STATUS.md`
- Modify: `release/verification-policy.json` if the new module/test path is not already covered.
- Modify: `.superpowers/sdd/task-12-prerelease-fixes-report.md`

**Interfaces:**
- Produces: wording that distinguishes R19's historical accepted `ai-off` target from the unverified current recovery-adoption target and preserves the no-hosted-success evidence boundary.

- [ ] Add documentation REDs for exact historical/current wording and absence of replay or hosted-success claims.
- [ ] Update the runbook/status and make the documentation tests GREEN.
- [ ] Run focused suites, full Python, frontend, Ruff, diff/static checks, and proportionate guarded PostgreSQL tests.
- [ ] Commit the coherent implementation, obtain independent read-only security/release review at zero Critical/Important, fix findings TDD-first, update the report, and verify final HEAD/tree/worktree cleanliness.

## Plan self-review

- Spec coverage: separate history/profile, derivation, identity, 12+1 adoption, future transition, docs, gates, and review each map to an explicit task.
- Placeholder scan: no deferred implementation, retry, or ambiguous target remains.
- Type consistency: the successor derivation mapping is the sole source for fresh Task 10 target, prepackage identity, reader expectation, and authority projection; historical validation remains a separate exact path.
