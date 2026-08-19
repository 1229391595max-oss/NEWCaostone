# Azure Admin AI Launch Runbook

## Evidence boundary

This runbook describes the separately authorized hosted execution path for the
administrator AI controls. The Task 11 implementation and its local tests do
not publish an image, deploy an Azure resource, read or write Key Vault, call
OpenAI, access the hosted Demo, or prove Hosted, Staging, Production, or paid-AI
acceptance.

Never replay an R19, D1-D3, V4-V6, stopped, failed, expired, eleven-read, or
otherwise retired package. A new attempt starts from a newly committed source
SHA/tree, a new immutable `linux/amd64` image digest, the current authority
file, a fresh twelve-read Azure observation, and a new unused receipt path.

## Local package preparation

The package generator is
`scripts/create_admin_ai_release_package.py`. It is local and read-only. It
requires:

- a clean tracked Git tree and exact 40-character HEAD/tree identifiers;
- an owner-only OCI archive whose exact `linux/amd64` manifest digest is known;
- `release/current_authority.json` with unexpired
  `sanitized_azure_readback` freshness evidence;
- an Azure observation no more than 15 minutes old, with exactly twelve
  sanitized reads, one healthy ready revision at 100% traffic, both database AI
  channels false, and an exact `legacy_only` or `officer_only` RBAC phase;
- one bounded public `/health/ready` read from that exact revision, binding the
  current database head to `0014`, `0015`, or `0016` before any publication or
  mutation;
- a new receipt path and the allowlisted hashes of every retired package.
- a reviewed adapter factory committed at the package source SHA.
- the exact Container Apps migration job name bound into the package.

### Separately authorized current-authority refresh

If `release/current_authority.json` is expired, stop before choosing an Admin
AI attempt UUID or building a candidate. Run the following command only under
separate authorization for the exact read-only Azure refresh and the local
tracked authority/document update. It executes the committed refresh
entrypoint from one clean exact source, verifies the owner-only R19 package and
failed receipt only as retired provenance, builds a fresh Task 10 successor in
memory, performs exactly twelve sanitized Azure reads plus one bounded public
`/health/ready` GET, and performs no Azure mutation, Docker operation, release
package generation, credential read, or paid call.

```bash
set -o pipefail
ADMIN_AI_SOURCE_SHA="$(git rev-parse --verify 'HEAD^{commit}')"
git show "${ADMIN_AI_SOURCE_SHA}:./scripts/admin_ai_exact_runtime.py" | \
  .venv/bin/python -I -B -S - --project-root "$PWD" \
  --source-sha "$ADMIN_AI_SOURCE_SHA" authority-refresh
```

R19 remains consumed historical provenance: its last accepted target is
`newcaostone-demo-app--ai-off-9c35ae6a-2bf7086`. The refresh never reuses or
executes that package. Its expected current recovery-adoption baseline is
`newcaostone-demo-app--recover-b-9c35ae6a-2bf7086`, derived from the exact R19
package-hash prefix and terminal image-digest prefix. The refresh requires that
exact recovery revision, digest, immutable tag, healthy single revision at
100% traffic, `registry_only` App identity, `officer_only` RBAC, process AI
disabled with no AI bindings, and public readiness at exact
`0014_import_base_lineage`. Schema 0014
predates database AI-control channels, so those exact two observations prove
both channels false without a database credential or mutation. Any R18/R19
provenance drift, source/document drift, extra revision, traffic, RBAC,
readiness, schema, identity, or resource mismatch stops without changing the
authority file or documents. Output is limited to safe counts, identifiers,
timestamps, and hashes; raw Azure/HTTP responses are not persisted or printed.
The resulting local authority update does not prove hosted acceptance, and
operators must never replay R19.

On success the command atomically updates only
`release/current_authority.json` and the policy-generated current blocks. It
preserves prepared and historical authority, records the live deployed facts,
keeps repository development at `0017_ai_turn_credential_binding`, and grants
one hour of freshness. The tracked update intentionally makes the checkout
dirty. Review and commit that exact authority/document-only delta before
capturing a new source SHA for candidate build. Never continue directly from
the dirty post-refresh tree.

