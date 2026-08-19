# Two-Stage Release Partial-Failure Receipt — 2026-08-16

Status: immutable local incident evidence; no continuation authority.

## Approved authority

- Authorization path: `.tmp/LAUNCH_AUTHORIZATION_TWO_STAGE_V1.md`
- Authorization SHA-256: `084ee41e9c79bb96b8e60cd3ac417cac30e9e8f18af5de88ab0304a2374493b6`
- Authorization ID: `20b9eadd-a525-459b-b7a3-fd7e47df5267`
- Candidate source: `82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3`
- Attestation commit: `c573f2be9d8d6414143fbeab2fa2af788caf4f19`
- Candidate image:
  `sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`
- Candidate image-input SHA-256:
  `8fec360c0073bb85ec5837af2ee118f5cdc4eb90a388a77006096fb334064c90`
- Candidate migration: `0014_import_base_lineage`
- Candidate manifest SHA-256:
  `5e0d761fddae1d7add1739ed5cff06eb1e1aad7c494152abd3334841bec61fde`
- Candidate dataset version: `b91e1179-c76a-53a5-b036-ce7b88b74cbe`
- Prior application source: `537effe3036f77f83225beef12589bd447205a8b`
- Prior application image:
  `sha256:2a95c20046cde04a383a280b350a450c15cc7c46df92e1e8eaf5014eeb5c8512`
- Package issued: `2026-08-16T20:10:24Z`
- Package expiry: `2026-08-18T20:10:24Z`

The package is consumed despite its later timestamp. Expiry never grants replay
authority after a stopped or failed execution.

## Executed operations

1. Exact read-only preflight passed.
2. The candidate image was published to ACR and its immutable digest verified.
3. The prior rollback image digest was verified.
4. A post-publication preflight passed.
5. The prepare and seed Job templates were updated to the candidate image.
6. Prepare execution `newcaostone-demo-prepare-pc747ae` ran from
   `2026-08-16T20:25:35Z` to `2026-08-16T20:26:09Z` and succeeded.
7. Seed execution `newcaostone-demo-seed-8a8k7de` started at
   `2026-08-16T20:26:17Z` and failed.
8. Execution stopped at that first failed operation.

The candidate prepare program upgrades to Alembic head and exits successfully
only after its readiness probe sees `0014_import_base_lineage`. This binds the
successful prepare execution to the inference that the database reached 0014.

## Exact failure

The seed execution raised:

```text
RuntimeError: seed_authority_mismatch
```

At readback, the seed Job used the candidate image but retained these preceding
arguments:

- manifest SHA-256:
  `8bb389bb241e904fcb2bb092b082da31d99aa314acab47068a293d184e5c329e`
- dataset version: `8df2ff5e-ed7e-5ae2-b3e8-4bb5ae9e2550`

The candidate container validates its bundle authority before calling the seed
write path, so this failed execution did not create a partial candidate seed.
The root cause is an update-mode package-ordering defect: it updated the Job
image without atomically replacing the authority-bound arguments.

## State after stop

Read-only control-plane evidence at `2026-08-16T20:36:02Z` showed:

- the public Container App still selected the prior immutable image and revision;
- Single-mode 100% latest traffic still targeted that prior revision;
- the Container App resource reported `provisioningState=Succeeded`;
- the prepare and seed Job templates selected the candidate image;
- the seed Job retained the preceding manifest/version arguments;
- the latest prepare execution succeeded and the latest seed execution failed.

Direct `/health/live` and `/health/ready` requests both timed out during the
same cleanup readback. Earlier application logs changed readiness responses
from 200 to 503 immediately after the migration window. Therefore this receipt
does not claim the public Demo healthy, ready, hosted-accepted or Production
ready.

## Operations not executed

- no candidate application deployment;
- no traffic switch;
- no hosted browser, capacity or natural-expiry acceptance;
- no restart or rollback rehearsal;
- no Stage-2 model qualification;
- no OpenAI Key read, write or injection;
- no paid AI request;
- no DNS, Git push, PR or CI operation.

## Continuation boundary

Do not replay this package and do not resume at its next command. A successor
must first repair and test update-mode image-plus-authority binding, generate a
new package that explicitly recognizes the completed migration, and obtain the
user's approval of the successor package's complete SHA-256. Stage 2 remains
inert until an AI-disabled Stage 1 is healthy and has a valid receipt.

Historical tags, attestations and migration files remain provenance and must
not be deleted as "old fingerprints." The old implementation worktree may be
removed only in a separately verified physical-cleanup step after recovery.
