from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import phase1_receipt as receipt_module
from scripts.phase1_receipt import (
    Phase1ReceiptInvalid,
    collect_from_azure,
    collect_legacy_receipt,
    verify_receipt,
    write_receipt,
)
from tests.hosted.test_verify_azure_demo import _authorization, _write


SOURCE_SHA256 = "a" * 64
IMAGE_DIGEST = "sha256:" + "b" * 64
ROLLBACK_DIGEST = "sha256:" + "c" * 64
IMAGE = f"bpapprovedregistry.azurecr.io/bizpulse@{IMAGE_DIGEST}"
ANCHOR = "2026-08-15T22:20:24Z"
OBSERVED = datetime(2026, 8, 15, 22, 27, tzinfo=UTC)


def _source_authority() -> dict[str, object]:
    fence = (
        ".venv/bin/python scripts/verify_phase1_fence.py "
        "--subscription 11111111-1111-4111-8111-111111111111 "
        "--resource-group rg-approved --app bp-approved-app "
        f"--image {IMAGE} "
        "--prepare-job bp-approved-prepare --seed-job bp-approved-seed "
        "--session-job bp-approved-sessions --storage-job bp-approved-storage "
        "--storage-account bpapprovedstorage --blob-container synthetic-demo "
        f"--synthetic-manifest-sha256 {'d' * 64} "
        "--synthetic-dataset-version-id 33333333-3333-4333-8333-333333333333 "
        "--environment bp-approved-env --ai-enabled false "
        "--ai-daily-attempt-limit 25 --ai-monthly-token-limit 25000 "
        "--ai-max-concurrent-turns 15 "
        "--ai-session-attempt-limit-per-minute 2 "
        "--ai-global-attempt-limit-per-minute 20 "
        "--demo-session-rate-limit-per-hour 50 --mode initial"
    )
    return {
        "authorization_id": "22222222-2222-4222-8222-222222222222",
        "release": {
            "git_sha": "e" * 40,
            "image_digest": IMAGE_DIGEST,
            "image_input_sha256": "f" * 64,
            "rollback_git_sha": "1" * 40,
            "rollback_image_digest": ROLLBACK_DIGEST,
            "rollback_image_input_sha256": "2" * 64,
        },
        "commands": {
            "provision": [
                "az provider register --namespace Microsoft.App",
                (
                    "az deployment group create --subscription "
                    "11111111-1111-4111-8111-111111111111 "
                    "--resource-group rg-approved --name bp-approved-phase1"
                ),
                fence,
            ]
        },
    }


def _deployment() -> dict[str, object]:
    return {
        "id": (
            "/subscriptions/11111111-1111-4111-8111-111111111111/"
            "resourceGroups/rg-approved/providers/Microsoft.Resources/"
            "deployments/bp-approved-phase1"
        ),
        "name": "bp-approved-phase1",
        "properties": {
            "provisioningState": "Succeeded",
            "timestamp": ANCHOR,
        },
    }


def _app() -> dict[str, object]:
    return {
        "name": "bp-approved-app",
        "properties": {
            "latestRevisionName": "bp-approved-app--prep-bbbbbbb",
            "configuration": {
                "activeRevisionsMode": "Single",
                "ingress": {
                    "external": False,
                    "traffic": [{"latestRevision": True, "weight": 100}],
                },
                "secrets": [],
            },
            "template": {
                "containers": [
                    {
                        "name": "bizpulse",
                        "image": IMAGE,
                        "command": ["python"],
                        "args": ["scripts/phase1_fence_server.py"],
                        "env": [
                            {
                                "name": "BIZPULSE_RUNTIME_ENVIRONMENT",
                                "value": "phase1-fenced",
                            }
                        ],
                    }
                ],
                "scale": {"maxReplicas": 1, "minReplicas": 0},
            },
        },
    }


def _revisions() -> list[dict[str, object]]:
    return [
        {
            "name": "bp-approved-app--prep-bbbbbbb",
            "properties": {"replicas": 0},
        }
    ]


def _job(name: str, role: str, args: list[str]) -> dict[str, object]:
    return {
        "name": name,
        "properties": {
            "configuration": {"triggerType": "Manual"},
            "template": {
                "containers": [
                    {
                        "name": role,
                        "image": IMAGE,
                        "command": ["python"],
                        "args": args,
                    }
                ]
            },
        },
    }


def _jobs() -> dict[str, dict[str, object]]:
    return {
        "prepare": _job(
            "bp-approved-prepare", "prepare", ["scripts/prepare_cloud.py"]
        ),
        "seed": _job(
            "bp-approved-seed",
            "seed",
            [
                "scripts/seed_demo.py",
                "tests/fixtures/synthetic/v1",
                "--expected-manifest-sha256",
                "d" * 64,
                "--expected-dataset-version-id",
                "33333333-3333-4333-8333-333333333333",
            ],
        ),
        "maintain-sessions": _job(
            "bp-approved-sessions",
            "maintain-sessions",
            ["scripts/maintain_sessions.py"],
        ),
        "maintain-storage": _job(
            "bp-approved-storage",
            "maintain-storage",
            ["scripts/maintain_storage.py", "--expire-temporary"],
        ),
    }


