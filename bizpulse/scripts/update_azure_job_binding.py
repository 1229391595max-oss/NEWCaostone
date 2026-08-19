#!/usr/bin/env python3
"""Atomically replace an existing Azure Container Apps Job container binding."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tempfile
from typing import Any


UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
)
RESOURCE_GROUP_PATTERN = re.compile(r"[A-Za-z0-9._()/-]{1,90}")
NAME_PATTERN = re.compile(r"[a-z](?:[a-z0-9-]{1,61}[a-z0-9])?")
IMAGE_PATTERN = re.compile(r"[^@\s]+@sha256:[0-9a-f]{64}")


class AzureJobBindingInvalid(RuntimeError):
    """The requested Job binding or Azure response is not exact."""


def _string_list(value: object, code: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise AzureJobBindingInvalid(code)
    return list(value)


def _job_copy_and_container(
    job: object,
    *,
    subscription_id: str,
    resource_group: str,
    job_name: str,
    container_name: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if (
        not isinstance(job, Mapping)
        or UUID_PATTERN.fullmatch(subscription_id) is None
        or RESOURCE_GROUP_PATTERN.fullmatch(resource_group) is None
        or NAME_PATTERN.fullmatch(job_name) is None
        or NAME_PATTERN.fullmatch(container_name) is None
    ):
        raise AzureJobBindingInvalid("azure_job_binding_target_invalid")
    expected_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}/"
        f"providers/Microsoft.App/jobs/{job_name}"
    )
    if str(job.get("id", "")).lower() != expected_id.lower():
        raise AzureJobBindingInvalid("azure_job_binding_target_invalid")
    try:
        containers = job["properties"]["template"]["containers"]
    except (KeyError, TypeError) as error:
        raise AzureJobBindingInvalid(
            "azure_job_binding_container_invalid"
        ) from error
    if (
        not isinstance(containers, list)
        or len(containers) != 1
        or not isinstance(containers[0], Mapping)
        or containers[0].get("name") != container_name
    ):
        raise AzureJobBindingInvalid("azure_job_binding_container_invalid")
    updated = deepcopy(dict(job))
    container = updated["properties"]["template"]["containers"][0]
    return updated, container


def build_job_binding_patch(
    job: object,
    *,
    subscription_id: str,
    resource_group: str,
    job_name: str,
    container_name: str,
    image: str,
    command: list[str],
    arguments: list[str],
) -> dict[str, Any]:
    if IMAGE_PATTERN.fullmatch(image) is None:
        raise AzureJobBindingInvalid("azure_job_binding_target_invalid")
    updated, container = _job_copy_and_container(
        job,
        subscription_id=subscription_id,
        resource_group=resource_group,
        job_name=job_name,
        container_name=container_name,
    )
    container["image"] = image
    container["command"] = _string_list(command, "azure_job_binding_command_invalid")
    container["args"] = _string_list(arguments, "azure_job_binding_arguments_invalid")
    return updated


def validate_job_binding(
    job: object,
    *,
    subscription_id: str,
    resource_group: str,
    job_name: str,
    container_name: str,
    image: str,
    command: list[str],
    arguments: list[str],
) -> dict[str, Any]:
    if IMAGE_PATTERN.fullmatch(image) is None:
        raise AzureJobBindingInvalid("azure_job_binding_target_invalid")
    validated, container = _job_copy_and_container(
        job,
        subscription_id=subscription_id,
        resource_group=resource_group,
        job_name=job_name,
        container_name=container_name,
    )
    if (
        container.get("image") != image
        or container.get("command") != _string_list(
            command, "azure_job_binding_command_invalid"
        )
        or container.get("args") != _string_list(
            arguments, "azure_job_binding_arguments_invalid"
        )
    ):
        raise AzureJobBindingInvalid("azure_job_binding_readback_invalid")
    return validated


def _az_json(arguments: list[str], code: str) -> dict[str, Any]:
    try:
        completed = subprocess.run(
            ["az", *arguments, "--only-show-errors", "--output", "json"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise AzureJobBindingInvalid(code) from error
    if completed.returncode != 0:
        raise AzureJobBindingInvalid(code)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise AzureJobBindingInvalid(code) from error
    if not isinstance(payload, dict):
        raise AzureJobBindingInvalid(code)
    return payload


def update_job_binding(
    *,
    subscription_id: str,
    resource_group: str,
    job_name: str,
    container_name: str,
    image: str,
    command: list[str],
    arguments: list[str],
) -> None:
    current = _az_json(
        [
            "containerapp",
            "job",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            job_name,
        ],
        "azure_job_binding_read_failed",
    )
    update_document = build_job_binding_patch(
        current,
        subscription_id=subscription_id,
        resource_group=resource_group,
        job_name=job_name,
        container_name=container_name,
        image=image,
        command=command,
        arguments=arguments,
    )
    descriptor, raw_path = tempfile.mkstemp(
        prefix="bizpulse-job-binding-",
        suffix=".json",
    )
    document_path = Path(raw_path)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(update_document, stream, separators=(",", ":"))
        if stat.S_IMODE(document_path.stat().st_mode) != 0o600:
            raise AzureJobBindingInvalid("azure_job_binding_document_invalid")
        _az_json(
            [
                "containerapp",
                "job",
                "update",
                "--subscription",
                subscription_id,
                "--resource-group",
                resource_group,
                "--name",
                job_name,
                "--yaml",
                str(document_path),
            ],
            "azure_job_binding_update_failed",
        )
    finally:
        document_path.unlink(missing_ok=True)
    updated = _az_json(
        [
            "containerapp",
            "job",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            job_name,
        ],
        "azure_job_binding_readback_failed",
    )
    validate_job_binding(
        updated,
        subscription_id=subscription_id,
        resource_group=resource_group,
        job_name=job_name,
        container_name=container_name,
        image=image,
        command=command,
        arguments=arguments,
    )


def _json_list(value: str, code: str) -> list[str]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as error:
        raise AzureJobBindingInvalid(code) from error
    return _string_list(payload, code)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--container-name", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument("--command-json", required=True)
    parser.add_argument("--arguments-json", required=True)
    options = parser.parse_args(argv)
    try:
        update_job_binding(
            subscription_id=options.subscription,
            resource_group=options.resource_group,
            job_name=options.job,
            container_name=options.container_name,
            image=options.image,
            command=_json_list(
                options.command_json,
                "azure_job_binding_command_invalid",
            ),
            arguments=_json_list(
                options.arguments_json,
                "azure_job_binding_arguments_invalid",
            ),
        )
    except AzureJobBindingInvalid as error:
        print(str(error))
        print("azure_job_binding=failed")
        return 1
    print("azure_job_binding=updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
