# No-AI Chat Availability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a restricted no-AI deployment show Ask BizPulse as explicitly unavailable without a browser console error, while every Chat mutation remains fail-closed.

**Architecture:** The server will authenticate the list request before returning a bounded `ChatTurnListResponse` availability projection. The frontend will carry that projection from reducer to view model and render a clear bilingual no-AI state with no enabled Chat controls. A real local Chrome acceptance path will run the normal core workflow against an application whose Chat service is absent, proving the hosted failure mode cannot recur.

**Tech Stack:** FastAPI, Pydantic v2, PostgreSQL test harness, native Node.js tests, browser CDP gate, Python pytest.

## Global Constraints

- Keep `BIZPULSE_AI_CHAT_ENABLED=false`; do not add an OpenAI key, provider configuration, or provider request.
- `GET /api/v1/ai-chat/turns` must authenticate its viewer/operator first and retain `Cache-Control: private, no-store` plus `Vary: Cookie`.
- Only the list projection changes for a disabled service. Submit, save, draft, get-by-id, and session mutations continue returning `503 AI_CHAT_UNAVAILABLE` when no service exists.
- Do not suppress, filter, or downgrade browser console errors in `scripts/browser_release_gate.mjs`.
- Preserve the existing available Chat contract, server-owned scope, CSRF boundary, session pinning, and saved-Q&A behavior.
- Do not touch Azure, ACR, Keychain, secrets, or the currently deployed image during implementation. A new immutable image and a new SHA-specific launch authorization are required after the code is verified.

---

### Task 1: Make the authenticated Chat list expose a closed availability projection

**Files:**
- Modify: `api/v1/schemas/ai_chat.py:105-109`
- Modify: `api/v1/routers/ai_chat.py:214-237`
- Modify: `tests/api/v1/test_ai_chat.py`

**Interfaces:**
- Consumes: the existing session-scoped `_principal(request, mutate=False)` and `PRIVATE_NO_STORE` route helpers.
- Produces: `ChatTurnListResponse` with required `availability: Literal["available", "unavailable"]` and `unavailable_code: Literal["AI_CHAT_UNAVAILABLE"] | None` fields.
- Produces: an authenticated disabled-service list response with `items=()`, `saved_items=()`, `recommended_questions=()`, `availability="unavailable"`, and `unavailable_code="AI_CHAT_UNAVAILABLE"`.

- [ ] **Step 1: Write the failing API regression**

  Add `test_disabled_chat_list_is_authenticated_availability_projection` to `tests/api/v1/test_ai_chat.py`. Seed the operator and public synthetic release exactly as the existing route test does, build the default container without replacing `ai_chat_service`, and assert all three boundaries:

  ```python
  with TestClient(app) as anonymous:
      assert anonymous.get("/api/v1/ai-chat/turns").status_code == 401

  with TestClient(app) as operator:
      login = operator.post(
          "/api/operator/login",
          headers={"Origin": ORIGIN},
          json={"login_name": LOGIN_NAME, "password": PASSWORD},
      )
      listed = operator.get("/api/v1/ai-chat/turns")
      rejected = operator.post(
          "/api/v1/ai-chat/turns",
          headers={
              "Origin": ORIGIN,
              "X-CSRF-Token": login.json()["csrf_token"],
              "Idempotency-Key": "no-ai-submit",
          },
          json={"recommended_question_id": "data_quality"},
      )

  assert listed.status_code == 200
  assert listed.headers["cache-control"] == "private, no-store"
  assert listed.headers["vary"] == "Cookie"
  assert listed.json() == {
      "items": [],
      "saved_items": [],
      "recommended_questions": [],
      "availability": "unavailable",
      "unavailable_code": "AI_CHAT_UNAVAILABLE",
  }
  assert rejected.status_code == 503
  assert rejected.json() == {"code": "AI_CHAT_UNAVAILABLE"}
  ```

  Extend the existing available-service assertions so a normal list explicitly returns:

  ```python
  assert listed.json()["availability"] == "available"
  assert listed.json()["unavailable_code"] is None
  ```

