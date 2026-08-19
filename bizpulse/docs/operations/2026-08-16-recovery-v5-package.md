# Recovery V5 Generated Package Receipt — 2026-08-16

Status: approved and invoked once; retired after read-only preflight failure.

## Package identity

- Path: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md`
- SHA-256: `656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab`
- Authorization ID: `75bbbbb4-69e9-4b38-921e-08f64b0bd6cf`
- Issued: `2026-08-16T22:46:52Z`
- Expires: `2026-08-17T22:46:52Z`
- File mode: `0600`
- Execution receipt: `.tmp/RECOVERY_V5_EXECUTION_RECEIPT.json` absent

The package was generated once, separately approved and invoked once. It
stopped during `deployed_preflight` after a successful application read and
before revision, Job, registry, Keychain or hosted-acceptance work. The V5
receipt is absent, but V5 is retired and grants no replay or manual-resume
authority.

## Bound deployed continuation

- Continuation:
  `release/incidents/2026-08-16-recovery-v4-deployed-continuation.json`
- Candidate source: `82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3`
- Candidate attestation: `c573f2be9d8d6414143fbeab2fa2af788caf4f19`
- Candidate image:
  `sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`
- Candidate revision: `newcaostone-demo-app--713a6984d4a0`
- Rollback image:
  `sha256:2a95c20046cde04a383a280b350a450c15cc7c46df92e1e8eaf5014eeb5c8512`
- AI: disabled; no OpenAI Key action or paid request

V4 is consumed. Registry publication, PostgreSQL migration, seed Job binding,
prepare, synthetic seed, application deployment, session maintenance and
storage maintenance are recorded as complete and have no V5 command.

## Exact V5 execution boundary

The package contains these stages in this exact order:

1. `deployed_preflight` — read-only candidate app, revision, Job binding and
   exact execution identity verification;
2. `registry_verify` — candidate and rollback digest readback;
3. `health`;
4. `browser_acceptance`;
5. `capacity`;
6. `expiry`;
7. `restart_readback`;
8. `rollback`.

It contains no application deployment, registry publication, migration, Job
binding/start, prepare, seed, maintenance replay, AI enablement, model
qualification, paid request, DNS, push, PR or CI command.

## Credential boundary

The package records exactly two service/account descriptors and no values:

1. `NEWCaostone Azure Demo Operator Password Hash` / `operator`, loaded only as
   `BIZPULSE_OPERATOR_PASSWORD_HASH_CHECK` for credential-pair validation;
2. `NEWCaostone Azure Demo Operator Password` / `operator`, loaded only as
   `BIZPULSE_BROWSER_OPERATOR_PASSWORD` for browser acceptance.

The one-shot runner was invoked but stopped before reading either item. The hash
was not passed to a child process. PostgreSQL password, session pepper and
OpenAI Key were not read by V5.

Package generation did not access Azure, registry, Keychain, the public URL,
OpenAI or any paid provider. The approved invocation made one successful
read-only application request and no Azure mutation or paid-provider request.

## Local verification evidence

- Focused V5 suite: `35 passed`.
- Release-static suite from the policy's exact argv: `226 passed, 2 skipped`.
- Verification selector: `64 passed`.
- `authority_contract=ok`.
- `verification_changed=passed` with base `16f5220` and `--no-reuse`.
- Ruff, Python compilation, JSON policy parsing, diff checks, control hashes,
  package mode, independent SHA-256, loader reconstruction, exact stage order,
  two-descriptor boundary and absent execution receipt all passed.

## Retired execution boundary

V5 was separately approved and invoked once. It stopped during
`deployed_preflight` after a successful application read and before revision,
Job, registry, Keychain or hosted-acceptance work. The V5 receipt is absent,
but V5 is retired and grants no replay or manual-resume authority. The failure
was caused by whole-object comparison against Azure-owned scale defaults; the
approved `minReplicas=1` and `maxReplicas=1` values did not drift.

Read
`docs/operations/2026-08-16-recovery-v5-readonly-preflight-failure.md` for the
immutable failure boundary. Do not execute V5 again or manually resume a child
command from it.
