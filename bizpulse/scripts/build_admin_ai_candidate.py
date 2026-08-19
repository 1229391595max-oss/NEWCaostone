#!/usr/bin/env python3
"""Build one OCI candidate from a detached archive of the exact clean commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tempfile
import tarfile
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _require_exact_runtime_for_script() -> None:
    marker = PROJECT_ROOT / ".admin-ai-exact-runtime.json"
    try:
        metadata = marker.lstat()
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        payload = None
        metadata = None
    if (
        os.environ.get("BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT")
        != str(PROJECT_ROOT)
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
        or not sys.flags.no_site
        or metadata is None
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or not isinstance(payload, Mapping)
        or payload.get("schema_version")
        != "newcaostone.admin-ai-exact-runtime.v1"
    ):
        print("admin_ai_exact_runtime=failed")
        print("reason=runtime_snapshot_required")
        raise SystemExit(1)


if __name__ == "__main__":
    _require_exact_runtime_for_script()

from scripts.admin_ai_oci_artifact import (  # noqa: E402
    AdminAIOCIArtifactInvalid,
    inspect_oci_archive,
)
from scripts.create_admin_ai_release_package import (  # noqa: E402
    AdminAIReleasePackageInvalid,
    capture_repository,
)
from scripts.create_release_manifest import (  # noqa: E402
    DEPENDENCY_FILES,
    image_input_sha256,
)


class AdminAICandidateBuildInvalid(RuntimeError):
    """The exact detached candidate could not be materialized and built."""


def _invalid(code: str) -> AdminAICandidateBuildInvalid:
    return AdminAICandidateBuildInvalid(code)


def _materialize_exact_source(
    *, source_sha: str, project_root: Path, destination: Path
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
            )
            archive_stream.seek(0)
            with tarfile.open(fileobj=archive_stream, mode="r:") as archive:
                for member in archive.getmembers():
                    raw_path = PurePosixPath(member.name)
                    if member.name.startswith("/") or ".." in raw_path.parts:
                        raise _invalid("candidate_source_archive_invalid")
                    parts = raw_path.parts
                    if not parts:
                        continue
                    target = destination.joinpath(*parts)
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True, mode=0o700)
                        continue
                    if not member.isfile() or member.mode & ~0o777 not in {0}:
                        raise _invalid("candidate_source_archive_invalid")
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    extracted = archive.extractfile(member)
                    if extracted is None:
                        raise _invalid("candidate_source_archive_invalid")
                    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
                    if hasattr(os, "O_NOFOLLOW"):
                        flags |= os.O_NOFOLLOW
                    descriptor = os.open(target, flags, 0o600)
                    with os.fdopen(descriptor, "wb") as stream:
                        payload = extracted.read(member.size + 1)
                        if len(payload) != member.size:
                            raise _invalid("candidate_source_archive_invalid")
                        stream.write(payload)
                    target.chmod(0o500 if member.mode & stat.S_IXUSR else 0o400)
        except AdminAICandidateBuildInvalid:
            raise
        except (OSError, subprocess.SubprocessError, tarfile.TarError) as error:
            raise _invalid("candidate_source_archive_invalid") from error
    for directory in sorted(
        (path for path in destination.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        directory.chmod(0o500)
    destination.chmod(0o500)


def _verify_materialized_manifest(
    root: Path, manifest: Mapping[str, object]
) -> None:
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise _invalid("candidate_context_manifest_invalid")
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise _invalid("candidate_context_manifest_invalid")
        try:
            candidate = root / str(entry["path"])
            metadata = candidate.lstat()
            payload = candidate.read_bytes()
        except (KeyError, OSError) as error:
            raise _invalid("candidate_context_manifest_invalid") from error
        expected_executable = entry["mode"] == "100755"
        if (
            not stat.S_ISREG(metadata.st_mode)
            or candidate.is_symlink()
            or len(payload) != entry["size"]
            or hashlib.sha256(payload).hexdigest() != entry["sha256"]
            or bool(metadata.st_mode & stat.S_IXUSR) is not expected_executable
        ):
            raise _invalid("candidate_context_manifest_invalid")


def _detached_image_input_sha256(root: Path, source_tree: str) -> str:
    try:
        dependencies = {
            path: hashlib.sha256((root / path).read_bytes()).hexdigest()
            for path in DEPENDENCY_FILES
        }
    except OSError as error:
        raise _invalid("candidate_dependency_invalid") from error
    return image_input_sha256(
        git_tree=source_tree,
        dependency_hashes=dependencies,
    )


@contextmanager
def _candidate_build_context(
    root: Path,
    *,
    source_sha: str,
) -> Iterator[Path]:
    from scripts.admin_ai_exact_runtime import load_exact_runtime_marker

    marker = load_exact_runtime_marker(root)
    if marker is not None:
        if marker["source_sha"] != source_sha:
            raise _invalid("candidate_source_archive_invalid")
        yield root
        return
    with tempfile.TemporaryDirectory(prefix="newcaostone-exact-source-") as raw:
        detached = Path(raw) / "source"
        detached.mkdir(mode=0o700)
        _materialize_exact_source(
            source_sha=source_sha,
            project_root=root,
            destination=detached,
        )
        yield detached


def build_candidate_artifact(
    output: Path,
    *,
    project_root: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, object]:
    """Build once from a read-only exact commit and bind the resulting OCI bytes."""

    root = PROJECT_ROOT if project_root is None else project_root
    try:
        if output.exists() or output.is_symlink():
            raise _invalid("candidate_artifact_exists")
        output.parent.mkdir(parents=True, exist_ok=True)
        repository = capture_repository(project_root=root)
    except AdminAIReleasePackageInvalid as error:
        raise _invalid(str(error)) from error
    source_sha = str(repository["source_sha"])
    source_tree = str(repository["source_tree"])
    build_context_sha256 = str(repository["build_context_manifest"]["sha256"])
    temporary_output: Path | None = None
    try:
        with _candidate_build_context(root, source_sha=source_sha) as detached:
            _verify_materialized_manifest(
                detached, repository["build_context_manifest"]
            )
            image_input = _detached_image_input_sha256(detached, source_tree)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{output.name}.", suffix=".building", dir=output.parent
            )
            os.close(descriptor)
            os.unlink(temporary_name)
            temporary_output = Path(temporary_name)
            completed = runner(
                [
                    "docker",
                    "buildx",
                    "build",
                    "--platform",
                    "linux/amd64",
                    "--provenance=false",
                    "--sbom=false",
                    "--build-arg",
                    f"SOURCE_REVISION={source_sha}",
                    "--build-arg",
                    f"SOURCE_TREE_SHA={source_tree}",
                    "--build-arg",
                    f"IMAGE_INPUT_SHA256={image_input}",
                    "--build-arg",
                    f"BUILD_CONTEXT_SHA256={build_context_sha256}",
                    "--output",
                    (
                        f"type=oci,dest={temporary_output},"
                        f"name=candidate-{source_sha[:12]},tar=true"
                    ),
                    str(detached),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=2400,
                shell=False,
            )
            if completed.returncode != 0 or not temporary_output.is_file():
                raise _invalid("candidate_build_failed")
            temporary_output.chmod(0o400)
            inspected = inspect_oci_archive(
                temporary_output,
                source_sha=source_sha,
                source_tree=source_tree,
                image_input_sha256=image_input,
                build_context_sha256=build_context_sha256,
            )
            os.link(temporary_output, output)
            temporary_output.unlink()
            temporary_output = None
    except (OSError, subprocess.SubprocessError, AdminAIOCIArtifactInvalid) as error:
        if isinstance(error, AdminAICandidateBuildInvalid):
            raise
        raise _invalid("candidate_build_failed") from error
    finally:
        if temporary_output is not None:
            try:
                temporary_output.unlink(missing_ok=True)
            except OSError:
                pass
    inspected["artifact_path"] = str(output)
    return inspected


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args(arguments)
    try:
        result = build_candidate_artifact(options.output)
    except AdminAICandidateBuildInvalid as error:
        print("admin_ai_candidate=failed")
        print(f"reason={error}")
        return 1
    print("admin_ai_candidate=created")
    print(f"artifact_sha256={result['artifact_sha256']}")
    print(f"image_digest={result['image_digest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
