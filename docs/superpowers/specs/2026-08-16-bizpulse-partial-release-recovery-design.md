# BizPulse Partial Release Recovery Design

Status: approved by the user's instruction to repair local package binding and
generate a new recovery package.

## Problem

The consumed two-stage update package changed the prepare and seed Job images
without changing the seed Job's authority-bound arguments. Prepare advanced the
database to `0014_import_base_lineage`; seed then rejected the previous manifest
and dataset-version arguments with `seed_authority_mismatch`. The candidate
application was never deployed, AI remained disabled, and Stage 2 never began.

## Selected approach

Use the already published and attested candidate image. Do not rebuild or
republish it. Repair ordinary update packages so every Job update binds image,
container name, command and arguments in one Azure CLI operation. Generate a
separate AI-disabled recovery package that starts from the exact recorded
partial-failure state, skips the completed migration, rebinds only the seed Job,
seeds, deploys the candidate application and runs the complete non-AI hosted
acceptance sequence.

The package is generated locally and grants no execution authority until its
complete SHA-256 is separately approved.

## Alternatives rejected

1. Replaying the consumed package is rejected because its seed command is known
   invalid and its one-time authorization has been consumed.
2. Re-running the complete two-stage flow is rejected because registry
   publication and migration already completed, and Stage 2 must remain inert
   until Stage 1 is healthy.
3. Manually editing the Azure Job is rejected because it would bypass the
   hash-bound package, verifier and recovery record.

## Components

### Update-mode binding repair

`tests/hosted/verify_azure_demo.py` will generate update commands with:

- exact candidate image digest;
- exact container name;
- command `python`;
- prepare arguments `scripts/prepare_cloud.py`;
- seed arguments containing the candidate manifest SHA-256 and dataset version.

The existing authorization verifier recomputes these commands, so old packages
with image-only Job updates fail validation after the repair.

### Machine-readable incident

A tracked, secret-free JSON record binds the consumed package hash, target,
candidate/rollback identities, successful prepare execution, failed seed
execution, old seed arguments and all explicitly unexecuted operations. The
human incident receipt remains the narrative record.

### Partial-state preflight

A read-only verifier will check the exact old application image/revision and
100% traffic, candidate prepare/seed Job images, expected Job arguments and the
named prepare/seed execution outcomes. It supports two modes:

- `failed`: seed Job still has the recorded previous arguments;
- `rebound`: seed Job has the candidate manifest/version arguments.

It never calls public health before recovery and never reads secret values.

### Recovery package

The mode-0600 package contains only these ordered stages:

1. incident-state preflight;
2. candidate and rollback registry digest verification;
3. atomic seed Job rebind;
4. rebound-state preflight;
5. seed execution;
6. AI-disabled application deployment plus maintenance Jobs and fence;
7. health, browser, capacity, expiry, restart/readback and rollback rehearsal.

There is no registry publication, migration, model qualification, AI deploy,
Key handling, paid request, DNS, Git push, PR or CI operation.

## Failure handling

Every command has zero deployment retries. Any identity, digest, Job argument,
execution, schema, secret-presence or health mismatch stops execution. The
recovery package is consumed on the first write or failed operation and cannot
be resumed without a newly generated successor.

## Verification

- TDD proves old image-only update commands fail the new binding contract.
- Unit tests cover incident parsing, both preflight modes, package command
  order, absence of migration/publication/AI/secret actions, mode 0600 and
  fail-closed drift behavior.
- Existing release/hosted suites and `verify_changed --no-reuse` must pass.
- Package generation occurs only after committed code and fresh verification.

## Scope boundary

This design authorizes local code, tests, documentation, commits, image
readback and package construction only. It does not authorize any new Azure,
registry, Job, application, traffic, rollback, secret or paid-provider action.