def _execution(
    name: str,
    status: str,
    start_time: str,
    end_time: str,
) -> dict[str, object]:
    return {
        "name": name,
        "properties": {
            "status": status,
            "startTime": start_time,
            "endTime": end_time,
        },
    }


def _executions() -> dict[str, list[dict[str, object]]]:
    return {
        "prepare": [
            _execution(
                "prepare-1",
                "Succeeded",
                "2026-08-15T22:25:27Z",
                "2026-08-15T22:25:59Z",
            )
        ],
        "seed": [
            _execution(
                "seed-1",
                "Succeeded",
                "2026-08-15T22:26:07Z",
                "2026-08-15T22:26:44Z",
            )
        ],
        "maintain-sessions": [
            _execution(
                "sessions-1",
                "Succeeded",
                "2026-08-15T22:15:00Z",
                "2026-08-15T22:15:26Z",
            )
        ],
        "maintain-storage": [
            _execution(
                "storage-1",
                "Succeeded",
                "2026-08-15T22:00:00Z",
                "2026-08-15T22:00:20Z",
            )
        ],
    }


def _collect(
    *,
    app: dict[str, object] | None = None,
    executions: dict[str, list[dict[str, object]]] | None = None,
) -> dict[str, object]:
    return collect_legacy_receipt(
        source_authority=_source_authority(),
        source_sha256=SOURCE_SHA256,
        deployment=_deployment(),
        app=app or _app(),
        revisions=_revisions(),
        jobs=_jobs(),
        executions=executions or _executions(),
        observed_at=OBSERVED,
    )


def test_legacy_receipt_accepts_terminal_maintenance_before_phase1_anchor() -> None:
    receipt = _collect()

    assert receipt["schema_version"] == "newcaostone.phase1-receipt.v1"
    assert receipt["kind"] == "legacy"
    assert receipt["phase1_anchor_at"] == ANCHOR
    assert receipt["executions"]["prepare"]["name"] == "prepare-1"
    assert receipt["executions"]["seed"]["name"] == "seed-1"


def test_legacy_receipt_rejects_maintenance_at_or_after_anchor() -> None:
    executions = _executions()
    executions["maintain-sessions"] = [
        _execution(
            "sessions-2",
            "Succeeded",
            "2026-08-15T22:21:00Z",
            "2026-08-15T22:21:20Z",
        )
    ]

    with pytest.raises(
        Phase1ReceiptInvalid,
        match="phase1_receipt_maintenance_after_anchor",
    ):
        _collect(executions=executions)


def test_legacy_receipt_rejects_prepare_before_anchor() -> None:
    executions = _executions()
    executions["prepare"] = [
        _execution(
            "prepare-early",
            "Succeeded",
            "2026-08-15T22:19:59Z",
            "2026-08-15T22:20:10Z",
        )
    ]

    with pytest.raises(
        Phase1ReceiptInvalid,
        match="phase1_receipt_prepare_not_proved",
    ):
        _collect(executions=executions)


def test_legacy_receipt_rejects_duplicate_seed_after_anchor() -> None:
    executions = _executions()
    executions["seed"].append(
        _execution(
            "seed-2",
            "Succeeded",
            "2026-08-15T22:26:50Z",
            "2026-08-15T22:27:10Z",
        )
    )

    with pytest.raises(
        Phase1ReceiptInvalid,
        match="phase1_receipt_seed_not_proved",
    ):
        _collect(executions=executions)


def test_legacy_receipt_rejects_unknown_execution_status() -> None:
    executions = _executions()
    executions["maintain-storage"] = [
        _execution(
            "storage-queued",
            "Queued",
            "2026-08-15T22:00:00Z",
            "2026-08-15T22:00:20Z",
        )
    ]

    with pytest.raises(
        Phase1ReceiptInvalid,
        match="phase1_receipt_execution_state_invalid",
    ):
        _collect(executions=executions)


def test_legacy_receipt_rejects_public_application() -> None:
    app = _app()
    app["properties"]["configuration"]["ingress"]["external"] = True

    with pytest.raises(
        Phase1ReceiptInvalid,
        match="phase1_receipt_app_not_fenced",
    ):
        _collect(app=app)


def test_legacy_receipt_accepts_azure_default_scale_projection() -> None:
    app = _app()
    app["properties"]["template"]["scale"].update(
        cooldownPeriod=300,
        pollingInterval=30,
        rules=None,
    )

    receipt = _collect(app=app)

    assert receipt["app"]["external"] is False


def test_legacy_receipt_rejects_phase1_scale_rules() -> None:
    app = _app()
    app["properties"]["template"]["scale"].update(
        cooldownPeriod=300,
        pollingInterval=30,
        rules=[{"name": "unexpected-trigger"}],
    )

    with pytest.raises(
        Phase1ReceiptInvalid,
        match="phase1_receipt_app_not_fenced",
    ):
        _collect(app=app)


