# Admin AI Current Authority Refresh Design

## Goal

Provide one executable, read-only path that refreshes the checked-in current
authority before Admin AI package preparation without weakening the exact
source, retired-attempt, hosted-state, or document-drift boundaries.

## Decision

Add an `authority-refresh` mode to the committed Git-object bootstrap. It runs
one dedicated refresh entrypoint from the exact clean commit snapshot. The
entrypoint verifies the complete retired-attempt set, including the exact R19
package and failed receipt, but never executes or copies R19 as authority for a
new operation. It builds a fresh in-memory Task 10 successor request for the
current source and validates the existing R19 terminal revision, digest, tag,
candidate source, and AI-disabled state with Task 10's existing twelve
sanitized Azure reads.

The public readiness read must return exact schema
`0014_import_base_lineage`. That predecessor predates the database AI-control
tables, so combined with the Azure projection's exact
`BIZPULSE_AI_CHAT_ENABLED=false` it is authoritative evidence that both AI
channels are false. A different schema, revision topology, traffic weight,
digest, tag, RBAC phase, readiness result, or resource projection stops before
any local file changes.

## Data flow

1. The bootstrap proves one exact clean commit/tree and materializes it into
   the existing private, read-only runtime snapshot.
2. It copies only the owner-only R19 package and receipt into private inputs,
   with their checked-in SHA-256 values and receipt contract revalidated.
3. The refresh entrypoint derives a fresh Task 10 successor request in memory.
   The request receives a new transient artifact identity only for strict Task
   10 schema validation; no request, release package, receipt, or observation
   artifact is written.
4. The existing Task 10 reader performs exactly twelve sanitized Azure CLI
   reads. The bounded public readiness client performs one credential-free
   HTTPS read with ambient proxy/trust disabled.
5. The safe result/projection is canonicalized and hashed. Raw CLI and HTTP
   responses are never printed or stored.
6. The existing authority file and every policy-controlled document are
   revalidated for pre-read drift. New bytes are rendered in memory, validated
   as a complete bundle, staged as owner-only regular files, and committed with
   rollback on any replacement failure. No target changes before all external
   reads and all validations succeed.

## Authority semantics

- `observed_deployment` and `freshness` are replaced from the fresh evidence.
- `development.repository_migration_head` is derived from the exact source and
  remains `0017_ai_turn_credential_binding`.
- `development.ai_capability_state` is derived from the exact source.
- `attested_rollback` and `prepared_candidate` are preserved byte-for-byte in
  meaning; a read-only observation does not silently rewrite historical or
  prepared authority.
- The observation's deployed candidate/source and image input are bound to the
  exact verified R19 package, while revision/digest are bound to its terminal
  receipt and then independently confirmed by the fresh Azure reads.
- Freshness lasts one bounded hour. Future or expired windows are invalid.

## Failure and security behavior

The command fails before Azure reads when the source is dirty, the committed
bootstrap/source/tree differs, ignored import shadows exist, dependencies are
untrusted, the R19 files drift, the prior-attempt set is incomplete, or policy
documents already drift. It fails after reads but before writes for every
hosted mismatch or malformed observation. It never invokes an Azure mutation,
Docker, registry publication, Key Vault secret read, paid provider call, or
Admin AI release-package generator.

## Testing

Hermetic tests must prove exact command/read count and arguments, zero mutation
commands, no ambient secrets, strict R18/R19 and hosted mismatch rejection,
exact `0014` readiness/channel-false inference, bounded freshness, no raw
response output, atomic all-or-restored local updates, prepared/historical
preservation, dirty/document-drift rejection, and exact committed-bootstrap
execution from the `bizpulse` subdirectory.
