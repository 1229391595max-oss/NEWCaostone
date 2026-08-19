from __future__ import annotations

import json
import subprocess

import pytest

from scripts.publish_registry_image import (
    RegistryPublicationInvalid,
    publish_registry_image,
    publish_registry_image_discover_digest,
)

SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
AUTHORIZATION = "22222222-2222-4222-8222-222222222222"
GIT_SHA = "a" * 40
DIGEST = "sha256:" + "b" * 64
IMAGE_INPUT = "c" * 64
PACKAGE_SHA256 = "d" * 64
BUILD_CONTEXT_SHA256 = "e" * 64


def test_registry_publish_discovers_one_package_bound_immutable_digest() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(command, **kwargs):
        calls.append((tuple(command), kwargs))
        if command[1:3] == ["image", "inspect"]:
            payload = [
                {
                    "Architecture": "amd64",
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": GIT_SHA,
                            "org.opencontainers.image.bizpulse.image-input-sha256": (
                                IMAGE_INPUT
                            ),
                            "org.opencontainers.image.bizpulse.build-context-sha256": (
                                BUILD_CONTEXT_SHA256
                            ),
                        }
                    },
                    "Os": "linux",
                }
            ]
        elif command[:4] == ["az", "acr", "login", "--name"]:
            payload = {
                "accessToken": "synthetic-access-token-0123456789abcdef",
                "loginServer": "bpapprovedregistry.azurecr.io",
            }
        elif command[:4] == ["az", "acr", "repository", "show-tags"]:
            payload = [
                {
                    "digest": DIGEST,
                    "name": f"ai-{GIT_SHA[:12]}-{PACKAGE_SHA256[:8]}",
                }
            ]
        elif command[:4] == ["az", "acr", "manifest", "show-metadata"]:
            raise AssertionError("preview metadata query must not be used")
        else:
            payload = {}
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    assert publish_registry_image_discover_digest(
        subscription_id=SUBSCRIPTION,
        registry_name="bpapprovedregistry",
        repository="bizpulse",
        candidate_git_sha=GIT_SHA,
        package_sha256=PACKAGE_SHA256,
        image_input_sha256=IMAGE_INPUT,
        build_context_sha256=BUILD_CONTEXT_SHA256,
        runner=runner,
    ) == DIGEST

    tag = f"ai-{GIT_SHA[:12]}-{PACKAGE_SHA256[:8]}"
    assert calls[3][0][-1].endswith(f"/bizpulse:{tag}")
    assert calls[4][0] == (
        "docker",
        "push",
        f"bpapprovedregistry.azurecr.io/bizpulse:{tag}",
    )
    assert calls[5][0] == (
        "az",
        "acr",
        "repository",
        "show-tags",
        "--subscription",
        SUBSCRIPTION,
        "--name",
        "bpapprovedregistry",
        "--repository",
        "bizpulse",
        "--detail",
        "--query",
        f"[?name=='{tag}']",
        "--only-show-errors",
        "--output",
        "json",
    )
    assert calls[2][1]["input"] == "synthetic-access-token-0123456789abcdef"
    assert "synthetic-access-token-0123456789abcdef" not in " ".join(calls[2][0])


def test_registry_publish_refuses_mismatched_exact_build_context_label() -> None:
    def runner(command, **_kwargs):
        assert command[1:3] == ["image", "inspect"]
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(
                [
                    {
                        "Architecture": "amd64",
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.revision": GIT_SHA,
                                "org.opencontainers.image.bizpulse.image-input-sha256": IMAGE_INPUT,
                                "org.opencontainers.image.bizpulse.build-context-sha256": "f"
                                * 64,
                            }
                        },
                        "Os": "linux",
                    }
                ]
            ),
            stderr="",
        )

    with pytest.raises(RegistryPublicationInvalid, match="local_image_invalid"):
        publish_registry_image_discover_digest(
            subscription_id=SUBSCRIPTION,
            registry_name="bpapprovedregistry",
            repository="bizpulse",
            candidate_git_sha=GIT_SHA,
            package_sha256=PACKAGE_SHA256,
            image_input_sha256=IMAGE_INPUT,
            build_context_sha256=BUILD_CONTEXT_SHA256,
            runner=runner,
        )