First create the candidate with the dedicated builder. It rejects any tracked
or untracked repository change, materializes one detached `git archive` of the
exact source SHA, makes that source tree read-only, derives the build-context
and image-input hashes from those committed bytes, and performs exactly one
`linux/amd64` BuildKit export to an OCI archive. It never builds from the
mutable checkout. The Dockerfile binds `SOURCE_REVISION`, `SOURCE_TREE_SHA`,
`IMAGE_INPUT_SHA256`, and `BUILD_CONTEXT_SHA256` as image labels.

Run every command below from the `bizpulse` project directory. In Git's
`<sha>:<path>` syntax, the leading `./` makes the bootstrap path relative to
that required subdirectory; omitting it incorrectly addresses the repository
top level and must fail closed. Each complete Bash block enables `pipefail` so
a failed object lookup cannot be masked by the empty Python process succeeding.

```bash
set -o pipefail
ADMIN_AI_SOURCE_SHA="$(git rev-parse --verify 'HEAD^{commit}')"
git show "${ADMIN_AI_SOURCE_SHA}:./scripts/admin_ai_exact_runtime.py" | \
  .venv/bin/python -I -B -S - --project-root "$PWD" \
  --source-sha "$ADMIN_AI_SOURCE_SHA" build \
  --output .tmp/ADMIN_AI_CANDIDATE_<new-id>.oci.tar
```

The committed Git-object bootstrap above is the only supported entry point for
candidate build, package creation, and release; never execute the mutable
checkout copy directly. Isolated `-I -B -S` startup imports no checkout or
mutable virtual-environment dependency code, and
ignored bytecode, `.pth`, extension, or `sitecustomize` shadows never enter the
committed archive. Each command captures one exact 40-character commit SHA,
loads the bootstrap from that SHA, derives the tree only from that commit, and
archives that same SHA into a
private read-only directory, drops ambient credential variables, and executes
the builder, generator, and controller only from that snapshot. The runtime
package binds the complete installed distribution/file/hash manifest required
by the live controller; release copies only those approved files to the private
snapshot and imports them there with system site packages disabled. The runtime
manifest also binds both executed AI Bicep files and the reviewed migration-job
IaC; Azure never receives a `--template-file` path from the mutable checkout.

The result is mode `0400`. Its archive SHA-256, single OCI image-manifest
digest, every referenced blob digest, exact `linux/amd64` platform, and all
four source labels are checked before package preparation. Do not rebuild,
load, retag, replace, chmod, or edit this archive. ORAS 1.2 or newer is a local
execution prerequisite because the approved archive itself is later copied to
ACR; no mutable Docker daemon tag is part of this release path.

Example shape only; do not run it until the current read-only observation and
exact candidate digest exist:

```bash
set -o pipefail
ADMIN_AI_SOURCE_SHA="$(git rev-parse --verify 'HEAD^{commit}')"
git show "${ADMIN_AI_SOURCE_SHA}:./scripts/admin_ai_exact_runtime.py" | \
  .venv/bin/python -I -B -S - --project-root "$PWD" \
  --source-sha "$ADMIN_AI_SOURCE_SHA" package \
  --candidate-artifact .tmp/ADMIN_AI_CANDIDATE_<new-id>.oci.tar \
  --create-azure-authority-request \
    .tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_TASK12_<new-uuid>.json \
  --task10-role-assignment-state <legacy_only-or-officer_only> \
  --authority release/current_authority.json \
  --operations-factory scripts.admin_ai_release_operations:create_operations \
  --receipt .tmp/ADMIN_AI_RELEASE_RECEIPT_<new-id>.json \
  --output .tmp/ADMIN_AI_RELEASE_PACKAGE_<new-id>.json \
  --retired-package-sha256 <retired-sha256>
```

