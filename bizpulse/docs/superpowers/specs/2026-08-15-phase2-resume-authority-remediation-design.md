# Phase 2 Resume Authority Remediation Design

**Status:** Approved under the user's continuous no-AI launch authorization on
2026-08-15.

## Incident and objective

The restricted no-AI launch completed Phase 1, schema migration, foundation
bootstrap, synthetic seeding, Phase 2 ARM deployment, and both maintenance Job
executions. The Phase 2 application then failed readiness because the launch
controller generated a new randomly salted Argon2 hash after its process was
interrupted. PostgreSQL retained the first hash while the resumed Container App
received the second hash. The same plaintext password therefore no longer had
one exact credential authority.

The final Phase 2 fence also compared Azure Storage's Blob endpoint with a URL
that omitted its trailing slash. Azure Resource Manager returns
`primaryEndpoints.blob` as `https://<account>.blob.core.windows.net/`; the
[Microsoft Storage REST example](https://learn.microsoft.com/en-us/rest/api/storagerp/storage-accounts/create?tabs=HTTP&view=rest-storagerp-2025-06-01)
uses that exact root URL form.

The objective is to make launch recovery deterministic without weakening the
foundation, Blob authority, revision, readiness, or no-AI boundaries.

## Selected approach

1. The Phase 2 readback verifier will require the exact Microsoft-projected
   Blob root endpoint, including `/`. It will continue to require HTTPS, the
   declared storage account hostname, the declared container, and the exact
   application environment; other hosts, paths, query strings, fragments, or
   schemes remain invalid.
2. The local launch controller will store one Argon2id operator hash in macOS
   Keychain, separately from the plaintext operator password. A resume will
   read that hash, validate its parameters, and verify it against the Keychain
   plaintext before any Azure command. It will create the hash only when the
   item is absent and will fail closed on mismatch, malformed data, or Keychain
   ambiguity.
3. The current partial pure-synthetic deployment will not be repaired through
   ad-hoc SQL or a relaxed readiness check. A new exact cleanup package will
   remove only the declared Demo resources. A new immutable candidate/image,
   attestation, and restricted no-AI package will then replay from an empty
   PostgreSQL authority with the persistent hash.

## Alternatives rejected

- Directly updating `operator_accounts.password_hash` inside the live
  container is faster but creates an unreviewed database mutation outside the
  approved command graph.
- Treating any valid Argon2 hash as foundation-ready would allow an app secret
  and the login authority to drift apart.
- Removing the endpoint comparison or stripping arbitrary URL characters
  would weaken the storage-account binding.

## Verification and evidence

Tests must first reproduce the Microsoft trailing-slash projection and prove
the current verifier rejects it. The minimal implementation then changes only
the expected exact endpoint. Focused hosted/infra tests, the full release gate,
fresh image inspection, manifest-only attestation, and detached attestation
verification must pass before new packages are generated.

The Keychain controller must prove create-once/reuse, plaintext-to-hash
verification, malformed/mismatched fail-closed behavior, no secret output, and
resume stability. Secret values must never enter Git, package files, argv,
logs, tool output, or chat.

Local remediation evidence is not hosted evidence. Deployed, hosted-verified,
accepted, and Production-ready remain false until a newly approved cleanup and
launch finish every prescribed non-AI hosted gate, including natural expiry
and rollback readback.
