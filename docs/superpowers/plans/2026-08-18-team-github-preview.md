# NEWCaostone Team GitHub Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a private, teammate-facing NEWCaostone repository that clearly separates implemented work, current evidence, and prioritized next work.

**Architecture:** Build three concise team documents on an isolated publication branch derived from authoritative commit `fb29737a6e6152d7811fedc2e8be6065b18aad2d`. Validate the unchanged product tree and publication history locally, then create an empty private GitHub repository and push only the reviewed publication commit as remote `main` plus one team-preview tag.

**Tech Stack:** Git, GitHub CLI, Markdown, Python 3.12 project verification, pytest, Ruff, Node.js 24, npm, repository-native authority checks.

## Global Constraints

- Publication target is exactly the private repository `1229391595max-oss/NEWCaostone`.
- Publication source is branch `codex/team-github-preview`, derived from exact commit `fb29737a6e6152d7811fedc2e8be6065b18aad2d`.
- Remote default branch is `main`; the only initial publication tag is `team-preview-2026-08-18`.
- Do not modify or push the stale local root `main`, any unrelated branch, or any existing GitHub repository.
- Do not use force push, `git push --all`, blanket staging, or a public repository.
- Do not publish `.tmp`, receipts, local outputs, presentation artifacts, QR images, credentials, local Azure state, or another worktree's uncommitted changes.
- Do not claim hosted Admin acceptance, hosted AI, arbitrary workbook compatibility, multi-account tenancy, GitHub CI, or Production readiness.
- Do not perform Azure writes, Key Vault secret access, OpenAI calls, deployments, or paid requests.

---

### Task 1: Create the teammate landing page and evidence documents

**Files:**
- Create: `README.md`
- Create: `docs/TEAM_STATUS.md`
- Create: `docs/ROADMAP.md`
- Read: `.superpowers/sdd/progress.md`
- Read: `CURRENT_STATUS.md`
- Read: `docs/handoffs/CURRENT_HANDOFF.md`
- Read: `bizpulse/docs/superpowers/plans/2026-08-18-admin-operations-and-ai-control.md`

**Interfaces:**
- Consumes: exact authoritative Git tree at `fb29737`, Admin progress Tasks 0-12, API route inventory, migration inventory, and the approved team-preview design.
- Produces: a root landing page linking to a fact table (`docs/TEAM_STATUS.md`) and prioritized work queue (`docs/ROADMAP.md`).

- [ ] **Step 1: Reconfirm the publication base and clean scope**

Run:

```bash
git merge-base --is-ancestor fb29737 HEAD
git status --short --branch
git diff --name-only fb29737...HEAD
```

Expected: the ancestry check exits `0`; the branch is `codex/team-github-preview`; before teammate-document edits, the only branch delta is the approved design and this plan.

- [ ] **Step 2: Write the root README**

Create `README.md` with these exact top-level sections:

```markdown
# BizPulse / NEWCaostone

> Private team preview. Local implementation and hosted evidence are reported separately. This repository is not a Production release.

中文说明：这是给项目组员查看的当前代码预览，重点说明已经实现的功能、证据边界和下一步计划；不代表 AI、多人账号或 Production 已完成。

## Product goal
## Product surfaces
## Implemented now
## Evidence-first AI boundary
## Architecture
## Repository map
## Local setup and verification
## Current status and roadmap
## Team rules
```

The three product surfaces must be named `Synthetic Demo`, `Operator App`, and `Admin Console`. Link `Current status and roadmap` to `docs/TEAM_STATUS.md` and `docs/ROADMAP.md`. Link release detail to `CURRENT_STATUS.md` without copying its incident history into the README.

- [ ] **Step 3: Write the evidence-separated team status**

Create `docs/TEAM_STATUS.md` with these exact evidence rows:

