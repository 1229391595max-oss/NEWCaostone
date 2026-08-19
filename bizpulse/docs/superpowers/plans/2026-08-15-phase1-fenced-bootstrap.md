# Phase 1 Fenced Bootstrap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pre-migration API startup with a dependency-free Phase 1 fence process, prove the Phase 1 and Phase 2 authorities locally, then create a new immutable candidate and two new approval-bound cleanup/launch packages without retrying the failed package.

**Architecture:** The same immutable image supports two mutually exclusive Container App states. Phase 1 overrides the image command with a standard-library-only health server, exposes no application secrets, and drains to zero before migration. Phase 2 removes the override and restores Docker's Uvicorn command, the exact application environment and secret references, external HTTPS ingress, one ready replica, and single-revision traffic. Migration, seed, and maintenance Jobs retain their existing secure authority in both phases.

**Tech Stack:** Python 3.12 standard library, pytest, Ruff, Azure Bicep/ARM, Azure CLI readback, Docker BuildKit, PostgreSQL/Azurite release gates, Git manifest-only attestation.

## Global Constraints

- Run repository commands from `bizpulse/` unless a step explicitly names the repository root.
- Keep `applicationEnabled=false` until a newly approved package reaches its exact Phase 2 command.
- Do not reuse either consumed SHA-approved package; do not retry any command from them.
- Do not mutate Azure, publish an image, clean up the failed private Phase 1, or create public traffic while Tasks 1-6 are executing.
- Keep AI disabled: no OpenAI key, endpoint override, provider call, paid smoke, budget rehearsal, or provider-failure rehearsal.
- Preserve the four Job resources and their secure PostgreSQL/Blob/operator/session settings; only the application container is inert in Phase 1.
- Never write secret values to Git, package files, command output, logs, or chat. Reuse the macOS Keychain values only after exact authority is proved; otherwise rotate them before a future approved launch.
- Treat local tests, a local image, an attestation, and generated authorization packages as local evidence only. Hosted, accepted, deployed, and Production-ready remain false until a future approved launch finishes all hosted non-AI gates.

---

### Task 1: Add the dependency-free Phase 1 fence server

**Files:**
- Create: `tests/unit/test_phase1_fence_server.py`
- Create: `scripts/phase1_fence_server.py`
- Modify: `tests/release/test_container_contract.py`
- Modify: `Dockerfile`
- Modify: `.dockerignore`

**Interfaces:**
- Produces: `build_server(host: str = "0.0.0.0", port: int = 8000) -> ThreadingHTTPServer` and `main() -> int`.
- Serves: `GET /health/live` and `GET /health/ready` with the exact bounded body `{"status":"phase1-fenced"}\n`.
- Rejects: every other path with 404 and the exact bounded body `{"error":"not_found"}\n`.
- Imports: Python standard library only; no `api`, `src`, SQLAlchemy, Azure SDK, configuration, environment, database, or Blob code.

- [ ] **Step 1: Write the failing HTTP and import-boundary tests**

Create `tests/unit/test_phase1_fence_server.py`. Start `build_server("127.0.0.1", 0)` in a daemon thread, then assert both health paths return status 200, `Content-Type: application/json`, `Cache-Control: no-store`, the exact body, and the exact `Content-Length`. Assert `/`, `/metrics`, query-bearing unknown paths, and POST/PUT/PATCH/DELETE/OPTIONS return a fixed 404/405 response without reflecting the path or request body.

Parse the source with `ast` and require every imported top-level module to be in:

```python
{"__future__", "http", "typing"}
```

Also assert the source contains no `os.environ`, `getenv`, `api`, `src`, `sqlalchemy`, or `azure` reference.

Extend `tests/release/test_container_contract.py` to require this exact Docker instruction:

```dockerfile
COPY --chown=bizpulse:bizpulse scripts/phase1_fence_server.py /app/scripts/phase1_fence_server.py
```

Also require the exact `.dockerignore` allowlist entry `!scripts/phase1_fence_server.py`; the current context prunes every script that is not explicitly re-included.

- [ ] **Step 2: Run the focused tests and verify RED**

```bash
.venv/bin/pytest tests/unit/test_phase1_fence_server.py tests/release/test_container_contract.py -q
```

