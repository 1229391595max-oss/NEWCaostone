# No-AI Restricted Launch Design

**Status:** Approved by the user on 2026-08-15.

## Objective

Publish the synthetic NEWCaostone Demo without paid AI while preserving the
existing immutable-image, PostgreSQL, Blob, operator-authentication, health,
capacity, expiry, restart, and rollback authorities. Ask BizPulse remains
explicitly unavailable until a later, separately approved AI security package
passes the provider and budget rehearsals.

## Authorization contract

The authorization JSON keeps its exact schema and exact command-field set.
When `ai_limits.enabled` is `false`:

- `secret_presence.openai_api_key` is `false`;
- `external_publication.paid_ai_smoke` is `false`;
- `limits_usd.openai_smoke_cap` is zero;
- `budget_failure`, `provider_failure`, and `paid_ai_smoke` are exact empty
  command arrays;
- `budget_failure`, `provider_failure`, and `paid_ai_smoke` do not appear in
  `execution_order`;
- the deployed application contains no OpenAI key, secret reference, or
  provider endpoint override.

When `ai_limits.enabled` is `true`, the existing contract remains unchanged:
both failure rehearsals are mandatory, paid AI smoke is mandatory, the exact
minimum attempt/token limits apply, and all three stages remain in the exact
execution order. An AI-enabled package cannot use the restricted mode.

## Release flow

The no-AI package retains this exact order:

1. read-only Azure recovery/configuration preflight;
2. immutable current and rollback image verification or authorized publish;
3. private phase-1 deployment and drain fence;
4. migration and deterministic synthetic seed Jobs;
5. prepared-authority activation fence;
6. canonical phase-2 deployment with AI disabled;
7. strict live/ready health checks;
8. non-provider core browser acceptance;
9. exact-15 session/read capacity check;
10. natural session-expiry verification;
11. restart readback;
12. rollback and forward recovery rehearsal.

The package is generated from a new clean candidate, a new `linux/amd64`
immutable image digest, and a manifest-only attestation child. No Azure write,
retry, public activation, registry publication, or cleanup occurs until the
user approves the new package's exact SHA256.

For the existing private Azure target, the rollback authority is the exact
currently deployed candidate/image pair. This permits a non-destructive update
preflight: the current app must equal the package rollback before the new image
is published or activated. A different running digest fails closed.

## Failure behavior

The verifier rejects a restricted package if it includes either AI failure
command, lists either stage in `execution_order`, claims an OpenAI key, carries
a nonzero AI smoke cap, or enables paid AI smoke. It also rejects an AI-enabled
package that omits the mandatory budget/provider rehearsals.

## Verification

Tests must prove both sides of the mode boundary:

- the strict AI-disabled fixture validates with empty failure commands and no
  failure stages in the execution order;
- adding a failure command or stage to an AI-disabled package fails closed;
- AI-enabled packages still require both failure rehearsals and paid AI smoke;
- the deployment runbook documents the conditional order without weakening
  any non-AI hosted gate;
- release, hosted authorization, Ruff, and diff checks pass before rebuilding
  the candidate/image/attestation/package authority.

## Evidence boundary

Successful local tests and package verification prove only the candidate and
authorization contract. They do not prove deployment, hosted acceptance, or
Production readiness. The public Demo becomes hosted-verified only after the
new package is approved and every command in its reduced exact order succeeds.
