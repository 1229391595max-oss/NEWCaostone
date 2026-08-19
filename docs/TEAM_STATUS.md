# NEWCaostone Team Status

**Team-preview source:** `fb29737a6e6152d7811fedc2e8be6065b18aad2d` plus teammate documentation commits
**Publication branch:** `codex/team-github-preview`
**Status review date:** 2026-08-18 (America/Chicago)
**GitHub history format:** privacy-preserving single-commit snapshot; earlier local Git history is intentionally not included

This document is the short teammate view. [CURRENT_STATUS.md](../CURRENT_STATUS.md) remains the detailed engineering and release record.

## Evidence summary

| Evidence state | Team preview result |
|---|---|
| Designed | Current product, integrated Viewer/Operator, and Admin control designs are present. |
| Locally implemented | Core BizPulse surfaces and Admin Tasks 0-11 are in the publication tree. |
| Fresh local verification | 2026-08-18: 1,349 Python tests passed, 314 skipped, and 1 private-artifact test was explicitly deselected; 220 Node tests passed; Ruff and the documentation-authority contract passed. |
| Admin Task 12 | In progress: hosted acceptance and closeout. |
| GitHub | Publication target: private team preview; remote identity is verified after push. |
| GitHub CI | Not configured in this initial preview. |
| Deployed application | Historical Azure revisions and traffic changes exist, but current hosted acceptance is not closed by this preview. |
| Hosted AI | Disabled. |
| Multi-account tenancy | Not implemented; the current product remains single-Operator. |
| Production ready | No. This remains a bounded sample-data Demo and engineering preview. |

## Implemented product surfaces

### Data and evidence

- PostgreSQL migration chain through repository revision `0017_ai_turn_credential_binding`.
- Formal Operator workflow: upload, recognition, mapping, standardization, preview, immutable commit, and analysis execution.
- Row-level deduplication, import-base lineage, atomic conflict blocking, immutable dataset versions, and evidence snapshots.
- Formal imports support verified formats only. Arbitrary marketplace Excel compatibility is not claimed.

### Analytics and decisions

- Today Overview and Sales, Inventory, Profit, Profit Bridge, and Forecast surfaces.
- All/Main/Launch store scope on the main Viewer and Operator surfaces.
- BP Library browsing, exports, public-release views, and preferences/saved views.
- Action Inbox decisions and resettable Viewer simulation overlays.

### Viewer and Operator boundaries

- Anonymous Demo sessions use prepared synthetic data.
- Viewer behavior is read-only for canonical data: no personal upload or recomputation.
- The authenticated Operator retains upload, calculation, publish, export, and canonical decision authority.

### Ask BizPulse

- Persistent chat turns and saved outcomes.
- Server-managed bilingual preset catalog and preset audit metadata.
- Evidence-bound context, session fences, rate limits, daily/monthly budgets, and concurrent-turn controls.
- AI-disabled behavior fails closed and does not invent a simulated provider result.

## Admin and AI control

The publication tree includes Admin Tasks 0-11:

- protected `/admin` shell and safe login return;
- operations overview, data-management workflow, and system-status views;
- Admin summary and AI-control JSON APIs;
- current-password reauthentication for sensitive changes;
- immutable Admin AI audit records and database-authoritative channel state;
- independent Operator and Demo AI switches;
- idempotent AI mutations and stable failure receipts;
- one-time candidate-key submission with no key-read API;
- exact Azure Key Vault secret-version binding;
- managed-identity/RBAC infrastructure and hosted acceptance tooling;
- full local gate recorded by the originating implementation task.

Admin Task 12 is not closed. A fresh authority refresh, hosted acceptance sequence, and evidence closeout remain required. Local Admin implementation must not be described as hosted Admin acceptance.

## Known boundaries

- The unfiltered Python run produced the same 1,349 passes and 314 skips plus one failure: a hosted recovery test expects owner-only `.tmp` AI authorization packages and receipts that are intentionally absent from this clean publication clone. Those private artifacts were not copied or published. The reproducible publication run deselected only that exact test.
- `npm ci` completed, but `npm audit` reported eight moderate dependency vulnerabilities. No automatic dependency rewrite or `npm audit fix` was applied during this documentation-only publication.
- Hosted AI remains disabled; no real API key or paid provider qualification is claimed here.
- The current product is single-Operator. Invitation-based multi-account tenancy, memberships, roles, and workspace isolation remain future work.
- GitHub CI is not configured in this initial preview; local verification is reported separately.
- The hosted URL, a reachable page, or 100% revision traffic alone does not prove current hosted acceptance.
- Product Opportunity web search, marketplace connections, real customer files, and autonomous marketplace actions are deferred.
- Production readiness is explicitly false.

## Work outside this preview

The following local work is intentionally excluded:

- `codex/offline-demo-repair`, including its uncommitted test change and experimental Chinese-workbook compatibility;
- divergent historical Operator-rotation commits not selected by the authoritative preview;
- local PPTX/DOCX files, QR code, generated spreadsheets, inspection output, and `.DS_Store`;
- `.tmp` authorization packages, execution receipts, Keychain state, Azure state, and all credential material;
- earlier local Git history containing private author metadata; GitHub starts from the reviewed snapshot tree;
- unrelated worktrees, branches, and tags.

## Fresh local verification details

The checks below ran from the isolated publication clone on 2026-08-18:

- Python: `1,349 passed, 314 skipped, 1 deselected` in the public-reproducible run. The deselected test is exactly `tests/hosted/test_create_ai_enablement_package.py::test_prior_attempts_are_exact_owner_only_consumed_artifacts`.
- Node: `220 passed, 0 failed, 0 skipped`.
- Ruff: `All checks passed!` for `api`, `src`, `scripts`, `tests`, and `alembic`.
- Documentation authority: `authority_contract=ok`.
- Bicep compilation used a writable temporary local CLI/cache directory; no Azure write, deployment, secret access, or paid provider request was performed.

These are local implementation checks only. They are not GitHub CI, hosted acceptance, or Production evidence.

## Evidence sources

- [Root teammate README](../README.md)
- [Prioritized roadmap](ROADMAP.md)
- [Detailed current status](../CURRENT_STATUS.md)
- [Current engineering handoff](handoffs/CURRENT_HANDOFF.md)
- [Admin design](../bizpulse/docs/superpowers/specs/2026-08-18-admin-operations-and-ai-control-design.md)
- [Admin implementation plan](../bizpulse/docs/superpowers/plans/2026-08-18-admin-operations-and-ai-control.md)
- [Admin Task 12 prerelease report](../.superpowers/sdd/task-12-prerelease-fixes-report.md)
