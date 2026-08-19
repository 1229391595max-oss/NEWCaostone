# Recovery V3 Local Entrypoint Stop — 2026-08-16

Status: immutable local incident evidence; V3 retired; no continuation authority.

## Approved authority

- Package: `.tmp/LAUNCH_AUTHORIZATION_SEEDED_RELEASE_RECOVERY_V3.md`
- Package SHA-256:
  `94b89c07ff77b158d8e561f2a2fcf0d91ca5cb4943c0897b6d9cab93e3d369e7`
- Authorization ID: `381bb738-2ba8-4a7d-9035-ad0cb2d4dd21`
- Candidate source: `82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3`
- Candidate image:
  `sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`
- Package issued: `2026-08-16T22:01:11Z`
- Package expiry: `2026-08-17T22:01:11Z`

The exact package hash was approved once. V3 is retired and must not be retried,
even though no execution receipt was created.

## Completed local checks

1. Package path, SHA-256, mode `0600`, authorization ID, expiry and all recorded
   control hashes matched before execution.
2. The worktree was clean at
   `f3e99495422682dff47bb8e09f26b88a7fab2086`.
3. `.tmp/RECOVERY_V3_EXECUTION_RECEIPT.json` did not exist before either
   invocation and remains absent.

## Exact failure

The documented direct controller invocation stopped during local Python module
loading with `ModuleNotFoundError: No module named 'scripts'`. It failed before
loading or executing the package.

A module-mode controller invocation then validated the package and reached its
first read-only child command. That child used the package's direct-file
`scripts/verify_seeded_release_state.py` entrypoint and stopped with the same
import error. The controller reported `seeded_execution_readonly_stage_failed`
in approximately one tenth of a second.

No package stage completed. The failure was reproduced without Azure by showing
that the direct verifier `--help` failed while its module-mode `--help`
succeeded.

## Operations not performed

- no Keychain read and no credential prompt;
- no Azure read or write request;
- no application deployment or traffic switch;
- no health, browser, capacity, expiry, restart or rollback action;
- no receipt creation;
- no AI enablement, OpenAI Key access or paid request;
- no DNS, push, PR or CI operation.

## Successor boundary

Commit `e59f8f1` adds regression coverage for direct-file execution without
`PYTHONPATH`, bootstraps the project root in both affected entrypoints and
changes the generated document title to Recovery V4. Because those scripts are
control-hashed inside the package, V3 cannot authorize the fixed code.

A successor must be generated with a fresh authorization ID, expiry, package
path, receipt path and SHA-256. It must preserve the same seeded-state boundary,
skip registry publication, migration, Job binding and seed, keep AI disabled,
and require separate exact-hash approval before execution.
