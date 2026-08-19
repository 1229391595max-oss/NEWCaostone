# NEWCaostone Deployed Diagnostic D2 Response Compatibility and Integration Design

**Date:** 2026-08-16
**Status:** Approved design, pending written-spec review
**Scope:** Local code, tests, documentation, Git commits, isolated integration evidence, and generation of a successor one-shot diagnostic package. No Azure request or mutation is authorized by this design.

## 1. Outcome

D2 repairs the local deployed-state diagnostic that consumed D1 after one successful application read and one successful revisions request. It must accept Azure-compliant collection terminal pages, preserve the existing fail-closed network and secret boundaries, produce useful safe failure provenance, record real completion times, and close the local branch-integration ambiguity before a successor package is generated.

D2 does not prove hosted health, deployment acceptance, recovery success, AI availability, or Production readiness. The failed D1 receipt remains immutable and consumed.

## 2. Confirmed Evidence

The following facts are current evidence, not assumptions:

- D1 SHA `8b05ef98021b7111aa556d39342270425b10c35b7976bda5b065540ccf1a73af` executed once and is consumed.
- Its receipt is mode `0600`, has status `failed`, records one completed logical read (`application`), and contains `diagnostic_arm_response_invalid`.
- The observation file was not created.
- The two corresponding Azure CLI `rest` command logs both report exit code `0`; therefore the failure occurred after the revisions response was returned, inside local response handling.
- `scripts/observe_deployed_release_state.py` requires every collection page to have exactly the keys `value` and `nextLink`.
- The existing test suite explicitly treats a page containing only `value` as invalid.
- Microsoft Azure REST guidance says services should omit JSON fields whose value is null and clients must treat missing and null fields as semantically equivalent.
- The D1 implementation is committed on `codex/integrated-viewer-ai-anti-drift`; the failure was not caused by an uncommitted reader.
- The implementation branch is not merged into `main`. The current graph has six `main`-only commits and 234 implementation-branch-only commits. Five main-side design/handoff changes were introduced into the implementation line with different commit identities, so integration must be content-aware.

## 3. Root Cause

The primary root cause is a contract error in both production code and tests. The reader interpreted the collection response schema as an exact-key schema and required a nullable pagination field to be present. A valid terminal page that omits `nextLink` is therefore rejected after a successful ARM request.

The test suite passed because it encoded the same incorrect assumption. This is specification drift, not a missing commit, Azure authentication failure, or unsuccessful ARM request.

The raw D1 response was intentionally not retained. D2 therefore fixes the confirmed contract error without claiming the discarded response body as evidence.

## 4. Repair Scope

### 4.1 Collection response compatibility

`read_arm_collection` must:

- require the page to be a JSON object;
- require `value` to exist and be a list;
- interpret an absent `nextLink` or `nextLink: null` as a terminal page;
- require a present non-null `nextLink` to be a non-empty string;
- safely ignore unrelated top-level response fields;
- continue rejecting duplicate JSON keys;
- continue scanning the full decoded response for prohibited secret values before projection;
- continue enforcing the exact ARM host, HTTPS, resource path, API version, pagination token, page count, response-byte, request-count, timeout, and zero-retry limits.

Unknown top-level fields are ignored only after the entire response passes the existing secret and JSON integrity gates. They are never copied into the sanitized observation.

### 4.2 Safe failure provenance

ARM read and collection helpers must receive an allowlisted stage and resource role from their caller. A failure must identify the logical boundary without exposing the resource name, URL, response body, stdout, stderr, exception text, or secret values.

Expected mappings are:

- application resource: stage `application`, role `application`;
- revisions collection: stage `revision`, role `revision`;
- job resource: stage `job`, role equal to the allowlisted job role;
- job executions collection: stage `execution`, role equal to the allowlisted job role.

The existing safe error codes remain sufficient. D2 changes provenance, not the external secret boundary.

### 4.3 Owner-only evidence write failures

The runner must translate local observation creation, readback, hashing, and atomic receipt-update failures into `diagnostic_observation_write_failed` whenever a safe failed receipt can still be written.

Required behavior:

- no Azure request occurs if the initial receipt cannot be created;
- observation-write or observation-readback failure leaves no claim of completion;
- the receipt becomes `failed` when it can be updated safely;
- a failure to update the receipt itself remains a consumed crash state rather than authorizing replay;
- all receipt and observation files remain mode `0600`;
- partial or existing files never authorize a retry.

### 4.4 Real completion time

`started_at` and `observed_at` remain the bound attempt time used for package validity and deployed-state classification. `completed_at` must be captured after success or handled failure, using an injectable UTC clock for deterministic tests.

The runner must reject a naïve completion time and must never record a completion earlier than the start. Tests must demonstrate a positive elapsed interval rather than reusing `observed_at`.

## 5. Authority-Aware Branch Integration Gate

Branch integration is a required D2 deliverable, not an informational note.

### 5.1 Why a direct merge is unsafe

