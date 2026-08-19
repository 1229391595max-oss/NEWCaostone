# Recovery V2 Partial-Failure Receipt — 2026-08-16

Status: immutable local incident evidence; no continuation authority.

## Approved authority

- Package: `.tmp/LAUNCH_AUTHORIZATION_PARTIAL_RELEASE_RECOVERY_V2.md`
- Package SHA-256:
  `91e210d5c41c430eec8685e39ae10377bdf293e96a5a77662f2e77a51b764f6a`
- Authorization ID: `5b73b24d-2ae8-4245-a769-be9735b2fb24`
- Candidate source: `82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3`
- Candidate image:
  `sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`
- Candidate manifest:
  `5e0d761fddae1d7add1739ed5cff06eb1e1aad7c494152abd3334841bec61fde`
- Candidate dataset version: `b91e1179-c76a-53a5-b036-ce7b88b74cbe`
- Package issued: `2026-08-16T21:15:45Z`
- Package expiry: `2026-08-17T21:15:45Z`

The package is consumed. Its expiry does not grant replay authority.

## Completed operations

1. Package hash, mode, expiry, controller hashes and AI-disabled boundary
   matched the approval.
2. The recorded failed state matched current Azure readback.
3. Candidate and rollback registry digests were verified.
4. The seed Job was atomically rebound through a mode-0600 temporary YAML
   document; the temporary file was deleted after use.
5. Post-update Azure readback matched the candidate image, `python` command,
   candidate manifest and candidate dataset version.
6. Seed execution `newcaostone-demo-seed-vhamoeo` succeeded.

These operations changed the seed Job binding and completed candidate seed
writes. They did not deploy the application or switch traffic.

## Exact failure

The first deployment command stopped during local Bicep parameter evaluation
with `BCP427` because these required non-AI deployment environment variables
were absent:

- `BIZPULSE_DEPLOY_POSTGRES_PASSWORD`
- `BIZPULSE_DEPLOY_OPERATOR_PASSWORD_HASH`
- `BIZPULSE_DEPLOY_SESSION_PEPPER`

The failure occurred before an Azure deployment request was dispatched. No
secret value was read or printed.

## Operations not executed

- no candidate application deployment;
- no traffic switch;
- no session or storage maintenance Job execution;
- no Phase-2 fence or hosted acceptance;
- no restart or rollback rehearsal;
- no AI enablement;
- no OpenAI Key read, write or injection;
- no paid AI request;
- no DNS, push, PR or CI operation.

## Continuation boundary

Do not replay Recovery V2 or resume at its next command. A successor must
recognize that migration, Job rebinding and candidate seeding are complete and
must verify required deployment-variable presence before any Azure mutation.
The three non-AI secret values must be supplied through an explicitly authorized
secure mechanism, never through chat or a checked-in file. AI Stage 2 remains
separate and still requires its own Key procedure and authorization.
