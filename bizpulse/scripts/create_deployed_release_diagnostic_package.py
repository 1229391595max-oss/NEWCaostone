#!/usr/bin/env python3
"""Create a one-shot, owner-only deployed release diagnostic package."""

from __future__ import annotations

import argparse
import ast
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
from typing import Any
from uuid import UUID, uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.build_deployed_release_desired_projection import (  # noqa: E402
    PROJECTION_SCHEMA,
    compile_desired_projection,
)
from scripts.deployed_release_diagnostic_contract import (  # noqa: E402
    DeployedReleaseDiagnosticInvalid,
    assert_exact_keys,
    canonical_sha256,
    parse_utc,
    unique_object,
    utc_text,
)
from scripts.secret_boundary import SECRET_PATTERN  # noqa: E402
from scripts.verify_deployed_release_state import (  # noqa: E402
    load_deployed_release_continuation,
)


HEADER = "# NEWCaostone Deployed Release Diagnostic D3 Authorization"
PACKAGE_SCHEMA = "newcaostone.deployed-release-diagnostic-package.v2"
ATTEMPT_SCHEMA = "newcaostone.deployed-release-diagnostic-attempt.v2"
AUTHORIZED_BRANCH = "codex/deployed-diagnostic-d3"
CONTINUATION_REFERENCE = (
    "release/incidents/2026-08-16-recovery-v4-deployed-continuation.json"
)
D3_ENTRYPOINTS = (
    "scripts/build_deployed_release_desired_projection.py",
    "scripts/create_deployed_release_diagnostic_package.py",
    "scripts/deployed_release_diagnostic_contract.py",
    "scripts/observe_deployed_release_state.py",
    "scripts/run_deployed_release_diagnostic.py",
)
BOUND_DATA_PATHS = (
    "infra/modules/app.bicep",
    CONTINUATION_REFERENCE,
    "requirements.txt",
    "requirements-dev.txt",
    "package.json",
    "package-lock.json",
)
ALLOWED_OPERATIONS = (
    "local_contract_validation",
    "azure_resource_manager_read",
    "local_attempt_receipt_write",
    "local_sanitized_observation_write",
)
FORBIDDEN_OPERATIONS = (
    "azure_mutation",
    "registry_access",
    "keychain_access",
    "public_url_access",
    "ai_access",
)
PACKAGE_KEYS = {
    "allowed_operations",
    "arm",
    "attempt_schema",
    "authorization_id",
    "continuation",
    "control_sha256",
    "desired_projection_sha256",
    "expires_at",
    "forbidden_operations",
    "issued_at",
    "repository",
    "schema_version",
    "toolchain",
}
ARM_LIMITS = {
    "allowed_http_methods": ["GET"],
    "api_version": "2024-03-01",
    "host": "management.azure.com",
    "max_page_bytes": 1_000_000,
    "max_pages_per_collection": 5,
    "max_total_requests": 30,
    "max_total_response_bytes": 8_000_000,
    "request_retry_limit": 0,
    "request_timeout_seconds": 30,
}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
GIT_SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9._/-]{1,255}")
BICEP_VERSION_PATTERN = re.compile(
    r"Bicep CLI version (?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?:\s|$)"
)


def _invalid(
    code: str = "diagnostic_package_invalid",
) -> DeployedReleaseDiagnosticInvalid:
    return DeployedReleaseDiagnosticInvalid(code, "local", "local")


def _reference(value: object) -> str:
    if not isinstance(value, str) or REFERENCE_PATTERN.fullmatch(value) is None:
        raise _invalid()
    logical = PurePosixPath(value)
    if logical.is_absolute() or "." in logical.parts or ".." in logical.parts:
        raise _invalid()
    return value


def _inside_project(project_root: Path, relative_path: str) -> Path:
    logical = PurePosixPath(_reference(relative_path))
    try:
        root = project_root.resolve(strict=True)
        path = (root / Path(*logical.parts)).resolve(strict=True)
    except OSError as error:
        raise _invalid("diagnostic_control_drift") from error
    if not path.is_relative_to(root) or not path.is_file():
        raise _invalid("diagnostic_control_drift")
    return path