Expected: collection or file-contract failure because the fence server and Docker copy do not exist.

- [ ] **Step 3: Implement the minimal server**

Implement `scripts/phase1_fence_server.py` with this structure:

```python
from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Final

HOST: Final = "0.0.0.0"
PORT: Final = 8000
FENCED_BODY: Final = b'{"status":"phase1-fenced"}\n'
NOT_FOUND_BODY: Final = b'{"error":"not_found"}\n'
METHOD_NOT_ALLOWED_BODY: Final = b'{"error":"method_not_allowed"}\n'
HEALTH_PATHS: Final = frozenset({"/health/live", "/health/ready"})


class Phase1FenceHandler(BaseHTTPRequestHandler):
    def _write(self, status: int, body: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        body = FENCED_BODY if self.path in HEALTH_PATHS else NOT_FOUND_BODY
        self._write(200 if self.path in HEALTH_PATHS else 404, body)

    def _method_not_allowed(self) -> None:
        self._write(405, METHOD_NOT_ALLOWED_BODY)

    do_POST = _method_not_allowed
    do_PUT = _method_not_allowed
    do_PATCH = _method_not_allowed
    do_DELETE = _method_not_allowed
    do_OPTIONS = _method_not_allowed

    def log_message(self, _format: str, *args: object) -> None:
        del _format, args


def build_server(host: str = HOST, port: int = PORT) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), Phase1FenceHandler)


def main() -> int:
    with build_server() as server:
        server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Do not add configuration loading, structured application logging, redirects, metrics, or dependency checks. Add the exact Docker `COPY` before `USER bizpulse` and add the exact script allowlist entry to `.dockerignore`.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/unit/test_phase1_fence_server.py tests/release/test_container_contract.py -q
.venv/bin/ruff check scripts/phase1_fence_server.py tests/unit/test_phase1_fence_server.py tests/release/test_container_contract.py
git diff --check
git add scripts/phase1_fence_server.py tests/unit/test_phase1_fence_server.py tests/release/test_container_contract.py Dockerfile .dockerignore
git commit -m "fix: add inert phase1 fence server"
```

Expected: focused tests and Ruff pass, diff check prints nothing, and the commit contains only the five listed files.

---

### Task 2: Make the Container App phase boundary exact in Bicep

**Files:**
- Modify: `tests/infra/test_bicep_contract.py`
- Modify: `infra/modules/app.bicep`

**Interfaces:**
- Phase 1 application env: exactly `BIZPULSE_RUNTIME_ENVIRONMENT=phase1-fenced`.
- Phase 1 application secrets: exactly `[]`.
- Phase 1 command/args: exactly `python` and `scripts/phase1_fence_server.py`.
- Phase 2 command/args: omitted so Docker's immutable `CMD` is authoritative.
- Jobs: unchanged `jobEnvironment`, `jobSecrets`, commands, schedules, and resource limits.

- [ ] **Step 1: Add compiled-template RED tests**

Add `_compiled_app_template()` to compile `infra/modules/app.bicep` directly and fail on any Bicep warning. Add helpers that locate the single `Microsoft.App/containerApps` resource and serialize its configuration/template.

Add a test requiring the compiled container expression to select these exact phase-specific objects:

```python
PHASE1_ENV = [
    {"name": "BIZPULSE_RUNTIME_ENVIRONMENT", "value": "phase1-fenced"}
]
PHASE1_COMMAND = ["python"]
PHASE1_ARGS = ["scripts/phase1_fence_server.py"]
```

Require the app-level `secrets` expression to return `[]` when `applicationEnabled=false`, while every Job still references the unchanged four `jobSecrets`. Require the normal application env/secret-ref expressions, liveness/readiness probes, `external: applicationEnabled`, and `minReplicas: applicationEnabled ? 1 : 0` to remain present. Require `openai-api-key` only on the `aiChatEnabled` Phase 2 branch.

- [ ] **Step 2: Run the Bicep contract and verify RED**

```bash
.venv/bin/pytest tests/infra/test_bicep_contract.py -q
```

Expected: the new phase-boundary assertions fail because the current app always receives `jobEnvironment`, `jobSecrets`, and Docker's normal command.

