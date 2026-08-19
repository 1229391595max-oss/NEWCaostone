from __future__ import annotations

import json
import subprocess

import pytest

from scripts.run_hosted_check import HostedCheckInvalid, run_hosted_check

SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
RESOURCE_GROUP = "rg-approved"
APP = "bp-approved-app"
IMAGE = "bpapprovedregistry.azurecr.io/bizpulse@sha256:" + "b" * 64
URL = "https://bp-approved-app.synthetic.brazilsouth.azurecontainerapps.io"


def _az_app(*, fqdn: str = URL.removeprefix("https://"), external: bool = True):
    revision = f"{APP}--{'b' * 12}"
    return {
        "id": (
            f"/subscriptions/{SUBSCRIPTION}/resourceGroups/{RESOURCE_GROUP}"
            f"/providers/Microsoft.App/containerApps/{APP}"
        ),
        "name": APP,
        "properties": {
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": external,
                    "fqdn": fqdn,
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
            },
            "latestRevisionName": revision,
            "latestReadyRevisionName": revision,
            "provisioningState": "Succeeded",
            "template": {"containers": [{"image": IMAGE}]},
        },
    }


def _runner(payload: object):
    return lambda command, **_kwargs: subprocess.CompletedProcess(
        command,
        0,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_hosted_check_binds_server_fqdn_resource_image_and_strict_health() -> None:
    checked: list[str] = []
    run_hosted_check(
        subscription_id=SUBSCRIPTION,
        resource_group=RESOURCE_GROUP,
        app_name=APP,
        image=IMAGE,
        check="health",
        az_runner=_runner(_az_app()),
        health_verifier=checked.append,
    )
    assert checked == [URL]


def test_hosted_check_accepts_azure_resource_id_casing() -> None:
    app = _az_app()
    app["id"] = app["id"].replace(
        "/resourceGroups/", "/resourcegroups/"
    ).replace("/containerApps/", "/containerapps/")

    checked: list[str] = []
    run_hosted_check(
        subscription_id=SUBSCRIPTION,
        resource_group=RESOURCE_GROUP,
        app_name=APP,
        image=IMAGE,
        check="health",
        az_runner=_runner(app),
        health_verifier=checked.append,
    )

    assert checked == [URL]


def test_hosted_check_rejects_wrong_fqdn_or_inactive_ingress() -> None:
    for app in (
        _az_app(fqdn="bp-approved-app.attacker.example"),
        _az_app(external=False),
    ):
        with pytest.raises(HostedCheckInvalid, match="hosted_check_resource_invalid"):
            run_hosted_check(
                subscription_id=SUBSCRIPTION,
                resource_group=RESOURCE_GROUP,
                app_name=APP,
                image=IMAGE,
                check="health",
                az_runner=_runner(app),
                health_verifier=lambda _url: None,
            )


def test_hosted_check_rejects_revision_or_traffic_drift() -> None:
    wrong_revision = _az_app()
    wrong_revision["properties"]["latestRevisionName"] = f"{APP}--old"
    multiple = _az_app()
    multiple["properties"]["configuration"]["activeRevisionsMode"] = "Multiple"
    split = _az_app()
    split["properties"]["configuration"]["ingress"]["traffic"] = [
        {"latestRevision": True, "weight": 50},
        {"revisionName": f"{APP}--old", "weight": 50},
    ]
    unready = _az_app()
    unready["properties"]["latestReadyRevisionName"] = f"{APP}--old"
    failed = _az_app()
    failed["properties"]["provisioningState"] = "Failed"
    for app in (wrong_revision, multiple, split, unready, failed):
        with pytest.raises(HostedCheckInvalid, match="hosted_check_resource_invalid"):
            run_hosted_check(
                subscription_id=SUBSCRIPTION,
                resource_group=RESOURCE_GROUP,
                app_name=APP,
                image=IMAGE,
                check="health",
                az_runner=_runner(app),
                health_verifier=lambda _url: None,
            )


def test_browser_check_passes_only_minimal_child_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BIZPULSE_BROWSER_OPERATOR_PASSWORD", "operator-secret")
    monkeypatch.setenv("BIZPULSE_DEPLOY_POSTGRES_PASSWORD", "database-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    captured: list[dict[str, str]] = []

    def browser(command, **kwargs):
        captured.append(kwargs["env"])
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    run_hosted_check(
        subscription_id=SUBSCRIPTION,
        resource_group=RESOURCE_GROUP,
        app_name=APP,
        image=IMAGE,
        check="browser",
        scenario="core",
        az_runner=_runner(_az_app()),
        browser_runner=browser,
    )

    assert captured[0]["BIZPULSE_BROWSER_OPERATOR_PASSWORD"] == "operator-secret"
    assert "BIZPULSE_DEPLOY_POSTGRES_PASSWORD" not in captured[0]
    assert "OPENAI_API_KEY" not in captured[0]


def test_capacity_check_uses_server_issued_url_without_provider() -> None:
    checked: list[str] = []
    run_hosted_check(
        subscription_id=SUBSCRIPTION,
        resource_group=RESOURCE_GROUP,
        app_name=APP,
        image=IMAGE,
        check="capacity",
        az_runner=_runner(_az_app()),
        capacity_verifier=checked.append,
    )
    assert checked == [URL]


@pytest.mark.parametrize("scenario", ["provider-unavailable", "budget"])
def test_failure_browser_checks_are_explicit_and_same_image(
    scenario: str,
) -> None:
    commands: list[list[str]] = []

    def browser(command, **_kwargs):
        commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="{}", stderr="")

    run_hosted_check(
        subscription_id=SUBSCRIPTION,
        resource_group=RESOURCE_GROUP,
        app_name=APP,
        image=IMAGE,
        check="browser",
        scenario=scenario,
        az_runner=_runner(_az_app()),
        browser_runner=browser,
    )

    assert commands == [["node", "scripts/browser_release_gate.mjs", URL, scenario]]
