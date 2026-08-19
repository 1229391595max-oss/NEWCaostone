"""Publish one exact local candidate image and verify its ACR digest authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from scripts.admin_ai_oci_artifact import (
    AdminAIOCIArtifactInvalid,
    materialize_validated_oci_layout,
)

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
REGISTRY_PATTERN = re.compile(r"[a-z0-9]{5,50}")
REPOSITORY_PATTERN = re.compile(r"[a-z0-9][a-z0-9._/-]{1,127}")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
ACR_TOKEN_USERNAME = "00000000-0000-0000-0000-000000000000"
_PROCESS_ENVIRONMENT_NAMES = (
    "AZURE_CONFIG_DIR",
    "HOME",
    "LANG",
    "LC_ALL",
    "PATH",
    "REQUESTS_CA_BUNDLE",
    "SSL_CERT_FILE",
    "TMPDIR",
)


class RegistryPublicationInvalid(RuntimeError):
    """The exact registry publication authority was not proved."""


def _safe_process_environment(source: Mapping[str, str]) -> dict[str, str]:
    """Return the only ambient settings registry child processes may receive."""

    return {
        name: value
        for name in _PROCESS_ENVIRONMENT_NAMES
        if isinstance((value := source.get(name)), str)
    }


def _run_json(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    timeout: int,
    env: Mapping[str, str],
) -> Any:
    completed = runner(
        list(command),
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    if len(completed.stdout) > 1_000_000:
        raise RegistryPublicationInvalid("registry_publication_response_invalid")
    try:
        return json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise RegistryPublicationInvalid(
            "registry_publication_response_invalid"
        ) from error


def registry_access_token(
    *,
    subscription_id: str,
    registry_name: str,
    environment: Mapping[str, str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    """Acquire one bounded Entra-backed ACR token without exposing it."""

    child_environment = _safe_process_environment(environment)
    try:
        payload = _run_json(
            (
                "az",
                "acr",
                "login",
                "--name",
                registry_name,
                "--subscription",
                subscription_id,
                "--expose-token",
                "--only-show-errors",
                "--output",
                "json",
            ),
            runner=runner,
            timeout=60,
            env=child_environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RegistryPublicationInvalid(
            "registry_publication_token_unavailable"
        ) from error
    token = payload.get("accessToken") if isinstance(payload, dict) else None
    login_server = payload.get("loginServer") if isinstance(payload, dict) else None
    if (
        not isinstance(token, str)
        or not 32 <= len(token) <= 16_384
        or any(character in token for character in ("\0", "\r", "\n"))
        or login_server != f"{registry_name}.azurecr.io"
    ):
        raise RegistryPublicationInvalid("registry_publication_token_invalid")
    return token


def publish_registry_image(
    *,
    subscription_id: str,
    registry_name: str,
    repository: str,
    candidate_git_sha: str,
    authorization_id: str,
    expected_digest: str,
    image_input_sha256: str,
    environment: Mapping[str, str] = os.environ,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or UUID_PATTERN.fullmatch(authorization_id) is None
        or REGISTRY_PATTERN.fullmatch(registry_name) is None
        or REPOSITORY_PATTERN.fullmatch(repository) is None
        or SHA_PATTERN.fullmatch(candidate_git_sha) is None
        or DIGEST_PATTERN.fullmatch(expected_digest) is None
        or re.fullmatch(r"[0-9a-f]{64}", image_input_sha256) is None
    ):
        raise RegistryPublicationInvalid("registry_publication_authority_invalid")
    base_environment = _safe_process_environment(environment)
    local_image = f"newcaostone-local:{candidate_git_sha[:12]}"
    registry_server = f"{registry_name}.azurecr.io"
    tag = f"candidate-{candidate_git_sha[:12]}-{authorization_id[:8]}"
    target = f"{registry_server}/{repository}:{tag}"
    try:
        inspected = _run_json(
            ("docker", "image", "inspect", local_image),
            runner=runner,
            timeout=30,
            env=base_environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RegistryPublicationInvalid("registry_local_image_unavailable") from error
    if (
        not isinstance(inspected, list)
        or len(inspected) != 1
        or not isinstance(inspected[0], dict)
        or inspected[0].get("Os") != "linux"
        or inspected[0].get("Architecture") != "amd64"
        or inspected[0].get("Config", {}).get("Labels", {}).get(
            "org.opencontainers.image.revision"
        )
        != candidate_git_sha
        or inspected[0].get("Config", {}).get("Labels", {}).get(
            "org.opencontainers.image.bizpulse.image-input-sha256"
        )
        != image_input_sha256
    ):
        raise RegistryPublicationInvalid("registry_local_image_invalid")

    with tempfile.TemporaryDirectory(prefix="newcaostone-docker-config-") as directory:
        process_env = dict(base_environment)
        process_env["DOCKER_CONFIG"] = str(Path(directory))
        token = ""
        try:
            token = registry_access_token(
                subscription_id=subscription_id,
                registry_name=registry_name,
                environment=base_environment,
                runner=runner,
            )
            try:
                runner(
                    (
                        "docker",
                        "login",
                        registry_server,
                        "--username",
                        ACR_TOKEN_USERNAME,
                        "--password-stdin",
                    ),
                    input=token,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=process_env,
                )
                runner(
                    ("docker", "tag", local_image, target),
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=process_env,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise RegistryPublicationInvalid(
                    "registry_publication_preflight_failed"
                ) from error
            push_error: Exception | None = None
            try:
                runner(
                    ("docker", "push", target),
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=process_env,
                )
            except Exception as error:
                push_error = error
        finally:
            token = ""
            process_env.clear()

    try:
        manifest = _run_json(
            (
                "az",
                "acr",
                "manifest",
                "show-metadata",
                "--subscription",
                subscription_id,
                "--registry",
                registry_name,
                "--name",
                f"{repository}@{expected_digest}",
                "--only-show-errors",
                "--output",
                "json",
            ),
            runner=runner,
            timeout=60,
            env=base_environment,
        )
    except (OSError, subprocess.SubprocessError, RegistryPublicationInvalid) as error:
        raise RegistryPublicationInvalid(
            "registry_publication_outcome_unknown"
        ) from (push_error or error)
    if (
        not isinstance(manifest, dict)
        or manifest.get("digest") != expected_digest
        or not isinstance(manifest.get("tags"), list)
        or tag not in manifest["tags"]
    ):
        raise RegistryPublicationInvalid("registry_publication_digest_mismatch")
    return target


def _snapshot_artifact(
    source: Path, destination: Path, *, expected_sha256: str
) -> None:
    try:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        source_descriptor = os.open(source, flags)
        with os.fdopen(source_descriptor, "rb") as source_stream:
            source_metadata = os.fstat(source_stream.fileno())
            if (
                not stat.S_ISREG(source_metadata.st_mode)
                or stat.S_IMODE(source_metadata.st_mode) != 0o400
            ):
                raise RegistryPublicationInvalid(
                    "registry_artifact_file_invalid"
                )
            destination_descriptor = os.open(
                destination,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o400,
            )
            digest = hashlib.sha256()
            with os.fdopen(destination_descriptor, "wb") as destination_stream:
                os.fchmod(destination_stream.fileno(), 0o400)
                while chunk := source_stream.read(1024 * 1024):
                    digest.update(chunk)
                    destination_stream.write(chunk)
                destination_stream.flush()
                os.fsync(destination_stream.fileno())
    except RegistryPublicationInvalid:
        raise
    except OSError as error:
        raise RegistryPublicationInvalid(
            "registry_artifact_file_invalid"
        ) from error
    if digest.hexdigest() != expected_sha256:
        raise RegistryPublicationInvalid("registry_artifact_digest_mismatch")


def publish_registry_oci_artifact(
    *,
    subscription_id: str,
    registry_name: str,
    repository: str,
    candidate_git_sha: str,
    source_tree: str,
    package_sha256: str,
    artifact_path: Path,
    artifact_sha256: str,
    expected_digest: str,
    oci_reference: str,
    image_input_sha256: str,
    build_context_sha256: str,
    environment: Mapping[str, str] = os.environ,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Publish the exact approved OCI bytes without rebuilding or retagging them."""

    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or REGISTRY_PATTERN.fullmatch(registry_name) is None
        or REPOSITORY_PATTERN.fullmatch(repository) is None
        or SHA_PATTERN.fullmatch(candidate_git_sha) is None
        or SHA_PATTERN.fullmatch(source_tree) is None
        or re.fullmatch(r"[0-9a-f]{64}", package_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", artifact_sha256) is None
        or DIGEST_PATTERN.fullmatch(expected_digest) is None
        or oci_reference != f"candidate-{candidate_git_sha[:12]}"
        or re.fullmatch(r"[0-9a-f]{64}", image_input_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", build_context_sha256) is None
    ):
        raise RegistryPublicationInvalid("registry_publication_authority_invalid")
    base_environment = _safe_process_environment(environment)
    registry_server = f"{registry_name}.azurecr.io"
    tag = f"ai-{candidate_git_sha[:12]}-{package_sha256[:8]}"
    target = f"{registry_server}/{repository}:{tag}"
    push_error: Exception | None = None
    with tempfile.TemporaryDirectory(prefix="newcaostone-oci-publication-") as raw:
        private_root = Path(raw)
        snapshot = private_root / "candidate.oci.tar"
        _snapshot_artifact(
            artifact_path, snapshot, expected_sha256=artifact_sha256
        )
        layout = private_root / "candidate.oci-layout"
        try:
            inspected = materialize_validated_oci_layout(
                snapshot,
                layout,
                source_sha=candidate_git_sha,
                source_tree=source_tree,
                image_input_sha256=image_input_sha256,
                build_context_sha256=build_context_sha256,
            )
        except AdminAIOCIArtifactInvalid as error:
            raise RegistryPublicationInvalid(
                "registry_artifact_invalid"
            ) from error
        if (
            inspected["artifact_sha256"] != artifact_sha256
            or inspected["image_digest"] != expected_digest
            or inspected["oci_reference"] != oci_reference
        ):
            raise RegistryPublicationInvalid("registry_artifact_digest_mismatch")
        process_env = dict(base_environment)
        process_env["HOME"] = str(private_root)
        registry_config = private_root / "registry-config.json"
        token = ""
        try:
            token = registry_access_token(
                subscription_id=subscription_id,
                registry_name=registry_name,
                environment=base_environment,
                runner=runner,
            )
            runner(
                (
                    "oras",
                    "login",
                    registry_server,
                    "--username",
                    ACR_TOKEN_USERNAME,
                    "--password-stdin",
                    "--registry-config",
                    str(registry_config),
                ),
                input=token,
                check=True,
                capture_output=True,
                text=True,
                timeout=60,
                env=process_env,
            )
            try:
                runner(
                    (
                        "oras",
                        "cp",
                        "--from-oci-layout",
                        "--to-registry-config",
                        str(registry_config),
                        f"{layout}:{oci_reference}",
                        target,
                    ),
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=process_env,
                )
            except Exception as error:
                push_error = error
        except (OSError, subprocess.SubprocessError) as error:
            raise RegistryPublicationInvalid(
                "registry_publication_preflight_failed"
            ) from error
        finally:
            token = ""
            process_env.clear()
    try:
        manifest = _run_json(
            (
                "az",
                "acr",
                "manifest",
                "show-metadata",
                "--subscription",
                subscription_id,
                "--registry",
                registry_name,
                "--name",
                f"{repository}@{expected_digest}",
                "--only-show-errors",
                "--output",
                "json",
            ),
            runner=runner,
            timeout=60,
            env=base_environment,
        )
    except (OSError, subprocess.SubprocessError, RegistryPublicationInvalid) as error:
        raise RegistryPublicationInvalid(
            "registry_publication_outcome_unknown"
        ) from (push_error or error)
    if (
        not isinstance(manifest, dict)
        or manifest.get("digest") != expected_digest
        or not isinstance(manifest.get("tags"), list)
        or tag not in manifest["tags"]
    ):
        raise RegistryPublicationInvalid("registry_publication_digest_mismatch")
    return expected_digest


def publish_registry_image_discover_digest(
    *,
    subscription_id: str,
    registry_name: str,
    repository: str,
    candidate_git_sha: str,
    package_sha256: str,
    image_input_sha256: str,
    build_context_sha256: str | None = None,
    environment: Mapping[str, str] = os.environ,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Publish one package-bound tag and return its registry-issued digest."""

    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or REGISTRY_PATTERN.fullmatch(registry_name) is None
        or REPOSITORY_PATTERN.fullmatch(repository) is None
        or SHA_PATTERN.fullmatch(candidate_git_sha) is None
        or re.fullmatch(r"[0-9a-f]{64}", package_sha256) is None
        or re.fullmatch(r"[0-9a-f]{64}", image_input_sha256) is None
        or (
            build_context_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", build_context_sha256) is None
        )
    ):
        raise RegistryPublicationInvalid("registry_publication_authority_invalid")
    base_environment = _safe_process_environment(environment)
    local_image = f"newcaostone-local:{candidate_git_sha[:12]}"
    registry_server = f"{registry_name}.azurecr.io"
    tag = f"ai-{candidate_git_sha[:12]}-{package_sha256[:8]}"
    target = f"{registry_server}/{repository}:{tag}"
    try:
        inspected = _run_json(
            ("docker", "image", "inspect", local_image),
            runner=runner,
            timeout=30,
            env=base_environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise RegistryPublicationInvalid(
            "registry_local_image_unavailable"
        ) from error
    if (
        not isinstance(inspected, list)
        or len(inspected) != 1
        or not isinstance(inspected[0], dict)
        or inspected[0].get("Os") != "linux"
        or inspected[0].get("Architecture") != "amd64"
        or inspected[0].get("Config", {}).get("Labels", {}).get(
            "org.opencontainers.image.revision"
        )
        != candidate_git_sha
        or inspected[0].get("Config", {}).get("Labels", {}).get(
            "org.opencontainers.image.bizpulse.image-input-sha256"
        )
        != image_input_sha256
        or (
            build_context_sha256 is not None
            and inspected[0].get("Config", {}).get("Labels", {}).get(
                "org.opencontainers.image.bizpulse.build-context-sha256"
            )
            != build_context_sha256
        )
    ):
        raise RegistryPublicationInvalid("registry_local_image_invalid")

    push_error: Exception | None = None
    with tempfile.TemporaryDirectory(prefix="newcaostone-docker-config-") as directory:
        process_env = dict(base_environment)
        process_env["DOCKER_CONFIG"] = str(Path(directory))
        token = ""
        try:
            token = registry_access_token(
                subscription_id=subscription_id,
                registry_name=registry_name,
                environment=base_environment,
                runner=runner,
            )
            try:
                runner(
                    (
                        "docker",
                        "login",
                        registry_server,
                        "--username",
                        ACR_TOKEN_USERNAME,
                        "--password-stdin",
                    ),
                    input=token,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=60,
                    env=process_env,
                )
                runner(
                    ("docker", "tag", local_image, target),
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    env=process_env,
                )
            except (OSError, subprocess.SubprocessError) as error:
                raise RegistryPublicationInvalid(
                    "registry_publication_preflight_failed"
                ) from error
            try:
                runner(
                    ("docker", "push", target),
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=600,
                    env=process_env,
                )
            except Exception as error:
                push_error = error
        finally:
            token = ""
            process_env.clear()

    try:
        tag_details = _run_json(
            (
                "az",
                "acr",
                "repository",
                "show-tags",
                "--subscription",
                subscription_id,
                "--name",
                registry_name,
                "--repository",
                repository,
                "--detail",
                "--query",
                f"[?name=='{tag}']",
                "--only-show-errors",
                "--output",
                "json",
            ),
            runner=runner,
            timeout=60,
            env=base_environment,
        )
    except (OSError, subprocess.SubprocessError, RegistryPublicationInvalid) as error:
        raise RegistryPublicationInvalid(
            "registry_publication_outcome_unknown"
        ) from (push_error or error)
    tag_detail = (
        tag_details[0]
        if isinstance(tag_details, list) and len(tag_details) == 1
        else None
    )
    digest = tag_detail.get("digest") if isinstance(tag_detail, dict) else None
    if (
        not isinstance(tag_detail, dict)
        or tag_detail.get("name") != tag
        or not isinstance(digest, str)
        or DIGEST_PATTERN.fullmatch(digest) is None
    ):
        raise RegistryPublicationInvalid("registry_publication_digest_mismatch")
    return digest


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--candidate-git-sha", required=True)
    parser.add_argument("--authorization-id", required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--image-input-sha256", required=True)
    options = parser.parse_args(arguments)
    try:
        target = publish_registry_image(
            subscription_id=options.subscription,
            registry_name=options.registry,
            repository=options.repository,
            candidate_git_sha=options.candidate_git_sha,
            authorization_id=options.authorization_id,
            expected_digest=options.expected_digest,
            image_input_sha256=options.image_input_sha256,
        )
    except RegistryPublicationInvalid:
        print("registry_publication=failed")
        return 1
    print("registry_publication=ok")
    print(f"target={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
