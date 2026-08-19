# BizPulse Deployed Release Recovery V5 Design

Status: approach A and this written specification approved by the user on
2026-08-16. Approval covers local design, plan, code, tests, documentation,
commits and package generation only. V5 execution still requires separate
approval of its exact generated SHA-256.

## Problem

Recovery V4 is consumed. Its seeded-state and registry checks passed, the
AI-disabled candidate application deployment succeeded, 100% traffic moved to
revision `newcaostone-demo-app--713a6984d4a0`, and both maintenance executions
succeeded. The final read-only phase-2 fence failed because it required all four
Jobs to execute after V4's issue time even though V4 deliberately omitted the
already-completed prepare and seed operations.

The candidate application is deployed, but health, authenticated browser,
capacity, expiry, restart/readback and rollback acceptance did not run. V5 must
continue from that exact state without repeating deployment, prepare, seed or
either maintenance execution.

## Selected approach

Create a deployed-continuation evidence record, a recovery-specific read-only
state verifier, a V5 package builder and a one-shot V5 controller. The
continuation binds the exact completed execution identities instead of using a
new time window:

- prepare: `newcaostone-demo-prepare-pc747ae`;
- seed: `newcaostone-demo-seed-vhamoeo`;
- session maintenance: `newcaostone-demo-sessions-8yiqp1m`;
- storage maintenance: `newcaostone-demo-storage-bch1i2u`.

The generic `verify_phase1_fence.py` remains unchanged. V5 gets a specialized
deployed-state verifier so the strict initial-deployment fence is not weakened
for other release paths.

## Alternatives rejected

1. Relaxing only the `not-before` comparison is rejected because an unrelated
   old or scheduled execution could satisfy a recovery check without proving
   the exact V4 operations.
2. Replaying V4 or manually starting at its failed command is rejected because
   V4 is consumed and its control contract contradicts the completed state.
3. Rolling back and performing a clean deployment is rejected because it adds
   avoidable Azure writes, traffic transitions, time and failure risk.

## Components

### Deployed-continuation evidence

Create
`bizpulse/release/incidents/2026-08-16-recovery-v4-deployed-continuation.json`.
It is secret-free, tracked and non-authorizing. It binds:

- the V4 package SHA-256, authorization ID and failed receipt state;
- candidate and rollback source/image identities;
- the deployed candidate revision, environment and 100% traffic state;
- the four exact successful Job execution identities above;
- completed migration, seed, deployment and maintenance operations;
- `application_deployed=true`, `traffic_switched=true` and
  `ai_enabled=false`;
- all remaining hosted-acceptance boundaries as false;
- `openai_key_accessed=false` and `paid_ai_called=false`.

The record receives its own SHA-256. It cannot be edited in place after a V5
package binds it; later state requires a new incident record and package.

### Read-only deployed-state verifier

Create `bizpulse/scripts/verify_deployed_release_state.py`. It validates the
continuation schema and hash before Azure reads, then proves:

- the application is provisioned and ready at the exact candidate revision and
  image, with one minimum/maximum replica, external ingress, single-revision
  mode and 100% latest-revision traffic;
- the environment, probes, non-secret configuration, secret-reference names
  and `BIZPULSE_AI_CHAT_ENABLED=false` match the approved release;
- all four Jobs remain candidate-bound with exact commands, arguments and
  trigger schedules;
- each bound execution identity exists with `Succeeded` status;
- later scheduled executions cannot substitute for the four bound identities.

Additional legitimate scheduled maintenance executions may exist, but they
never satisfy a bound identity. Later `Succeeded` executions and the recognized
active states `Pending`, `Processing`, `Queued`, `Running`, `Starting` and
`Deactivating` are allowed. A later `Failed`, `Stopped`, missing/changed bound
execution, unknown state or Job-binding drift fails closed. The verifier never
reads secret values and does not call the public URL.

### V5 recovery package

Create `bizpulse/scripts/create_deployed_release_recovery_package.py`. It writes
one owner-only (`0600`) package with a fresh authorization ID and expiry. The
ordered stages are exactly:

