# Admin AI Current Authority Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use test-driven development for every task and request an independent review before completion. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clean exact-source, read-only authority refresh that converts fresh Task 10 and readiness evidence into an atomic checked-in authority/document update.

**Architecture:** A new committed-bootstrap mode launches a dedicated snapshot entrypoint. The entrypoint verifies retired R19 provenance, builds a fresh in-memory Task 10 successor, reuses the existing twelve-read verifier plus bounded readiness, constructs the existing observation schema, and transactionally applies the authority/document bundle only after all reads and validations pass.

**Tech Stack:** Python 3.12, pytest, Azure CLI read-only projections, HTTPX bounded public readiness, existing exact-runtime and release-authority modules.

## Global Constraints

- No Azure, Docker, registry, Key Vault, OpenAI, package, UUID, or deployment action during implementation/tests.
- The future live command performs exactly twelve sanitized Azure reads and one bounded public readiness GET; every Azure command is read-only.
- R19 is verified as provenance and is never reused or executed.
- Source SHA/tree, runtime snapshot, dependency manifest, and document policy remain fail-closed.
- No local authority/document target changes until all external reads and validations succeed.
- RED must be observed before each production change.

---

### Task 1: Exact-runtime authority-refresh mode

**Files:**
- Modify: `scripts/admin_ai_exact_runtime.py`
- Modify: `tests/hosted/test_admin_ai_exact_runtime.py`

**Interfaces:**
- Consumes: `authority-refresh` mode plus explicit R19 package/receipt paths.
- Produces: private canonical copies and invocation of `scripts/refresh_admin_ai_current_authority.py` from the exact snapshot.

- [ ] Add a failing exact-bootstrap test that rejects dirty source and changed R19 files, and proves the child receives only canonical private inputs.
- [ ] Run the focused test and confirm the missing-mode failure.
- [ ] Add the mode, copy/hash checks, trusted dependencies, and safe original-project output-root binding.
- [ ] Run the exact-runtime suite and confirm GREEN.

### Task 2: Fresh Task 10 observation and provenance

**Files:**
- Create: `scripts/refresh_admin_ai_current_authority.py`
- Modify: `scripts/create_admin_ai_release_package.py`
- Modify: `scripts/create_ai_enablement_package.py`
- Create: `tests/hosted/test_refresh_admin_ai_current_authority.py`

**Interfaces:**
- Consumes: exact source/tree, verified R19 files, requested RBAC phase, injected Azure/readiness readers.
- Produces: the strict observation mapping consumed by `refresh_current_authority`.

- [ ] Add failing tests for a successful exact 12-read/one-readiness observation and zero writes.
- [ ] Add failing tests for R18/R19 drift, revision/digest/tag/traffic/RBAC/resource mismatch, non-0014 readiness, future/stale time, secret-like output, and any non-read Azure command.
- [ ] Run the focused tests and confirm failures reflect missing behavior.
- [ ] Implement minimal provenance validation, fresh in-memory successor generation, existing reader reuse, exact evidence hashing, and safe observation construction.
- [ ] Run the focused observation/action tests and confirm GREEN.

### Task 3: Transactional authority/document update

**Files:**
- Modify: `scripts/release_authority.py`
- Modify: `scripts/refresh_current_authority.py`
- Modify: `tests/release/test_authority_contract.py`
- Modify: `tests/hosted/test_refresh_admin_ai_current_authority.py`

**Interfaces:**
- Consumes: validated observation, existing authority, exact document policy, expected pre-read file hashes.
- Produces: refreshed authority and generated documents, or the original complete bundle after any failure.

- [ ] Add failing tests for preserved rollback/prepared authority, development head 0017, one-hour freshness, pre/post-read drift, injected replace failure, and no partial update.
- [ ] Run focused tests and confirm the current direct-write behavior fails.
- [ ] Add in-memory render/validation and staged owner-only replace-with-rollback support.
- [ ] Run authority and refresh suites and confirm GREEN.

### Task 4: Supported command, full gates, report, review

**Files:**
- Modify: `docs/operations/AZURE_LAUNCH_RUNBOOK.md`
- Modify: `.superpowers/sdd/task-12-prerelease-fixes-report.md`
- Modify: provenance/runtime manifest policy files as required by exact-source execution.

**Interfaces:**
- Produces: one exact `git show <sha>:./scripts/admin_ai_exact_runtime.py` authority-refresh command for later separately authorized execution.

- [ ] Add a failing test that extracts and executes the documented command hermetically from `bizpulse`, proving no package/UUID output.
- [ ] Document the exact command and stop boundary, then make the documentation test GREEN.
- [ ] Run focused suites, full Python/npm/Ruff/diff/static checks, and proportionate guarded PostgreSQL tests.
- [ ] Commit the coherent implementation, obtain independent read-only review with zero Critical/Important findings, fix any findings TDD-first, update the report, and verify a clean final tree.

## Plan self-review

- Spec coverage: exact runtime, provenance, 12+1 reads, strict hosted state, atomic local update, docs, gates, and review each have a task.
- Placeholder scan: no deferred implementation or unspecified retry remains.
- Type consistency: the observation mapping is the sole handoff to the existing authority refresh contract; no release package is produced.
