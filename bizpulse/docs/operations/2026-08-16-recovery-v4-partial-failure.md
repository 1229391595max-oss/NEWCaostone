# Recovery V4 Partial-Failure Receipt — 2026-08-16

Status: immutable local and read-only Azure evidence; V4 consumed; no
continuation authority.

## Approved authority

- Package: `.tmp/LAUNCH_AUTHORIZATION_SEEDED_RELEASE_RECOVERY_V4.md`
- Package SHA-256:
  `978110287eb3335bcf5537ee59e9bd887a41eee9753861148680f1a5475beae8`
- Authorization ID: `993b492e-aba0-40e8-87e5-65019caaa291`
- Issued: `2026-08-16T22:09:20Z`
- Expires: `2026-08-17T22:09:20Z`
- Execution started: `2026-08-16T22:13:56Z`
- Local receipt: `.tmp/RECOVERY_V4_EXECUTION_RECEIPT.json`, mode `0600`

The exact SHA-256 was approved once. V4 is consumed and must not be retried or
manually resumed.

## Completed operations

1. Package SHA-256, mode, expiry, authorization ID, continuation and all control
   hashes matched the approval.
2. Seeded-state and candidate/rollback registry readbacks passed.
3. All four existing non-AI Keychain values were loaded without serialization;
   the Operator plaintext verified against the Argon2id hash.
4. Azure deployment `newcaostone-demo-phase2` returned exit code `0`.
5. The candidate application is provisioned at revision
   `newcaostone-demo-app--713a6984d4a0`, image digest
   `sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`,
   with one ready replica, external ingress and 100% latest-revision traffic.
6. AI remains disabled (`BIZPULSE_AI_CHAT_ENABLED=false`).
7. Maintenance executions `newcaostone-demo-sessions-8yiqp1m` at
   `2026-08-16T22:17:08Z` and `newcaostone-demo-storage-bch1i2u` at
   `2026-08-16T22:17:47Z` both succeeded.

The V4 receipt records `seeded_preflight` and `registry_verify` as completed and
the aggregate `deploy` stage as failed because its final read-only fence command
did not pass. The preceding deployment and two maintenance commands inside that
aggregate stage did complete.

## Exact failure and root cause

The final deploy-stage command was `verify_phase1_fence.py --mode phase2` with
`--not-before 2026-08-16T22:09:20Z`. It passed application and revision checks,
then stopped while checking the first prepare Job execution history.

The verifier requires every one of the four Jobs to have a successful execution
at or after `not-before`. V4 intentionally omitted prepare and seed because V2
had already completed them. The exact prepare execution
`newcaostone-demo-prepare-pc747ae` succeeded at
`2026-08-16T20:25:35Z`, before the V4 threshold. The continuation also records
successful seed execution `newcaostone-demo-seed-vhamoeo`. Therefore the fence
contract contradicted the recovery package's completed-operation contract; it
would require replaying operations V4 was designed to skip.

## Operations not executed

- no health endpoint acceptance;
- no authenticated browser acceptance;
- no capacity or expiry acceptance;
- no restart readback or rollback rehearsal;
- no OpenAI Key read, AI enablement, model qualification or paid request;
- no DNS, push, PR or CI operation.

The candidate app and traffic are present in Azure, but hosted acceptance and
Production readiness are not proved.

## Successor boundary

A successor must not redeploy the application or rerun prepare, seed, session
maintenance or storage maintenance. It must bind exact completed execution
identities, verify the deployed AI-disabled candidate state and registry
digests read-only, then contain only the remaining health, browser, capacity,
expiry, restart/readback and compatible rollback checks. Any successor package
requires a fresh authorization ID, expiry, control hashes, package SHA-256 and
separate exact-hash approval.
