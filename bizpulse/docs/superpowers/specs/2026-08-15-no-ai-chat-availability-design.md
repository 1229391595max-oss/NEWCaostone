# No-AI Chat Availability Design

## Goal

Make a restricted no-AI Azure deployment render the AI Decision Center as an
explicitly unavailable feature without generating a browser console error or
sending a model request.

## Context

The no-AI launch config correctly creates no Chat service and no OpenAI secret.
`GET /api/v1/ai-chat/turns` currently returns `503 AI_CHAT_UNAVAILABLE`; the
Ask BizPulse loader catches that response, but Chrome records the failed
resource in its console. The hosted core browser gate correctly fails on that
console error even though the rest of the application is healthy.

## Options Considered

1. **Recommended: explicit read availability projection.** Return a bounded
   successful chat-list projection containing `availability=unavailable` and
   `unavailable_code=AI_CHAT_UNAVAILABLE` only when the Chat service is absent.
   The UI displays the no-AI boundary and disables all Chat submission controls.
   Mutation endpoints remain `503` and preserve existing CSRF/auth boundaries.
2. Suppress the expected `503` in the browser gate. This would leave a broken
   user interaction visible and weaken the console-error acceptance signal.
3. Enable AI without an approved provider/key. This violates the restricted
   launch boundary and could initiate paid provider traffic.

## Approved Design

### API

`ChatTurnListResponse` gains a closed availability field:

- `availability`: `available | unavailable`
- `unavailable_code`: `null | AI_CHAT_UNAVAILABLE`

For an active Chat service, the existing list response remains available with a
null unavailable code. For a disabled service, `GET /turns` still authenticates
the viewer/operator session, returns an empty bounded list with
`availability=unavailable`, and sets the existing private no-store headers.
No write endpoint changes: submit, draft, save, and session mutation continue
to fail closed with `503 AI_CHAT_UNAVAILABLE` when no service exists.

### Frontend

Ask BizPulse state stores the availability projection. In unavailable mode the
page renders a bilingual restricted-launch notice, presents no recommended
questions, and disables the free-text input and Ask button. It must not call a
Chat mutation. Existing available-state behavior, context selection, saved Q&A,
and action drafts remain unchanged.

### Error and Security Boundaries

- The response is session-scoped and `Cache-Control: private, no-store`.
- No OpenAI key, provider configuration, or request is added.
- A raw 503 for every write endpoint remains visible to an API client but is
  unreachable through the disabled UI.
- The browser gate continues to reject genuine console errors; it must pass
  because no unavailable GET request is emitted.

### Verification

1. API regression: no-service `GET /turns` returns the unavailable projection;
   unauthenticated access remains 401 and no-service `POST /turns` remains 503.
2. Node state/view regressions: unavailable projection disables controls and
   renders the boundary notice without affecting available chat state.
3. The focused PostgreSQL/API/Node suite passes.
4. Build a new immutable Linux/amd64 image, republish it under a new
   authorization, and rerun the complete no-AI hosted release chain. Do not
   claim hosted acceptance until browser, capacity, expiry, restart, and
   rollback gates all succeed.
