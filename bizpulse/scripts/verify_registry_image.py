"""Verify one immutable ACR image digest against its committed build authority."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_PROJECT_ROOT))

from scripts.publish_registry_image import (  # noqa: E402
    ACR_TOKEN_USERNAME,
    DIGEST_PATTERN,
    REGISTRY_PATTERN,
    REPOSITORY_PATTERN,
    SHA_PATTERN,
    RegistryPublicationInvalid,
    UUID_PATTERN,
    registry_access_token,
)


class RegistryImageInvalid(RuntimeError):
    """The remote image did not prove its exact source and input authority."""


def _json_output(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
    environment: Mapping[str, str],
) -> Any:
    completed = runner(
        list(command),
        check=True,
        capture_output=True,
        text=True,
        timeout=120,
        env=environment,
    )
    if len(completed.stdout) > 1_000_000:
        raise RegistryImageInvalid("registry_image_response_invalid")
    try:
        return json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as error:
        raise RegistryImageInvalid("registry_image_response_invalid") from error


def verify_registry_image(
    *,
    subscription_id: str,
    registry_name: str,
    repository: str,
    source_git_sha: str,
    expected_digest: str,
    image_input_sha256: str,
    environment: Mapping[str, str] = os.environ,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or REGISTRY_PATTERN.fullmatch(registry_name) is None
        or REPOSITORY_PATTERN.fullmatch(repository) is None
        or SHA_PATTERN.fullmatch(source_git_sha) is None
        or DIGEST_PATTERN.fullmatch(expected_digest) is None
        or re.fullmatch(r"[0-9a-f]{64}", image_input_sha256) is None
    ):
        raise RegistryImageInvalid("registry_image_authority_invalid")
    registry_server = f"{registry_name}.azurecr.io"
    exact_image = f"{registry_server}/{repository}@{expected_digest}"
    with tempfile.TemporaryDirectory(
        prefix="newcaostone-registry-verify-"
    ) as directory:
        process_env = {
            name: environment[name]
            for name in ("HOME", "PATH", "TMPDIR")
            if name in environment
        }
        process_env["DOCKER_CONFIG"] = str(Path(directory))
        try:
            token = registry_access_token(
                subscription_id=subscription_id,
                registry_name=registry_name,
                environment=environment,
                runner=runner,
            )
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
                (
                    "docker",
                    "pull",
                    "--platform",
                    "linux/amd64",
                    exact_image,
                ),
                check=True,
                capture_output=True,
                text=True,
                timeout=600,
                env=process_env,
            )
            inspected = _json_output(
                ("docker", "image", "inspect", exact_image),
                runner=runner,
                environment=process_env,
            )
        except (OSError, subprocess.SubprocessError, RegistryPublicationInvalid) as error:
            raise RegistryImageInvalid("registry_image_unavailable") from error

    if (
        not isinstance(inspected, list)
        or len(inspected) != 1
        or not isinstance(inspected[0], dict)
        or inspected[0].get("Os") != "linux"
        or inspected[0].get("Architecture") != "amd64"
        or exact_image not in inspected[0].get("RepoDigests", [])
        or inspected[0].get("Config", {}).get("Labels", {}).get(
            "org.opencontainers.image.revision"
        )
        != source_git_sha
        or inspected[0].get("Config", {}).get("Labels", {}).get(
            "org.opencontainers.image.bizpulse.image-input-sha256"
        )
        != image_input_sha256
    ):
        raise RegistryImageInvalid("registry_image_binding_invalid")
    return exact_image


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--source-git-sha", required=True)
    parser.add_argument("--expected-digest", required=True)
    parser.add_argument("--image-input-sha256", required=True)
    options = parser.parse_args(arguments)
    try:
        verify_registry_image(
            subscription_id=options.subscription,
            registry_name=options.registry,
            repository=options.repository,
            source_git_sha=options.source_git_sha,
            expected_digest=options.expected_digest,
            image_input_sha256=options.image_input_sha256,
        )
    except RegistryImageInvalid:
        print("registry_image_verification=failed")
        return 1
    print("registry_image_verification=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
