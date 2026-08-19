# BizPulse Partial Release Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair update-mode Job authority binding and generate a verified,
AI-disabled recovery package for the exact 2026-08-16 partial release state.

**Architecture:** Extend the existing canonical command generator so update
packages bind Job image, command and args atomically. Add a typed incident
record, a read-only partial-state verifier and a single-stage recovery-package
builder that reuses existing hosted checks but omits completed or unauthorized
stages.

**Tech Stack:** Python 3.12, pytest, Azure CLI command contracts, JSON/Markdown
hash-bound release artifacts, existing BizPulse hosted verifier helpers.

## Global Constraints

- Reuse candidate image digest `sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`.
- Do not publish an image or execute any Azure write while implementing this plan.
- Database migration `0014_import_base_lineage` is already complete and must not be rerun by the recovery package.
- AI remains disabled; no Key field, secret injection, qualification or paid call.
- The consumed package SHA-256 `084ee41e9c79bb96b8e60cd3ac417cac30e9e8f18af5de88ab0304a2374493b6` is evidence only and must not be replayed.
- Every implementation change follows RED, GREEN and fresh verification.

---

### Task 1: Atomically bind update-mode Job commands

**Files:**
- Modify: `bizpulse/tests/release/test_two_stage_release_package.py`
- Modify: `bizpulse/tests/hosted/verify_azure_demo.py`

**Interfaces:**
- Consumes: `_expected_commands(authority)`.
- Produces: update-mode `provision` commands with exact `--container-name`,
  `--command python` and role-specific `--args`.

- [ ] Add a failing test that tokenizes both update-mode provision commands and
  asserts the exact prepare and seed command/argument tails.
- [ ] Run the focused test and confirm it fails because `--command`/`--args` are absent.
- [ ] Change `update_job_command` to accept container name and an args tuple, and
  emit exact Azure CLI tokens for both Jobs.
- [ ] Run `tests/release/test_two_stage_release_package.py` and the hosted
  authorization tests.
- [ ] Commit `fix: bind update jobs to candidate data authority`.

### Task 2: Add partial-state evidence and recovery package contracts

**Files:**
- Create: `bizpulse/release/incidents/2026-08-16-two-stage-partial-failure.json`
- Create: `bizpulse/scripts/verify_partial_release_state.py`
- Create: `bizpulse/scripts/create_partial_release_recovery_package.py`
- Create: `bizpulse/tests/hosted/test_verify_partial_release_state.py`
- Create: `bizpulse/tests/release/test_partial_release_recovery_package.py`
- Modify: `bizpulse/release/verification-policy.json`

**Interfaces:**
- Consumes: the exact incident JSON, candidate attestation and existing hosted
  command generator.
- Produces: `load_partial_release_incident(path)`,
  `verify_partial_release_state(expected, runner, mode)`,
  `build_partial_release_recovery_package(...)`,
  `load_partial_release_recovery_package(path)` and a mode-0600 Markdown package.

- [ ] Add failing parser, command-order, prohibited-stage, drift and mode tests.
- [ ] Run the focused tests and confirm assertion failures for missing behavior.
- [ ] Implement strict schemas, exact commands and read-only Azure JSON checks.
- [ ] Confirm the package has no `registry_publish`, `migrate`, AI, Key, secret,
  paid-provider, DNS, push, PR or CI command.
- [ ] Run the two focused test files plus release/hosted contract tests.
- [ ] Commit `feat: add partial release recovery authority`.

### Task 3: Close and generate the recovery artifact

**Files:**
- Modify: `CURRENT_STATUS.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`
- Modify: `NEXT_AI_HANDOFF.md`
- Create outside Git: `bizpulse/.tmp/LAUNCH_AUTHORIZATION_PARTIAL_RELEASE_RECOVERY_V1.md`

**Interfaces:**
- Consumes: committed Tasks 1-2, exact candidate attestation and incident JSON.
- Produces: one verified package path, SHA-256, expiry, execution order and cost boundary.

- [ ] Run focused release/hosted tests, Ruff, compile, secret scan,
  `verify_changed --no-reuse` and full release verification required by policy.
- [ ] Commit the documentation/candidate checkpoint and create any required
  manifest-only attestation child without changing the candidate image identity.
- [ ] Generate the recovery package once with a fresh UUID and 24-hour expiry.
- [ ] Verify schema, owner-only permissions, exact hashes and absence of secrets.
- [ ] Report the package hash and stop. Do not execute it without a separate
  exact-hash approval.

## Self-review

- Spec coverage: binding, evidence, preflight, recovery order and no-AI boundary
  each map to a task.
- Placeholder scan: no incomplete implementation instruction remains.
- Type consistency: incident, preflight and package builder interfaces use exact
  dictionaries loaded from schema-validated JSON.
