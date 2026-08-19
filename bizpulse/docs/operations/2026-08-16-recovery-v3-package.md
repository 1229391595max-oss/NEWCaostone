# Recovery V3 Generated Package Receipt — 2026-08-16

Status: generated and locally verified; not approved or executed.

## Package identity

- Path: `.tmp/LAUNCH_AUTHORIZATION_SEEDED_RELEASE_RECOVERY_V3.md`
- SHA-256: `94b89c07ff77b158d8e561f2a2fcf0d91ca5cb4943c0897b6d9cab93e3d369e7`
- Authorization ID: `381bb738-2ba8-4a7d-9035-ad0cb2d4dd21`
- Issued: `2026-08-16T22:01:11Z`
- Expires: `2026-08-17T22:01:11Z`
- File mode: `0600`

The complete package hash requires a separate exact approval. Generation and
this receipt grant no execution authority.

## Bound release

- Candidate source: `82fd4a4dcfbc04a6cbe6386ce8891b750a1ea7e3`
- Candidate attestation: `c573f2be9d8d6414143fbeab2fa2af788caf4f19`
- Candidate image:
  `sha256:713a6984d4a034a0be73b46c10a897aeb236c201325ff8a88ba524fc6c10295c`
- Rollback image:
  `sha256:2a95c20046cde04a383a280b350a450c15cc7c46df92e1e8eaf5014eeb5c8512`
- Migration: `0014_import_base_lineage` already complete
- Seed execution: `newcaostone-demo-seed-vhamoeo` already succeeded
- AI: disabled

## Exact execution boundary

The package contains only:

1. seeded-state preflight;
2. candidate and rollback registry readback;
3. AI-disabled application deployment, maintenance Jobs and Phase-2 fence;
4. health, authenticated browser, capacity and expiry acceptance;
5. restart/readback and compatible rollback rehearsal.

Registry publication, migration, Job binding and synthetic seed are recorded as
complete and have no V3 command. There is no AI enablement, OpenAI Key action,
model qualification, paid request, DNS, push, PR or CI command.

## Credential boundary

The package records four service/account/environment descriptors and no value.
Only the one-shot runner may read them after package SHA, expiry, control hashes
and read-only cloud state pass. All four are required before the first Azure
write; the Operator plaintext must verify against the Argon2id hash. Deploy
values are scoped to the Bicep child and the plaintext to the browser child.

Package generation did not read Keychain, execute a command from the package,
or access Azure. No secret value is in this receipt, the package, argv, output
or Git.

## Local verification evidence

- Focused V3 tests: `11 passed`.
- Verification selector: `57 passed`.
- Release static suite: `189 passed, 2 skipped`.
- `verify_changed --base 16f5220 --no-reuse`:
  `verification_changed=passed`.
- Ruff, Python compilation, tracked-change secret-pattern scan, owner/mode,
  loader reconstruction, control hashes and prohibited-command checks passed.

## Future execution command

Only after the user approves the exact SHA-256 above, run the one-shot
controller from the BizPulse project root with an unused receipt path:

```bash
.venv/bin/python scripts/run_seeded_release_recovery.py \
  --package .tmp/LAUNCH_AUTHORIZATION_SEEDED_RELEASE_RECOVERY_V3.md \
  --approved-sha256 94b89c07ff77b158d8e561f2a2fcf0d91ca5cb4943c0897b6d9cab93e3d369e7 \
  --continuation release/incidents/2026-08-16-recovery-v2-seeded-continuation.json \
  --receipt .tmp/RECOVERY_V3_EXECUTION_RECEIPT.json
```

Do not execute after expiry, replay after a receipt exists, manually resume a
failed stage, or substitute another package/hash.