- [ ] **Step 3: Implement the conditional app object**

In `infra/modules/app.bicep`, retain `jobSecrets` and `jobEnvironment` unchanged. Add:

```bicep
var phase1AppEnvironment = [
  {
    name: 'BIZPULSE_RUNTIME_ENVIRONMENT'
    value: 'phase1-fenced'
  }
]
var appSecrets = applicationEnabled ? [
  ...jobSecrets
  ...(aiChatEnabled ? [
    {
      name: 'openai-api-key'
      value: openaiApiKey
    }
  ] : [])
] : []
```

Move the existing normal application environment into `phase2AppEnvironment`. Build the application container with `union` so the override is absent, not null, in Phase 2:

```bicep
var appContainer = union({
  name: 'bizpulse'
  image: containerImage
  env: applicationEnabled ? phase2AppEnvironment : phase1AppEnvironment
  probes: appProbes
  resources: jobResources
}, applicationEnabled ? {} : {
  command: [
    'python'
  ]
  args: [
    'scripts/phase1_fence_server.py'
  ]
})
```

Use `secrets: appSecrets` and `containers: [appContainer]` in the Container App. Do not change Job secrets/env, ingress, revision suffix, identity, registry, probes, or scale semantics.

- [ ] **Step 4: Compile, verify GREEN, and commit**

```bash
az bicep build --file infra/main.bicep --stdout \
  >/tmp/newcaostone-phase1-main.json \
  2>/tmp/newcaostone-phase1-main.stderr
test ! -s /tmp/newcaostone-phase1-main.stderr
.venv/bin/pytest tests/infra/test_bicep_contract.py -q
.venv/bin/ruff check tests/infra/test_bicep_contract.py
git diff --check
git add infra/modules/app.bicep tests/infra/test_bicep_contract.py
git commit -m "fix: fence the phase1 app container"
```

Run the Bicep command with stderr redirected to `/tmp/newcaostone-phase1-main.stderr`; require exit 0 and an empty stderr file. Expected: all infra tests pass and no Bicep warning is emitted.

---

### Task 3: Bind Azure readback to command, env, probes, and secrets

**Files:**
- Modify: `tests/hosted/test_azure_preflight.py`
- Modify: `scripts/verify_phase1_fence.py`
- Modify: `tests/hosted/verify_azure_demo.py`
- Modify: `tests/hosted/test_verify_azure_demo.py`

**Interfaces:**
- Add private helpers:
  - `_env_authority(container: dict[str, Any]) -> tuple[dict[str, str], dict[str, str]]`
  - `_require_phase1_app(container: dict[str, Any], configuration: dict[str, Any]) -> None`
  - `_require_phase2_app(container: dict[str, Any], configuration: dict[str, Any], expected_values: dict[str, str]) -> None`
- Extend `verify_phase1_fence()` with required `storage_account_name: str` and `blob_container_name: str` keyword arguments.
- Extend the CLI with required `--storage-account` and `--blob-container` arguments.
- Stable failure code for any mixed/unknown app projection: `phase1_app_not_fenced`.

- [ ] **Step 1: Upgrade the Azure CLI fixtures**

Define exact test fixtures for:

```python
PHASE1_CONTAINER = {
    "name": "bizpulse",
    "image": image,
    "command": ["python"],
    "args": ["scripts/phase1_fence_server.py"],
    "env": [
        {"name": "BIZPULSE_RUNTIME_ENVIRONMENT", "value": "phase1-fenced"}
    ],
    "probes": EXPECTED_PROBES,
}
PHASE1_SECRETS: list[dict[str, str]] = []
```

Extend the Phase 2 fixture to include the exact four secret references, runtime/Blob/origin/monitoring values, AI-disabled values, expected probes, no command/args override, and exactly these application secret names:

```python
{"database-url", "blob-connection-string", "operator-password-hash", "session-pepper"}
```

Add this shared authority to every direct `verify_phase1_fence()` call:

```python
def _phase_app_authority() -> dict[str, str]:
    return {
        "storage_account_name": "bpapprovedstorage",
        "blob_container_name": "synthetic-demo",
    }
```

