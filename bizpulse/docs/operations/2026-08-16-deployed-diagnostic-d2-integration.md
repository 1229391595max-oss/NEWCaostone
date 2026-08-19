# Deployed Diagnostic D2 Integration Evidence

Status: local integration candidate verified. D2 package generation and Azure
execution had not occurred when this evidence was recorded.

## Git authority and topology

- Worktree:
  `/Users/maxli/Desktop/NEWCaostone/.worktrees/integrated-viewer-ai-anti-drift-d2-integration`
- Branch: `codex/integrated-viewer-ai-anti-drift-d2-integration`
- Main base: `ef78397d6cc9b110c4a1f969e0c4109b0b400f47`
- Feature parent: `873f99ed5d327af16b29938b1b9d35e689a008fc`
- Pre-report verified integration HEAD:
  `fb3d514420c75a8379cddbf7a2d470f1649bc2a1`
- Pre-report verified tree:
  `63b70a1a787c9107e7dbdca774bd21d0d76b9549`
- Merge commit: `49dcff048b56b15eb6af4813821caf0d435c6ddb`
- Merge tree: `90ec7bcc843d15517cc702822a88eb1afb8e164b`
- Merge parents, in order:
  `ef78397d6cc9b110c4a1f969e0c4109b0b400f47` and
  `873f99ed5d327af16b29938b1b9d35e689a008fc`
- Integration-normalization commit:
  `fb3d514420c75a8379cddbf7a2d470f1649bc2a1`
- `main...integration` before this report commit: `0 243`
- `feature...integration` before this report commit: `0 8`

`main` and the feature worktree were clean and unchanged. `main` remained at
`ef78397d6cc9b110c4a1f969e0c4109b0b400f47`; this work did not move `main`.

Before merging, `main...feature` was `6 241`. `git cherry -v feature main`
classified `f1b32d8`, `d311852`, `55d9a4f`, `669ed7a`, and `db3defc` as
patch-equivalent, with only `ef78397` unique on `main`.

## Merge resolution

The no-fast-forward merge produced exactly the two preclassified add/add
conflicts and no others:

- `NEXT_AI_HANDOFF.md`
- `docs/superpowers/specs/2026-08-15-bizpulse-integrated-viewer-ai-experience-design.md`

Both were resolved to the feature-side content because it contains the later
recovery/D1/D2 handoff and the integrated v1.1 design. The merge was committed
as `49dcff0`.

The initial integration also exposed two repository-hygiene issues that were
hidden while `bizpulse/` existed only on the feature branch. Commit `fb3d514`
adds an exact ignored `node_modules` symlink rule and removes only the nine
`git diff --check` findings reported when the entire project is introduced to
the docs-only main tree. No business behavior changed in that commit.

## Verification

The D2-focused integration suite passed `113` tests. The exact checked-in
`release_static` argv passed `346` tests with two declared skips. Ruff, Ruff
format checking, Python compilation, Bicep compilation, and the documentation
authority contract all passed.

The approved plan expected `verify_changed --base ef78397... --no-reuse` to
pass. It correctly failed closed before executing a selected check with:

```text
verification_policy_unmapped_path:bizpulse/.dockerignore
```

Full classification showed why this was not a one-path typo: `main` contains no
`bizpulse/` project, so the first integration presents 560 paths as changed.
Of those, 111 are intentionally unmapped by the incremental selector and eight
historical attestation paths require its non-cacheable `full_release_gate`.
The policy was not weakened and no attestation was reclassified.

Instead, the clean entire candidate at `fb3d514` ran the stronger local full
release verifier with the existing integrated-release attestation identity. It
returned:

```text
release_verification=ok
candidate_git_sha=fb3d514420c75a8379cddbf7a2d470f1649bc2a1
checks_passed=8
```

That gate covered the full Python/PostgreSQL suite, all frontend tests,
exact-15/restart/rollback, Ruff, compilation, diff checking, static release
boundaries, and browser smoke.

The integration-only delta then ran non-reused changed-path verification from
feature parent `873f99ed5d327af16b29938b1b9d35e689a008fc` and returned
`verification_changed=passed`. Its literal results were:

- verification policy: 74 passed;
- migration: 24 passed;
- restart: 1 passed;
- rollback: 1 passed;
- authority contract: passed;
- frontend: 170 passed;
- browser local: 8 passed;
- library focused: 16 passed;
- exact-15: 2 passed.

This combination verifies both the full first-import candidate and the actual
merge/integration delta without pretending that immutable historical release
proofs are ordinary incremental edits.

## Stop and successor boundary

At evidence capture, all of the following were absent:

- `.tmp/LAUNCH_AUTHORIZATION_DEPLOYED_RELEASE_DIAGNOSTIC_D2.md`
- `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_ATTEMPT_RECEIPT.json`
- `.tmp/DEPLOYED_RELEASE_DIAGNOSTIC_D2_OBSERVATION.json`

No Azure request, registry access, Keychain access, public URL request, AI
request, paid request, push, PR, CI, deployment, or `main` update occurred.
D1 remains consumed. D2 generation is a separate local step; D2 execution
requires a new explicit approval containing the exact generated SHA-256.
