# Recovery V6 Generated Package Receipt — 2026-08-16

Status: approved and invoked once; retired after read-only preflight failure.

## Package identity

- Path: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md`
- SHA-256: `b66cd4d1b2cb84391045376cbc262db040394b388b9322385a90954c63406de4`
- Authorization ID: `34059824-5881-4bbd-a03c-9389ba6a175a`
- Issued: `2026-08-16T23:03:44Z`
- Expires: `2026-08-17T23:03:44Z`
- File mode: `0600`
- Execution receipt: `.tmp/RECOVERY_V6_EXECUTION_RECEIPT.json` absent

The package was generated exactly once and independently reconstructed. It was
then separately approved and invoked once. V6 stopped during
`deployed_preflight` after successful application, revision, prepare Job and
prepare execution reads. Its receipt is absent, but V6 is retired and grants no
replay or manual-resume authority.

## Retired predecessor boundary

V5 SHA-256
`656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab`
was separately approved and invoked once. It stopped during
`deployed_preflight` after a successful application read and before revision,
Job, registry, Keychain or hosted-acceptance work. Its receipt is absent, but V5
is retired and grants no replay or manual-resume authority. Read
`docs/operations/2026-08-16-recovery-v5-readonly-preflight-failure.md`.

## Exact V6 execution boundary

The package contains these stages in this exact order:

1. `deployed_preflight`;
2. `registry_verify`;
3. `health`;
4. `browser_acceptance`;
5. `capacity`;
6. `expiry`;
7. `restart_readback`;
8. `rollback`.

The deployed verifier accepts Azure-owned extra scale fields while requiring
exact integer bounds `minReplicas=1` and `maxReplicas=1`. V6 contains no
application deployment, registry publication, migration, Job binding/start,
prepare, seed, maintenance replay, AI enablement, model qualification, paid
request, DNS, push, PR or CI command.

## Credential and AI boundary

The package records exactly two service/account descriptors and no values:

1. `NEWCaostone Azure Demo Operator Password Hash` / `operator`, scoped to
   credential-pair validation;
2. `NEWCaostone Azure Demo Operator Password` / `operator`, scoped only to
   browser acceptance.

The one-shot runner may read this pair only after both read-only deployed and
registry checks pass. PostgreSQL password, session pepper and OpenAI Key are
not read by V6. AI remains disabled and no paid-provider request is authorized.
Package generation accessed no Azure, registry, Keychain, public URL, OpenAI or
paid provider.

## Local verification evidence

- Focused V6 control suite: `41 passed`.
- Release-static suite from the policy's exact argv: `232 passed, 2 skipped`.
- Verification selector: `64 passed`.
- `authority_contract=ok` in docs mode.
- `verification_changed=passed` with base `16f5220` and `--no-reuse`.
- Ruff, Python compilation, diff checks, package mode, independent SHA-256,
  loader reconstruction, exact stage order, two-descriptor boundary and absent
  V6 execution receipt all passed.

## Retired execution boundary

The approved V6 command was invoked once and returned
`deployed_execution_readonly_stage_failed`. Four read-only Azure commands
completed successfully before the local verifier rejected the first prepare
Job/bound execution contract. Registry, Keychain and hosted acceptance were not
reached; no receipt or mutation exists.

Read
`docs/operations/2026-08-16-recovery-v6-readonly-preflight-failure.md` for the
immutable failure boundary. Do not execute V6 again or manually resume a child
command from it.
