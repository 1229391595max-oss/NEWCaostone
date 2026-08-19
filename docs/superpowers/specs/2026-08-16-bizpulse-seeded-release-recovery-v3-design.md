# BizPulse Seeded Release Recovery V3 Design

Status: approved by the user's instruction to produce V3 after the exact
seeded continuation boundary was explained. This approval covers local design,
code, tests, documentation, commits and package generation only. It does not
authorize package execution or any Azure, registry, traffic, secret, AI, Git
remote, PR, CI or deployment mutation.

## Problem

Recovery V2 is consumed. It verified the recorded incident and registry,
atomically rebound the seed Job, and completed candidate seed execution
`newcaostone-demo-seed-vhamoeo`. Its first deployment command then failed during
local Bicep parameter evaluation because three required non-AI environment
variables were absent. No Azure deployment request was dispatched, the old
application revision still owns traffic, and AI remains disabled.

V3 must not replay V2 or resume from an unbound command. It must independently
prove the exact seeded state and the approved package hash, prove every secret
needed for the complete deployment and hosted acceptance sequence before the
first Azure write, and then execute only the still-pending stages.

## Selected approach

Create a new seeded-continuation evidence schema, read-only Azure verifier,
V3 package schema and single execution controller. The package reuses the
already published candidate and rollback digests but omits publication,
migration, Job binding and synthetic seed commands. The controller validates
the approved package SHA-256, expiry, control hashes, continuation evidence and
read-only cloud state before reading Keychain or dispatching a write.

Immediately before execution, the controller reads four exact macOS login
Keychain items in memory:

- PostgreSQL password for Bicep only;
- Operator Argon2id hash for Bicep only;
- Session pepper for Bicep only;
- Operator plaintext password for the complete authenticated browser gate only.

All four are preloaded and validated before the first Azure write so a missing
browser credential cannot strand the release after deployment. The plaintext
must verify against the Argon2id hash. Values are never printed, serialized,
placed in argv, inherited by unrelated stages or written to a receipt. Package
generation does not read any Keychain value.

## Alternatives rejected

1. Extending or replaying Recovery V2 is rejected because its one-shot
   authority is consumed and its recorded state predates successful seeding.
2. Manually exporting three variables and running the old deploy command is
   rejected because it bypasses package-hash, state, expiry and replay gates.
3. Omitting authenticated Operator browser acceptance is rejected because it
   would leave the user's required Operator workflow unverified after a cloud
   mutation.

## Components

### Seeded continuation evidence

A tracked, secret-free JSON record binds the original incident, consumed V2
package, successful V2 stages, successful seed execution, candidate and
rollback identities, and the still-false application/traffic/AI boundaries.
It is append-only evidence for V3 generation; it grants no execution authority.

### Read-only seeded-state verifier

The verifier checks the old application image/revision and 100% traffic, the
candidate-bound prepare and seed Jobs, the original successful prepare
execution and `newcaostone-demo-seed-vhamoeo` successful seed execution. It
does not call public health and does not read secret values.

### V3 package

The mode-0600 package contains only these ordered external stages:

1. seeded-state preflight;
2. candidate and rollback registry digest readback;
3. AI-disabled application deployment, maintenance Jobs and Phase-2 fence;
4. health, authenticated browser, capacity and expiry acceptance;
5. restart/readback and compatible rollback rehearsal.

It records the four exact Keychain service/account/environment mappings but no
value. It marks registry publication, migration, seed binding and synthetic
seed as completed and contains no command for them.

### One-shot execution controller

The controller accepts the package path and separately approved SHA-256. It
uses argument arrays without a shell, executes only exact package commands,
loads all four Keychain values after read-only preflight but before deployment,
injects deployment variables only into the Bicep child and the Operator
plaintext only into the browser child, and creates an owner-only execution
receipt immediately before the first write. An existing receipt, failed write
or failed acceptance consumes the package and requires a new successor.

## Failure handling

There are zero deployment retries. Hash, expiry, state, registry, Keychain,
Argon2, command, child-environment, deployment or acceptance drift stops the
controller with a value-free error. Read-only checks may run once. No failure
path enables AI, reads an OpenAI Key, performs a paid request, changes DNS, or
pushes Git.

## Verification

- TDD proves wrong package hashes fail before Keychain access.
- Tests prove all four values are required before mutation and validate the
  plaintext/hash pair without exposing either value.
- Tests prove deploy secrets reach only the Bicep child and the Operator
  plaintext reaches only the browser child.
- Tests prove completed stages are absent, commands run without a shell,
  owner-only package/receipt modes are enforced and a consumed package cannot
  replay.
- Seeded-state drift, secret-shaped output, AI commands and OpenAI references
  fail closed.
- Focused release tests and `verify_changed --no-reuse` must pass before the
  package is generated.

## Scope boundary

V3 is generated but not executed. Its exact SHA-256 must receive a new explicit
approval before the controller may read Keychain or perform any Azure action.
OpenAI Key creation, storage, reading, injection, qualification and paid AI are
separate future work.
