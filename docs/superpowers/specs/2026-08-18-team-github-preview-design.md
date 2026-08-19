# NEWCaostone Team GitHub Preview Design

**Status:** Approved scope captured for written review  
**Date:** 2026-08-18 (America/Chicago)  
**Source commit:** `fb29737a6e6152d7811fedc2e8be6065b18aad2d`  
**Publication target:** private repository `1229391595max-oss/NEWCaostone`

## 1. Purpose

Create a teammate-facing GitHub repository that answers two questions clearly:

1. What has NEWCaostone / BizPulse implemented now?
2. What work remains, in what order, and with which evidence boundaries?

This is a team preview, not a Production release, hosted acceptance report, or
backup of every local branch and artifact.

## 2. Publication model

The publication is built in an isolated local clone from the exact authoritative
source commit. The publication branch is `codex/team-github-preview`; only its
reviewed state is pushed to the new private GitHub repository as remote `main`.

The initial remote tag is `team-preview-2026-08-18`. The tag identifies a team
handoff snapshot and must not be presented as a Production version.

No force push, `git push --all`, blanket staging, or publication from the stale
local root `main` is allowed. Existing repositories such as `bizpulse` and
`bizpulse-private-cloud` are not modified.

## 3. Team-facing documents

### 3.1 Root `README.md`

The README is English-first with a short Chinese orientation paragraph. It
contains:

- the product problem and current goal;
- the three product surfaces: public synthetic Demo, authenticated Operator app,
  and protected Admin console;
- a concise implemented-feature map;
- the deterministic-evidence-first AI boundary;
- the PostgreSQL, Azure Blob, FastAPI, browser UI, and Key Vault architecture;
- verified local setup and test commands;
- links to the detailed team status and roadmap;
- an explicit non-Production disclaimer.

The README must not reproduce the long release-incident history. It routes
engineers to the existing authority and operations documents when that detail is
needed.

### 3.2 `docs/TEAM_STATUS.md`

The status document separates evidence states instead of using one blanket
"complete" label. It reports:

- locally implemented product functionality;
- locally verified functionality and the fresh checks used for this preview;
- Admin Tasks 0-11 as locally complete and Task 12 as in progress;
- GitHub publication and CI state;
- deployed/hosted state;
- hosted AI state;
- Production readiness.

It also lists the known non-authoritative work:

- the separate offline Chinese-workbook repair branch and its uncommitted test
  change;
- local presentation, QR, inspection, and spreadsheet outputs;
- divergent operator-rotation history that is not part of this preview.

### 3.3 `docs/ROADMAP.md`

The roadmap uses three priority levels:

- **P0:** finish Admin Task 12 authority refresh, hosted acceptance, and evidence
  closeout; establish GitHub collaboration and CI.
- **P1:** perform separately authorized Admin-based real AI qualification and
  enablement; support the current Chinese marketplace workbooks in the formal
  import path; design and implement invitation-only multi-account tenancy.
- **P2:** expand import diagnostics and adapter coverage, then separately assess
  external Product Opportunity search and marketplace connections.

The roadmap explicitly defers public registration, subscription billing,
multi-region infrastructure, microservice decomposition, user-supplied API
keys, and autonomous marketplace actions.

## 4. Implemented-scope wording

The team documents may describe these capabilities as locally implemented when
they are present in the authoritative tree:

- PostgreSQL migrations and evidence-backed datasets;
- Operator authentication and the formal import workflow: upload, recognize,
  map, standardize, preview, commit, and calculate;
- Sales, Inventory, Profit, Forecast, BP Library, store scope, exports, and
  Action Inbox/Viewer simulation;
- Ask BizPulse persistence, preset auditing, rate/budget controls, and
  evidence-bounded responses;
- protected Admin shell, operations cockpit, system status, Admin JSON APIs,
  Operator reauthentication, idempotent AI controls, exact Key Vault version
  binding, independent Operator/Demo AI switches, and hosted acceptance tooling.

The same documents must say that arbitrary Excel compatibility is not proven,
the current product remains single-Operator, hosted Admin acceptance is not
closed, hosted AI is disabled, GitHub CI is not yet established, and the system
is not Production ready.

## 5. Excluded material

The publication excludes:

- `.tmp` packages, consumed or retired authorization packages, and local
  execution receipts;
- Operator rotation deliverables;
- secrets, credentials, tokens, password material, and local Azure state;
- root `deliverables/`, `outputs/`, QR images, inspection files, and `.DS_Store`;
- uncommitted changes from any other worktree;
- additional local branches and tags not required for the team preview;
- claims that real AI, multi-account tenancy, arbitrary workbook import,
  GitHub CI, hosted acceptance, or Production readiness is complete.

## 6. Verification and failure handling

Before the remote is created or pushed, the publication clone must pass:

1. clean-scope review with only the three team documents and this design/plan
   work in the publication commit;
2. Markdown unfinished-marker and prohibited-claim scans;
3. link/path review for every teammate-facing local reference;
4. Git whitespace checks;
5. tracked-file large-object and sensitive-filename scans;
6. high-signal credential scan over the publication history, with scanner/test
   literals classified rather than treated as credentials;
7. the strongest fresh project verification that the isolated environment can
   run without real secrets, Azure writes, or paid provider calls.

If the target repository already exists unexpectedly, authentication changes,
verification fails, or the remote visibility is not private, publication stops
without force pushing or switching to another repository.

After pushing, verify the remote repository is private, remote `main` resolves
to the exact local publication commit, the team tag resolves to that same
commit, and no unrelated branches were published.

## 7. Success criteria

The work is successful only when:

- teammates can understand the product, current implemented scope, evidence
  limits, and next priorities from the GitHub landing page;
- the new repository is private and contains only the reviewed publication
  branch plus the team-preview tag;
- local artifacts, credentials, unrelated branches, and unsupported claims are
  absent;
- remote commit and tag identities are independently read back and verified.
