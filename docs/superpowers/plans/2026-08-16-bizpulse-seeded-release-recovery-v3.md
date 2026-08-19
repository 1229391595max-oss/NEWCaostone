# BizPulse Seeded Release Recovery V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate a verified, owner-only V3 recovery package that resumes from
the exact successfully seeded state and cannot deploy until all non-AI deploy
and Operator acceptance credentials are safely available.

**Architecture:** Add an immutable seeded-continuation record and exact
read-only verifier. Build a new package that omits completed stages, then run it
only through a hash-first, Keychain-backed, one-shot controller that scopes
secrets to the minimum child environments.

**Tech Stack:** Python 3.12, pytest, macOS `/usr/bin/security`, argon2-cffi,
Azure CLI command contracts, JSON/Markdown SHA-256-bound artifacts.

## Global Constraints

- Candidate source is `82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3` and image is `sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`.
- Recovery V2 SHA-256 `91e210d5c41c430eec8685e39ae10377bdf293e96a5a77662f2e77a51b764f6a` is consumed and must not be replayed.
- Registry publication, migration `0014_import_base_lineage`, seed Job binding and candidate seeding are complete and absent from V3 commands.
- AI remains disabled. No OpenAI Key read, reference, injection, qualification or paid request is allowed.
- Package generation is local only; V3 execution requires separate approval of its complete SHA-256.
- Every implementation behavior follows RED, GREEN and fresh verification.

---

### Task 1: Model and verify the exact seeded continuation state

**Files:**
- Create: `bizpulse/release/incidents/2026-08-16-recovery-v2-seeded-continuation.json`
- Create: `bizpulse/scripts/verify_seeded_release_state.py`
- Create: `bizpulse/tests/hosted/test_verify_seeded_release_state.py`

**Interfaces:**
- Produces: `load_seeded_release_continuation(path, expected_sha256=None)` and
  `verify_seeded_release_state(continuation, reader=_read_json)`.

- [ ] Write failing tests for strict continuation parsing, old app/traffic,
  candidate-bound Jobs and successful prepare/seed execution readback.
- [ ] Run the focused test and confirm failure because the module is absent.
- [ ] Implement the strict schema and read-only verifier with fixed error codes.
- [ ] Run the focused test and confirm all cases pass.
- [ ] Commit the state contract and verifier.

### Task 2: Build the successor-only V3 package

**Files:**
- Create: `bizpulse/scripts/create_seeded_release_recovery_package.py`
- Create: `bizpulse/tests/release/test_seeded_release_recovery_package.py`

**Interfaces:**
- Consumes: candidate attestation and seeded continuation record.
- Produces: `build_seeded_release_recovery_package(...)`,
  `load_seeded_release_recovery_package(...)` and mode-0600 Markdown output.

- [ ] Write failing tests for exact stage order, completed-stage omission, four
  Keychain descriptors, control hashes, expiry, drift and secret/AI absence.
- [ ] Run the focused test and confirm failure because the builder is absent.
- [ ] Implement the minimum strict builder and loader.
- [ ] Run the focused test and confirm all cases pass.
- [ ] Commit the package contract.

### Task 3: Add the hash-first one-shot Keychain execution controller

**Files:**
- Create: `bizpulse/scripts/run_seeded_release_recovery.py`
- Create: `bizpulse/tests/hosted/test_run_seeded_release_recovery.py`

**Interfaces:**
- Consumes: V3 path, separately approved package SHA-256 and continuation path.
- Produces: value-free stage status and a mode-0600 one-shot receipt.

- [ ] Write failing tests proving wrong hash and read-only drift fail before
  Keychain, all four secrets fail before mutation, Argon2 pair mismatch fails,
  per-child environments are minimal and a receipt blocks replay.
- [ ] Run the focused test and confirm failure because the runner is absent.
- [ ] Implement exact Keychain reads, validation, argv execution, environment
  scoping and atomic receipt creation/update without logging values.
- [ ] Run the focused test and confirm all cases pass.
- [ ] Commit the execution controller.

### Task 4: Close policy, authority docs and generate V3

**Files:**
- Modify: `bizpulse/release/verification-policy.json`
- Modify: `CURRENT_STATUS.md`
- Modify: `docs/handoffs/CURRENT_HANDOFF.md`
- Modify: `NEXT_AI_HANDOFF.md`
- Create outside Git: `bizpulse/.tmp/LAUNCH_AUTHORIZATION_SEEDED_RELEASE_RECOVERY_V3.md`

**Interfaces:**
- Produces: one verified package path, authorization ID, expiry and SHA-256.

- [ ] Add the new scripts/tests to the release-static policy and verify selector coverage.
- [ ] Run focused tests, Ruff/compile checks, secret scans and
  `verify_changed --base 16f5220 --no-reuse`.
- [ ] Commit code and authority documentation before package generation.
- [ ] Generate V3 once with a fresh UUID and 24-hour expiry; verify mode 0600,
  exact control hashes and absence of secret values or OpenAI authority.
- [ ] Report the exact SHA-256 and stop without executing V3.

## Self-review

- Spec coverage: seeded state, completed-stage omission, secure credentials,
  replay prevention, verification and no-AI boundaries each map to one task.
- Placeholder scan: no incomplete implementation instruction remains.
- Type consistency: continuation, package and runner use strict dictionaries
  with SHA-256-bound file references.