This supported successor path exclusively writes a new owner-only Task 10
request with the current source/tree/control hashes, the full exact RBAC
contract, and a UUID-addressed unused artifact set. It then strictly validates
that request against the current candidate before the first Azure read. An
already-created fresh request can instead be supplied with
`--azure-authority-request`; R19 and every other prior or fixed-path request are
not successors and must not be reused. The successor also requires the exact
owner-only R19 package and failed receipt hashes as consumed provenance. R19's
last proved healthy AI-disabled target revision
`newcaostone-demo-app--ai-off-9c35ae6a-2bf7086` remains historical evidence.
The fresh read instead requires the exact derived recovery target
`newcaostone-demo-app--recover-b-9c35ae6a-2bf7086`, immutable digest
`sha256:2bf7086bccec9cdb8fb6a9c2c5383909207b021344d8dfee692437829bd87425`,
tag `ai-962a4fa43804-9c35ae6a`, and `registry_only` identity as the expected
current recovery-adoption baseline. Any live difference stops package
generation. These values do not prove hosted acceptance or assert current
hosted state without that new read; never replay R19.

The generator invokes Task 10's sanitized Azure reader and requires exactly
twelve reads, then reads the exact public readiness projection and binds its
current database revision. It hashes and binds the canonical safe Azure
result/projection as a fresh observation. The checked-in authority evidence remains a separate binding
to its established image-input hash domain. The generator reopens and inspects
the exact owner-only OCI archive. It binds its relative path, archive SHA-256,
OCI manifest digest/reference, platform, source SHA/tree, image-input hash, and
build-context hash. It also binds full sorted manifests for both the Docker
context and every transitive release-controller/adapter source and lockfile.
The named operations factory must be a regular tracked file whose bytes match
`git show` at the exact source SHA. The package is created exclusively at
mode `0600`, prints its exact SHA-256, and refuses to overwrite an existing
path. It never reads an ambient OpenAI key. Generation must stop if the
checked-in authority file is expired; refreshing that file requires a
separately authorized read-only Azure action.

## Separate approval

Package creation is not launch approval. Before any mutation, the user must
approve the complete printed 64-character SHA-256 in a separate message. The
controller compares that value to the exact deterministic package bytes and
checks it against every retired hash. A mismatch, old hash, expired package,
dirty tracked or untracked tree, release-tool manifest drift, import-shadowing
file, source/tree drift, OCI archive/path/hash/manifest/platform/label drift,
authority drift, Azure baseline drift, or pre-existing receipt stops before
the key prompt and before mutation.

## One-shot execution contract

`scripts/run_admin_ai_release.py` contains the fixed, injected one-shot
controller. The separately authorized live operations adapter must implement
the exact allowlisted operations; it may not add retries, cleanup, fallback
deployment, broad role deletion, or a second attempt.

The executable entry point takes only `--package` and the separately approved
`--approved-sha256`. The controller refuses any factory other than the exact
module/path/SHA-256 already bound into the package, rechecks its bytes against
the committed source SHA, durably writes a `started` receipt, and only then
imports or constructs it. The injected adapter cannot change the fixed
controller state order.
Because the bootstrap source arrives on standard input, release mode opens and
validates the local controlling terminal separately and attaches only that TTY
to the controller's hidden candidate prompt. If no controlling TTY exists, the
bootstrap stops before controller construction, preflight, publication, or any
mutation; a pipe, argument, environment variable, or file is never accepted as
candidate input.

```bash
set -o pipefail
ADMIN_AI_SOURCE_SHA="$(git rev-parse --verify 'HEAD^{commit}')"
git show "${ADMIN_AI_SOURCE_SHA}:./scripts/admin_ai_exact_runtime.py" | \
  .venv/bin/python -I -B -S - --project-root "$PWD" \
  --source-sha "$ADMIN_AI_SOURCE_SHA" release \
  --package .tmp/ADMIN_AI_RELEASE_PACKAGE_<new-id>.json \
  --approved-sha256 <separately-approved-complete-sha256>
```

The order is fixed:

1. repeat the current sanitized Azure preflight, then the bounded public
   readiness read, and prove the same twelve-read observation, exact
   package-bound RBAC phase, and exact package-bound pre-migration database
   head before publication;
2. snapshot and revalidate the package-bound OCI archive, then use
   `oras cp --from-oci-layout` to copy that exact archive manifest and blobs to
   the package-bound ACR tag without a Docker build/load/tag substitution;
   require the ACR readback digest to equal the pre-approved OCI manifest;
