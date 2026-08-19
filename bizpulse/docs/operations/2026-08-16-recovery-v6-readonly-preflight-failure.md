# Recovery V6 Read-Only Preflight Failure — 2026-08-16

Status: V6 approved once, invoked once, stopped before receipt and retired.

## Bound package

- Package: `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V6.md`
- SHA-256: `b66cd4d1b2cb84391045376cbc262db040394b388b9322385a90954c63406de4`
- Authorization ID: `34059824-5881-4bbd-a03c-9389ba6a175a`
- Controller result: `deployed_execution_readonly_stage_failed`
- V6 execution receipt: absent

## Authority and path preflight

Before execution, the isolated worktree, branch, clean Git state, development
anchor, deployed compare-only anchor and annotated handoff tag all matched their
recorded identities. The package absolute path, independent SHA-256, `0600`
mode, authorization ID, expiry, continuation, eight-stage order and three
control-file hashes also matched. Docs authority returned
`authority_contract=ok`; AI was disabled and no receipt existed.

## Exact stop boundary

V6 was invoked once with the exact approved SHA-256. These four Azure read-only
commands completed with exit code `0`, in order:

1. application `containerapp show`;
2. application `containerapp revision list`;
3. prepare Job `containerapp job show`;
4. prepare Job `containerapp job execution list`.

The local deployed-state verifier then rejected the first prepare Job/bound
execution contract before reading the seed, session-maintenance or
storage-maintenance Jobs. The runner intentionally reduced the verifier's
specific subcode to `deployed_execution_readonly_stage_failed`; existing
evidence therefore does not distinguish Job configuration drift, bound
execution drift or an additional prepare execution. Distinguishing those cases
would require a new Azure read and is not authorized by this consumed package.

Registry verification, Keychain loading, health, browser, capacity, expiry,
restart and rollback were not reached. No receipt was created. No Azure
mutation, public-URL request, OpenAI Key access or paid request occurred. AI
remained disabled. V6 is retired and must not be replayed or manually resumed.