Add RED tests proving the current verifier wrongly accepts: the normal API command in Phase 1, one leaked application secret in Phase 1, an extra Phase 1 env value, a missing/wrong probe, a Phase 2 fence command that was not removed, a missing Phase 2 secret reference, and an unexpected OpenAI secret/ref while `ai_enabled=False`.

Update the exact command fixtures in `tests/hosted/test_verify_azure_demo.py` to include the declared generated storage account and Blob container. Do not accept a legacy command that omits either new flag.

- [ ] **Step 2: Run the fence tests and verify RED**

```bash
.venv/bin/pytest tests/hosted/test_azure_preflight.py -k 'phase1 or phase2 or activate' -q
```

Expected: each new fail-closed assertion fails because `verify_phase1_fence()` currently checks only image, ingress, scale, and a subset of Phase 2 values.

- [ ] **Step 3: Implement exact projection validation**

In `scripts/verify_phase1_fence.py`, define immutable constants for the two probe dictionaries, the Phase 1 command/args/env, the Phase 2 secret-name set, secret-ref map, and allowed env-name set. Parse env rows fail-closed: reject non-dicts, duplicate names, rows containing both `value` and `secretRef`, missing values, or extra fields that change authority.

For `initial` and `activate`, require:

```python
container.get("name") == "bizpulse"
container.get("command") == ["python"]
container.get("args") == ["scripts/phase1_fence_server.py"]
value_env == {"BIZPULSE_RUNTIME_ENVIRONMENT": "phase1-fenced"}
secret_env == {}
configuration.get("secrets", []) == []
container.get("probes") == EXPECTED_PROBES
```

For `phase2`, require command and args to be absent or Azure's canonical empty projection, never the fence override; require the exact env-name and secret-ref sets; require the four application secret names and no extra secret names; derive `BIZPULSE_ALLOWED_ORIGIN` from the exact ingress FQDN; require `BIZPULSE_BLOB_ENDPOINT` to equal `https://<storage_account_name>.blob.core.windows.net`, `BIZPULSE_BLOB_CONTAINER` to equal `blob_container_name`, and the Application Insights string to be nonempty/bounded; require every fixed AI/rate/model value to match the function arguments. If `ai_enabled=False`, reject `OPENAI_API_KEY`, `OPENAI_BASE_URL`, and `openai-api-key`. Preserve all existing revision, traffic, replica, Job, timing, and execution checks.

Update `tests/hosted/verify_azure_demo.py` so every generated phase-fence command supplies the exact generated storage account and Blob container. This changes the package hash authority but not the stage order.

Never log or include an env value, secret reference, FQDN, object key, or Azure response in a raised error.

- [ ] **Step 4: Verify GREEN and commit**

```bash
.venv/bin/pytest tests/hosted/test_azure_preflight.py -q
.venv/bin/ruff check scripts/verify_phase1_fence.py tests/hosted/verify_azure_demo.py tests/hosted/test_azure_preflight.py tests/hosted/test_verify_azure_demo.py
git diff --check
git add scripts/verify_phase1_fence.py tests/hosted/verify_azure_demo.py tests/hosted/test_azure_preflight.py tests/hosted/test_verify_azure_demo.py
git commit -m "fix: verify exact phase app authority"
```

Expected: the full Azure preflight test module passes and all new mixed-state probes fail with the stable value-free code.

---

### Task 4: Lock the deployment contract and run the local regression gate

**Files:**
- Modify: `docs/runbooks/DEPLOY.md`
- Modify: `tests/hosted/test_verify_azure_demo.py`

**Interfaces:**
- Documents: Phase 1 application process, Job authority, drain/migrate/seed order, and Phase 2 command restoration.
- Preserves: the existing exact authorization grammar and no-AI execution order.

- [ ] **Step 1: Add the runbook contract test**

Require `docs/runbooks/DEPLOY.md` to contain these exact statements:

```text
Phase 1 runs only `python scripts/phase1_fence_server.py`; the application container has no PostgreSQL, Blob, operator, session, or OpenAI secret authority.
Migration and seed may start only after the exact Phase 1 command/env/secret projection is verified and every application revision reports zero replicas.
Phase 2 removes the command override, restores the normal Uvicorn application authority, and must pass the exact phase2 fence before hosted acceptance begins.
```

