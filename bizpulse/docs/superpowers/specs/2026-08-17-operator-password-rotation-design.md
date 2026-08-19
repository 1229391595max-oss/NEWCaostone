# Operator Password Rotation Design

**Status:** Draft for user review — the user approved the direction on
2026-08-17, but no credential, Azure, database, or application change has
been made by this design.

## 1. Context and decision

The target is the single-operator BizPulse Demo at
`https://newcaostone-demo-app.delightfulstone-15318d59.centralus.azurecontainerapps.io`.
At the time of investigation, its public readiness endpoint reported the
database, configuration, Blob, foundation, and migration checks as healthy.

The local Keychain plaintext item and its Argon2id hash item also verified as a
pair. A value-free smoke test using that plaintext received `201` from
`POST /api/operator/login` and immediately revoked the resulting session.
Subsequent browser requests were recorded as `401`, not `429`. The web UI
currently renders both outcomes as the same generic sign-in error. Therefore,
the observed login issue is not a lost account, a hosted foundation mismatch,
or a rate-limit response.

The operator nevertheless wants a new password that they enter themselves on
their Mac. This design makes that an explicit, auditable credential rotation,
not an ad-hoc Keychain or database edit.

## 2. Goals

- Rotate only the `operator` credential for workspace `synthetic-demo`.
- Let the user enter the new plaintext locally, without placing it in chat,
  source control, command arguments, files, logs, package manifests, or Azure
  output.
- Keep the current Keychain credential intact until the hosted rotation has
  passed verification.
- Update the PostgreSQL credential hash and revoke every active operator
  session in one transaction.
- Bind the new Container App revision to the same new Argon2id hash and prove
  that the new password works before promoting the local Keychain entries.
- Fail closed on a changed current revision, a current-hash mismatch, malformed
  hash, missing Keychain item, unexpected operator authority, or an ambiguous
  Job outcome.
- Retain a separately approved, exact-hash inverse path that can restore the
  old database hash before the old Keychain material is removed.

## 3. Non-goals

- No public self-service reset or "forgot password" route.
- No new account, role, workspace, user recovery email, password hint, or
  password value returned by an API.
- No AI, data, schema, tenant, viewer-session, marketplace, or pricing change.
- No direct SQL console update, Portal-only secret edit, deletion of a resource,
  or relaxed readiness predicate.
- No claim that a locally tested rotation is deployed or accepted until the
  exact hosted run completes.

## 4. Approaches considered

### A. Edit Keychain and issue SQL/Portal updates manually

This is fast, but the local, Azure, and PostgreSQL authorities can diverge. It
also bypasses session revocation, leaves no bounded retry behavior, and repeats
the exact unsupported live update pattern already rejected by the release
design. **Rejected.**

### B. Recreate the single-operator foundation

Deleting or rebuilding the workspace would rotate the password only by
reinitializing application state. It is disproportionate, risks demo data, and
does not preserve the exact authority. **Rejected.**

### C. Pending Keychain credential plus one-purpose maintenance Job

The user enters a new value into a pending local Keychain item. A new immutable
image contains a manual, idempotent rotation Job that verifies the current
database hash, updates it to the pending hash, and revokes all operator
sessions in the same transaction. The subsequent application revision receives
the pending hash, is checked, and only then is the pending local credential
promoted. **Selected.**

## 5. Credential authorities

All items use the Keychain account `operator`.

| Purpose | Keychain service | Lifecycle |
| --- | --- | --- |
| Current plaintext | `NEWCaostone Azure Demo Operator Password` | Preserved until hosted verification succeeds. |
| Current hash | `NEWCaostone Azure Demo Operator Password Hash` | Preserved until hosted verification succeeds. |
| Pending plaintext | `NEWCaostone Azure Demo Operator Password Pending` | Created by a local no-echo prompt; never printed. |
| Pending hash | `NEWCaostone Azure Demo Operator Password Pending Hash` | Written only through Security.framework and verified against pending plaintext. |

The prompt creates or replaces only the two **Pending** items. It first verifies
that the pending plaintext differs from the current plaintext using an
in-memory constant-time comparison. It derives a valid Argon2id hash with the
same cloud validation floor used by `src.config._validate_cloud_operator_password_hash`.
No helper may pass a secret via argv, standard output, a file, Bicep parameter
file, test fixture, or exception text.

The local launch/rotation controller reads Keychain values only into process
memory. It writes hash items through macOS Security.framework rather than
`security ... -w <secret>` arguments. If the user cancels the prompt or any
Keychain call is ambiguous, the controller exits without cloud activity.

The package also carries a validated, public deployment profile: the exact
non-secret topology values needed to replay the Bicep deployment. It excludes
all password hashes, PostgreSQL credentials, session pepper, and provider API
keys. The executor supplies only the PostgreSQL password, session pepper, and
operator-hash values through a minimal child process environment consumed by
`readEnvironmentVariable()`; it never reads or forwards a provider key. When
AI is enabled, the public profile binds the pre-existing Key Vault and managed
identity references instead. No secret is placed in an Azure CLI argument or
output.