- [ ] **Step 2: Run the focused regression and confirm the pre-change failure**

  Run:

  ```bash
  .venv/bin/python scripts/test_postgres.py \
    tests/api/v1/test_ai_chat.py::test_disabled_chat_list_is_authenticated_availability_projection -q
  ```

  Expected before implementation: `FAILED`; the authenticated GET currently returns HTTP 503 rather than the bounded JSON projection.

- [ ] **Step 3: Implement the smallest closed contract change**

  In `api/v1/schemas/ai_chat.py`, make the list metadata explicit and required:

  ```python
  class ChatTurnListResponse(BaseModel):
      items: tuple[ChatTurnResponse, ...]
      saved_items: tuple[ChatTurnResponse, ...]
      recommended_questions: tuple[RecommendedQuestionResponse, ...]
      availability: Literal["available", "unavailable"]
      unavailable_code: Literal["AI_CHAT_UNAVAILABLE"] | None
  ```

  In `list_turns`, resolve the principal before branching on `_service(request)`. Keep `AuthenticationRequiredError` raising unchanged. Set `PRIVATE_NO_STORE` before either success response. Return the disabled projection only after that authenticated scope check:

  ```python
  @router.get("/turns")
  def list_turns(request: Request, response: Response):
      service = _service(request)
      try:
          principal = _principal(request, mutate=False)
      except AuthenticationRequiredError:
          raise
      except Exception as error:
          return _error(error, request)

      response.headers.update(PRIVATE_NO_STORE)
      if service is None:
          return ChatTurnListResponse(
              items=(),
              saved_items=(),
              recommended_questions=(),
              availability="unavailable",
              unavailable_code="AI_CHAT_UNAVAILABLE",
          )
      try:
          turns = service.list(principal)
          saved_turns = service.list_saved(principal)
      except Exception as error:
          return _error(error, request)
      return ChatTurnListResponse(
          items=tuple(ChatTurnResponse.model_validate(turn, from_attributes=True) for turn in turns),
          saved_items=tuple(ChatTurnResponse.model_validate(turn, from_attributes=True) for turn in saved_turns),
          recommended_questions=service.recommended_questions(),
          availability="available",
          unavailable_code=None,
      )
  ```

  Do not alter the earlier service-null guards on POST, turn-detail, save, draft, or DELETE routes.

- [ ] **Step 4: Run the route suite and confirm both service modes pass**

  Run:

  ```bash
  .venv/bin/python scripts/test_postgres.py tests/api/v1/test_ai_chat.py -q
  ```

  Expected: all tests pass; the existing enabled-service route test still verifies Chat output, while the new no-service test verifies authenticated availability, no-store headers, and a fail-closed POST.

- [ ] **Step 5: Commit the independently verified API contract**

  ```bash
  git add api/v1/schemas/ai_chat.py api/v1/routers/ai_chat.py tests/api/v1/test_ai_chat.py
  git commit -m "fix: expose no-ai chat availability"
  ```

### Task 2: Carry the availability projection through the Ask BizPulse UI

**Files:**
- Modify: `frontend/assets/features/ask-bizpulse/state.mjs:1-78`
- Modify: `frontend/assets/features/ask-bizpulse/view-model.mjs:45-76`
- Modify: `frontend/assets/features/ask-bizpulse/view.mjs:137-220`
- Modify: `tests/frontend/ask-bizpulse-state.test.mjs`
- Modify: `tests/frontend/ask-bizpulse-view-model.test.mjs`
- Modify: `tests/frontend/ask-bizpulse-view.test.mjs`

**Interfaces:**
- Consumes: the server JSON keys `availability` and `unavailable_code` from `ChatTurnListResponse`.
- Produces: state fields `availability` (`"available" | "unavailable"`) and `unavailableCode` (`string | null`).
- Produces: a view model with `chatAvailable: boolean`, no recommended questions in unavailable mode, and a public-facing bilingual explanation.