```markdown
| Evidence state | Team preview result |
|---|---|
| Designed | Current product and Admin control designs are present. |
| Locally implemented | Core BizPulse surfaces and Admin Tasks 0-11 are in the publication tree. |
| Fresh local verification | Recorded only after Task 2 commands complete. |
| Admin Task 12 | In progress: hosted acceptance and closeout. |
| GitHub | Publication target: private team preview; remote identity is verified after push. |
| GitHub CI | Not configured in this initial preview. |
| Hosted AI | Disabled. |
| Multi-account tenancy | Not implemented; current product remains single-Operator. |
| Production ready | No. |
```

Add sections `Implemented product surfaces`, `Admin and AI control`, `Known boundaries`, `Work outside this preview`, and `Evidence sources`. State that the formal import pipeline supports verified formats only and that the separate offline Chinese-workbook branch is not included.

- [ ] **Step 4: Write the prioritized roadmap**

Create `docs/ROADMAP.md` with sections `P0 — Close and share safely`, `P1 — Complete the next product capabilities`, `P2 — Expand after the foundations`, and `Explicitly deferred`. Use the priorities approved in `docs/superpowers/specs/2026-08-18-team-github-preview-design.md` without adding new features.

- [ ] **Step 5: Run document structure and boundary checks**

Run:

```bash
test -s README.md
test -s docs/TEAM_STATUS.md
test -s docs/ROADMAP.md
rg -n '^## ' README.md docs/TEAM_STATUS.md docs/ROADMAP.md
if rg -n -i '\b(T[B]D|T[O]DO|FIX[M]E)\b|implement[[:space:]]+later|fill[[:space:]]+in' README.md docs/TEAM_STATUS.md docs/ROADMAP.md; then exit 1; fi
rg -n 'Hosted AI|Production ready|single-Operator|GitHub CI|Task 12|verified formats' README.md docs/TEAM_STATUS.md docs/ROADMAP.md
git diff --check
```

Expected: all three files are non-empty; required headings and boundary statements are present; unfinished-marker scan has no matches; whitespace check exits `0`.

- [ ] **Step 6: Commit only the teammate documents**

Run:

```bash
git add README.md docs/TEAM_STATUS.md docs/ROADMAP.md
git diff --cached --name-only
git commit -m "docs: add teammate project handoff"
```

Expected: the staged list contains exactly the three teammate documents and the commit succeeds.

---

### Task 2: Run fresh local verification and record exact evidence

**Files:**
- Modify: `docs/TEAM_STATUS.md`
- Verify: `bizpulse/tests/`
- Verify: `bizpulse/api/`
- Verify: `bizpulse/src/`
- Verify: `bizpulse/frontend/`
- Verify: `bizpulse/alembic/`

**Interfaces:**
- Consumes: unchanged application source inherited from `fb29737` and the Python environment at `/Users/maxli/Desktop/NEWCaostone/.worktrees/ai-enable-preset-buttons/bizpulse/.venv`.
- Produces: fresh test counts and command results recorded without converting them into hosted or Production claims.

- [ ] **Step 1: Install locked frontend dependencies in the isolated clone**

Run:

```bash
cd bizpulse
npm ci
```

Expected: installation exits `0`; `node_modules/` remains ignored and untracked.

- [ ] **Step 2: Run the full local Python suite**

Run from `bizpulse/`:

```bash
/Users/maxli/Desktop/NEWCaostone/.worktrees/ai-enable-preset-buttons/bizpulse/.venv/bin/python -m pytest -q
```

Expected: exit `0` with zero failures. If PostgreSQL, Azurite, Chrome, Bicep, or another required local service is unavailable, stop and report the exact failure rather than weakening or skipping the suite silently.

- [ ] **Step 3: Run frontend and Ruff verification**

Run from `bizpulse/`:

```bash
npm test
/Users/maxli/Desktop/NEWCaostone/.worktrees/ai-enable-preset-buttons/bizpulse/.venv/bin/python -m ruff check api src scripts tests alembic
```

Expected: both commands exit `0`.

- [ ] **Step 4: Run authority and Git checks**

Run from `bizpulse/`:

```bash
/Users/maxli/Desktop/NEWCaostone/.worktrees/ai-enable-preset-buttons/bizpulse/.venv/bin/python scripts/check_authority_contract.py --mode docs
cd ..
git diff --check
git status --short --branch
```

