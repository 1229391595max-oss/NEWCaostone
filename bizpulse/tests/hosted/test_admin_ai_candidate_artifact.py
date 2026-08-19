from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

import pytest

import scripts.build_admin_ai_candidate as candidate_builder
from scripts.admin_ai_oci_artifact import (
    AdminAIOCIArtifactInvalid,
    inspect_oci_archive,
)
from scripts.build_admin_ai_candidate import build_candidate_artifact
from scripts.create_admin_ai_release_package import (
    RUNTIME_TOOL_PATHS,
    capture_candidate_artifact,
)
from scripts.publish_registry_image import publish_registry_oci_artifact


SOURCE_SHA = "1" * 40
SOURCE_TREE = "2" * 40
IMAGE_INPUT_SHA256 = "3" * 64
BUILD_CONTEXT_SHA256 = "4" * 64


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _descriptor(payload: bytes, media_type: str) -> dict[str, object]:
    return {
        "digest": f"sha256:{hashlib.sha256(payload).hexdigest()}",
        "mediaType": media_type,
        "size": len(payload),
    }


def _write_oci_archive(
    path: Path,
    *,
    source_sha: str = SOURCE_SHA,
    source_tree: str = SOURCE_TREE,
    image_input_sha256: str = IMAGE_INPUT_SHA256,
    build_context_sha256: str = BUILD_CONTEXT_SHA256,
    runtime_user: str = "bizpulse",
) -> str:
    labels = {
        "org.opencontainers.image.revision": source_sha,
        "org.opencontainers.image.bizpulse.source-tree-sha": source_tree,
        "org.opencontainers.image.bizpulse.image-input-sha256": (
            image_input_sha256
        ),
        "org.opencontainers.image.bizpulse.build-context-sha256": (
            build_context_sha256
        ),
    }
    config = _json_bytes(
        {
            "architecture": "amd64",
            "config": {"Labels": labels, "User": runtime_user},
            "os": "linux",
        }
    )
    layer = b"synthetic-layer"
    config_descriptor = _descriptor(
        config, "application/vnd.oci.image.config.v1+json"
    )
    layer_descriptor = _descriptor(
        layer, "application/vnd.oci.image.layer.v1.tar"
    )
    manifest = _json_bytes(
        {
            "config": config_descriptor,
            "layers": [layer_descriptor],
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "schemaVersion": 2,
        }
    )
    manifest_descriptor = _descriptor(
        manifest, "application/vnd.oci.image.manifest.v1+json"
    )
    manifest_descriptor["platform"] = {"architecture": "amd64", "os": "linux"}
    manifest_descriptor["annotations"] = {
        "org.opencontainers.image.ref.name": f"candidate-{source_sha[:12]}"
    }
    index = _json_bytes(
        {
            "manifests": [manifest_descriptor],
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "schemaVersion": 2,
        }
    )
    entries = {
        "oci-layout": b'{"imageLayoutVersion":"1.0.0"}\n',
        "index.json": index,
        f"blobs/sha256/{config_descriptor['digest'].split(':', 1)[1]}": config,
        f"blobs/sha256/{layer_descriptor['digest'].split(':', 1)[1]}": layer,
        f"blobs/sha256/{manifest_descriptor['digest'].split(':', 1)[1]}": manifest,
    }
    with tarfile.open(path, "w") as archive:
        for name, payload in entries.items():
            member = tarfile.TarInfo(name)
            member.mode = 0o444
            member.size = len(payload)
            archive.addfile(member, io.BytesIO(payload))
    path.chmod(0o400)
    return str(manifest_descriptor["digest"])


