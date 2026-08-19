# Integrated Viewer / AI Local Acceptance Review

Date: 2026-08-16 (America/Chicago)

Scope: Integrated Viewer / AI / Anti-Drift plan Tasks 1–13 in the isolated
local worktree. This review is local product evidence only.

## Result

The concentrated Task 13 acceptance and security set passed:

```sh
cd /Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift/bizpulse
.venv/bin/python scripts/test_postgres.py \
  tests/acceptance/test_exact_15_sessions.py \
  tests/acceptance/test_restart_readback.py \
  tests/acceptance/test_rollback_compatibility.py \
  tests/acceptance/test_browser_smoke.py \
  tests/security/test_cross_session_isolation.py \
  tests/security/test_ai_chat_boundary.py -q
```

Observed result: `16 passed in 71.37s`.

Supporting focused checks also passed:

- language-shell, Viewer Evidence and catalog tests: 23 passed;
- verification selector policy: 25 passed;
- the full browser file by itself: 2 passed in 76.89 seconds;
- exact-15 by itself: 1 passed in 17.92 seconds;
- restart by itself: 1 passed in 11.41 seconds;
- rollback by itself: 1 passed in 6.49 seconds.

All PostgreSQL and Blob state was disposable. AI used deterministic fake
providers and test-only injected values. No real Key, paid request, external
image or external action execution was used.

## Contract coverage

| Contract | Local evidence |
|---|---|
| Product Theater | Four ordered local SVG slides; manual previous/next/dot controls; 6-second autoplay; reduced-motion disables autoplay while retaining manual controls. |
| Responsive browser | 1280×900, 820×900 and 390×844 have no blocking horizontal overflow. |
| Language | English and Chinese catalogs switch the active business view; Viewer Evidence displays only the selected language. |
| Login | The stable heading and submit label are exactly `Sign in`; retired `Operator sign in` is absent. |
| Viewer areas | Data & Evidence, Overview, Sales, Inventory, Profit and AI Decision Center are reachable. Forecast and Action Inbox remain inside the AI Decision Center. |
| Viewer boundary | No upload input or Operator import/publish controls appear. Evidence reads the pinned release. |
| Prompt presets | Exactly six server-owned versioned presets are visible in general Ask. A non-empty draft requires replacement confirmation. |
| Explicit Send | Clicking the monthly report preset changes only the textarea. Browser request-method evidence proves no Chat POST occurs until Send. |
| Monthly report | The exact preset uses the bounded monthly tool and displays the pinned `2026-07-01` through `2026-07-31` release period. |
| Edited prompt | Edited preset text is preserved and submitted through the planner path with complete audit metadata. |
| Viewer Action | Three estimates are shown: purchase cash, budget change and additional cover. Review state remains session-local. |
| Exact-15 | Fifteen unique sessions share one `release_id` and `dataset_version_id`; each receives an isolated Chat turn and Action overlay. |
| No authority copies | Dataset series, dataset version, artifact, analysis-run, public-release and Blob-object counts are equal before and after exact-15 admission and Action edits. |
| Restart | One unexpired Viewer recovers release, analysis and Chat after process replacement. A separately expired Viewer returns 401 and its Chat/overlay rows are removed. |
| Rollback | The attested prior application reads the forward schema and release pointers while Alembic remains at `0009_prompt_preset_audit`; no downgrade runs. |
| One in flight | With the limit set to one, an existing active turn blocks a second turn before any provider attempt. |
| Global budget | One completed provider attempt exhausts the injected daily limit for a second Operator session; no second provider attempt occurs. |
| Isolation | One Viewer cannot read or act on another Viewer's Chat; reset and expiry clear only the targeted session's Action overlay and Chat. |
| Provider failure | Unavailable, budget and disabled terminal states remain usable while analytical pages still load. |
| Operator controls | Authenticated local browser flow retains import, immutable version commit, publish, Action export/download and synthetic outcome recording. |
| Browser hygiene | Zero console errors and zero HTTP(S) requests outside the local same origin. |

## Acceptance-discovered wiring fixes

The browser tests exposed two real presentation seams:

1. language switching updated the shell but did not re-render the active
   business route; the handler now re-renders the same route after catalog and
   release-label updates;
2. Viewer Data & Evidence still concatenated English and Chinese strings; it
   now uses the central catalog and renders exactly one language.

The anti-drift policy also gained explicit exact-15 and browser acceptance
domains, and rollback compatibility now selects migration/restart/rollback
checks as well as release-static checks.

## Demonstration limits

- All business data is preconfigured sample data; it is not real-market proof.
- Exact-15 is a bounded classroom/Demo capacity claim, not a Production load
  or stress-test claim.
- Viewer users cannot upload. Operator import is authenticated and separate.
- Action changes are estimates and overlays only. They do not create authority
  data or execute on Shopee, Mercado Livre or another external platform.
- The monthly report reads completed snapshots and existing evidence. It does
  not import, scan raw files, launch analysis jobs or extend the release period.
- Hosted AI remains disabled. Local implementation does not prove a hosted Key,
  a paid call or hosted AI acceptance.

## Evidence classification

| State | Classification |
|---|---|
| Implemented | Yes, locally. |
| Focused local acceptance | Yes. |
| Candidate committed | Pending when this review was written; the review is included in that candidate commit. |
| Changed-path selector | Must run after the candidate commit with `--no-reuse`. |
| Local release attestation | Not yet; Task 14 only. |
| Deployed / Hosted verified | Unchanged from `release/current_authority.json`. |
| Azure accepted | Not claimed. |
| Real or paid AI | Not used. |
| Production ready | No. |

## Remaining gate

Task 14 requires a fresh sanitized observation under the ignored local
authority-artifact path and a matching checked-in attestation. A missing, stale
or unbound observation is a fail-closed stop, not permission to query or modify
Azure. Any later Key injection, paid AI call, registry work or deployment needs
separate explicit authorization.