- [ ] **Step 1: Write failing state and view-model regressions**

  Add a reducer assertion that a loaded unavailable projection is a ready state, not an error:

  ```javascript
  state = reduceAskBizPulse(state, {
    type: "chat/loaded",
    generation: 1,
    payload: {
      items: [],
      saved_items: [],
      recommended_questions: [{ id: "data_quality", label: "Data quality" }],
      availability: "unavailable",
      unavailable_code: "AI_CHAT_UNAVAILABLE",
    },
  });
  assert.equal(state.status, "ready");
  assert.equal(state.availability, "unavailable");
  assert.equal(state.unavailableCode, "AI_CHAT_UNAVAILABLE");
  ```

  Add a view-model regression proving unavailable state cannot surface question affordances:

  ```javascript
  const model = toAskBizPulseViewModel({
    release: { version_number: 2, dataset_version_id: "version-1" },
    mode: "viewer",
    status: "ready",
    turns: [],
    savedTurns: [],
    recommendedQuestions: [{ id: "data_quality", label: "Data quality" }],
    availability: "unavailable",
    unavailableCode: "AI_CHAT_UNAVAILABLE",
    submitting: false,
    context: null,
    error: null,
  });
  assert.equal(model.chatAvailable, false);
  assert.equal(model.unavailableCode, "AI_CHAT_UNAVAILABLE");
  assert.deepEqual(model.recommendedQuestions, []);
  ```

  Add a lightweight fake-DOM `renderAskBizPulse` regression following the existing `FakeElement` pattern in `tests/frontend/workspace.test.mjs`. It must find the notice text, the disabled `<textarea>`, and the disabled `Ask / 提问` button, then assert no recommended-question button was appended.

- [ ] **Step 2: Run the focused Node tests and confirm they fail first**

  Run:

  ```bash
  node --test \
    tests/frontend/ask-bizpulse-state.test.mjs \
    tests/frontend/ask-bizpulse-view-model.test.mjs \
    tests/frontend/ask-bizpulse-view.test.mjs
  ```

  Expected before implementation: the new state/view-model assertions fail because the reducer and model currently discard the availability fields, and the UI has enabled composer controls.

- [ ] **Step 3: Implement one immutable projection path from reducer to renderer**

  In `initialAskBizPulseState`, set safe enabled defaults for pre-load behavior:

  ```javascript
  availability: "available",
  unavailableCode: null,
  ```

  In the `chat/loaded` reducer branch, retain the closed server projection and default only absent legacy payloads to available:

  ```javascript
  availability: action.payload?.availability === "unavailable" ? "unavailable" : "available",
  unavailableCode: action.payload?.unavailable_code === "AI_CHAT_UNAVAILABLE"
    ? "AI_CHAT_UNAVAILABLE"
    : null,
  ```

  In `toAskBizPulseViewModel`, compute and expose:

  ```javascript
  const chatAvailable = state.availability !== "unavailable";
  // ...
  recommendedQuestions: chatAvailable ? filteredQuestions : [],
  chatAvailable,
  unavailableCode: chatAvailable ? null : state.unavailableCode ?? "AI_CHAT_UNAVAILABLE",
  ```

  In `renderAskBizPulse`, render a text-only, accessible notice before the composer when unavailable:

  ```javascript
  if (!model.chatAvailable) {
    const notice = element(
      "p",
      "action-feedback",
      "AI chat is disabled for this restricted synthetic demo / 当前受限纯合成演示未启用 AI 问答",
    );
    notice.setAttribute("role", "status");
    notice.setAttribute("aria-live", "polite");
    composer.append(notice);
  }
  ```

  Use one boolean for all composer controls:

  ```javascript
  const composerDisabled = model.submitting || !model.chatAvailable;
  button.disabled = composerDisabled;
  question.disabled = composerDisabled;
  submit.disabled = composerDisabled;
  ```

  Do not call `effects.submit` from any unavailable branch, and do not replace the API’s 503 behavior for direct mutation clients.

- [ ] **Step 4: Run the focused UI suite and verify available behavior remains intact**

  Run:

  ```bash
  node --test \
    tests/frontend/ask-bizpulse-state.test.mjs \
    tests/frontend/ask-bizpulse-view-model.test.mjs \
    tests/frontend/ask-bizpulse-view.test.mjs \
    tests/frontend/ask-bizpulse-effects.test.mjs
  ```

  Expected: all tests pass. The disabled projection is rendered without an error state, and the existing context, stale-async, idempotency, and available-chat behavior remain green.