Expected: authority check and whitespace check exit `0`; only the intended `docs/TEAM_STATUS.md` evidence update may be uncommitted.

- [ ] **Step 5: Record fresh evidence without overclaiming**

Replace the `Fresh local verification` row in `docs/TEAM_STATUS.md` with the exact Python pass/skip count, Node pass count, Ruff result, authority result, and date from Steps 2-4. Do not label those results GitHub CI, hosted acceptance, or Production verification.

- [ ] **Step 6: Commit the verification record**

Run:

```bash
git add docs/TEAM_STATUS.md
git diff --cached --check
git commit -m "docs: record team preview verification"
```

Expected: only `docs/TEAM_STATUS.md` is committed.

---

### Task 3: Perform publication privacy and scope gates

**Files:**
- Inspect: complete publication Git history reachable from `HEAD`
- Inspect: `.gitignore`
- Inspect: `README.md`
- Inspect: `docs/TEAM_STATUS.md`
- Inspect: `docs/ROADMAP.md`

**Interfaces:**
- Consumes: final local publication commit after Tasks 1-2.
- Produces: a clean, privacy-checked exact commit eligible for a private remote push.

- [ ] **Step 1: Confirm exact branch scope**

Run:

```bash
git status --short --branch
git log --oneline fb29737..HEAD
git diff --stat fb29737...HEAD
git diff --name-only fb29737...HEAD
```

Expected: clean branch; delta contains only `README.md`, `docs/TEAM_STATUS.md`, `docs/ROADMAP.md`, the approved design, and this implementation plan.

- [ ] **Step 2: Scan reachable blobs and filenames**

Run:

```bash
git rev-list --objects HEAD |
  git cat-file --batch-check='%(objecttype) %(objectsize) %(rest)' |
  awk '$1 == "blob" && $2 >= 10000000 {print; found=1} END {exit found ? 1 : 0}'

git rev-list --objects HEAD |
  rg -i '(^| )([^ ]*/)?(\.env($|\.)|id_rsa|id_ed25519|[^/]*\.(pem|key|p12|pfx|jks|keystore|sqlite3?|db|dump|bak)$|credentials?([^/]*$|/))' || true
```

Expected: no blob at or above 10 MB. Filename matches are limited to source modules/tests whose names describe secret handling; no credential or private-key file is present.

- [ ] **Step 3: Scan reachable history for high-signal credentials**

Run:

```bash
for commit in $(git rev-list HEAD); do
  git grep -I -l -E '(BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY|AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9]{20,})' "$commit" -- 2>/dev/null |
    sed "s#^$commit:##"
done | sort -u
```

Expected: any output is limited to credential-verifier source or security tests and is inspected as a scanner/test literal. Any other path blocks publication.

- [ ] **Step 4: Confirm the target repository still does not exist**

Run:

```bash
gh auth status
if gh repo view 1229391595max-oss/NEWCaostone --json nameWithOwner,visibility >/dev/null 2>&1; then
  echo 'target_repository_already_exists'
  exit 1
fi
```

Expected: GitHub authentication is active and the repository lookup reports not found. Any other authentication or network failure must be distinguished from an existing repository before proceeding.

- [ ] **Step 5: Create the annotated team-preview tag locally**

Run:

```bash
git tag -a team-preview-2026-08-18 -m "Private teammate preview; not a Production release" HEAD
git rev-parse HEAD
git rev-parse 'team-preview-2026-08-18^{}'
```

Expected: both commit identities match exactly.

---

### Task 4: Create the private GitHub repository and publish the exact preview

**Files:**
- External create: GitHub repository `1229391595max-oss/NEWCaostone`
- External push: branch `main`
- External push: tag `team-preview-2026-08-18`

**Interfaces:**
- Consumes: privacy-checked clean `HEAD` and annotated local preview tag from Task 3.
- Produces: a private teammate repository with one branch and one preview tag.

- [ ] **Step 1: Preserve the local-source remote and create the empty private repository**