## 6. Database rotation boundary

Add a focused `OperatorPasswordRotationService` backed by repository methods;
it does not reuse `FoundationBootstrapService`, whose intentionally strict
contract refuses a changed credential.

The Job receives the replacement Argon2id hash through its scoped secret and
two non-secret, Job-only values:

- `BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256`: the SHA-256 fingerprint
  of the expected current hash;
- `BIZPULSE_OPERATOR_ROTATION_ID`: the approved package identifier.

Within one PostgreSQL transaction, under an advisory lock scoped to
`operator/credential-rotation/synthetic-demo`, it must:

1. lock and read the sole active `operator` row;
2. compare the stored hash with the expected current hash using
   `hmac.compare_digest`;
3. if it matches, replace `password_hash` with the pending hash and update the
   timestamp;
4. revoke every unrevoked `operator_sessions` row for that operator and remove
   its ephemeral operator-chat state; and
5. commit both changes together.

If the stored hash already equals the pending hash, the Job returns a
value-free `already_rotated` result and does not create a second rotation. If
it equals neither expected hash, has more than one active operator, or cannot
complete the transaction, it returns a value-free authority conflict and makes
no partial change.

No database migration is required: the existing `password_hash`, `updated_at`,
and `revoked_at` columns are sufficient.

## 7. Azure delivery and rollback

The delivery package targets only the current Container App and its declared
resource group/subscription. It binds two distinct immutable images: the
currently serving image observed during the read-only preflight, and the
candidate image that contains the rotation Job. Before any write it rereads the
current FQDN, single-revision mode, latest-ready revision, serving-image digest,
and strict `/health/ready` result. A changed serving image or revision fails the
package rather than being silently adopted; the candidate image remains bound
to the package source and is verified separately against its registry labels.

The package performs these bounded phases:

1. Build and inspect one immutable candidate image that contains the rotation
   Job code and its tests; do not change the existing app hash yet.
2. Deploy/update the manual rotation Job with the current and pending hashes as
   secret references; the currently serving application revision remains bound
   to its current hash.
3. Run the Job exactly once. It either returns `rotated`/`already_rotated` or
   stops without a retry.
4. Deploy the inspected application revision with the pending hash. A brief
   readiness-maintenance interval is expected while the prior revision sees the
   new database hash and the new revision becomes ready.
5. Read the exact revision, `/health/ready`, and a one-time new-password login
   followed by logout. Success requires HTTP `201`, HTTP `204`, and a ready
   foundation using the expected migration.

If the Job did not commit, the current revision and Keychain records remain
unchanged. If it committed but the new application revision fails readiness or
the login/logout smoke, the controller stops before Keychain promotion and
does not auto-run an inverse. It emits the package-bound command to generate a
new inverse package from the forward package. That inverse swaps only the two
fingerprints, rechecks the current app identity (while deliberately allowing
the failed app to be unready), and needs a new explicit approval before its one
Job execution. It never restores an old session token. A successful inverse
retains Pending locally for investigation; it does not silently delete it.

## 8. Local promotion and cleanup

After hosted success, the controller verifies the pending plaintext against the
hosted login endpoint without outputting it. It then promotes the pending
plaintext and hash into the two Current services via Security.framework. A
post-promotion in-memory check must show that the new Current pair matches.

Only after that check may it remove the two Pending items. If promotion fails,
the Pending items remain for recovery and the controller reports a value-free
local-promotion failure. It never deletes the Current entries first.

## 9. Required verification

Local tests must prove all of the following before an authorization package is
generated:

- a missing, cancelled, same-as-current, malformed, or mismatched pending
  credential aborts before any Azure command;
- secret values never appear in captured command arguments, output, logs,
  manifests, exceptions, or test snapshots;
- a correct current database hash changes exactly one operator credential and
  revokes every active operator session atomically;
- a stale expected hash changes nothing;
- an already-rotated retry is idempotent;
- an inverse rotation accepts only the pending hash and cannot overwrite an
  unrelated authority;
- Bicep exposes the new and expected hash only to the manual rotation Job and
  exposes the new hash, not the expected old hash, to the application;
- no AI setting, public reset endpoint, raw secret projection, or migration is
  introduced; and
- package preflight rejects a changed target revision, serving-image digest,
  FQDN, secret reference, or health state before external mutation, while still
  allowing the separately verified candidate image to differ from the serving
  image.

Hosted acceptance is separate. It requires a new user-approved, time-bounded
authorization package, successful Job execution, new revision readiness, a
new-password login/logout smoke, and a post-promotion Keychain verification.

## 10. User interaction and final authorization

The user enters the new password only in a local no-echo Keychain prompt. They
must not paste it into this chat. Before the first Azure or PostgreSQL write,
the generated authorization package will show its exact target, candidate image
digest, source SHA, public deployment profile, expected fingerprints, and the
expected short maintenance interval. The user must approve that exact package;
this design
approval alone does not execute it. The pending local Keychain write occurs
only after the controller has completed its value-free local preflight, and
the destructive promotion/removal of Keychain items occurs only after hosted
acceptance.
