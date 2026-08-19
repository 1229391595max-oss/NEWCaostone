# BizPulse AI Enablement Local Handoff — 2026-08-17

## Current boundary

Branch `codex/ai-enable-preset-buttons` in the isolated worktree implements the
six bilingual server-owned prompt presets, managed-identity runtime key access,
the task-owned Key Vault/UAMI deployment, bounded failure rehearsals and the
exact-package runner. No real key has been requested, read or searched. No Azure
write, public Demo access, image publication, real OpenAI request, push, PR or CI
has occurred.

The Demo passcode is explicitly deferred. It would reduce casual Demo admission
and abuse but would not make the Key Vault public endpoint private.

## Locally implemented

- Six EN/ZH presets remain visible in disabled mode, are server-projected and
  context-filtered, fill/focus without submitting, confirm draft replacement,
  clear audit metadata after edits and submit the exact id/locale/version/SHA
  quartet only for an unchanged official template.
- Cloud AI accepts only the fixed OpenAI endpoint/model/limits and retrieves the
  key lazily through a dedicated UAMI from the task vault. Browser and Container
  Apps configuration receive no API key.
- Base Bicep creates exactly vault/UAMI/read-role/diagnostics. A second inert
  Bicep template contains exactly one `openai-api-key` Secret and accepts its
  `@secure()` value only through the approved child's stdin.
- Runner binds clean Git authority, D3 invariants, the complete execution-control
  hash set including the actual hash-locked `requirements.txt`, rollback revision/image,
  Azure target, official pricing, `$0.19` conservative
  estimate, `$1.00` hard cap, exact operations and a 24-hour expiry.
- Placeholder Secret deletion was removed after confirming Azure soft-delete
  and purge-protection semantics. The real version overwrites the placeholder.
- Provider/budget rehearsals record safe attempt/ledger evidence and recover to
  a freshly verified ready AI-disabled revision. A provider-auth rejection is
  distinct from a Key Vault lookup failure without exposing either value.
- A durable `0600` started receipt is reserved before the first mutation and
  finalized only at terminal success. Ambiguous enabled patches, final receipt
  failure and every failure after the real-write attempt use the same verified
  emergency recovery; the existing receipt permanently fences replay.
- Hosted completion requires one real, manual-send AI turn from the public
  Azure Demo Viewer path with Demo session/CSRF, preset audit quartet,
  workspace/store scope and synchronized ledger evidence. Local or Operator-only
  success is insufficient.

## Local verification at handoff authoring

- Ordinary Python suite: `913 passed, 252 skipped`.
- Ephemeral PostgreSQL suite: `1160 passed, 5 skipped`.
- Frontend Node suite: `176 passed, 0 failed`.
- Full same-origin browser acceptance against temporary PostgreSQL, Azurite and
  the deterministic fake provider: `1 passed`; local Browser screenshots also
  prove the six presets are visible, preset click fills/focuses with no history
  turn, and only explicit Send creates the answered turn.
- Focused Azure action test after the final command-shape assertion:
  `11 passed`.
- Both Bicep templates and both inert parameter files compile locally; Ruff,
  `compileall` and `git diff --check` pass.

These are local results only. The release authority check remains blocked by
the existing stale authority observation, and changed-path verification remains
blocked because `.dockerignore` is not mapped by the existing verification
policy. Neither control file was rewritten merely to manufacture a pass.
Hosted Azure, paid-provider and deployment states remain unverified until the
exact package is separately approved and executed.

The public Demo remains available without the deferred passcode. Existing
session and budget controls contain scope and spend, but an anonymous visitor
can consume the shared AI budget; that residual abuse risk must be accepted for
this Demo posture or addressed in a later passcode/rate-control batch.

## Azure and D3 authority

Recorded Azure anchors are subscription
`fc89e7d3-5428-425e-863f-415859810c2c`, tenant
`13d04c38-d91c-4f9f-8b65-6af2b515dd63`, resource group
`rg-bizpulse-centralus`, app `newcaostone-demo-app`, ready revision
`newcaostone-demo-app--713a6984d4a0`, and rollback image digest
`sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`.
They are not claimed current until the final fresh seven-query sanitized Azure
read completes. Any mismatch blocks package creation.

D3 remains on `codex/deployed-diagnostic-d3`, selected base
`afd3a2f0a9311aafaca35ad4a412c911aadf1e32`, package SHA-256
`2ca7c7aa0d133b94607569af437dcf0f6a2b7aa44afc475c332dfe16e0ac8687`,
mode `0600`, with receipt and observation absent. It must remain unused and
byte-identical.

## Final stop gate

After final code commit, clean-tree verification, local image build/label check,
browser screenshots and fresh Azure read, create exactly one owner-only package.
Report its path, mode, issued/expiry times and SHA-256, then stop.

Execution requires a separate user message with exactly:

```text
批准执行 AI Enablement SHA256：<exact-sha256>
```

Only after that approval should the runner display the hidden local API-key
prompt. The user must not send the key back through chat.