def test_write_receipt_is_mode_600_canonical_and_no_overwrite(tmp_path: Path) -> None:
    path = tmp_path / "phase1-receipt.json"
    receipt = _collect()

    write_receipt(path, receipt)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text(encoding="utf-8")) == receipt
    with pytest.raises(FileExistsError):
        write_receipt(path, receipt)


def test_verify_receipt_rejects_changed_private_revision() -> None:
    expected = _collect()
    observed = deepcopy(expected)
    observed["receipt_id"] = "44444444-4444-4444-8444-444444444444"
    observed["phase1_fence_observed_at"] = "2026-08-15T22:30:00Z"
    observed["app"]["revision"] = "bp-approved-app--prep-ccccccc"

    with pytest.raises(
        Phase1ReceiptInvalid,
        match="phase1_receipt_observation_mismatch",
    ):
        verify_receipt(expected=expected, observed=observed)


def _completed(payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["az"],
        returncode=0,
        stdout=json.dumps(payload),
        stderr="",
    )


def test_collect_from_azure_uses_only_bounded_exact_read_projections() -> None:
    outputs: list[object] = [_deployment(), _app(), _revisions()]
    jobs = _jobs()
    executions = _executions()
    for role in ("prepare", "seed", "maintain-sessions", "maintain-storage"):
        outputs.extend([jobs[role], executions[role]])
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((arguments, kwargs))
        return _completed(outputs.pop(0))

    receipt = collect_from_azure(
        source_authority=_source_authority(),
        source_sha256=SOURCE_SHA256,
        observed_at=OBSERVED,
        runner=runner,
    )

    assert receipt["phase1_anchor_at"] == ANCHOR
    assert len(calls) == 11
    assert calls[0][0][1:4] == ["deployment", "group", "show"]
    assert calls[1][0][1:3] == ["containerapp", "show"]
    assert calls[2][0][1:4] == ["containerapp", "revision", "list"]
    assert all(call[-3:] == ["--only-show-errors", "--output", "json"] for call, _ in calls)
    assert all(kwargs["timeout"] == 30 for _, kwargs in calls)
    assert all(kwargs["capture_output"] is True for _, kwargs in calls)
    assert all(kwargs["text"] is True for _, kwargs in calls)


def test_collect_from_azure_collapses_transport_errors() -> None:
    def runner(arguments: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired(arguments, 30)

    with pytest.raises(
        Phase1ReceiptInvalid,
        match="phase1_receipt_azure_read_failed",
    ):
        collect_from_azure(
            source_authority=_source_authority(),
            source_sha256=SOURCE_SHA256,
            observed_at=OBSERVED,
            runner=runner,
        )


def test_collect_cli_writes_receipt_without_resource_arguments(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    output = tmp_path / "receipt.json"
    monkeypatch.setattr(
        receipt_module,
        "load_source_authority",
        lambda path, sha256: _source_authority(),
    )
    monkeypatch.setattr(
        receipt_module,
        "collect_from_azure",
        lambda **kwargs: _collect(),
    )

    status = receipt_module.main(
        [
            "collect",
            "--source-authorization",
            str(source),
            "--source-sha256",
            SOURCE_SHA256,
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    assert captured.out.splitlines()[0] == "phase1_receipt=ok"
    assert captured.out.splitlines()[1] == f"output={output}"
    assert captured.out.splitlines()[2].startswith("sha256=")
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_direct_script_loader_resolves_project_modules_without_pythonpath(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.md"
    _write(source, _authorization())
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    script = Path(receipt_module.__file__).resolve()
    code = (
        "import runpy; from pathlib import Path; "
        f"module=runpy.run_path({str(script)!r}, run_name='receipt_direct'); "
        f"authority=module['load_source_authority'](Path({str(source)!r}), {digest!r}); "
        "print(authority['authorization_id'])"
    )

    completed = subprocess.run(
        (sys.executable, "-c", code),
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": ""},
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert completed.stdout.strip() == "22222222-2222-4222-8222-222222222222"


def test_verify_cli_recollects_and_compares_authority(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source.md"
    source.write_text("source", encoding="utf-8")
    receipt = tmp_path / "receipt.json"
    expected = _collect()
    write_receipt(receipt, expected)
    observed = deepcopy(expected)
    observed["receipt_id"] = "44444444-4444-4444-8444-444444444444"
    observed["phase1_fence_observed_at"] = "2026-08-15T22:30:00Z"
    monkeypatch.setattr(
        receipt_module,
        "load_source_authority",
        lambda path, sha256: _source_authority(),
    )
    monkeypatch.setattr(
        receipt_module,
        "collect_from_azure",
        lambda **kwargs: observed,
    )

    status = receipt_module.main(
        [
            "verify",
            "--source-authorization",
            str(source),
            "--source-sha256",
            SOURCE_SHA256,
            "--receipt",
            str(receipt),
        ]
    )

    captured = capsys.readouterr()
    assert status == 0
    assert captured.err == ""
    assert captured.out == "phase1_receipt=ok\n"
