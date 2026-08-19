# Operator Password Rotation Job-Only Delivery Design

**Status:** Approved by the owner on 2026-08-17 for the current Demo `operator`
password rotation.

## Context

The first generated rotation package used the full `infra/main.bicep` deployment
for its stage phase. That command supplied the already-active Container App
revision suffix while supplying a different candidate image. Azure Container Apps
revisions are immutable and their suffixes must be unique, so that stage could
not safely prepare the Job. An incremental deployment could also update an
unrelated resource before the App suffix conflict is returned.

## Decision

Stage and cleanup will use a dedicated Bicep entry point that manages only the
manual operator-rotation Container Apps Job. It will reference the existing
managed environment, registry identity, PostgreSQL server, and storage account;
it will not declare or update `Microsoft.App/containerApps`.

The executor has three distinct deployment paths:

1. **Stage:** deploy the manual Job with the pending hash and exact old-hash
   fingerprint. The existing App revision remains untouched.
2. **Activate:** use the full application template once, with a fresh,
   rotation-ID-derived revision suffix and the pending App hash.
3. **Cleanup:** deploy only the manual Job again with rotation material disabled.
   It does not redeploy the App.

The authority schema becomes v3 and records the `job-only-stage-v1` delivery
contract. A v2 package is not executable by the repaired controller. The
existing immutable candidate image can be reused because it already contains
the Job entry point; the repair concerns local deployment orchestration rather
than application-container contents.

## Constraints

- The rotation Job remains manual and has `replicaRetryLimit: 0`.
- No password, Argon2 string, database credential, session pepper, cookie, or
  provider key appears in an argument, package, receipt, or output.
- The stage and cleanup commands may update only the named rotation Job.
- A fresh package still binds the live App identity, live revision, serving
  image, health state, current Keychain pair, pending Keychain pair, and
  immutable candidate image before any cloud write.
- The Keychain Pending pair is promoted only after new-revision health and a
  pending-password login/logout smoke pass.

## Verification

Tests will first prove that stage and cleanup select the job-only parameter
file and never pass App deployment flags or a revision suffix. Bicep compilation
will prove the dedicated template has a Job resource and no Container App
resource. The focused controller suite will run in the Linux/amd64 candidate
image, which is the same platform used by Azure. Before cloud execution, the
new authority package will be generated from a fresh read-only preflight. After
the single Job execution, acceptance requires the target revision, ready health,
and one login/logout with the Pending credential.