def _module_path(project_root: Path, module: str) -> tuple[str, Path] | None:
    if not (module == "scripts" or module.startswith("scripts.")) and not (
        module == "src" or module.startswith("src.")
    ):
        return None
    stem = Path(*module.split("."))
    candidates = (stem.with_suffix(".py"), stem / "__init__.py")
    for candidate in candidates:
        absolute = project_root / candidate
        if absolute.is_file():
            return candidate.as_posix(), absolute
    raise _invalid("diagnostic_control_drift")


def _local_imports(path: Path, project_root: Path) -> set[str]:
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (OSError, SyntaxError, UnicodeError) as error:
        raise _invalid("diagnostic_control_drift") from error
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise _invalid("diagnostic_control_drift")
            if node.module:
                modules.add(node.module)
        elif isinstance(node, ast.Call):
            is_dynamic_import = (
                isinstance(node.func, ast.Name) and node.func.id == "__import__"
            ) or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            )
            if is_dynamic_import and node.args:
                requested = node.args[0]
                if not isinstance(requested, ast.Constant) or not isinstance(
                    requested.value, str
                ):
                    raise _invalid("diagnostic_control_drift")
                if requested.value.startswith("."):
                    raise _invalid("diagnostic_control_drift")
                modules.add(requested.value)
    result: set[str] = set()
    for module in modules:
        resolved = _module_path(project_root, module)
        if resolved is not None:
            result.add(resolved[0])
    return result


def discover_control_paths(
    *,
    project_root: Path = PROJECT_ROOT,
    entrypoints: Sequence[str] = D3_ENTRYPOINTS,
    bound_data_paths: Sequence[str] = BOUND_DATA_PATHS,
) -> tuple[str, ...]:
    if not entrypoints or not bound_data_paths:
        raise _invalid("diagnostic_control_drift")
    pending = list(entrypoints)
    discovered: set[str] = set()
    while pending:
        relative = _reference(pending.pop())
        if relative in discovered:
            continue
        path = _inside_project(project_root, relative)
        discovered.add(relative)
        for imported in _local_imports(path, project_root):
            if imported not in discovered:
                pending.append(imported)
    for relative in bound_data_paths:
        normalized = _reference(relative)
        _inside_project(project_root, normalized)
        discovered.add(normalized)
    if not discovered:
        raise _invalid("diagnostic_control_drift")
    return tuple(sorted(discovered))


def _control_sha256() -> dict[str, str]:
    result: dict[str, str] = {}
    for relative in discover_control_paths():
        try:
            result[relative] = hashlib.sha256(
                _inside_project(PROJECT_ROOT, relative).read_bytes()
            ).hexdigest()
        except OSError as error:
            raise _invalid("diagnostic_control_drift") from error
    return result


