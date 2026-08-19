#!/usr/bin/env python3
"""Run admin-AI release entrypoints only from one exact committed snapshot."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping, Sequence


RUNTIME_MARKER = ".admin-ai-exact-runtime.json"
RUNTIME_MARKER_SCHEMA = "newcaostone.admin-ai-exact-runtime.v1"
RUNTIME_DEPENDENCY_MARKER = ".admin-ai-runtime-dependencies.json"
RUNTIME_DEPENDENCY_SCHEMA = "newcaostone.admin-ai-runtime-dependencies.v1"
TRUSTED_RUNTIME_DEPENDENCY_MANIFEST = Path(
    "scripts/admin_ai_runtime_dependencies.json"
)
RUNTIME_DEPENDENCY_DISTRIBUTIONS = (
    "anyio",
    "azure-core",
    "azure-identity",
    "certifi",
    "cffi",
    "charset-normalizer",
    "cryptography",
    "h11",
    "httpcore",
    "httpx",
    "idna",
    "msal",
    "msal-extensions",
    "pycparser",
    "pyjwt",
    "requests",
    "typing-extensions",
    "urllib3",
)
ENTRYPOINTS = {
    "authority-refresh": "scripts/refresh_admin_ai_current_authority.py",
    "build": "scripts/build_admin_ai_candidate.py",
    "package": "scripts/create_admin_ai_release_package.py",
    "release": "scripts/run_admin_ai_release.py",
}
R19_PACKAGE_PATH = Path(
    ".tmp/LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R19_2026-08-17.json"
)
R19_PACKAGE_SHA256 = (
    "9c35ae6a39e6db86b021b9938b966492046f0e745111dab2c1dd8bedbf3ddae9"
)
R19_RECEIPT_PATH = Path(".tmp/AI_ENABLEMENT_RECEIPT_R19_2026-08-17.json")
R19_RECEIPT_SHA256 = (
    "fdec28661cb43268526b3c0aa34944b2a472191dc9a362035acc3c8a446f9cb1"
)
SAFE_ENVIRONMENT_NAMES = (
    "AZURE_CONFIG_DIR",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "TMPDIR",
)
_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_ALLOWED_PROJECT_ROOT_ENTRIES = frozenset(
    {
        ".dockerignore",
        ".gitignore",
        "Dockerfile",
        "alembic",
        "alembic.ini",
        "api",
        "deliverables",
        "docs",
        "frontend",
        "infra",
        "package-lock.json",
        "package.json",
        "release",
        "requirements-dev.txt",
        "requirements.txt",
        "scripts",
        "src",
        "tests",
    }
)


class AdminAIExactRuntimeInvalid(RuntimeError):
    """The exact committed runtime could not be established."""


def _invalid(code: str) -> AdminAIExactRuntimeInvalid:
    return AdminAIExactRuntimeInvalid(code)


def _git(project_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", *arguments],
            cwd=project_root,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
            shell=False,
            env={
                name: value
                for name in SAFE_ENVIRONMENT_NAMES
                if isinstance((value := os.environ.get(name)), str)
            },
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise _invalid("runtime_repository_unavailable") from error
    if completed.returncode != 0 or not isinstance(completed.stdout, str):
        raise _invalid("runtime_repository_unavailable")
    return completed.stdout.strip()


def _canonical_directory(path: Path, *, code: str) -> Path:
    """Resolve one existing directory once and retain only its real path."""

    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.lstat()
    except OSError as error:
        raise _invalid(code) from error
    if resolved.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise _invalid(code)
    return resolved


def _copy_archive_member(
    archive: tarfile.TarFile,
    member: tarfile.TarInfo,
    destination: Path,
) -> None:
    raw_path = PurePosixPath(member.name)
    if member.name.startswith("/") or not raw_path.parts or ".." in raw_path.parts:
        raise _invalid("runtime_archive_invalid")
    target = destination.joinpath(*raw_path.parts)
    if member.isdir():
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        return
    if not member.isfile() or member.mode & ~0o777:
        raise _invalid("runtime_archive_invalid")
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    extracted = archive.extractfile(member)
    if extracted is None:
        raise _invalid("runtime_archive_invalid")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(target, flags, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        payload = extracted.read(member.size + 1)
        if len(payload) != member.size:
            raise _invalid("runtime_archive_invalid")
        stream.write(payload)
    target.chmod(0o500 if member.mode & stat.S_IXUSR else 0o400)


def _materialize_exact_commit(
    project_root: Path,
    *,
    source_sha: str,
    destination: Path,
) -> None:
    with tempfile.TemporaryFile() as archive_stream:
        try:
            subprocess.run(
                ["git", "archive", "--format=tar", source_sha, "--", "."],
                cwd=project_root,
                check=True,
                stdout=archive_stream,
                stderr=subprocess.PIPE,
                timeout=120,
                shell=False,
                env={
                    name: value
                    for name in SAFE_ENVIRONMENT_NAMES
                    if isinstance((value := os.environ.get(name)), str)
                },
            )
            archive_stream.seek(0)
            with tarfile.open(fileobj=archive_stream, mode="r:") as archive:
                for member in archive.getmembers():
                    _copy_archive_member(archive, member, destination)
        except AdminAIExactRuntimeInvalid:
            raise
        except (OSError, subprocess.SubprocessError, tarfile.TarError) as error:
            raise _invalid("runtime_archive_invalid") from error


def _reject_materialized_import_shadows(snapshot: Path) -> None:
    scripts = snapshot / "scripts"
    try:
        named_shadows = (
            snapshot / "sitecustomize.py",
            snapshot / "usercustomize.py",
            scripts / "sitecustomize.py",
            scripts / "usercustomize.py",
        )
        executable_shadow = scripts.is_dir() and any(
            path.is_file() or path.is_symlink()
            for path in scripts.rglob("*")
            if path.suffix.lower() in {".pyc", ".pyo", ".pth", ".so", ".pyd"}
        )
        unexpected_root_entry = any(
            path.name not in _ALLOWED_PROJECT_ROOT_ENTRIES
            for path in snapshot.iterdir()
        )
        if unexpected_root_entry or executable_shadow or any(
            path.exists() or path.is_symlink() for path in named_shadows
        ):
            raise _invalid("runtime_import_shadow")
    except AdminAIExactRuntimeInvalid:
        raise
    except OSError as error:
        raise _invalid("runtime_archive_invalid") from error


def _write_marker(destination: Path, *, source_sha: str, source_tree: str) -> None:
    marker = destination / RUNTIME_MARKER
    payload = json.dumps(
        {
            "schema_version": RUNTIME_MARKER_SCHEMA,
            "source_sha": source_sha,
            "source_tree": source_tree,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(marker, flags, 0o400)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(payload)
    marker.chmod(0o400)


def _canonical_distribution_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).casefold()


def _validate_runtime_dependency_manifest(
    value: object,
    *,
    distribution_names: Sequence[str] | None = RUNTIME_DEPENDENCY_DISTRIBUTIONS,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema_version",
        "python_cache_tag",
        "python_version",
        "distributions",
        "entries",
        "sha256",
    }:
        raise _invalid("runtime_dependency_manifest_invalid")
    cache_tag = value["python_cache_tag"]
    python_version = value["python_version"]
    raw_distributions = value["distributions"]
    raw_entries = value["entries"]
    if (
        value["schema_version"] != RUNTIME_DEPENDENCY_SCHEMA
        or not isinstance(cache_tag, str)
        or re.fullmatch(r"cpython-[0-9]{2,3}", cache_tag) is None
        or not isinstance(python_version, str)
        or re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", python_version) is None
        or not isinstance(raw_distributions, list)
        or not isinstance(raw_entries, list)
        or len(raw_entries) > 5000
    ):
        raise _invalid("runtime_dependency_manifest_invalid")
    distributions: list[dict[str, str]] = []
    for item in raw_distributions:
        if (
            not isinstance(item, Mapping)
            or set(item) != {"name", "version"}
            or not isinstance(item["name"], str)
            or _canonical_distribution_name(item["name"]) != item["name"]
            or not isinstance(item["version"], str)
            or not item["version"]
            or len(item["version"]) > 64
        ):
            raise _invalid("runtime_dependency_manifest_invalid")
        distributions.append({"name": item["name"], "version": item["version"]})
    if distributions != sorted(distributions, key=lambda item: item["name"]):
        raise _invalid("runtime_dependency_manifest_invalid")
    names = [item["name"] for item in distributions]
    if len(names) != len(set(names)):
        raise _invalid("runtime_dependency_manifest_invalid")
    if distribution_names is not None and names != sorted(
        _canonical_distribution_name(name) for name in distribution_names
    ):
        raise _invalid("runtime_dependency_manifest_invalid")
    entries: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    total_size = 0
    for item in raw_entries:
        if not isinstance(item, Mapping) or set(item) != {
            "distribution",
            "path",
            "mode",
            "size",
            "sha256",
        }:
            raise _invalid("runtime_dependency_manifest_invalid")
        path = item["path"]
        parsed = PurePosixPath(path) if isinstance(path, str) else None
        if (
            item["distribution"] not in names
            or parsed is None
            or parsed.is_absolute()
            or not parsed.parts
            or ".." in parsed.parts
            or path in seen_paths
            or not isinstance(item["mode"], int)
            or item["mode"] < 0
            or item["mode"] > 0o777
            or item["mode"] & 0o022
            or not isinstance(item["size"], int)
            or item["size"] < 0
            or item["size"] > 64 * 1024 * 1024
            or not isinstance(item["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) is None
        ):
            raise _invalid("runtime_dependency_manifest_invalid")
        seen_paths.add(path)
        total_size += item["size"]
        entries.append(dict(item))
    if total_size > 512 * 1024 * 1024 or entries != sorted(
        entries,
        key=lambda item: (item["distribution"], item["path"]),
    ):
        raise _invalid("runtime_dependency_manifest_invalid")
    canonical = json.dumps(
        {
            "schema_version": RUNTIME_DEPENDENCY_SCHEMA,
            "python_cache_tag": cache_tag,
            "python_version": python_version,
            "distributions": distributions,
            "entries": entries,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    digest = hashlib.sha256(canonical).hexdigest()
    if value["sha256"] != digest:
        raise _invalid("runtime_dependency_manifest_invalid")
    return {
        "schema_version": RUNTIME_DEPENDENCY_SCHEMA,
        "python_cache_tag": cache_tag,
        "python_version": python_version,
        "distributions": distributions,
        "entries": entries,
        "sha256": digest,
    }


def capture_runtime_dependency_manifest(
    site_packages: Path,
    *,
    distribution_names: Sequence[str] = RUNTIME_DEPENDENCY_DISTRIBUTIONS,
) -> dict[str, object]:
    """Hash the complete installed file set for the live controller closure."""

    expected_names = sorted(
        _canonical_distribution_name(name) for name in distribution_names
    )
    try:
        discovered = {
            _canonical_distribution_name(str(distribution.metadata["Name"])): distribution
            for distribution in importlib.metadata.distributions(
                path=[str(site_packages)]
            )
            if distribution.metadata["Name"] is not None
        }
    except (OSError, TypeError) as error:
        raise _invalid("runtime_dependency_unavailable") from error
    if any(name not in discovered for name in expected_names):
        raise _invalid("runtime_dependency_unavailable")
    distributions: list[dict[str, str]] = []
    entries: list[dict[str, object]] = []
    seen_paths: set[str] = set()
    try:
        for name in expected_names:
            distribution = discovered[name]
            version = distribution.version
            if not isinstance(version, str) or not version:
                raise _invalid("runtime_dependency_unavailable")
            distributions.append({"name": name, "version": version})
            for package_path in distribution.files or ():
                parsed = PurePosixPath(str(package_path))
                if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
                    continue
                relative = parsed.as_posix()
                if relative in seen_paths:
                    raise _invalid("runtime_dependency_unavailable")
                source = site_packages.joinpath(*parsed.parts)
                metadata = source.lstat()
                if not stat.S_ISREG(metadata.st_mode) or source.is_symlink():
                    raise _invalid("runtime_dependency_unavailable")
                mode = stat.S_IMODE(metadata.st_mode)
                if mode & 0o022:
                    raise _invalid("runtime_dependency_unavailable")
                digest = hashlib.sha256(source.read_bytes()).hexdigest()
                seen_paths.add(relative)
                entries.append(
                    {
                        "distribution": name,
                        "path": relative,
                        "mode": mode,
                        "size": metadata.st_size,
                        "sha256": digest,
                    }
                )
    except AdminAIExactRuntimeInvalid:
        raise
    except OSError as error:
        raise _invalid("runtime_dependency_unavailable") from error
    entries.sort(key=lambda item: (item["distribution"], item["path"]))
    base = {
        "schema_version": RUNTIME_DEPENDENCY_SCHEMA,
        "python_cache_tag": sys.implementation.cache_tag,
        "python_version": (
            f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        ),
        "distributions": distributions,
        "entries": entries,
    }
    canonical = json.dumps(base, sort_keys=True, separators=(",", ":")).encode()
    return _validate_runtime_dependency_manifest(
        {**base, "sha256": hashlib.sha256(canonical).hexdigest()},
        distribution_names=distribution_names,
    )


def validate_trusted_runtime_dependencies(
    site_packages: Path,
    trusted_path: Path,
    *,
    distribution_names: Sequence[str] = RUNTIME_DEPENDENCY_DISTRIBUTIONS,
) -> dict[str, object]:
    """Require installed dependency bytes to match one immutable manifest."""

    try:
        metadata = trusted_path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or trusted_path.is_symlink()
            or stat.S_IMODE(metadata.st_mode) & 0o022
            or metadata.st_size > 4 * 1024 * 1024
        ):
            raise _invalid("runtime_dependency_trust_invalid")
        raw = json.loads(trusted_path.read_text(encoding="utf-8"))
        trusted = _validate_runtime_dependency_manifest(
            raw,
            distribution_names=distribution_names,
        )
        observed = capture_runtime_dependency_manifest(
            site_packages,
            distribution_names=distribution_names,
        )
    except AdminAIExactRuntimeInvalid:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _invalid("runtime_dependency_trust_invalid") from error
    if observed != trusted:
        raise _invalid("runtime_dependency_trust_mismatch")
    return trusted


def materialize_runtime_dependencies(
    site_packages: Path,
    destination: Path,
    *,
    expected: object,
    distribution_names: Sequence[str] | None = None,
) -> dict[str, object]:
    """Copy only package-bound dependency bytes into one private directory."""

    validated = _validate_runtime_dependency_manifest(
        expected,
        distribution_names=distribution_names,
    )
    if (
        validated["python_cache_tag"] != sys.implementation.cache_tag
        or validated["python_version"]
        != f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    ):
        raise _invalid("runtime_dependency_python_mismatch")
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    for entry in validated["entries"]:
        source = site_packages.joinpath(*PurePosixPath(entry["path"]).parts)
        target = destination.joinpath(*PurePosixPath(entry["path"]).parts)
        try:
            observed = _copy_regular_file(
                source,
                target,
                required_mode=entry["mode"],
                destination_mode=0o500 if entry["mode"] & 0o111 else 0o400,
                expected_sha256=entry["sha256"],
                allow_empty=True,
            )
        except AdminAIExactRuntimeInvalid as error:
            if str(error) == "runtime_input_hash_mismatch":
                raise _invalid("runtime_dependency_hash_mismatch") from error
            raise _invalid("runtime_dependency_unavailable") from error
        if observed != entry["sha256"]:
            raise _invalid("runtime_dependency_hash_mismatch")
    return validated


def _write_runtime_dependency_marker(
    destination: Path,
    manifest: Mapping[str, object],
) -> None:
    marker = destination / RUNTIME_DEPENDENCY_MARKER
    payload = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(marker, flags, 0o400)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        marker.chmod(0o400)
    except OSError as error:
        raise _invalid("runtime_dependency_unavailable") from error


def _open_release_tty():
    """Open only the controlling terminal for the release child prompt."""

    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open("/dev/tty", flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISCHR(metadata.st_mode) or not os.isatty(descriptor):
            raise _invalid("runtime_release_tty_unavailable")
        stream = os.fdopen(descriptor, "r", encoding="utf-8")
        descriptor = None
        if not stream.isatty():
            stream.close()
            raise _invalid("runtime_release_tty_unavailable")
        return stream
    except AdminAIExactRuntimeInvalid:
        raise
    except OSError as error:
        raise _invalid("runtime_release_tty_unavailable") from error
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass


def load_runtime_dependency_manifest(project_root: Path) -> dict[str, object] | None:
    """Load the private runtime dependency marker without importing a dependency."""

    marker = project_root / RUNTIME_DEPENDENCY_MARKER
    if not marker.exists():
        return None
    try:
        metadata = marker.lstat()
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _invalid("runtime_dependency_manifest_invalid") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or marker.is_symlink()
        or stat.S_IMODE(metadata.st_mode) != 0o400
    ):
        raise _invalid("runtime_dependency_manifest_invalid")
    return _validate_runtime_dependency_manifest(value)


def _runtime_site_packages(python_executable: str) -> Path:
    try:
        executable = Path(python_executable).absolute()
        running_executable = Path(sys.executable).absolute()
        if (
            not executable.is_absolute()
            or not os.path.samefile(executable, running_executable)
        ):
            raise _invalid("runtime_python_invalid")
        environment_root = executable.parent.parent
        configuration = environment_root / "pyvenv.cfg"
        configuration_metadata = configuration.lstat()
        encoded = configuration.read_bytes()
        if (
            environment_root.is_symlink()
            or configuration.is_symlink()
            or not stat.S_ISREG(configuration_metadata.st_mode)
            or len(encoded) > 4096
        ):
            raise _invalid("runtime_python_invalid")
        values: dict[str, str] = {}
        for raw_line in encoded.decode("utf-8").splitlines():
            key, separator, value = raw_line.partition("=")
            normalized = key.strip().casefold()
            if not separator or not normalized or normalized in values:
                raise _invalid("runtime_python_invalid")
            values[normalized] = value.strip()
        version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        if (
            values.get("include-system-site-packages", "").casefold() != "false"
            or values.get("version") != version
        ):
            raise _invalid("runtime_python_invalid")
        site_packages = (
            environment_root
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
            / "site-packages"
        )
        metadata = site_packages.lstat()
    except AdminAIExactRuntimeInvalid:
        raise
    except (OSError, TypeError, UnicodeError) as error:
        raise _invalid("runtime_dependency_unavailable") from error
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or site_packages.is_symlink()
    ):
        raise _invalid("runtime_dependency_unavailable")
    return site_packages


def _argument_value(arguments: Sequence[str], name: str) -> tuple[int, str]:
    try:
        index = arguments.index(name)
        value = arguments[index + 1]
    except (ValueError, IndexError) as error:
        raise _invalid("runtime_arguments_invalid") from error
    if not value or value.startswith("--") or arguments.count(name) != 1:
        raise _invalid("runtime_arguments_invalid")
    return index + 1, value


def _copy_regular_file(
    source: Path,
    destination: Path,
    *,
    required_mode: int,
    destination_mode: int,
    expected_sha256: str | None = None,
    allow_empty: bool = False,
) -> str:
    source_flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        source_flags |= os.O_NOFOLLOW
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        destination_flags |= os.O_NOFOLLOW
    digest = hashlib.sha256()
    try:
        source_descriptor = os.open(source, source_flags)
        with os.fdopen(source_descriptor, "rb") as source_stream:
            before = os.fstat(source_stream.fileno())
            if (
                not stat.S_ISREG(before.st_mode)
                or stat.S_IMODE(before.st_mode) != required_mode
                or (before.st_size <= 0 and not allow_empty)
            ):
                raise _invalid("runtime_input_invalid")
            destination_descriptor = os.open(
                destination,
                destination_flags,
                destination_mode,
            )
            with os.fdopen(destination_descriptor, "wb") as destination_stream:
                while chunk := source_stream.read(1024 * 1024):
                    digest.update(chunk)
                    destination_stream.write(chunk)
                destination_stream.flush()
                os.fsync(destination_stream.fileno())
            after = os.fstat(source_stream.fileno())
        if (
            (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        ):
            raise _invalid("runtime_input_changed")
        observed = digest.hexdigest()
        if expected_sha256 is not None and observed != expected_sha256:
            raise _invalid("runtime_input_hash_mismatch")
        destination.chmod(destination_mode)
        return observed
    except AdminAIExactRuntimeInvalid:
        raise
    except OSError as error:
        raise _invalid("runtime_input_invalid") from error


def _load_release_package_authority(
    path: Path,
    *,
    approved_sha256: str,
    source_sha: str,
) -> tuple[dict[str, object], str, dict[str, object]]:
    def unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise _invalid("runtime_package_invalid")
            result[key] = value
        return result

    if re.fullmatch(r"[0-9a-f]{64}", approved_sha256) is None:
        raise _invalid("runtime_package_invalid")
    try:
        encoded = path.read_bytes()
        package = json.loads(encoded, object_pairs_hook=unique)
        repository = package["repository"]
        runtime_dependencies = repository["runtime_dependency_manifest"]
        candidate = package["candidate"]
        artifact_path = candidate["artifact_path"]
        artifact_sha256 = candidate["artifact_sha256"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        if isinstance(error, AdminAIExactRuntimeInvalid):
            raise
        raise _invalid("runtime_package_invalid") from error
    if (
        not isinstance(package, dict)
        or not isinstance(repository, Mapping)
        or repository.get("source_sha") != source_sha
        or not isinstance(candidate, Mapping)
        or not isinstance(artifact_path, str)
        or PurePosixPath(artifact_path).is_absolute()
        or PurePosixPath(artifact_path).parts[:1] != (".tmp",)
        or ".." in PurePosixPath(artifact_path).parts
        or not isinstance(artifact_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", artifact_sha256) is None
        or hashlib.sha256(encoded).hexdigest() != approved_sha256
    ):
        raise _invalid("runtime_package_invalid")
    validated_dependencies = _validate_runtime_dependency_manifest(
        runtime_dependencies
    )
    return package, artifact_path, validated_dependencies


def _copy_runtime_inputs(
    mode: str,
    arguments: Sequence[str],
    *,
    project_root: Path,
    snapshot: Path,
    source_sha: str,
) -> tuple[list[str], dict[str, object] | None]:
    child_arguments = list(arguments)
    runtime_dependencies = None
    if mode == "authority-refresh":
        prohibited = {
            "--authority-output-root",
            "--r19-package",
            "--r19-receipt",
        }
        if prohibited.intersection(child_arguments):
            raise _invalid("runtime_arguments_invalid")
        package_target = snapshot / ".inputs" / "r19-package.json"
        receipt_target = snapshot / ".inputs" / "r19-receipt.json"
        _copy_regular_file(
            project_root / R19_PACKAGE_PATH,
            package_target,
            required_mode=0o600,
            destination_mode=0o400,
            expected_sha256=R19_PACKAGE_SHA256,
        )
        _copy_regular_file(
            project_root / R19_RECEIPT_PATH,
            receipt_target,
            required_mode=0o600,
            destination_mode=0o400,
            expected_sha256=R19_RECEIPT_SHA256,
        )
        child_arguments.extend(
            (
                "--r19-package",
                str(package_target),
                "--r19-receipt",
                str(receipt_target),
                "--authority-output-root",
                str(project_root),
            )
        )
    elif mode == "package":
        artifact_index, artifact_value = _argument_value(
            child_arguments, "--candidate-artifact"
        )
        artifact_source = Path(artifact_value).resolve(strict=True)
        try:
            artifact_relative = artifact_source.relative_to(project_root)
        except ValueError as error:
            raise _invalid("runtime_input_invalid") from error
        artifact_target = snapshot / artifact_relative
        _copy_regular_file(
            artifact_source,
            artifact_target,
            required_mode=0o400,
            destination_mode=0o400,
        )
        child_arguments[artifact_index] = str(artifact_target)
        if "--azure-authority-request" in child_arguments:
            authority_index, authority_value = _argument_value(
                child_arguments, "--azure-authority-request"
            )
            authority_source = Path(authority_value).resolve(strict=True)
            authority_target = snapshot / ".inputs" / "task10-authority.json"
            _copy_regular_file(
                authority_source,
                authority_target,
                required_mode=0o600,
                destination_mode=0o400,
            )
            child_arguments[authority_index] = str(authority_target)
        elif "--create-azure-authority-request" not in child_arguments:
            raise _invalid("runtime_arguments_invalid")
    elif mode == "release":
        package_index, package_value = _argument_value(child_arguments, "--package")
        approved_index, approved = _argument_value(
            child_arguments, "--approved-sha256"
        )
        del approved_index
        package_source = Path(package_value).resolve(strict=True)
        package, artifact_relative, runtime_dependencies = (
            _load_release_package_authority(
                package_source,
                approved_sha256=approved,
                source_sha=source_sha,
            )
        )
        package_target = snapshot / ".inputs" / "release-package.json"
        _copy_regular_file(
            package_source,
            package_target,
            required_mode=0o600,
            destination_mode=0o600,
            expected_sha256=approved,
        )
        artifact_source = project_root / artifact_relative
        artifact_target = snapshot / artifact_relative
        _copy_regular_file(
            artifact_source,
            artifact_target,
            required_mode=0o400,
            destination_mode=0o400,
            expected_sha256=str(package["candidate"]["artifact_sha256"]),
        )
        child_arguments[package_index] = str(package_target)
    return child_arguments, runtime_dependencies


def _make_read_only(root: Path) -> None:
    for directory in sorted(
        (path for path in root.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    root.chmod(0o500)


def load_exact_runtime_marker(project_root: Path) -> dict[str, str] | None:
    """Return a valid private-snapshot marker, or ``None`` outside a snapshot."""

    marker = project_root / RUNTIME_MARKER
    if not marker.exists():
        return None
    try:
        metadata = marker.lstat()
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _invalid("runtime_marker_invalid") from error
    if (
        not stat.S_ISREG(metadata.st_mode)
        or marker.is_symlink()
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or not isinstance(payload, Mapping)
        or set(payload) != {"schema_version", "source_sha", "source_tree"}
        or payload["schema_version"] != RUNTIME_MARKER_SCHEMA
        or not isinstance(payload["source_sha"], str)
        or _GIT_SHA.fullmatch(payload["source_sha"]) is None
        or not isinstance(payload["source_tree"], str)
        or _GIT_SHA.fullmatch(payload["source_tree"]) is None
    ):
        raise _invalid("runtime_marker_invalid")
    return {
        "source_sha": payload["source_sha"],
        "source_tree": payload["source_tree"],
    }


def run_from_exact_snapshot(
    mode: str,
    arguments: Sequence[str],
    *,
    project_root: Path,
    source_sha: str,
    environment: Mapping[str, str],
    python_executable: str,
) -> int:
    """Materialize one captured commit and run only its selected entrypoint bytes."""

    if mode not in ENTRYPOINTS:
        raise _invalid("runtime_mode_invalid")
    if _GIT_SHA.fullmatch(source_sha) is None:
        raise _invalid("runtime_source_invalid")
    project_root = _canonical_directory(
        project_root,
        code="runtime_repository_unavailable",
    )
    resolved_commit = _git(
        project_root,
        "rev-parse",
        "--verify",
        f"{source_sha}^{{commit}}",
    )
    if resolved_commit != source_sha:
        raise _invalid("runtime_source_invalid")
    source_tree = _git(project_root, "rev-parse", f"{source_sha}^{{tree}}")
    status = _git(
        project_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    )
    if (
        _GIT_SHA.fullmatch(source_tree) is None
        or status
    ):
        raise _invalid("runtime_repository_dirty")
    temporary_root = _canonical_directory(
        Path(tempfile.gettempdir()),
        code="runtime_temporary_root_invalid",
    )
    with tempfile.TemporaryDirectory(
        prefix="newcaostone-admin-ai-runtime-",
        dir=temporary_root,
    ) as raw:
        runtime_root = _canonical_directory(
            Path(raw),
            code="runtime_temporary_root_invalid",
        )
        try:
            runtime_metadata = runtime_root.lstat()
        except OSError as error:
            raise _invalid("runtime_temporary_root_invalid") from error
        if (
            runtime_root.parent != temporary_root
            or stat.S_IMODE(runtime_metadata.st_mode) & 0o077
        ):
            raise _invalid("runtime_temporary_root_invalid")
        snapshot = runtime_root / "source"
        snapshot.mkdir(mode=0o700)
        snapshot = _canonical_directory(
            snapshot,
            code="runtime_temporary_root_invalid",
        )
        if snapshot.parent != runtime_root:
            raise _invalid("runtime_temporary_root_invalid")
        _materialize_exact_commit(
            project_root,
            source_sha=source_sha,
            destination=snapshot,
        )
        _reject_materialized_import_shadows(snapshot)
        entrypoint = snapshot / ENTRYPOINTS[mode]
        try:
            metadata = entrypoint.lstat()
        except OSError as error:
            raise _invalid("runtime_entrypoint_invalid") from error
        if not stat.S_ISREG(metadata.st_mode) or entrypoint.is_symlink():
            raise _invalid("runtime_entrypoint_invalid")
        _write_marker(snapshot, source_sha=source_sha, source_tree=source_tree)
        child_arguments, approved_dependencies = _copy_runtime_inputs(
            mode,
            arguments,
            project_root=project_root,
            snapshot=snapshot,
            source_sha=source_sha,
        )
        site_packages = _runtime_site_packages(python_executable)
        trusted_dependencies: dict[str, object] | None = None
        if mode in {"authority-refresh", "package", "release"}:
            trusted_dependencies = validate_trusted_runtime_dependencies(
                site_packages,
                snapshot / TRUSTED_RUNTIME_DEPENDENCY_MANIFEST,
            )
        dependency_root: Path | None = None
        if mode in {"authority-refresh", "package"}:
            if trusted_dependencies is None:  # pragma: no cover - mode guard
                raise _invalid("runtime_dependency_trust_invalid")
            dependency_manifest = trusted_dependencies
            dependency_root = snapshot / ".runtime-dependencies"
            materialize_runtime_dependencies(
                site_packages,
                dependency_root,
                expected=dependency_manifest,
                distribution_names=RUNTIME_DEPENDENCY_DISTRIBUTIONS,
            )
            _write_runtime_dependency_marker(snapshot, dependency_manifest)
        elif mode == "release":
            if (
                approved_dependencies is None
                or trusted_dependencies is None
                or approved_dependencies != trusted_dependencies
            ):
                raise _invalid("runtime_dependency_manifest_invalid")
            dependency_root = snapshot / ".runtime-dependencies"
            dependency_manifest = materialize_runtime_dependencies(
                site_packages,
                dependency_root,
                expected=approved_dependencies,
                distribution_names=RUNTIME_DEPENDENCY_DISTRIBUTIONS,
            )
            _write_runtime_dependency_marker(snapshot, dependency_manifest)
        _make_read_only(snapshot)
        child_environment = {
            name: value
            for name in SAFE_ENVIRONMENT_NAMES
            if isinstance((value := environment.get(name)), str)
        }
        child_environment["BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT"] = str(snapshot)
        wrapper = (
            "import runpy,sys;"
            "dependency_root=sys.argv.pop(1);"
            "project_root=sys.argv.pop(1);"
            "entrypoint=sys.argv.pop(1);"
            "sys.path.insert(0,dependency_root) if dependency_root else None;"
            "sys.path.insert(0,project_root);"
            "runpy.run_path(entrypoint,run_name='__main__')"
        )
        release_tty = None
        try:
            if mode == "release":
                release_tty = _open_release_tty()
            completed = subprocess.run(
                [
                    python_executable,
                    "-I",
                    "-B",
                    "-S",
                    "-c",
                    wrapper,
                    str(dependency_root) if dependency_root is not None else "",
                    str(snapshot),
                    str(entrypoint),
                    *child_arguments,
                ],
                cwd=project_root,
                check=False,
                env=child_environment,
                stdin=release_tty,
                timeout=None,
                shell=False,
            )
        except AdminAIExactRuntimeInvalid:
            raise
        except (OSError, subprocess.SubprocessError) as error:
            raise _invalid("runtime_entrypoint_failed") from error
        finally:
            if release_tty is not None:
                release_tty.close()
        return completed.returncode


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "Run from the bizpulse project directory with shell pipefail "
            "enabled, and load this committed bootstrap with git show "
            "'<source-sha>:./scripts/admin_ai_exact_runtime.py'."
        ),
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("mode", choices=tuple(ENTRYPOINTS))
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    options = parser.parse_args(arguments)
    if (
        not sys.flags.isolated
        or not sys.dont_write_bytecode
        or not sys.flags.no_site
    ):
        print("admin_ai_exact_runtime=failed")
        print("reason=runtime_isolation_required")
        return 1
    if __file__ != "<stdin>":
        print("admin_ai_exact_runtime=failed")
        print("reason=runtime_bootstrap_not_committed")
        return 1
    try:
        return run_from_exact_snapshot(
            options.mode,
            options.arguments,
            project_root=options.project_root.resolve(),
            source_sha=options.source_sha,
            environment=os.environ,
            python_executable=sys.executable,
        )
    except AdminAIExactRuntimeInvalid as error:
        print("admin_ai_exact_runtime=failed")
        print(f"reason={error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
