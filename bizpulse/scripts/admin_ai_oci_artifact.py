"""Inspect the exact owner-only OCI archive approved for admin-AI release."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
from typing import Any


_GIT_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_REF = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}")
_MAX_ARCHIVE_SIZE = 4 * 1024 * 1024 * 1024
_MAX_JSON_SIZE = 4 * 1024 * 1024
_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
_CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
_LAYER_MEDIA_TYPES = frozenset(
    {
        "application/vnd.oci.image.layer.v1.tar",
        "application/vnd.oci.image.layer.v1.tar+gzip",
        "application/vnd.oci.image.layer.v1.tar+zstd",
    }
)


class AdminAIOCIArtifactInvalid(ValueError):
    """The candidate OCI archive did not prove the approved image bytes."""


def _invalid(code: str) -> AdminAIOCIArtifactInvalid:
    return AdminAIOCIArtifactInvalid(code)


def _json(payload: bytes) -> Any:
    if len(payload) > _MAX_JSON_SIZE:
        raise _invalid("artifact_json_invalid")
    try:
        return json.loads(payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise _invalid("artifact_json_invalid") from error


def _descriptor(value: object, *, media_types: frozenset[str]) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise _invalid("artifact_descriptor_invalid")
    digest = value.get("digest")
    size = value.get("size")
    media_type = value.get("mediaType")
    if (
        not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
        or type(size) is not int
        or size < 0
        or size > _MAX_ARCHIVE_SIZE
        or media_type not in media_types
    ):
        raise _invalid("artifact_descriptor_invalid")
    return {"digest": digest, "size": size, "mediaType": media_type}


def _blob_name(digest: str) -> str:
    return f"blobs/sha256/{digest.split(':', 1)[1]}"


def _verify_blob(
    files: Mapping[str, bytes], descriptor: Mapping[str, object]
) -> bytes:
    name = _blob_name(str(descriptor["digest"]))
    payload = files.get(name)
    if (
        payload is None
        or len(payload) != descriptor["size"]
        or f"sha256:{hashlib.sha256(payload).hexdigest()}"
        != descriptor["digest"]
    ):
        raise _invalid("artifact_blob_invalid")
    return payload


def _read_regular_archive(path: Path) -> tuple[dict[str, bytes], str]:
    try:
        metadata = path.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or stat.S_IMODE(metadata.st_mode) != 0o400
            or not 0 < metadata.st_size <= _MAX_ARCHIVE_SIZE
        ):
            raise _invalid("artifact_file_invalid")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "rb") as stream:
            encoded = stream.read(_MAX_ARCHIVE_SIZE + 1)
        if len(encoded) != metadata.st_size:
            raise _invalid("artifact_file_changed")
    except AdminAIOCIArtifactInvalid:
        raise
    except OSError as error:
        raise _invalid("artifact_file_invalid") from error
    files: dict[str, bytes] = {}
    try:
        with tarfile.open(fileobj=__import__("io").BytesIO(encoded), mode="r:") as archive:
            for member in archive.getmembers():
                member_path = PurePosixPath(member.name)
                if (
                    member.name.startswith("/")
                    or ".." in member_path.parts
                    or member.name in files
                ):
                    raise _invalid("artifact_archive_invalid")
                if member.isdir():
                    if member.name.rstrip("/") not in {"blobs", "blobs/sha256"}:
                        raise _invalid("artifact_archive_invalid")
                    continue
                if not member.isfile() or member.size > _MAX_ARCHIVE_SIZE:
                    raise _invalid("artifact_archive_invalid")
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise _invalid("artifact_archive_invalid")
                payload = extracted.read(member.size + 1)
                if len(payload) != member.size:
                    raise _invalid("artifact_archive_invalid")
                files[member.name] = payload
    except AdminAIOCIArtifactInvalid:
        raise
    except (OSError, tarfile.TarError) as error:
        raise _invalid("artifact_archive_invalid") from error
    return files, hashlib.sha256(encoded).hexdigest()


def inspect_oci_archive(
    path: Path,
    *,
    source_sha: str,
    source_tree: str,
    image_input_sha256: str,
    build_context_sha256: str,
) -> dict[str, object]:
    """Validate one single-platform OCI archive and return its immutable binding."""

    if (
        _GIT_SHA.fullmatch(source_sha) is None
        or _GIT_SHA.fullmatch(source_tree) is None
        or _SHA256.fullmatch(image_input_sha256) is None
        or _SHA256.fullmatch(build_context_sha256) is None
    ):
        raise _invalid("artifact_authority_invalid")
    files, archive_sha256 = _read_regular_archive(path)
    layout = _json(files.get("oci-layout", b""))
    index = _json(files.get("index.json", b""))
    if (
        layout != {"imageLayoutVersion": "1.0.0"}
        or not isinstance(index, Mapping)
        or index.get("schemaVersion") != 2
        or index.get("mediaType") != "application/vnd.oci.image.index.v1+json"
        or not isinstance(index.get("manifests"), list)
        or len(index["manifests"]) != 1
    ):
        raise _invalid("artifact_index_invalid")
    raw_manifest_descriptor = index["manifests"][0]
    manifest_descriptor = _descriptor(
        raw_manifest_descriptor, media_types=frozenset({_MANIFEST_MEDIA_TYPE})
    )
    if not isinstance(raw_manifest_descriptor, Mapping):
        raise _invalid("artifact_index_invalid")
    platform = raw_manifest_descriptor.get("platform")
    annotations = raw_manifest_descriptor.get("annotations")
    reference = (
        annotations.get("org.opencontainers.image.ref.name")
        if isinstance(annotations, Mapping)
        else None
    )
    if (
        platform != {"architecture": "amd64", "os": "linux"}
        or not isinstance(reference, str)
        or _REF.fullmatch(reference) is None
    ):
        raise _invalid("artifact_platform_invalid")
    manifest = _json(_verify_blob(files, manifest_descriptor))
    if (
        not isinstance(manifest, Mapping)
        or manifest.get("schemaVersion") != 2
        or manifest.get("mediaType") != _MANIFEST_MEDIA_TYPE
        or not isinstance(manifest.get("layers"), list)
        or not manifest["layers"]
    ):
        raise _invalid("artifact_manifest_invalid")
    config_descriptor = _descriptor(
        manifest.get("config"), media_types=frozenset({_CONFIG_MEDIA_TYPE})
    )
    config = _json(_verify_blob(files, config_descriptor))
    for raw_layer in manifest["layers"]:
        layer_descriptor = _descriptor(raw_layer, media_types=_LAYER_MEDIA_TYPES)
        _verify_blob(files, layer_descriptor)
    if not isinstance(config, Mapping):
        raise _invalid("artifact_config_invalid")
    runtime_config = config.get("config")
    if not isinstance(runtime_config, Mapping):
        raise _invalid("artifact_config_invalid")
    if runtime_config.get("User") != "bizpulse":
        raise _invalid("artifact_user_invalid")
    labels = runtime_config.get("Labels", {})
    if (
        config.get("os") != "linux"
        or config.get("architecture") != "amd64"
        or not isinstance(labels, Mapping)
        or labels.get("org.opencontainers.image.revision") != source_sha
        or labels.get("org.opencontainers.image.bizpulse.source-tree-sha")
        != source_tree
        or labels.get("org.opencontainers.image.bizpulse.image-input-sha256")
        != image_input_sha256
        or labels.get("org.opencontainers.image.bizpulse.build-context-sha256")
        != build_context_sha256
    ):
        raise _invalid("artifact_labels_invalid")
    expected_files = {
        "oci-layout",
        "index.json",
        _blob_name(str(manifest_descriptor["digest"])),
        _blob_name(str(config_descriptor["digest"])),
        *(
            _blob_name(str(_descriptor(layer, media_types=_LAYER_MEDIA_TYPES)["digest"]))
            for layer in manifest["layers"]
        ),
    }
    if set(files) != expected_files:
        raise _invalid("artifact_archive_invalid")
    return {
        "artifact_format": "oci-archive",
        "artifact_path": str(path),
        "artifact_sha256": archive_sha256,
        "image_digest": manifest_descriptor["digest"],
        "platform": "linux/amd64",
        "source_sha": source_sha,
        "source_tree": source_tree,
        "image_input_sha256": image_input_sha256,
        "build_context_sha256": build_context_sha256,
        "oci_reference": reference,
        "runtime_user": "bizpulse",
    }


def materialize_validated_oci_layout(
    path: Path,
    destination: Path,
    *,
    source_sha: str,
    source_tree: str,
    image_input_sha256: str,
    build_context_sha256: str,
) -> dict[str, object]:
    """Write only validated archive members to one private OCI layout directory."""

    inspected = inspect_oci_archive(
        path,
        source_sha=source_sha,
        source_tree=source_tree,
        image_input_sha256=image_input_sha256,
        build_context_sha256=build_context_sha256,
    )
    files, archive_sha256 = _read_regular_archive(path)
    if archive_sha256 != inspected["artifact_sha256"]:
        raise _invalid("artifact_file_changed")
    try:
        destination.mkdir(mode=0o700)
        for name, payload in files.items():
            relative = PurePosixPath(name)
            target = destination.joinpath(*relative.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(target, flags, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            target.chmod(0o400)
            if not stat.S_ISREG(target.lstat().st_mode) or target.is_symlink():
                raise _invalid("artifact_layout_invalid")
        for directory in sorted(
            (item for item in destination.rglob("*") if item.is_dir()),
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            directory.chmod(0o500)
        destination.chmod(0o500)
    except AdminAIOCIArtifactInvalid:
        raise
    except OSError as error:
        raise _invalid("artifact_layout_invalid") from error
    return inspected