def test_registry_publish_never_inherits_browser_operator_credential() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(command, **kwargs):
        calls.append((tuple(command), kwargs))
        if command[1:3] == ["image", "inspect"]:
            payload = [
                {
                    "Architecture": "amd64",
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": GIT_SHA,
                            "org.opencontainers.image.bizpulse.image-input-sha256": (
                                IMAGE_INPUT
                            ),
                        }
                    },
                    "Os": "linux",
                }
            ]
        elif command[:4] == ["az", "acr", "login", "--name"]:
            payload = {
                "accessToken": "synthetic-access-token-0123456789abcdef",
                "loginServer": "bpapprovedregistry.azurecr.io",
            }
        elif command[:4] == ["az", "acr", "repository", "show-tags"]:
            payload = [
                {
                    "digest": DIGEST,
                    "name": f"ai-{GIT_SHA[:12]}-{PACKAGE_SHA256[:8]}",
                }
            ]
        else:
            payload = {}
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    assert publish_registry_image_discover_digest(
        subscription_id=SUBSCRIPTION,
        registry_name="bpapprovedregistry",
        repository="bizpulse",
        candidate_git_sha=GIT_SHA,
        package_sha256=PACKAGE_SHA256,
        image_input_sha256=IMAGE_INPUT,
        environment={
            "HOME": "/safe-home",
            "PATH": "/safe-bin",
            "BIZPULSE_BROWSER_OPERATOR_PASSWORD": "operator-secret",
            "UNRELATED_SECRET": "must-not-inherit",
        },
        runner=runner,
    ) == DIGEST

    assert all(
        "BIZPULSE_BROWSER_OPERATOR_PASSWORD" not in kwargs["env"]
        and "UNRELATED_SECRET" not in kwargs["env"]
        for _command, kwargs in calls
    )
    assert calls[0][1]["env"] == {"HOME": "/safe-home", "PATH": "/safe-bin"}
    assert calls[-1][1]["env"] == {"HOME": "/safe-home", "PATH": "/safe-bin"}


@pytest.mark.parametrize(
    "tag_details",
    [
        [],
        {},
        ["not-a-tag-detail"],
        [{"name": f"ai-{GIT_SHA[:12]}-{PACKAGE_SHA256[:8]}", "digest": "bad"}],
        [{"name": "wrong-tag", "digest": DIGEST}],
        [
            {"name": f"ai-{GIT_SHA[:12]}-{PACKAGE_SHA256[:8]}", "digest": DIGEST},
            {"name": f"ai-{GIT_SHA[:12]}-{PACKAGE_SHA256[:8]}", "digest": DIGEST},
        ],
    ],
)
def test_registry_publish_rejects_invalid_tag_details(tag_details: object) -> None:
    def runner(command, **_kwargs):
        if command[1:3] == ["image", "inspect"]:
            output = json.dumps(
                [
                    {
                        "Architecture": "amd64",
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.revision": GIT_SHA,
                                "org.opencontainers.image.bizpulse.image-input-sha256": (
                                    IMAGE_INPUT
                                ),
                            }
                        },
                        "Os": "linux",
                    }
                ]
            )
        elif command[:4] == ["az", "acr", "login", "--name"]:
            output = json.dumps(
                {
                    "accessToken": "synthetic-access-token-0123456789abcdef",
                    "loginServer": "bpapprovedregistry.azurecr.io",
                }
            )
        elif command[:4] == ["az", "acr", "repository", "show-tags"]:
            output = json.dumps(tag_details)
        else:
            output = "{}"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    with pytest.raises(RegistryPublicationInvalid, match="digest_mismatch"):
        publish_registry_image_discover_digest(
            subscription_id=SUBSCRIPTION,
            registry_name="bpapprovedregistry",
            repository="bizpulse",
            candidate_git_sha=GIT_SHA,
            package_sha256=PACKAGE_SHA256,
            image_input_sha256=IMAGE_INPUT,
            runner=runner,
        )