- [ ] **Step 5: Commit the independently verified UI boundary**

  ```bash
  git add frontend/assets/features/ask-bizpulse/state.mjs \
    frontend/assets/features/ask-bizpulse/view-model.mjs \
    frontend/assets/features/ask-bizpulse/view.mjs \
    tests/frontend/ask-bizpulse-state.test.mjs \
    tests/frontend/ask-bizpulse-view-model.test.mjs \
    tests/frontend/ask-bizpulse-view.test.mjs
  git commit -m "fix: render restricted no-ai chat state"
  ```

### Task 3: Reproduce the no-AI browser path with a real local application process

**Files:**
- Modify: `tests/acceptance/support.py:93-136, 300-370`
- Modify: `tests/acceptance/restart_server.py:20-41`
- Modify: `tests/acceptance/test_browser_smoke.py:46-120`

**Interfaces:**
- Consumes: `gateway_mode="disabled"` from `acceptance_server` into `restart_server.py`.
- Produces: `build_acceptance_app(..., ai_enabled: bool = True)` so the existing normal, provider-unavailable, and budget test modes stay unchanged while disabled mode has `ai_chat_service=None`.
- Produces: a real Chrome core-gate acceptance pass against the disabled Chat service, with the gate’s existing console-error rejection unmodified.

- [ ] **Step 1: Add the failing local Chrome regression**

  Extend `test_real_browser_runs_full_same_origin_release_gate` with a disabled-service process:

  ```python
  with acceptance_server(
      migrated_engine,
      container,
      gateway_mode="disabled",
  ) as base_url:
      no_ai_core = _run_gate(base_url, "core")

  assert no_ai_core == {
      "consoleErrors": 0,
      "externalRequests": 0,
      "operator": True,
      "operatorExport": True,
      "operatorImport": True,
      "operatorOutcome": True,
      "operatorPublish": True,
      "pinnedRefresh": True,
      "scenario": "core",
      "sessionsEnded": 2,
      "viewers": 2,
      "viewports": [390, 820, 1280],
  }
  ```

- [ ] **Step 2: Run the real browser regression and confirm the current failure**

  Run:

  ```bash
  .venv/bin/python scripts/test_postgres.py \
    tests/acceptance/test_browser_smoke.py::test_real_browser_runs_full_same_origin_release_gate -q -rs
  ```

  Expected before implementation: the disabled service either cannot be constructed by the acceptance helper or the core browser gate fails with `browser_console_errors` caused by `GET /api/v1/ai-chat/turns` returning 503.

- [ ] **Step 3: Give the acceptance server a true service-absent mode**

  Add an `ai_enabled: bool = True` keyword-only parameter to `build_acceptance_app`. Construct the `AIChatService` only when it is true, and set the container’s field to `None` otherwise:

  ```python
  chat = None
  if ai_enabled:
      chat = AIChatService(
          engine=engine,
          workspace_id=WORKSPACE_ID,
          catalog=QueryCatalog(),
          executor=QueryExecutor(backend=PostgresQueryBackend(...)),
          gateway=gateway or BoundedLatencyGateway(),
          budget_limits=budget_limits or AIBudgetLimits(...),
          action_service=actions,
          clock=clock,
      )
  # ...
  ai_chat_service=chat,
  ```

  In `restart_server.py`, keep the existing unavailable gateway and budget modes intact, and pass:

  ```python
  ai_enabled=gateway_mode != "disabled",
  ```

  Do not add a special browser scenario or a console-error allowlist: the existing core workflow must pass exactly as-is when the list endpoint returns its successful unavailable projection.

- [ ] **Step 4: Run the real browser acceptance test and confirm no console error is hidden**

  Run:

  ```bash
  .venv/bin/python scripts/test_postgres.py tests/acceptance/test_browser_smoke.py -q -rs
  ```

  Expected: all browser smoke cases pass. The disabled-service core path reports `consoleErrors: 0`, uses no external request, and still exercises viewer pinning, operator import/publish/export/outcome, and session end behavior.

- [ ] **Step 5: Commit the verified end-to-end regression**

  ```bash
  git add tests/acceptance/support.py tests/acceptance/restart_server.py tests/acceptance/test_browser_smoke.py
  git commit -m "test: cover no-ai browser release gate"
  ```

