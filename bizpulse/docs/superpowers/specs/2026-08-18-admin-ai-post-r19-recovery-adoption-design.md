# Admin AI Post-R19 Recovery Adoption Design Addendum

## Goal

Adopt one exact, legitimate post-R19 disabled recovery revision as the only
current read-only authority baseline without changing any R18/R19 historical
constant, package validator, receipt, or accepted reconciliation.

## Historical and current authority split

R19 remains immutable history. Its exact package SHA-256 is
`9c35ae6a39e6db86b021b9938b966492046f0e745111dab2c1dd8bedbf3ddae9`;
its failed receipt SHA-256 is
`fdec28661cb43268526b3c0aa34944b2a472191dc9a362035acc3c8a446f9cb1`;
and its last accepted reconciliation remains
`newcaostone-demo-app--ai-off-9c35ae6a-2bf7086`. Existing R18/R19 constants,
receipt contracts, and historical validation continue to require their
original predecessor, target, and `registry_plus_ai` prepackage semantics.

A distinct Admin AI successor/adoption profile represents the only permissible
current baseline. It derives the expected revision suffix from the exact R19
package-hash prefix `9c35ae6a`, the terminal image-digest prefix `2bf7086`, the
receipt failure `ai_enablement_emergency_disable_failed`, the last accepted
`ai-off` terminal reconciliation, and the absence of an accepted recovery
record. The resulting exact target is:

- revision `newcaostone-demo-app--recover-b-9c35ae6a-2bf7086`;
- image digest `sha256:2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425`;
- immutable registry tag `ai-962a4fa43804-9c35ae6a`;
- application identity class `registry_only`;
- process AI disabled and no AI secret-binding environment entries.

R19 inputs are copied and verified only as consumed read-only provenance. They
are never executed, rewritten, deleted, replayed, or accepted as a new request.

## Contract and data flow

The successor profile lives separately from the historical Task 10 constants.
Only a fresh Task12 UUID-shaped in-memory artifact set may select it. The
strict Task 10 successor validator requires the complete existing package
schema plus the exact recovery target and a prepackage gate whose
`rollback_identity_state` is `registry_only`. Historical fixed-path packages
continue through the original validator and retain `registry_plus_ai`.

The existing twelve-read observer is parameterized only by the validated
package profile. For the successor profile it requires one active healthy and
provisioned recovery revision, latest and latest-ready equality, one running
replica, single-revision mode, 100% latest traffic, the exact digest-qualified
image and immutable tag, registry-only application identity, exact
`officer_only` RBAC, exact resource/diagnostic projections, fixed disabled AI
runtime values, and no AI bindings. One bounded public readiness read must
then return exact schema `0014_import_base_lineage`; because 0014 predates the
database AI-control tables, the two channel states are inferred false.

The authority observation binds the recovery revision, exact digest, R19
candidate source, current exact-source attestation, combined 12+1 evidence
hash, and one-hour freshness. It does not convert the historical `ai-off`
reconciliation into hosted-success evidence.

## Future mutation boundary

Read-only adoption grants no write. A later Admin AI package must begin from
the exact `registry_only` recovery baseline. The application may gain the
exact AI user-assigned identity only inside the package-bound Task 10/Admin AI
capability transition that also verifies its target revision, Key Vault
binding, RBAC, and disabled database channels. Before that state, and after
any failed disabled recovery, registry-only/no-binding semantics remain the
required fail-closed condition. Arbitrary recovery labels, the historical
R18/R19 `ai-off` revisions, different digests/tags, or `registry_plus_ai` at
the adoption boundary are rejected.

## Failure and evidence behavior

Every source, R19 hash/receipt, derivation, target, identity, topology, health,
traffic, RBAC, runtime, binding, readiness, schema, channel, and document drift
fails before local authority updates. No raw Azure/HTTP response or credential
is retained. Implementation and tests perform no live reads or writes, Docker
operation, package generation, UUID creation, cleanup, or R19 mutation.

## Testing

Hermetic tests must prove deterministic recovery derivation, exact baseline
acceptance, rejection of R18/R19 `ai-off` and arbitrary recovery revisions,
digest/tag/identity drift, `registry_only` versus `registry_plus_ai`, unchanged
historical R19 validation, strict fresh successor generation, 12+1 authority
projection, and package-bound future identity transition semantics.