def test_oci_archive_binds_exact_manifest_and_source_labels(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.oci.tar"
    digest = _write_oci_archive(artifact)

    result = inspect_oci_archive(
        artifact,
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        image_input_sha256=IMAGE_INPUT_SHA256,
        build_context_sha256=BUILD_CONTEXT_SHA256,
    )

    assert result == {
        "artifact_format": "oci-archive",
        "artifact_path": str(artifact),
        "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        "image_digest": digest,
        "platform": "linux/amd64",
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "image_input_sha256": IMAGE_INPUT_SHA256,
        "build_context_sha256": BUILD_CONTEXT_SHA256,
        "oci_reference": f"candidate-{SOURCE_SHA[:12]}",
        "runtime_user": "bizpulse",
    }


@pytest.mark.parametrize("runtime_user", ("", "root", "0", "1000"))
def test_oci_archive_rejects_any_non_bizpulse_runtime_user(
    tmp_path: Path,
    runtime_user: str,
) -> None:
    artifact = tmp_path / "candidate.oci.tar"
    _write_oci_archive(artifact, runtime_user=runtime_user)

    with pytest.raises(AdminAIOCIArtifactInvalid, match="artifact_user_invalid"):
        inspect_oci_archive(
            artifact,
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_input_sha256=IMAGE_INPUT_SHA256,
            build_context_sha256=BUILD_CONTEXT_SHA256,
        )


def test_oci_archive_rejects_mismatched_source_tree_label(tmp_path: Path) -> None:
    artifact = tmp_path / "candidate.oci.tar"
    _write_oci_archive(artifact, source_tree="f" * 40)

    with pytest.raises(AdminAIOCIArtifactInvalid, match="artifact_labels_invalid"):
        inspect_oci_archive(
            artifact,
            source_sha=SOURCE_SHA,
            source_tree=SOURCE_TREE,
            image_input_sha256=IMAGE_INPUT_SHA256,
            build_context_sha256=BUILD_CONTEXT_SHA256,
        )


def test_package_capture_normalizes_exact_artifact_inside_project(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / ".tmp" / "candidate.oci.tar"
    artifact.parent.mkdir()
    _write_oci_archive(artifact)

    result = capture_candidate_artifact(
        artifact,
        source_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        image_input_sha256=IMAGE_INPUT_SHA256,
        build_context_sha256=BUILD_CONTEXT_SHA256,
        project_root=tmp_path,
    )

    assert result["artifact_path"] == ".tmp/candidate.oci.tar"


def test_builder_uses_one_detached_exact_commit_context(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository = repository_root / "bizpulse"
    repository.mkdir(parents=True)
    (repository / "Dockerfile").write_text("FROM scratch\n")
    (repository / ".dockerignore").write_text(".git\n")
    for name in ("requirements.txt", "requirements-dev.txt"):
        (repository / name).write_text(f"# {name}\n")
    (repository / "package.json").write_text("{}\n")
    (repository / "package-lock.json").write_text("{}\n")
    for relative in RUNTIME_TOOL_PATHS:
        runtime_path = repository / relative
        if not runtime_path.exists():
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.write_text(f"# {relative}\n")
    subprocess.run(["git", "init", "-q"], cwd=repository_root, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=repository_root,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"], cwd=repository_root, check=True
    )
    subprocess.run(["git", "add", "."], cwd=repository_root, check=True)
    subprocess.run(
        ["git", "commit", "-qm", "fixture"], cwd=repository_root, check=True
    )
    committed_dockerfile = (repository / "Dockerfile").read_bytes()
    output = tmp_path / "candidate.oci.tar"
    observed_contexts: list[Path] = []

    def docker_runner(command, **_kwargs):
        assert command[:3] == ["docker", "buildx", "build"]
        context = Path(command[-1])
        observed_contexts.append(context)
        assert context != repository
        assert (context / "Dockerfile").read_bytes() == committed_dockerfile
        (repository / "Dockerfile").write_text("FROM mutable-later-build\n")
        assert (context / "Dockerfile").read_bytes() == committed_dockerfile
        arguments = {
            command[index + 1].split("=", 1)[0]: command[index + 1].split("=", 1)[1]
            for index, value in enumerate(command)
            if value == "--build-arg"
        }
        destination = next(
            value.split("dest=", 1)[1]
            for value in command
            if value.startswith("type=oci,dest=")
        ).split(",", 1)[0]
        _write_oci_archive(
            Path(destination),
            source_sha=arguments["SOURCE_REVISION"],
            source_tree=arguments["SOURCE_TREE_SHA"],
            image_input_sha256=arguments["IMAGE_INPUT_SHA256"],
            build_context_sha256=arguments["BUILD_CONTEXT_SHA256"],
        )
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = build_candidate_artifact(
        output,
        project_root=repository,
        runner=docker_runner,
    )

    assert len(observed_contexts) == 1
    assert result["artifact_path"] == str(output)
    assert result["source_sha"] == subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert output.stat().st_mode & 0o777 == 0o400


def test_builder_reuses_the_private_exact_runtime_snapshot_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = tmp_path / "exact-snapshot"
    snapshot.mkdir()
    dockerfile = snapshot / "Dockerfile"
    dockerfile.write_text("FROM scratch\n")
    dockerfile.chmod(0o400)
    marker = snapshot / ".admin-ai-exact-runtime.json"
    marker.write_text(
        '{"schema_version":"newcaostone.admin-ai-exact-runtime.v1",'
        f'"source_sha":"{SOURCE_SHA}","source_tree":"{SOURCE_TREE}"}}'
    )
    marker.chmod(0o400)
    output = tmp_path / "candidate.oci.tar"
    manifest_entry = {
        "mode": "100644",
        "path": "Dockerfile",
        "sha256": hashlib.sha256(dockerfile.read_bytes()).hexdigest(),
        "size": len(dockerfile.read_bytes()),
    }
    repository = {
        "source_sha": SOURCE_SHA,
        "source_tree": SOURCE_TREE,
        "tracked_tree_clean": True,
        "build_context_manifest": {
            "schema_version": "newcaostone.docker-build-context.v1",
            "entries": [manifest_entry],
            "sha256": BUILD_CONTEXT_SHA256,
        },
        "runtime_tool_manifest": {},
    }
    monkeypatch.setattr(
        candidate_builder,
        "capture_repository",
        lambda **_kwargs: repository,
    )
    monkeypatch.setattr(
        candidate_builder,
        "_detached_image_input_sha256",
        lambda _root, _tree: IMAGE_INPUT_SHA256,
    )
    monkeypatch.setattr(
        candidate_builder,
        "inspect_oci_archive",
        lambda path, **_kwargs: {
            "artifact_format": "oci-archive",
            "artifact_path": str(path),
            "artifact_sha256": "5" * 64,
            "image_digest": "sha256:" + "6" * 64,
            "platform": "linux/amd64",
            "source_sha": SOURCE_SHA,
            "source_tree": SOURCE_TREE,
            "image_input_sha256": IMAGE_INPUT_SHA256,
            "build_context_sha256": BUILD_CONTEXT_SHA256,
            "oci_reference": f"candidate-{SOURCE_SHA[:12]}",
            "runtime_user": "bizpulse",
        },
    )

    def runner(command, **_kwargs):
        assert Path(command[-1]) == snapshot
        destination = Path(
            next(value for value in command if value.startswith("type=oci,dest="))
            .split("dest=", 1)[1]
            .split(",", 1)[0]
        )
        destination.write_bytes(b"synthetic oci")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    result = build_candidate_artifact(
        output,
        project_root=snapshot,
        runner=runner,
    )

    assert result["source_sha"] == SOURCE_SHA
    assert output.read_bytes() == b"synthetic oci"


def test_publisher_copies_only_the_bound_oci_manifest_without_rebuild(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "candidate.oci.tar"
    digest = _write_oci_archive(artifact)
    artifact_sha256 = hashlib.sha256(artifact.read_bytes()).hexdigest()
    calls: list[tuple[str, ...]] = []
    published_layout: dict[str, object] = {}

    def runner(command, **_kwargs):
        calls.append(tuple(command))
        if command[:4] == ["az", "acr", "login", "--name"]:
            payload: object = {
                "accessToken": "synthetic-access-token-0123456789abcdef",
                "loginServer": "bpapprovedregistry.azurecr.io",
            }
        elif command[:4] == ["az", "acr", "manifest", "show-metadata"]:
            payload = {
                "digest": digest,
                "tags": [f"ai-{SOURCE_SHA[:12]}-{'a' * 8}"],
            }
        elif command[:2] == ("oras", "cp"):
            source = command[-2].rsplit(":", 1)[0]
            layout = Path(source)
            published_layout["is_dir"] = layout.is_dir()
            published_layout["files"] = {
                str(path.relative_to(layout))
                for path in layout.rglob("*")
                if path.is_file()
            }
            published_layout["symlinks"] = [
                str(path.relative_to(layout))
                for path in layout.rglob("*")
                if path.is_symlink()
            ]
            published_layout["modes"] = {
                path.stat().st_mode & 0o777
                for path in layout.rglob("*")
                if path.is_file()
            }
            payload = {}
        else:
            payload = {}
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    result = publish_registry_oci_artifact(
        subscription_id="11111111-1111-4111-8111-111111111111",
        registry_name="bpapprovedregistry",
        repository="bizpulse",
        candidate_git_sha=SOURCE_SHA,
        source_tree=SOURCE_TREE,
        package_sha256="a" * 64,
        artifact_path=artifact,
        artifact_sha256=artifact_sha256,
        expected_digest=digest,
        oci_reference=f"candidate-{SOURCE_SHA[:12]}",
        image_input_sha256=IMAGE_INPUT_SHA256,
        build_context_sha256=BUILD_CONTEXT_SHA256,
        runner=runner,
    )

    assert result == digest
    assert not any(command[:3] == ("docker", "buildx", "build") for command in calls)
    copy = next(command for command in calls if command[:2] == ("oras", "cp"))
    assert copy[-1] == f"bpapprovedregistry.azurecr.io/bizpulse:ai-{SOURCE_SHA[:12]}-{'a' * 8}"
    assert copy[-2].rsplit(":", 1)[0].endswith("candidate.oci-layout")
    assert copy[-2].endswith(f":candidate-{SOURCE_SHA[:12]}")
    assert published_layout == {
        "is_dir": True,
        "files": {
            "oci-layout",
            "index.json",
            *{
                f"blobs/sha256/{descriptor.split(':', 1)[1]}"
                for descriptor in (
                    digest,
                    _descriptor(
                        _json_bytes(
                            {
                                "architecture": "amd64",
                                "config": {
                                    "User": "bizpulse",
                                    "Labels": {
                                        "org.opencontainers.image.revision": SOURCE_SHA,
                                        "org.opencontainers.image.bizpulse.source-tree-sha": SOURCE_TREE,
                                        "org.opencontainers.image.bizpulse.image-input-sha256": IMAGE_INPUT_SHA256,
                                        "org.opencontainers.image.bizpulse.build-context-sha256": BUILD_CONTEXT_SHA256,
                                    }
                                },
                                "os": "linux",
                            }
                        ),
                        "application/vnd.oci.image.config.v1+json",
                    )["digest"],
                    _descriptor(
                        b"synthetic-layer",
                        "application/vnd.oci.image.layer.v1.tar",
                    )["digest"],
                )
            },
        },
        "symlinks": [],
        "modes": {0o400},
    }
    assert calls[-1] == (
        "az",
        "acr",
        "manifest",
        "show-metadata",
        "--subscription",
        "11111111-1111-4111-8111-111111111111",
        "--registry",
        "bpapprovedregistry",
        "--name",
        f"bizpulse@{digest}",
        "--only-show-errors",
        "--output",
        "json",
    )
