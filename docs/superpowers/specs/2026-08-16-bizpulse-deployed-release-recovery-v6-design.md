# BizPulse Deployed Release Recovery V6 Design

Status: approach A selected by the user on 2026-08-16. This written
specification requires user review before implementation planning. Approval of
the approach or design never authorizes V6 execution; a generated V6 package
will require a separate exact-SHA-256 approval.

## Problem and observed failure

Recovery V5 package
`bizpulse/.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_RECOVERY_V5.md`, SHA-256
`656e8df0951f4b98d67eaf00067a2a2ba99571dfb92d64c1142040b49791f4ab`, was
approved and invoked once. Its first `containerapp show` completed successfully,
then the deployed-state verifier returned
`deployed_execution_readonly_stage_failed` before revision, Job, registry,
Keychain or hosted-acceptance work. No V5 execution receipt exists.

The application readback has the authorized values:

- revision `newcaostone-demo-app--713a6984d4a0` and candidate image digest;
- 100% latest-revision traffic, external ingress and single-revision mode;
- `minReplicas=1` and `maxReplicas=1`;
- the exact AI-disabled environment, probes and secret-reference names.

Azure also materializes non-authoritative scale defaults:
`cooldownPeriod=300`, `pollingInterval=30` and `rules=null`. V5 compared the
entire scale object with only `{minReplicas: 1, maxReplicas: 1}`. The generic
Phase-2 fence correctly compares the two authoritative replica values by key.
V5 therefore failed because its local verifier was stricter than the deployed
Azure representation, not because the approved replica bounds drifted.

## Authority audit

The pre-design read-only audit established:

- worktree branch `codex/integrated-viewer-ai-anti-drift` was clean at
  `84ae5636f9bc775e5b6cde0f88ec3bf2cc5694a1`;
- development anchor `3e4cc229245cf32a13623da23eaa9685e176a82b`,
  deployed compare-only anchor
  `537effe3036f77f83225beef12589bd447205a8b`, and handoff tag target
  `db3defce15daf5d92d91e41a8062cbbb23053b3a` still resolve exactly;
- `check_authority_contract.py --mode docs` returns
  `authority_contract=ok`;
- the V5 package still hashes to its approved SHA-256 and the V5 receipt is
  absent;
- `release/current_authority.json` remains an explicitly expired historical
  Azure snapshot. Docs-mode contract success proves internal document/block
  consistency, not fresh Azure state;
- the current status, handoff and V5 package receipt still say V5 is unapproved
  and unexecuted. Those statements became stale when the approved V5 attempt
  occurred and must be corrected before V6 package generation.

V5 is treated as retired and non-replayable even though failure occurred before
receipt creation. Its approved execution attempt is historical evidence, not
authority to retry the package or manually resume a child command.

## Selected repair

Retain exact validation of the scale mapping and the two authoritative replica
bounds, but allow Azure-owned additional scale keys. Concretely:

1. require `properties.template.scale` to be a mapping;
2. require `minReplicas` to be the integer `1`;
3. require `maxReplicas` to be the integer `1`;
4. ignore additional Azure-returned keys for acceptance purposes;
5. continue rejecting missing scale, boolean/string replica values, changed
   bounds and every existing app/revision/traffic/AI/Job/execution drift case.

This matches the existing Phase-2 fence pattern without weakening any
BizPulse-owned authority value.

## Alternatives rejected

1. Redeploying to try to remove Azure defaults is rejected because those fields
   are platform materialization, and redeployment would repeat a completed
   mutation without solving the verifier contract.
2. Accepting any scale object is rejected because it would stop proving the
   required one-replica minimum and maximum.
3. Editing the verifier and replaying the same V5 package is rejected because
   the package binds the old verifier hash and its exact approval has already
   been exercised.

## V5 incident and authority correction

Before generating V6, create an immutable tracked V5 pre-receipt failure record
containing only value-free evidence:

- V5 authorization ID and approved package SHA-256;
- the exact controller failure code;
- the successful, sanitized `containerapp show` command-log boundary;
- the three Azure-added scale fields and the verifier comparison responsible;
- explicit false boundaries for Keychain reads, registry verification, health,
  browser, capacity, expiry, restart, rollback, OpenAI Key access and paid AI;
- absent V5 execution receipt and V5 retirement/no-replay rule.

Update `CURRENT_STATUS.md`, `NEXT_AI_HANDOFF.md`,
`docs/handoffs/CURRENT_HANDOFF.md` and the V5 package operation record so they
state that V5 was approved, attempted once, failed during deployed preflight
and is retired. Run the docs authority checker before and after these updates.
Do not represent docs-mode success as a fresh hosted observation.

The narrow V6 repair does not rewrite `release/current_authority.json`: that
file's schema and refresh path require a separately designed fresh sanitized
Azure observation workflow. V6 continues to use the immutable deployed
continuation and exact candidate attestation as its package authority.

## V6 package boundary

After the fix, change the generated authorization title and output identity to
V6, keep the existing package schema and eight-stage order, and embed fresh
control hashes:

1. `deployed_preflight`;
2. `registry_verify`;
3. `health`;
4. `browser_acceptance`;
5. `capacity`;
6. `expiry`;
7. `restart_readback`;
8. `rollback`.

V6 still contains no deployment, registry publication, migration, Job binding
or start, prepare, seed, maintenance replay, AI enablement, OpenAI Key or paid
provider command. It may describe only the Operator hash/plaintext Keychain
pair; values remain absent. The hash is validation-only and the plaintext is
browser-only after the two read-only stages pass.

Generate V6 exactly once to a new owner-only path, reserve a new unused V6
receipt path, independently verify its SHA-256/mode/loader/control hashes, then
stop. V6 execution requires a new user message approving its exact 64-character
SHA-256 before expiry.

## Error handling and non-replay rules

- Never rerun V5 or manually resume its deployed-preflight child.
- A V6 pre-receipt state mismatch stops before Keychain and receipt creation.
- A V6 credential failure stops before receipt creation and browser access.
- A V6 post-receipt failure records its exact stage, consumes V6 and stops all
  later stages.
- No failure path enables AI, reads an OpenAI Key, makes a paid request, changes
  DNS, pushes Git, opens a PR or modifies CI.

## Test and verification design

TDD must first add a failing regression where the app scale mapping includes
the observed Azure defaults. The test must prove acceptance when bounds remain
`1/1`, plus rejection for missing scale, changed bounds and boolean/string
bounds. Only then change the verifier.

Run:

- the complete deployed-state verifier, V6 package and one-shot runner tests;
- the exact `release_static` argv from verification policy;
- selector and authority-contract tests;
- Ruff and Python compilation;
- secret-pattern, owner-only mode, loader reconstruction and control-hash
  checks;
- `verify_changed.py --base 16f5220 --no-reuse`;
- independent package SHA-256 and absent V6 receipt checks.

Local tests and package generation must not access Azure, registry, Keychain,
the public URL, OpenAI or a paid provider. Only a later exact-SHA approval may
authorize the V6 one-shot controller.