- [ ] **Step 2: Run the contract test and verify RED**

```bash
.venv/bin/pytest tests/hosted/test_verify_azure_demo.py -q
```

Expected: the new documentation assertion fails because the runbook still describes the old pre-migration application behavior.

- [ ] **Step 3: Update the runbook and preserve stop conditions**

Insert the three exact statements beside the Phase 1/activate/Phase 2 order. Record the observed failure signature only as historical evidence: normal API startup before migration caused `analysis_runs` to be missing; do not include Azure IDs, URLs, credentials, or response payloads. State that a fence mismatch, nonzero replicas, Job ambiguity, migration failure, seed failure, or Phase 2 authority mismatch stops execution without retry.

- [ ] **Step 4: Run the complete local regression set**

```bash
.venv/bin/pytest \
  tests/unit/test_phase1_fence_server.py \
  tests/release/test_container_contract.py \
  tests/infra/test_bicep_contract.py \
  tests/hosted/test_azure_preflight.py \
  tests/hosted/test_verify_azure_demo.py \
  tests/hosted/test_run_hosted_check.py \
  tests/hosted/test_run_hosted_failure_check.py -q
.venv/bin/ruff check scripts/phase1_fence_server.py scripts/verify_phase1_fence.py tests/unit/test_phase1_fence_server.py tests/infra/test_bicep_contract.py tests/hosted/test_azure_preflight.py tests/hosted/test_verify_azure_demo.py
.venv/bin/python -m compileall -q scripts tests
git diff --check
```

Expected: all tests pass, Ruff and compileall are clean, and diff check prints nothing.

- [ ] **Step 5: Commit the runbook contract**

```bash
git add docs/runbooks/DEPLOY.md tests/hosted/test_verify_azure_demo.py
git commit -m "docs: define fenced phase1 rollout"
```

---

### Task 5: Prepare and verify the immutable remediation candidate

**Files:**
- Modify: `../CURRENT_STATUS.md`
- Modify: `../AUTHORIZATION_LEDGER.md`
- Modify: `../docs/handoffs/CURRENT_HANDOFF.md`
- Delete in candidate: `release/task15-local-release-manifest.json`
- Create in manifest child: `release/task15-local-release-manifest.json`
- Verify: `scripts/verify_release.py`
- Verify: `scripts/create_release_manifest.py`

**Interfaces:**
- Consumes: the clean implementation commits from Tasks 1-4 and the proven schema-0008 rollback authority at Git `8896d17d7c69c684e150b611e3066008842a240f`, image digest `sha256:c4073fd0db994d2f4c900950448a35bbc1fea8d2876aad492d25c7ae2aa706e8`, image-input `a1514f77ef984790000a72f400a593147372603a9046a4c5aa476ac4735515c5`.
- Produces: one clean candidate SHA, one inspected `linux/amd64` image, and one direct manifest-only attestation child.

- [ ] **Step 1: Update current evidence without overclaiming**

Update the three root status/handoff files to state:

- the prior restricted package reached private Phase 1 only;
- migration, seed, Phase 2, public traffic, hosted acceptance, and Production remain false;
- the stop condition was a normal API process requiring `analysis_runs` before migration;
- the approved remediation uses the dependency-free fence server;
- both prior approved packages are consumed and must not be retried;
- the next external boundary is approval of new exact cleanup and launch package hashes.

Do not include secret values, transient Azure payloads, or claims that the remediation is hosted.

- [ ] **Step 2: Retire the superseded attestation and create the candidate**

```bash
git add ../CURRENT_STATUS.md ../AUTHORIZATION_LEDGER.md ../docs/handoffs/CURRENT_HANDOFF.md
git add release/task15-local-release-manifest.json
git diff --cached --name-status
git commit -m "release: prepare fenced phase1 candidate"
CANDIDATE=$(git rev-parse HEAD)
test -z "$(git status --short)"
```

Expected: the old manifest is deleted, the three evidence files contain only the bounded status update, and the worktree is clean. The candidate commit must not add a replacement manifest.

- [ ] **Step 3: Run the full release verifier on the clean candidate**