def _run_text(
    command: list[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    timeout: int = 30,
) -> str:
    try:
        completed = runner(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid("diagnostic_toolchain_drift") from error
    if completed.returncode != 0 or not isinstance(completed.stdout, str):
        raise _invalid("diagnostic_toolchain_drift")
    return completed.stdout.strip()


def _repository_state(
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    def git(*arguments: str) -> str:
        try:
            completed = runner(
                ["git", *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise _invalid("diagnostic_repository_drift") from error
        if completed.returncode != 0 or not isinstance(completed.stdout, str):
            raise _invalid("diagnostic_repository_drift")
        return completed.stdout.strip()

    branch = git("branch", "--show-current")
    head_sha = git("rev-parse", "HEAD")
    tree_sha = git("rev-parse", "HEAD^{tree}")
    status = git("status", "--porcelain=v1", "--untracked-files=no")
    if (
        branch != AUTHORIZED_BRANCH
        or GIT_SHA_PATTERN.fullmatch(head_sha) is None
        or GIT_SHA_PATTERN.fullmatch(tree_sha) is None
        or status
    ):
        raise _invalid("diagnostic_repository_drift")
    return {
        "branch": branch,
        "head_sha": head_sha,
        "tracked_clean_required": True,
        "tree_sha": tree_sha,
    }


def _toolchain_state(
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, str]:
    python_version = _run_text(
        [str(PROJECT_ROOT / ".venv/bin/python"), "--version"], runner=runner
    )
    azure_source = _run_text(["az", "version", "--output", "json"], runner=runner)
    bicep_source = _run_text(["az", "bicep", "version"], runner=runner)
    try:
        azure = json.loads(azure_source, object_pairs_hook=unique_object)
        bicep_match = BICEP_VERSION_PATTERN.search(bicep_source)
        extensions = azure["extensions"]
        result = {
            "azure_cli": azure["azure-cli"],
            "bicep": bicep_match.group("version") if bicep_match else "",
            "containerapp_extension_observed": extensions["containerapp"],
            "python": python_version,
        }
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise _invalid("diagnostic_toolchain_drift") from error
    if not all(isinstance(value, str) and value for value in result.values()):
        raise _invalid("diagnostic_toolchain_drift")
    return result


def _arm_paths(continuation: Mapping[str, Any]) -> list[str]:
    try:
        target = continuation["target"]
        prefix = (
            f"/subscriptions/{target['subscription_id']}/resourceGroups/"
            f"{target['resource_group']}/providers/Microsoft.App"
        )
        application = f"{prefix}/containerApps/{target['application']}"
        paths = [application, f"{application}/revisions"]
        for key in (
            "prepare_job",
            "seed_job",
            "session_maintenance_job",
            "storage_maintenance_job",
        ):
            job = f"{prefix}/jobs/{target[key]}"
            paths.extend((job, f"{job}/executions"))
    except (KeyError, TypeError) as error:
        raise _invalid() from error
    if len(paths) != 10 or len(set(paths)) != 10:
        raise _invalid()
    return paths


def _identity(
    authorization_id: object, issued_at: object, expires_at: object
) -> tuple[str, str, str]:
    if not all(
        isinstance(value, str) for value in (authorization_id, issued_at, expires_at)
    ):
        raise _invalid()
    try:
        parsed_uuid = UUID(authorization_id)
    except (ValueError, AttributeError) as error:
        raise _invalid() from error
    issued = parse_utc(issued_at)
    expires = parse_utc(expires_at)
    if (
        str(parsed_uuid) != authorization_id
        or utc_text(issued) != issued_at
        or utc_text(expires) != expires_at
        or expires <= issued
        or expires - issued > timedelta(hours=24)
    ):
        raise _invalid()
    return authorization_id, issued_at, expires_at


def _validate_desired_projection(
    desired_projection: Mapping[str, Any], continuation_sha256: str
) -> None:
    projection = assert_exact_keys(
        desired_projection,
        {"application", "continuation_sha256", "jobs", "schema_version"},
        code="diagnostic_bicep_projection_invalid",
    )
    if (
        projection["schema_version"] != PROJECTION_SCHEMA
        or projection["continuation_sha256"] != continuation_sha256
        or not isinstance(projection["application"], Mapping)
        or not isinstance(projection["jobs"], Mapping)
    ):
        raise _invalid("diagnostic_bicep_projection_invalid")


def build_deployed_release_diagnostic_package(
    *,
    continuation: Mapping[str, Any],
    continuation_reference: str,
    continuation_sha256: str,
    desired_projection: Mapping[str, Any],
    authorization_id: str,
    issued_at: str,
    expires_at: str,
    git_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    command_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    reference = _reference(continuation_reference)
    if SHA256_PATTERN.fullmatch(continuation_sha256) is None:
        raise _invalid()
    _identity(authorization_id, issued_at, expires_at)
    _validate_desired_projection(desired_projection, continuation_sha256)
    package = {
        "allowed_operations": list(ALLOWED_OPERATIONS),
        "arm": {
            **ARM_LIMITS,
            "allowed_resource_paths": _arm_paths(continuation),
        },
        "attempt_schema": ATTEMPT_SCHEMA,
        "authorization_id": authorization_id,
        "continuation": {
            "reference": reference,
            "sha256": continuation_sha256,
        },
        "control_sha256": _control_sha256(),
        "desired_projection_sha256": canonical_sha256(desired_projection),
        "expires_at": expires_at,
        "forbidden_operations": list(FORBIDDEN_OPERATIONS),
        "issued_at": issued_at,
        "repository": _repository_state(git_runner),
        "schema_version": PACKAGE_SCHEMA,
        "toolchain": _toolchain_state(command_runner),
    }
    if not package["control_sha256"] or SECRET_PATTERN.search(
        json.dumps(package, sort_keys=True)
    ):
        raise _invalid("diagnostic_control_drift")
    return package


def write_deployed_release_diagnostic_package(
    path: Path, package: Mapping[str, Any]
) -> str:
    document = (
        HEADER
        + "\n\n```json\n"
        + json.dumps(package, indent=2, sort_keys=True)
        + "\n```\n"
    ).encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(document)
            stream.flush()
            os.fsync(stream.fileno())
        if stat.S_IMODE(path.stat().st_mode) != 0o600:
            raise _invalid()
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return hashlib.sha256(document).hexdigest()


def _load_document(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or not 0 < metadata.st_size <= 4_000_000
        ):
            raise _invalid()
        source = path.read_text(encoding="utf-8")
    except OSError as error:
        raise _invalid() from error
    match = re.fullmatch(
        re.escape(HEADER) + r"\n\n```json\n(?P<payload>.*)\n```\n?",
        source,
        flags=re.DOTALL,
    )
    if match is None:
        raise _invalid()
    try:
        package = json.loads(match.group("payload"), object_pairs_hook=unique_object)
    except (ValueError, json.JSONDecodeError) as error:
        raise _invalid() from error
    return assert_exact_keys(package, PACKAGE_KEYS, code="diagnostic_package_invalid")


def _validate_package_shape(package: Mapping[str, Any]) -> None:
    repository = assert_exact_keys(
        package["repository"],
        {"branch", "head_sha", "tracked_clean_required", "tree_sha"},
        code="diagnostic_package_invalid",
    )
    continuation = assert_exact_keys(
        package["continuation"],
        {"reference", "sha256"},
        code="diagnostic_package_invalid",
    )
    toolchain = assert_exact_keys(
        package["toolchain"],
        {"azure_cli", "bicep", "containerapp_extension_observed", "python"},
        code="diagnostic_package_invalid",
    )
    controls = package["control_sha256"]
    arm = package["arm"]
    if (
        package["schema_version"] != PACKAGE_SCHEMA
        or package["attempt_schema"] != ATTEMPT_SCHEMA
        or package["allowed_operations"] != list(ALLOWED_OPERATIONS)
        or package["forbidden_operations"] != list(FORBIDDEN_OPERATIONS)
        or repository["branch"] != AUTHORIZED_BRANCH
        or repository["tracked_clean_required"] is not True
        or GIT_SHA_PATTERN.fullmatch(str(repository["head_sha"])) is None
        or GIT_SHA_PATTERN.fullmatch(str(repository["tree_sha"])) is None
        or SHA256_PATTERN.fullmatch(str(continuation["sha256"])) is None
        or SHA256_PATTERN.fullmatch(str(package["desired_projection_sha256"])) is None
        or not isinstance(controls, dict)
        or not controls
        or any(
            not isinstance(path, str) or SHA256_PATTERN.fullmatch(str(digest)) is None
            for path, digest in controls.items()
        )
        or not all(isinstance(value, str) and value for value in toolchain.values())
        or not isinstance(arm, dict)
    ):
        raise _invalid()
    _reference(continuation["reference"])
    _identity(package["authorization_id"], package["issued_at"], package["expires_at"])


def load_deployed_release_diagnostic_package(
    path: Path,
    *,
    continuation_path: Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    package = _load_document(path)
    _validate_package_shape(package)
    observed_at = now.astimezone(UTC) if now is not None else datetime.now(UTC)
    if observed_at >= parse_utc(package["expires_at"]):
        raise _invalid("diagnostic_package_expired")
    continuation_authority = package["continuation"]
    reference = continuation_authority["reference"]
    try:
        expected_path = (PROJECT_ROOT / reference).resolve(strict=True)
        supplied_path = continuation_path.resolve(strict=True)
        continuation_digest = hashlib.sha256(supplied_path.read_bytes()).hexdigest()
    except OSError as error:
        raise _invalid() from error
    if expected_path != supplied_path or not hmac.compare_digest(
        continuation_digest, continuation_authority["sha256"]
    ):
        raise _invalid("diagnostic_control_drift")
    continuation = load_deployed_release_continuation(
        supplied_path,
        expected_sha256=continuation_authority["sha256"],
    )
    desired_projection = compile_desired_projection(
        PROJECT_ROOT / "infra/modules/app.bicep",
        continuation,
        continuation_sha256=continuation_authority["sha256"],
    )
    if not hmac.compare_digest(
        canonical_sha256(desired_projection), package["desired_projection_sha256"]
    ):
        raise _invalid("diagnostic_bicep_projection_invalid")
    if package["repository"] != _repository_state(subprocess.run):
        raise _invalid("diagnostic_repository_drift")
    if package["toolchain"] != _toolchain_state(subprocess.run):
        raise _invalid("diagnostic_toolchain_drift")
    current_controls = _control_sha256()
    if set(current_controls) != set(package["control_sha256"]) or any(
        not hmac.compare_digest(current_controls[key], package["control_sha256"][key])
        for key in current_controls
    ):
        raise _invalid("diagnostic_control_drift")
    expected_arm = {**ARM_LIMITS, "allowed_resource_paths": _arm_paths(continuation)}
    if package["arm"] != expected_arm:
        raise _invalid()
    if SECRET_PATTERN.search(json.dumps(package, sort_keys=True)):
        raise _invalid()
    return dict(package)


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--continuation", type=Path, required=True)
    parser.add_argument("--continuation-reference", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expires-hours", type=int, choices=(24,), required=True)
    options = parser.parse_args(arguments)
    try:
        continuation_bytes = options.continuation.read_bytes()
        continuation_sha256 = hashlib.sha256(continuation_bytes).hexdigest()
        continuation = load_deployed_release_continuation(
            options.continuation, expected_sha256=continuation_sha256
        )
        desired_projection = compile_desired_projection(
            PROJECT_ROOT / "infra/modules/app.bicep",
            continuation,
            continuation_sha256=continuation_sha256,
        )
        issued = datetime.now(UTC).replace(microsecond=0)
        expires = issued + timedelta(hours=options.expires_hours)
        authorization_id = str(uuid4())
        package = build_deployed_release_diagnostic_package(
            continuation=continuation,
            continuation_reference=options.continuation_reference,
            continuation_sha256=continuation_sha256,
            desired_projection=desired_projection,
            authorization_id=authorization_id,
            issued_at=utc_text(issued),
            expires_at=utc_text(expires),
        )
        options.output.parent.mkdir(parents=True, exist_ok=True)
        digest = write_deployed_release_diagnostic_package(options.output, package)
    except (OSError, DeployedReleaseDiagnosticInvalid) as error:
        code = (
            error.code
            if isinstance(error, DeployedReleaseDiagnosticInvalid)
            else "diagnostic_package_invalid"
        )
        print(code)
        return 1
    print(f"package_path={options.output.resolve()}")
    print(f"authorization_id={authorization_id}")
    print(f"expires_at={utc_text(expires)}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