The implementation branch began from the approved development anchor and safely introduced five design/handoff commits in sequence. Those changes also exist on `main` under their original identities. `main` later added a handoff redirect. A blind merge or a rebase of 234 commits could duplicate history, revive stale authority text, or overwrite a newer incident handoff.

### 5.2 Required process

After D2 code is committed and verified on the implementation branch:

1. Confirm the implementation and main worktrees are clean. Preserve and stop on overlapping user changes.
2. Record exact `main`, implementation HEAD, merge-base, tree hashes, and `git rev-list --left-right --count` output.
3. Use patch-equivalence and file-content comparison to classify every main-only commit as:
   - equivalent content already introduced;
   - genuinely missing current content; or
   - superseded authority/handoff content.
4. Create branch `codex/integrated-viewer-ai-anti-drift-d2-integration` and an isolated worktree from current `main`; do not rewrite either existing branch.
5. Merge the implementation branch into the isolated integration branch with history preserved. Resolve only actual content overlap, using the newest approved D2 authority and incident state.
6. Run the D2 focused tests, release-static suite, `verify_changed` from the recorded integration base, and authority-drift checks in the integration worktree.
7. Record an integration report containing the exact merge commit, tree SHA, classification of the six main-only commits, verification commands, and evidence boundaries.
8. Do not move `main`, push, open a PR, run CI, or deploy as part of D2. Final integration into `main` remains a separately reported local branch-completion choice.

This approach avoids rewriting the large implementation history while proving that current `main` content and the complete feature line can coexist.

## 6. Test-Driven Implementation

Each production change begins with a failing focused test.

### Cycle A: collection terminal pages

- missing `nextLink` succeeds as a terminal page;
- explicit null `nextLink` succeeds;
- an unrelated safe top-level field is ignored;
- missing or non-list `value` fails;
- invalid non-null `nextLink` fails;
- cross-host, cross-path, extra-query, oversized, excessive-page, and duplicate-key cases remain rejected.

### Cycle B: end-to-end runner response shape

- all mocked revision and execution terminal pages omit `nextLink`;
- the one-shot runner completes locally with exactly the expected ten mocked ARM reads;
- receipt and observation stay mode `0600` and contain no raw response values.

### Cycle C: failure provenance

- malformed revisions response records stage/role `revision`;
- failed job-resource response records stage `job` and the exact allowlisted role;
- failed execution collection records stage `execution` and the exact allowlisted role;
- receipt text contains no injected stdout, stderr, URL, resource name, or secret.

### Cycle D: persistence and timestamps

- observation write/readback failure produces the safe failure code when receipt finalization is possible;
- initial receipt failure performs zero ARM calls;
- receipt-finalization crash stays consumed and is not replayable;
- completed and failed attempts use an actual injected completion time later than `started_at`.

## 7. Verification

Before creating a successor package, run at minimum:

- the focused observer and runner tests;
- all deployed diagnostic package, Bicep projection, observer, and runner tests;
- the release-static verification selection;
- Ruff and Python compilation for changed Python files;
- `verify_changed` against the exact pre-D2 implementation base, with no reused result;
- the same relevant verification again in the isolated integration worktree against its recorded base;
- authority-contract and dirty-worktree checks.

No success statement may exceed the evidence. Local mocked completion proves parser and runner behavior only.

## 8. Successor Package

Only after both the implementation branch and isolated integration candidate pass verification may the tooling generate `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md`, bound to:

- the integration branch name;
- exact integration HEAD and tree SHA;
- exact continuation SHA;
- exact desired projection SHA;
- exact control SHA;
- exact toolchain versions;
- a new authorization ID and expiry;
- new receipt and observation paths;
- the same zero-retry and read-only ARM boundaries.

Generating D2 is a local action. Executing D2 requires a new explicit approval containing its exact SHA-256. No Azure request is made during this implementation scope.

The new evidence paths are `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_ATTEMPT_RECEIPT.json` and `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_OBSERVATION.json`; they must be absent when D2 is generated.

## 9. Explicit Non-Goals

D2 does not:

- replay or modify D1 evidence;
- access Keychain, registry, public application URLs, AI providers, or paid services;
- mutate Azure resources;
- loosen tenant, host, path, method, timeout, byte, page, or retry limits;
- claim the currently deployed release is healthy;
- move `main`, push, create a PR, run CI, or deploy.

## 10. References

- Microsoft Azure REST API Guidelines: <https://github.com/microsoft/api-guidelines/blob/vNext/azure/Guidelines.md>
- Container Apps Revisions List, API `2024-03-01`: <https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/container-apps-revisions/list-revisions?view=rest-resource-manager-containerapps-2024-03-01>
- Container Apps Jobs Executions List, API `2024-03-01`: <https://learn.microsoft.com/en-us/rest/api/resource-manager/containerapps/jobs-executions/list?view=rest-resource-manager-containerapps-2024-03-01>