```bash
.venv/bin/python scripts/verify_release.py --manifest tests/fixtures/synthetic/v1/manifest.json
```

Expected: `release_verification=ok`, every required gate passes, and `git status --short` remains empty. Stop and fix locally if any gate fails; do not weaken, skip, or relabel a failing gate.

- [ ] **Step 4: Compute image input and build the exact image**

```bash
IMAGE_INPUT=$(.venv/bin/python -c 'from scripts.create_release_manifest import committed_image_input_sha256; import subprocess; sha=subprocess.check_output(["git","rev-parse","HEAD"], text=True).strip(); print(committed_image_input_sha256(sha))')
LOCAL_IMAGE="newcaostone-local:${CANDIDATE:0:12}"
docker buildx build --platform linux/amd64 --build-arg SOURCE_REVISION="$CANDIDATE" --build-arg IMAGE_INPUT_SHA256="$IMAGE_INPUT" --load -t "$LOCAL_IMAGE" .
export CANDIDATE IMAGE_INPUT LOCAL_IMAGE
.venv/bin/python - <<'PY'
import json
import os
import subprocess

image = json.loads(
    subprocess.check_output(
        ["docker", "image", "inspect", os.environ["LOCAL_IMAGE"]],
        text=True,
    )
)[0]
assert image["Os"] == "linux"
assert image["Architecture"] == "amd64"
assert image["Config"]["User"] == "bizpulse"
assert image["Config"]["Labels"]["org.opencontainers.image.revision"] == os.environ["CANDIDATE"]
assert image["Config"]["Labels"]["org.opencontainers.image.bizpulse.image-input-sha256"] == os.environ["IMAGE_INPUT"]
assert image["Config"]["Cmd"] == [
    "python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0",
    "--port", "8000", "--workers", "1", "--no-access-log",
]
PY
docker run --rm --entrypoint python "$LOCAL_IMAGE" -c \
  "from pathlib import Path; p=Path('/app/scripts/phase1_fence_server.py'); assert p.is_file() and 'sqlalchemy' not in p.read_text().lower()"
```

Require platform `linux/amd64`, user `bizpulse`, exact OCI revision and image-input labels, the copied `/app/scripts/phase1_fence_server.py`, and Docker's unchanged Uvicorn `CMD --no-access-log`. Record the immutable local image ID; do not publish it.

- [ ] **Step 5: Create the manifest-only child and fresh-verify it**

```bash
.venv/bin/python scripts/create_release_manifest.py --candidate-sha "$CANDIDATE"
git add release/task15-local-release-manifest.json
test "$(git diff --cached --name-only)" = "bizpulse/release/task15-local-release-manifest.json"
git commit -m "task15: attest fenced phase1 candidate"
ATTESTATION=$(git rev-parse HEAD)
test "$(git rev-parse HEAD^)" = "$CANDIDATE"
.venv/bin/python scripts/create_release_manifest.py --verify-attestation
```

Expected: `release_attestation=ok`; the attestation child changes only the manifest; all deployment/hosted/accepted/CI/Production claims remain false.

---

### Task 6: Generate two new exact authorization packages and stop

**Files:**
- Create outside Git: `.tmp/PHASE1_FENCE_BOOTSTRAP_CLEANUP_V1.md`
- Create outside Git: `.tmp/LAUNCH_AUTHORIZATION_PHASE1_FENCE_V1.md`
- Adapt outside Git: `.tmp/generate_cleanup_package.py`
- Adapt outside Git: `.tmp/generate_remediated_launch_package.py`
- Verify: `tests/hosted/verify_azure_demo.py`

**Interfaces:**
- Cleanup package: deletes only the current failed private Phase 1 resources and their deployment records; preserves ACR, repository, immutable current/rollback manifests, local Keychain entries, Git, and unrelated Azure resources.
- Launch package: fresh restricted no-AI launch using the new candidate/image/attestation and the proven schema-0008 rollback image.
- Approval boundary: two complete lowercase SHA256 values, each explicitly approved by the user before any external write.

- [ ] **Step 1: Refresh the failed Azure state read-only**