Run:

```bash
git remote rename origin source-local
gh repo create 1229391595max-oss/NEWCaostone \
  --private \
  --description "Private BizPulse team preview: implemented scope, evidence status, and roadmap"
git remote add origin https://github.com/1229391595max-oss/NEWCaostone.git
```

Expected: repository creation succeeds once; `source-local` still points to the local source repository and `origin` points to the new GitHub repository.

- [ ] **Step 2: Reconfirm private visibility before the first push**

Run:

```bash
gh repo view 1229391595max-oss/NEWCaostone --json nameWithOwner,visibility,url,defaultBranchRef
```

Expected: `visibility` is `PRIVATE`. If it is not private, stop before pushing.

- [ ] **Step 3: Push only the reviewed branch as remote main**

Run:

```bash
git push -u origin HEAD:main
git push origin refs/tags/team-preview-2026-08-18
```

Expected: both pushes succeed without force; no other local branch or tag is included.

- [ ] **Step 4: Set and verify the default branch**

Run:

```bash
gh repo edit 1229391595max-oss/NEWCaostone --default-branch main
gh repo view 1229391595max-oss/NEWCaostone --json defaultBranchRef,visibility,url
```

Expected: default branch is `main` and visibility remains `PRIVATE`.

---

### Task 5: Verify remote identity, content, and publication boundary

**Files:**
- Inspect external branch: `refs/heads/main`
- Inspect external tag: `refs/tags/team-preview-2026-08-18`
- Inspect external repository tree

**Interfaces:**
- Consumes: published private repository.
- Produces: remote evidence that the exact local preview was published without unrelated branches or excluded artifacts.

- [ ] **Step 1: Compare local and remote commit identities**

Run:

```bash
local_head=$(git rev-parse HEAD)
remote_main=$(git ls-remote origin refs/heads/main | awk '{print $1}')
remote_tag_commit=$(git ls-remote origin 'refs/tags/team-preview-2026-08-18^{}' | awk '{print $1}')
test "$local_head" = "$remote_main"
test "$local_head" = "$remote_tag_commit"
printf 'local=%s\nremote_main=%s\nremote_tag=%s\n' "$local_head" "$remote_main" "$remote_tag_commit"
```

Expected: all three SHA values are identical.

- [ ] **Step 2: Verify only one branch and the intended tag were published**

Run:

```bash
gh api repos/1229391595max-oss/NEWCaostone/branches --paginate --jq '.[].name'
git ls-remote --tags origin
```

Expected: branch output contains only `main`; tag output contains only the annotated `team-preview-2026-08-18` tag and its peeled commit line.

- [ ] **Step 3: Verify excluded artifact paths are absent remotely**

Run:

```bash
gh api 'repos/1229391595max-oss/NEWCaostone/git/trees/main?recursive=1' --jq '.tree[].path' > /tmp/newcaostone-team-preview-remote-paths.txt
if rg -n '(^|/)(\.tmp|outputs|deliverables)(/|$)|newcaostone-demo-url-qr\.png$|\.DS_Store$|\.inspect\.ndjson$' /tmp/newcaostone-team-preview-remote-paths.txt; then
  exit 1
fi
rg -n '^(README\.md|docs/TEAM_STATUS\.md|docs/ROADMAP\.md)$' /tmp/newcaostone-team-preview-remote-paths.txt
```

Expected: no excluded path match; all three team documents are present.

- [ ] **Step 4: Preserve immutable publication evidence**

Do not change the already-published commit merely to claim that it was published. Report the verified private repository URL, exact SHA, branch, tag, local test evidence, CI-not-configured boundary, and remaining Task 12 boundary in the user handoff.

- [ ] **Step 5: Final local closeout check**

Run:

```bash
git status --short --branch
git log -1 --format='%H%n%s'
gh repo view 1229391595max-oss/NEWCaostone --json nameWithOwner,visibility,defaultBranchRef,url
```

Expected: clean local publication clone; final SHA is the same verified remote `main`; repository remains private with default branch `main`.