### Task 4: Verify the candidate locally and prepare, but do not execute, a fresh Azure authorization

**Files:**
- Modify only if verification exposes a real defect: the exact file covered by the failing regression above.
- Create after all tests are green: the repository’s normal local release attestation artifact via `scripts/create_release_manifest.py`.

**Interfaces:**
- Consumes: the committed candidate Git SHA and all eight required local release gates.
- Produces: a local-only release attestation for the new candidate, followed by a new, separately reviewed Azure authorization package that names the new immutable image digest.

**Successor-attestation amendment (2026-08-15):** The existing
`release/task15-local-release-manifest.json` is a committed immutable proof for
the earlier deployed candidate and must never be overwritten. New candidates
derive one append-only manifest path from their exact 40-character Git SHA:
`bizpulse/release/attestations/<candidate-sha>.json`. The generator,
detached-attestation verifier, candidate-file boundary, and hosted
authorization verifier must all derive the same path. The two historical
static paths remain accepted only for their exact historical candidate SHAs.

- [ ] **Step 1: Run the focused API, frontend, and browser evidence together**

  Run:

  ```bash
  .venv/bin/python scripts/test_postgres.py tests/api/v1/test_ai_chat.py -q
  node --test \
    tests/frontend/ask-bizpulse-state.test.mjs \
    tests/frontend/ask-bizpulse-view-model.test.mjs \
    tests/frontend/ask-bizpulse-view.test.mjs \
    tests/frontend/ask-bizpulse-effects.test.mjs
  .venv/bin/python scripts/test_postgres.py tests/acceptance/test_browser_smoke.py -q -rs
  ```

  Expected: every command exits 0. If any command fails, stop at its first failing regression and repair only the code in Tasks 1–3 before creating a candidate attestation.

- [ ] **Step 2: Create and verify the local candidate attestation**

  First require a clean worktree and capture the candidate:

  ```bash
  git status --short
  candidate_sha=$(git rev-parse HEAD)
  .venv/bin/python scripts/verify_release.py \
    --manifest tests/fixtures/synthetic/v1/manifest.json
  .venv/bin/python scripts/create_release_manifest.py \
    --candidate-sha "$candidate_sha"
  .venv/bin/python scripts/create_release_manifest.py --verify-attestation
  ```

  Expected: empty `git status --short`, `release_verification=ok`, `release_manifest=ok`, and `release_attestation=ok`. If the manifest changes create a child commit, rerun `--verify-attestation` after that commit exactly as the repository’s two-commit procedure requires.

- [ ] **Step 3: Stop before any cloud mutation and request a new exact authorization**

  Build/inspect the new immutable Linux/amd64 image and create a new no-AI Azure authorization package only through the repository’s approved release tooling. Report its SHA-256, expiry, target resource group/app/image digest, and the exact non-AI gates it will run. Do not push to ACR, alter Azure resources, read a Keychain secret, or invoke a paid provider until the user explicitly approves that newly generated package SHA.

- [ ] **Step 4: Commit any verification-only correction separately**

  If and only if a real regression required a code correction after the Task 3 commit, commit the correction with its focused test before rerunning Step 2:

  ```bash
  git add <only-the-tested-files>
  git commit -m "fix: preserve no-ai release boundary"
  ```

  Do not create a cloud authorization from an uncommitted or dirty candidate.

## Self-Review

1. **Spec coverage:** Task 1 covers the authenticated API/read-cache and write-503 contract. Task 2 covers visible unavailable UI and disabled controls. Task 3 recreates the exact browser-console failure under a genuinely absent service. Task 4 separates local proof from a newly authorized hosted release.
2. **Placeholder scan:** No unfilled implementation markers or unspecified test commands remain. Every mutation is bounded to named files or a later approved release package.
3. **Type consistency:** The API emits `availability` and `unavailable_code`; reducer reads those snake-case keys into `availability` and `unavailableCode`; view model exposes `chatAvailable` and `unavailableCode`; renderer exclusively uses `chatAvailable` for controls.

## Execution Handoff

Plan complete. Execute it only in this already isolated linked worktree. Use `executing-plans` for inline task-by-task execution with test checkpoints. Do not use the plan itself as an Azure deployment authorization.
