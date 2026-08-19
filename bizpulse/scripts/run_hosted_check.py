"""Resolve one exact Container App authority and run a bounded hosted check."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

_SCRIPT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_SCRIPT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_PROJECT_ROOT))

from scripts.verify_hosted_health import (  # noqa: E402
    HostedHealthInvalid,
    verify_hosted_health,
)
from scripts.verify_hosted_capacity import (  # noqa: E402
    HostedCapacityInvalid,
    verify_hosted_capacity,
)

UUID_PATTERN = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.IGNORECASE,
)
NAME_PATTERN = re.compile(r"[a-z][a-z0-9-]{1,62}[a-z0-9]")
IMAGE_PATTERN = re.compile(
    r"[a-z0-9]{5,50}\.azurecr\.io/[a-z0-9][a-z0-9._/-]{1,127}@sha256:[0-9a-f]{64}"
)


class HostedCheckInvalid(RuntimeError):
    """The exact hosted Azure authority or bounded check was not proved."""


def _read_app(
    arguments: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> dict[str, Any]:
    try:
        completed = runner(
            ["az", *arguments, "--only-show-errors", "--output", "json"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if len(completed.stdout) > 1_000_000:
            raise HostedCheckInvalid("hosted_check_resource_invalid")
        payload = json.loads(completed.stdout)
    except HostedCheckInvalid:
        raise
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise HostedCheckInvalid("hosted_check_resource_unavailable") from error
    if not isinstance(payload, dict):
        raise HostedCheckInvalid("hosted_check_resource_invalid")
    return payload


def run_hosted_check(
    *,
    subscription_id: str,
    resource_group: str,
    app_name: str,
    image: str,
    check: str,
    scenario: str = "core",
    expected_url: str | None = None,
    expected_revision_suffix: str | None = None,
    az_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    health_verifier: Callable[[str], None] = verify_hosted_health,
    browser_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    capacity_verifier: Callable[[str], None] = verify_hosted_capacity,
) -> None:
    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or NAME_PATTERN.fullmatch(resource_group) is None
        or NAME_PATTERN.fullmatch(app_name) is None
        or IMAGE_PATTERN.fullmatch(image) is None
        or check not in {"browser", "capacity", "health"}
        or scenario
        not in {"budget", "core", "full", "paid-ai", "provider-unavailable"}
        or (check in {"capacity", "health"} and scenario != "core")
    ):
        raise HostedCheckInvalid("hosted_check_authority_invalid")
    url = resolve_hosted_url(
        subscription_id=subscription_id,
        resource_group=resource_group,
        app_name=app_name,
        image=image,
        expected_url=expected_url,
        expected_revision_suffix=expected_revision_suffix,
        az_runner=az_runner,
    )
    if check == "health":
        try:
            health_verifier(url)
        except HostedHealthInvalid as error:
            raise HostedCheckInvalid("hosted_check_health_invalid") from error
        return
    if check == "capacity":
        try:
            capacity_verifier(url)
        except HostedCapacityInvalid as error:
            raise HostedCheckInvalid("hosted_check_capacity_invalid") from error
        return
    try:
        child_environment = {
            name: value
            for name in (
                "BIZPULSE_BROWSER_OPERATOR_PASSWORD",
                "HOME",
                "LANG",
                "LC_ALL",
                "PATH",
                "TMPDIR",
            )
            if (value := os.getenv(name)) is not None
        }
        completed = browser_runner(
            ["node", "scripts/browser_release_gate.mjs", url, scenario],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
            env=child_environment,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise HostedCheckInvalid("hosted_check_browser_failed") from error
    if completed.returncode != 0:
        raise HostedCheckInvalid("hosted_check_browser_failed")


def resolve_hosted_url(
    *,
    subscription_id: str,
    resource_group: str,
    app_name: str,
    image: str,
    expected_url: str | None = None,
    expected_revision_suffix: str | None = None,
    recovery_role: str | None = None,
    az_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    """Return only the server-issued FQDN for the exact active app/image."""

    if (
        UUID_PATTERN.fullmatch(subscription_id) is None
        or NAME_PATTERN.fullmatch(resource_group) is None
        or NAME_PATTERN.fullmatch(app_name) is None
        or IMAGE_PATTERN.fullmatch(image) is None
        or (expected_revision_suffix is not None and recovery_role is not None)
        or recovery_role not in {None, "current", "rollback"}
        or (
            expected_revision_suffix is not None
            and re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?", expected_revision_suffix)
            is None
        )
    ):
        raise HostedCheckInvalid("hosted_check_authority_invalid")
    app = _read_app(
        (
            "containerapp",
            "show",
            "--subscription",
            subscription_id,
            "--resource-group",
            resource_group,
            "--name",
            app_name,
        ),
        runner=az_runner,
    )
    expected_id = (
        f"/subscriptions/{subscription_id}/resourceGroups/{resource_group}"
        f"/providers/Microsoft.App/containerApps/{app_name}"
    )
    properties = app.get("properties", {})
    configuration = properties.get("configuration", {})
    ingress = configuration.get("ingress", {})
    containers = properties.get("template", {}).get("containers", [])
    traffic = ingress.get("traffic", [])
    fqdn = ingress.get("fqdn")
    url = f"https://{fqdn}"
    parsed = urlsplit(url)
    digest = image.rsplit("@sha256:", 1)[1]
    default_suffix = digest[:12]
    actual_revision = properties.get("latestRevisionName")
    expected_revision = f"{app_name}--{expected_revision_suffix or default_suffix}"
    actual_id = app.get("id")
    if recovery_role == "rollback":
        revision_matches = isinstance(actual_revision, str) and re.fullmatch(
            rf"{re.escape(app_name)}--rollback-[0-9a-f]{{8}}-{digest[:7]}",
            actual_revision,
        ) is not None
    elif recovery_role == "current":
        revision_matches = isinstance(actual_revision, str) and re.fullmatch(
            rf"{re.escape(app_name)}--(?:forward|recover)-[0-9a-f]{{8}}-{digest[:7]}",
            actual_revision,
        ) is not None
    else:
        revision_matches = actual_revision == expected_revision
    if (
        not isinstance(actual_id, str)
        or actual_id.casefold() != expected_id.casefold()
        or app.get("name") != app_name
        or configuration.get("activeRevisionsMode") != "Single"
        or not revision_matches
        or properties.get("latestReadyRevisionName") != actual_revision
        or properties.get("provisioningState") != "Succeeded"
        or ingress.get("external") is not True
        or not isinstance(fqdn, str)
        or not fqdn.startswith(f"{app_name}.")
        or not fqdn.endswith(".azurecontainerapps.io")
        or parsed.hostname != fqdn
        or len(containers) != 1
        or containers[0].get("image") != image
        or not isinstance(traffic, list)
        or len(traffic) != 1
        or not isinstance(traffic[0], dict)
        or traffic[0].get("latestRevision") is not True
        or traffic[0].get("weight") != 100
        or traffic[0].get("revisionName") not in {None, expected_revision}
        or (expected_url is not None and expected_url.rstrip("/") != url)
    ):
        raise HostedCheckInvalid("hosted_check_resource_invalid")
    return url


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--resource-group", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--image", required=True)
    parser.add_argument(
        "--check",
        choices=("browser", "capacity", "health"),
        required=True,
    )
    parser.add_argument(
        "--scenario",
        choices=("budget", "core", "full", "paid-ai", "provider-unavailable"),
        default="core",
    )
    parser.add_argument("--expected-url")
    parser.add_argument("--expected-revision-suffix")
    options = parser.parse_args(arguments)
    try:
        run_hosted_check(
            subscription_id=options.subscription,
            resource_group=options.resource_group,
            app_name=options.app,
            image=options.image,
            check=options.check,
            scenario=options.scenario,
            expected_url=options.expected_url,
            expected_revision_suffix=options.expected_revision_suffix,
        )
    except HostedCheckInvalid:
        print("hosted_check=failed")
        return 1
    print("hosted_check=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