3. invoke Task 10's exact `reconcile_admin_ai_secret_access` action. That action
   uses Incremental deployment, enumerates the complete principal-assignment
   union, removes only the deterministic legacy assignment when the package
   phase is `legacy_only`, and finishes at secret-scoped `officer_only`;
4. deploy the candidate process capability with
   `BIZPULSE_AI_CHAT_ENABLED=true` while both authoritative database channels
   remain false. Validate the exact package-bound Manual migration Job and
   start it once with a complete package-bound execution-template override;
   no mutable Job image update supplies the executed command, image,
   resources, environment names, safe values, or secret references. Its
   readiness accepts only the bounded additive transition heads `0014`,
   `0015`, `0016`, and `0017`; then run migration
   `0017_ai_turn_credential_binding`, require exact `0017`, and retain this
   candidate as the safe stop revision;
5. verify exact `0017` readiness, protected `/admin`, and the secret-free
   summary while both AI channels are still false;
6. prompt locally once, without echo, for the candidate. Submit it only to the
   protected admin rotation endpoint; never place it in argv, environment,
   package, receipt, logs, browser storage, or evidence;
7. enable ordinary-login AI and complete one hosted Operator turn;
8. enable Demo AI and complete one hosted Demo turn;
9. prove both audit projections use the same immutable credential binding and
   eight-character safe fingerprint, and prove the real Demo cookie is denied
   `/admin` with `Cache-Control: private, no-store` and `Vary: Cookie`;
10. independently disable and re-enable each channel, leaving both enabled;
11. submit the fixed non-secret invalid sentinel and prove
    `ADMIN_AI_KEY_REJECTED`, the prior fingerprint, and both prior channel states
    remain authoritative;
12. scan bounded hosted response bodies and headers plus bounded raw log text
    in process against generic credential patterns and the exact candidate and
    operator password, retaining only a zero count; then finalize the
    owner-only receipt with a checked truncate/write/fsync cycle.
    Never retry automatically.

The committed live adapter is
`scripts/admin_ai_release_operations.py:create_operations`. It uses the
package-bound Task 10 authority and migration job, and it must use the existing
protected session, origin,
CSRF, current-password reauthentication, optimistic revision, and unique
idempotency contracts. Public Demo authority must never be accepted for an
admin route.

## Receipt and hosted evidence

The receipt contains only package/source/tree/image hashes, safe state names,
safe error codes, request IDs, revision names, fingerprint prefixes, and the
initial/final RBAC phase. It must not contain credentials, passwords, headers,
cookies, prompt or response bodies, stdout/stderr, raw provider errors, Key
Vault values, connection strings, or customer data.

`scripts/verify_admin_ai_control.py` accepts hosted evidence only when:

- protected admin entry and safe summary are ready;
- Operator and Demo turns both complete;
- both turns project the same safe credential fingerprint;
- the authenticated Demo session is denied `/admin` with the exact private
  no-store and Cookie-vary evidence;
- each channel is independently switched and both finish enabled;
- the known-invalid candidate is rejected without changing fingerprint or
  channel state; and
- the secret scan reports zero matches.

Local tests, a built image, package creation, a reachable URL, an Azure write,
or only one actor's hosted turn do not satisfy this acceptance contract.

## Failure handling

The first mismatch or exception is terminal. Before adapter import or any
mutation, the controller persists a valid `started` receipt. It later records
only a stable safe code using a checked complete write, stops before the next
state, and never retries. The receipt's
existence permanently fences package replay, including an interrupted or failed
attempt. Do not delete or reuse the receipt to manufacture a second attempt.

If failure occurs after external mutation, preserve the receipt and perform no
unspecified cleanup. Assess current Azure and database state read-only, design a
new bounded recovery, and obtain separate authorization for a fresh exact-hash
package. Credential invalidation or provider-side revocation is a separate
operator action and must never be inferred from an application rollback.

Never route traffic back to the old attested revision after 0017. That image's
exact-old-head readiness rejects the additive 0017 schema. The candidate
revision is the only safe stop after migration, including on a later acceptance
failure; recovery from that point must be a fresh forward package, not an old
revision traffic rollback. Every started and terminal receipt records this
candidate-only schema recovery boundary.
