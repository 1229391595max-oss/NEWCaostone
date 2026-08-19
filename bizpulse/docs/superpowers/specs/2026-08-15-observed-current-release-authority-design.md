# Observed Current Release Authority Design

## Goal

Allow a safe update when the image currently serving in Azure differs from the
candidate's immutable, attested rollback baseline, without weakening either
the release attestation or the recovery rehearsal.

## Problem

The release contract previously used `rollback_image_digest` for two different
facts: the immutable image to use for the final rollback rehearsal and the
image expected to be serving before an update.  This works only when those
facts happen to be identical.  After a prior successful update they can
legitimately differ, causing a read-only preflight to reject a safe repair.

## Decision

The contract has two explicitly different image identities:

1. `release.rollback_image_digest` remains immutable.  It is derived from the
   candidate attestation and is the only image accepted by rollback rehearsal.
2. `recovery.observed_current_image_digest` exists only for `target_mode=update`.
   It is a read-only observation of the Container App image immediately before
   the package is generated.  Preflight must match Azure's current app image
   exactly to this value before any mutation.

The package generator derives the rollback fields from the candidate
attestation; it must not contain hand-maintained rollback values.  It obtains
the observed-current value from a bounded Azure `containerapp show` read.  A
manual or stale observed value fails at the next read-only preflight.

## Contract Rules

- `target_mode=update` requires an exact SHA-256 observed-current digest.
- `target_mode=fresh` and `target_mode=prepared` reject an observed-current
  digest.
- Update preflight validates the existing app image against the observed-current
  digest, not the rollback digest.
- Prepared preflight validates the staged candidate image; it does not carry an
  observed-current value.
- Registry verification and final rollback continue to use only the attested
  candidate and rollback identities.
- The no-AI contract remains unchanged: no OpenAI secret, no paid-AI command,
  and a zero OpenAI smoke cap.

## Failure Behavior

Every mismatch is fail-closed before a deployment command is invoked.  A
package with a stale Azure observation, a manually altered rollback identity,
or an observed-current digest in a non-update phase is invalid.  No automatic
downgrade to the rollback image is permitted merely to satisfy preflight.

## Validation

Tests must prove all of the following:

- an update with a distinct observed current image and attested rollback image
  is accepted when the mocked app serves the observed image;
- the same update is rejected when the app serves another image;
- prepared and fresh flows reject an observed-current image;
- launch-package validation requires the new field and generates exact
  preflight commands;
- the package generator derives rollback values from the attestation rather
  than local literals.

## Scope Boundaries

This change is the minimal executable part of the broader anti-drift proposal.
It deliberately does not add a whole-repository documentation linter or a
general changed-path test selector; those remain a separate follow-up after
the hosted repair is complete.
