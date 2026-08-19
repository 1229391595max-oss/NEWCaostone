from __future__ import annotations

import json
import subprocess

import pytest

from scripts.verify_registry_image import (
    RegistryImageInvalid,
    verify_registry_image,
)

GIT_SHA = "a" * 40
SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
DIGEST = "sha256:" + "b" * 64
IMAGE_INPUT = "c" * 64
EXACT_IMAGE = f"bpapprovedregistry.azurecr.io/bizpulse@{DIGEST}"


def _runner_for(*, revision: str = GIT_SHA):
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def run(command, **kwargs):
        calls.append((tuple(command), kwargs))
        if tuple(command[:4]) == ("az", "acr", "login", "--name"):
            output = json.dumps(
                {
                    "accessToken": "synthetic-access-token-0123456789abcdef",
                    "loginServer": "bpapprovedregistry.azurecr.io",
                }
            )
        elif tuple(command[:3]) == ("docker", "image", "inspect"):
            output = json.dumps(
                [
                    {
                        "Architecture": "amd64",
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.revision": revision,
                                "org.opencontainers.image.bizpulse.image-input-sha256": IMAGE_INPUT,
                            }
                        },
                        "Os": "linux",
                        "RepoDigests": [EXACT_IMAGE],
                    }
                ]
            )
        else:
            output = "{}"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    return run, calls


def test_remote_registry_image_binds_digest_revision_and_input_hash() -> None:
    runner, calls = _runner_for()

    assert verify_registry_image(
        subscription_id=SUBSCRIPTION,
        registry_name="bpapprovedregistry",
        repository="bizpulse",
        source_git_sha=GIT_SHA,
        expected_digest=DIGEST,
        image_input_sha256=IMAGE_INPUT,
        environment={"PATH": "/usr/bin"},
        runner=runner,
    ) == EXACT_IMAGE

    token = calls[0]
    assert token[0][:4] == ("az", "acr", "login", "--name")
    assert "--expose-token" in token[0]
    login = calls[1]
    assert login[0][:3] == ("docker", "login", "bpapprovedregistry.azurecr.io")
    assert login[1]["input"] == "synthetic-access-token-0123456789abcdef"
    assert "synthetic-access-token-0123456789abcdef" not in " ".join(login[0])
    assert calls[2][0] == (
        "docker",
        "pull",
        "--platform",
        "linux/amd64",
        EXACT_IMAGE,
    )
    assert calls[3][0] == ("docker", "image", "inspect", EXACT_IMAGE)


def test_remote_registry_image_rejects_digest_to_source_mismatch() -> None:
    runner, _calls = _runner_for(revision="d" * 40)

    with pytest.raises(RegistryImageInvalid, match="registry_image_binding_invalid"):
        verify_registry_image(
            subscription_id=SUBSCRIPTION,
            registry_name="bpapprovedregistry",
            repository="bizpulse",
            source_git_sha=GIT_SHA,
            expected_digest=DIGEST,
            image_input_sha256=IMAGE_INPUT,
            environment={"PATH": "/usr/bin"},
            runner=runner,
        )