1. `deployed_preflight`;
2. `registry_verify` for candidate and rollback digests;
3. `health`;
4. `browser_acceptance`;
5. `capacity`;
6. `expiry`;
7. `restart_readback`;
8. `rollback`.

The package marks registry publication, migration, seed binding, prepare, seed,
application deployment and both maintenance executions as completed. It
contains no Bicep deployment, Job start, Job binding, seed, migration, image
publication, AI enablement or OpenAI command.

Health and remaining acceptance commands are copied from the V4 authority only
after exact candidate, rollback, target and limit equality checks. The V5
authorization ID replaces the old ID in restart/readback and rollback commands.

### One-shot V5 controller

Create `bizpulse/scripts/run_deployed_release_recovery.py`. It accepts the
package path, separately approved SHA-256, continuation path and unused receipt
path. It performs these gates in order:

1. verify package SHA-256, mode, schema, expiry, continuation hash and control
   hashes;
2. reject an existing receipt;
3. execute deployed-state and registry readbacks once;
4. read only the existing Operator Argon2id hash and Operator plaintext from
   their exact macOS Keychain service/account pairs;
5. verify the plaintext against the hash without printing or serializing either;
6. create an owner-only receipt before public health/browser acceptance;
7. execute only the remaining package stages in order without a shell.

PostgreSQL password and session pepper are not read because V5 has no deployment
command. The Operator plaintext is injected only into the authenticated browser
child. No secret is inherited by health, capacity, expiry, restart or rollback
children, stored in argv, written to the package/receipt, or emitted in errors.

The receipt records completed and failed stages atomically. Any failure after
receipt creation consumes V5. There are no deployment or paid-provider retries,
and no manual command-level continuation is permitted.

## Data and control flow

The tracked continuation supplies immutable evidence identities. Package
generation combines it with the existing candidate attestation and exact V4
remaining commands, then embeds hashes of every V5 control script. At execution,
the controller reconstructs the expected package before any Keychain read. A
live-state mismatch stops before receipt creation. After the credential pair is
validated, the receipt consumes the package and the controller proceeds through
the remaining acceptance sequence.

The public application may currently be reachable, but V5 must not treat that
as health, authenticated Operator workflow, capacity, expiry, restart, rollback
or Production proof. Each evidence state advances only after its exact stage
completes.

## Failure handling

- Package, continuation, control, target, image, revision, traffic, Job binding
  or execution drift fails closed before Keychain access.
- Missing or mismatched Operator credentials fail before receipt creation and
  before browser login.
- A failed hosted stage records its exact stage, stops later commands and
  consumes the package.
- V5 never retries or replays deployment or any Job.
- No failure path reads an OpenAI Key, enables AI, makes a paid request, changes
  DNS, pushes Git, opens a PR or modifies CI.

## Verification

TDD must prove:

- strict continuation schema/hash and exact execution identity validation;
- deployed app, revision, traffic, AI-disabled and Job-binding drift rejection;
- bound success cannot be replaced by a later scheduled execution;
- the V5 package contains only the eight pending stages and no completed
  mutation command;
- wrong package hashes and existing receipts stop before Keychain or commands;
- only the two Operator Keychain items are read and their values never escape;
- direct-file entrypoints work without `PYTHONPATH`;
- stage failure creates value-free, atomic, non-replayable receipt evidence;
- package and receipt modes are `0600`, control hashes reconstruct exactly and
  all commands use argument arrays with `shell=False`;
- release static tests, verification-policy tests, Ruff, Python compilation,
  secret-pattern checks and `verify_changed --base 16f5220 --no-reuse` pass.

## Scope boundary

The design, plan, implementation, local tests, commits, continuation evidence
and package generation may proceed locally after written-spec review. They do
not authorize Azure reads/writes, Keychain access, public URL checks, registry
calls, restart, rollback, OpenAI Key access, AI enablement or paid AI.

After local verification, generation produces one V5 package and an immutable
local receipt documenting its identity. Execution stops until the user approves
that package's exact SHA-256 in a new message.