Use `az account show`, resource-list/show, Container App/revision/Job show, ACR manifest show, PostgreSQL/Blob recovery reads, and deployment-list reads only. Prove the target is still private, `applicationEnabled=false`, unseeded, unmigrated, AI-disabled, and not publicly reachable. Stop on any unknown writer, public ingress, resource drift, digest mismatch, or non-synthetic authority.

- [ ] **Step 2: Generate the exact cleanup package**

Adapt `.tmp/generate_cleanup_package.py` to resolve every current failed Phase 1 target by full Azure resource ID and to emit a deterministic ordered delete/readback sequence. Set file mode `0600`. Require independent assertions that:

- every delete target belongs to the declared subscription/resource group and approved generated-name set;
- the ACR, `bizpulse` repository, both immutable image digests, Git worktree, Keychain entries, and any unrelated resource are excluded;
- no secret value or connection string is present;
- every destructive command has a bounded terminal readback and stop condition.

- [ ] **Step 3: Generate the fresh no-AI launch package**

Adapt `.tmp/generate_remediated_launch_package.py` to bind the new candidate, attestation, image ID/digest, image-input, local manifest hash, fixed target/resource/cost fields, and the exact approved no-AI settings:

```python
authority["ai_limits"]["enabled"] = False
authority["secret_presence"]["openai_api_key"] = False
authority["external_publication"]["paid_ai_smoke"] = False
authority["limits_usd"]["openai_smoke_cap"] = "0.00"
```

Generate command arrays and execution order only through `tests.hosted.verify_azure_demo._expected_commands()` and `_expected_execution_order()`. Require empty budget/provider/paid-AI command arrays and no corresponding stages. Set file mode `0600`; include secret-presence booleans only, never secret values.

- [ ] **Step 4: Validate both packages independently**

For cleanup, parse every command with `shlex.split`, compare its exact target set with the read-only Azure inventory, and simulate the state machine without executing commands. For launch, run:

```bash
LAUNCH_SHA=$(shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_PHASE1_FENCE_V1.md | awk '{print $1}')
set +e
LAUNCH_OUTPUT=$(.venv/bin/python tests/hosted/verify_azure_demo.py \
  --authorization .tmp/LAUNCH_AUTHORIZATION_PHASE1_FENCE_V1.md \
  --approved-sha256 "$LAUNCH_SHA")
LAUNCH_STATUS=$?
set -e
test "$LAUNCH_STATUS" -eq 2
test "$LAUNCH_OUTPUT" = "$(printf 'launch_package=valid\napproval_binding=matched\nrelease_git_sha=%s\nhosted_verification=not_executed' "$CANDIDATE")"
```

Require `launch_package=valid`, exact candidate/attestation/image bindings, no AI authority, and all non-AI health/browser/capacity/natural-expiry/maintenance/restart/rollback gates. Compute:

```bash
shasum -a 256 .tmp/PHASE1_FENCE_BOOTSTRAP_CLEANUP_V1.md
shasum -a 256 .tmp/LAUNCH_AUTHORIZATION_PHASE1_FENCE_V1.md
```

- [ ] **Step 5: Request two exact approvals and stop**

Report both complete SHA256 values, expiry, candidate SHA, attestation SHA, image digest, cleanup scope/count, and the remaining hosted gates. State explicitly that neither package has executed. End the implementation session here until the user explicitly approves both exact hashes; do not interpret approval of this plan as approval of those future external mutations.

---

## Plan self-review checklist

- [ ] Every production change starts with a failing test and a named RED command.
- [ ] The fence server has no application/config/database/storage import or secret/logging path.
- [ ] Phase 1 app authority is command/env/probe/secret exact, while Job authority is unchanged.
- [ ] Phase 2 proves Docker/Uvicorn restoration, exact env/ref sets, no OpenAI authority, one ready replica, and single-revision traffic.
- [ ] Bicep compiles with zero warnings; focused tests, Ruff, compileall, full release verification, image inspection, and detached attestation all pass before package generation.
- [ ] No `TODO`, placeholder SHA, mutable image tag, ellipsis, or unbounded target appears in a generated authority package.
- [ ] The current failed private deployment is not retried and is not called hosted/accepted/Production evidence.
- [ ] Two new external package SHA256 values are the only future mutation approval boundary.