def test_registry_publish_binds_local_revision_and_remote_digest() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def runner(command, **kwargs):
        calls.append((tuple(command), kwargs))
        if command[1:3] == ["image", "inspect"]:
            payload = [
                {
                    "Architecture": "amd64",
                    "Config": {
                        "Labels": {
                            "org.opencontainers.image.revision": GIT_SHA,
                            "org.opencontainers.image.bizpulse.image-input-sha256": IMAGE_INPUT,
                        }
                    },
                    "Os": "linux",
                }
            ]
        elif command[:4] == ["az", "acr", "login", "--name"]:
            payload = {
                "accessToken": "synthetic-access-token-0123456789abcdef",
                "loginServer": "bpapprovedregistry.azurecr.io",
            }
        elif command[:4] == ["az", "acr", "manifest", "show-metadata"]:
            payload = {
                "digest": DIGEST,
                "tags": [f"candidate-{GIT_SHA[:12]}-{AUTHORIZATION[:8]}"],
            }
        else:
            payload = {}
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(payload), stderr=""
        )

    target = publish_registry_image(
        subscription_id=SUBSCRIPTION,
        registry_name="bpapprovedregistry",
        repository="bizpulse",
        candidate_git_sha=GIT_SHA,
        authorization_id=AUTHORIZATION,
        expected_digest=DIGEST,
        image_input_sha256=IMAGE_INPUT,
        runner=runner,
    )

    assert target == (
        "bpapprovedregistry.azurecr.io/bizpulse:"
        f"candidate-{GIT_SHA[:12]}-{AUTHORIZATION[:8]}"
    )
    assert calls[0][0][-1] == f"newcaostone-local:{GIT_SHA[:12]}"
    token = calls[1]
    assert token[0][:4] == ("az", "acr", "login", "--name")
    assert "--expose-token" in token[0]
    login = calls[2]
    assert login[0][0:3] == ("docker", "login", "bpapprovedregistry.azurecr.io")
    assert login[1]["input"] == "synthetic-access-token-0123456789abcdef"
    assert "synthetic-access-token-0123456789abcdef" not in " ".join(login[0])
    assert calls[4][0][0:2] == ("docker", "push")
    assert calls[5][0][0:4] == ("az", "acr", "manifest", "show-metadata")


def test_registry_publish_recovers_push_ack_loss_from_exact_manifest() -> None:
    def runner(command, **_kwargs):
        if command[1:3] == ["image", "inspect"]:
            output = json.dumps(
                [
                    {
                        "Architecture": "amd64",
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.revision": GIT_SHA,
                                "org.opencontainers.image.bizpulse.image-input-sha256": IMAGE_INPUT,
                            }
                        },
                        "Os": "linux",
                    }
                ]
            )
        elif command[:4] == ["az", "acr", "login", "--name"]:
            output = json.dumps(
                {
                    "accessToken": "synthetic-access-token-0123456789abcdef",
                    "loginServer": "bpapprovedregistry.azurecr.io",
                }
            )
        elif command[0:2] == ["docker", "push"]:
            raise subprocess.TimeoutExpired(command, timeout=300)
        elif command[:4] == ["az", "acr", "manifest", "show-metadata"]:
            output = json.dumps(
                {
                    "digest": DIGEST,
                    "tags": [f"candidate-{GIT_SHA[:12]}-{AUTHORIZATION[:8]}"],
                }
            )
        else:
            output = "{}"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    assert publish_registry_image(
        subscription_id=SUBSCRIPTION,
        registry_name="bpapprovedregistry",
        repository="bizpulse",
        candidate_git_sha=GIT_SHA,
        authorization_id=AUTHORIZATION,
        expected_digest=DIGEST,
        image_input_sha256=IMAGE_INPUT,
        runner=runner,
    ).endswith(f"candidate-{GIT_SHA[:12]}-{AUTHORIZATION[:8]}")


def test_registry_publish_rejects_digest_or_label_mismatch() -> None:
    def runner(command, **_kwargs):
        if command[1:3] == ["image", "inspect"]:
            output = json.dumps(
                [
                    {
                        "Architecture": "amd64",
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.revision": "c" * 40,
                                "org.opencontainers.image.bizpulse.image-input-sha256": IMAGE_INPUT,
                            }
                        },
                        "Os": "linux",
                    }
                ]
            )
        else:
            output = "{}"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    with pytest.raises(RegistryPublicationInvalid):
        publish_registry_image(
            subscription_id=SUBSCRIPTION,
            registry_name="bpapprovedregistry",
            repository="bizpulse",
            candidate_git_sha=GIT_SHA,
            authorization_id=AUTHORIZATION,
            expected_digest=DIGEST,
            image_input_sha256=IMAGE_INPUT,
            runner=runner,
        )
