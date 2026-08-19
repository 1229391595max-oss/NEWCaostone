from __future__ import annotations

import importlib
import json
from pathlib import Path
import stat

import pytest


def _subject():
    try:
        return importlib.import_module("scripts.update_azure_job_binding")
    except ModuleNotFoundError:
        pytest.fail("atomic Azure Job binding helper is not implemented")


def _job() -> dict[str, object]:
    return {
        "id": (
            "/subscriptions/11111111-1111-4111-8111-111111111111/"
            "resourceGroups/rg-approved/providers/Microsoft.App/jobs/bp-seed"
        ),
        "properties": {
            "template": {
                "containers": [
                    {
                        "name": "seed",
                        "image": "registry.example/bizpulse@sha256:" + "a" * 64,
                        "command": ["python"],
                        "args": ["old"],
                        "env": [
                            {"name": "DATABASE_URL", "secretRef": "postgres-url"}
                        ],
                        "resources": {"cpu": 0.5, "memory": "1Gi"},
                    }
                ]
            }
        },
    }


def test_job_patch_preserves_container_authority_and_replaces_binding() -> None:
    subject = _subject()
    image = "registry.example/bizpulse@sha256:" + "b" * 64
    arguments = ["seed.py", "--expected-manifest-sha256", "c" * 64]

    patch = subject.build_job_binding_patch(
        _job(),
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-approved",
        job_name="bp-seed",
        container_name="seed",
        image=image,
        command=["python"],
        arguments=arguments,
    )

    container = patch["properties"]["template"]["containers"][0]
    assert container["image"] == image
    assert container["command"] == ["python"]
    assert container["args"] == arguments
    assert container["env"] == [
        {"name": "DATABASE_URL", "secretRef": "postgres-url"}
    ]
    assert container["resources"] == {"cpu": 0.5, "memory": "1Gi"}


def test_job_patch_rejects_target_or_shape_drift() -> None:
    subject = _subject()
    job = _job()
    job["properties"]["template"]["containers"].append(
        {"name": "unexpected", "image": "example.invalid/other"}
    )

    with pytest.raises(
        subject.AzureJobBindingInvalid,
        match="azure_job_binding_container_invalid",
    ):
        subject.build_job_binding_patch(
            job,
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-approved",
            job_name="bp-seed",
            container_name="seed",
            image="registry.example/bizpulse@sha256:" + "b" * 64,
            command=["python"],
            arguments=["seed.py"],
        )


def test_job_binding_readback_rejects_old_arguments() -> None:
    subject = _subject()

    with pytest.raises(
        subject.AzureJobBindingInvalid,
        match="azure_job_binding_readback_invalid",
    ):
        subject.validate_job_binding(
            _job(),
            subscription_id="11111111-1111-4111-8111-111111111111",
            resource_group="rg-approved",
            job_name="bp-seed",
            container_name="seed",
            image="registry.example/bizpulse@sha256:" + "b" * 64,
            command=["python"],
            arguments=["seed.py"],
        )


def test_update_job_binding_uses_mode_600_yaml_document(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    subject = _subject()
    image = "registry.example/bizpulse@sha256:" + "b" * 64
    arguments = ["seed.py", "--expected-manifest-sha256", "c" * 64]
    calls: list[list[str]] = []
    document_path: Path | None = None
    bound_job: dict[str, object] | None = None

    def fake_az_json(argv: list[str], _code: str) -> dict[str, object]:
        nonlocal bound_job, document_path
        calls.append(argv)
        if argv[1:3] == ["job", "show"]:
            return bound_job or _job()
        document_path = Path(argv[argv.index("--yaml") + 1])
        assert stat.S_IMODE(document_path.stat().st_mode) == 0o600
        bound_job = json.loads(document_path.read_text())
        return bound_job

    monkeypatch.setattr(subject, "_az_json", fake_az_json)

    subject.update_job_binding(
        subscription_id="11111111-1111-4111-8111-111111111111",
        resource_group="rg-approved",
        job_name="bp-seed",
        container_name="seed",
        image=image,
        command=["python"],
        arguments=arguments,
    )

    assert calls[0][:3] == ["containerapp", "job", "show"]
    assert calls[1][:3] == ["containerapp", "job", "update"]
    assert calls[2][:3] == ["containerapp", "job", "show"]
    assert document_path is not None
    assert not document_path.exists()
