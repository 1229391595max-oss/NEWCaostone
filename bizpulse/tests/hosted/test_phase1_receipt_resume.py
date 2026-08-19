from __future__ import annotations

import hashlib
import json
import shlex
import stat
import subprocess
import sys
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import generate_phase1_receipt_resume as resume_generator
from scripts.generate_phase1_receipt_resume import (
    RESUME_STAGES,
    ResumeAuthorityInvalid,
    generate_resume_authority,
    write_resume_authority,
)
from scripts.phase1_receipt import write_receipt
from tests.hosted.test_verify_azure_demo import (
    _authorization,
    _enable_paid_ai,
    _write,
)
from tests.hosted.verify_azure_demo import (
    _expected_commands,
    _expected_execution_order,
)


ANCHOR = "2026-08-15T22:20:24Z"
OBSERVED = "2026-08-15T22:27:00Z"
ISSUED_AT = datetime(2026, 8, 15, 23, 0, tzinfo=UTC)


def _refresh_commands(
    source: dict[str, object], *, legacy_update: bool = False
) -> None:
    source["commands"] = {
        stage: [shlex.join(tokens) for tokens in rows]
        for stage, rows in _expected_commands(
            source, legacy_update=legacy_update
        ).items()
    }
    source["execution_order"] = list(
        _expected_execution_order(source, legacy_update=legacy_update)
    )


def _update_source() -> dict[str, object]:
    source = _authorization()
    source["issued_at"] = "2026-08-15T22:12:46Z"
    source["expires_at"] = "2026-08-17T22:12:46Z"
    source["public_url"] = (
        "https://bp-approved-app.synthetic.azurecontainerapps.io"
    )
    source["public_url_source"] = "exact"
    source["recovery"].update(
        target_mode="update",
        observed_current_image_digest="sha256:" + "e" * 64,
    )
    source["external_publication"]["registry_publish"] = True
    source["allowed_operations"].insert(1, "registry_publish")
    _refresh_commands(source, legacy_update=True)
    return source


def _write_source(tmp_path: Path, source: dict[str, object] | None = None) -> Path:
    path = tmp_path / "source.md"
    _write(path, source or _update_source())
    return path


def _receipt(source: dict[str, object], source_sha256: str) -> dict[str, object]:
    image = (
        f"{source['generated_names']['registry_name']}.azurecr.io/"
        f"{source['generated_names']['image_repository']}@"
        f"{source['release']['image_digest']}"
    )
    return {
        "schema_version": "newcaostone.phase1-receipt.v1",
        "receipt_id": "44444444-4444-4444-8444-444444444444",
        "kind": "legacy",
        "source_launch_authorization_sha256": source_sha256,
        "source_authorization_id": source["authorization_id"],
        "release": deepcopy(source["release"]),
        "phase1_deployment": {
            "id": (
                f"/subscriptions/{source['subscription_id']}/resourceGroups/"
                f"{source['resource_group']}/providers/Microsoft.Resources/"
                "deployments/bp-approved-phase1"
            ),
            "name": "bp-approved-phase1",
            "status": "Succeeded",
            "finished_at": ANCHOR,
        },
        "phase1_anchor_at": ANCHOR,
        "phase1_fence_observed_at": OBSERVED,
        "app": {
            "name": source["generated_names"]["container_app"],
            "revision": "bp-approved-app--prep-bbbbbbb",
            "image": image,
            "external": False,
        },
        "jobs": {
            "prepare": source["generated_names"]["migration_job"],
            "seed": source["generated_names"]["seed_job"],
            "maintain-sessions": source["generated_names"][
                "session_maintenance_job"
            ],
            "maintain-storage": source["generated_names"][
                "storage_maintenance_job"
            ],
        },
        "executions": {
            "prepare": {
                "name": "prepare-1",
                "status": "Succeeded",
                "started_at": "2026-08-15T22:25:27Z",
                "ended_at": "2026-08-15T22:25:59Z",
            },
            "seed": {
                "name": "seed-1",
                "status": "Succeeded",
                "started_at": "2026-08-15T22:26:07Z",
                "ended_at": "2026-08-15T22:26:44Z",
            },
            "maintain-sessions": {
                "terminal_before_anchor_count": 1,
                "latest_started_at": "2026-08-15T22:15:00Z",
            },
            "maintain-storage": {
                "terminal_before_anchor_count": 1,
                "latest_started_at": "2026-08-15T22:00:00Z",
            },
        },
    }


def _write_receipt(tmp_path: Path, source: dict[str, object], source_path: Path) -> Path:
    path = tmp_path / "receipt.json"
    write_receipt(
        path,
        _receipt(source, hashlib.sha256(source_path.read_bytes()).hexdigest()),
    )
    return path


def _control_paths(tmp_path: Path) -> dict[str, Path]:
    controls = {
        "phase1_receipt_sha256": tmp_path / "phase1_receipt.py",
        "resume_generator_sha256": tmp_path / "resume_generator.py",
        "resume_runner_sha256": tmp_path / "resume_runner.py",
    }
    for name, path in controls.items():
        path.write_text(name, encoding="utf-8")
    return controls


def _generate(
    tmp_path: Path,
    *,
    source: dict[str, object] | None = None,
) -> tuple[dict[str, object], Path, Path]:
    source_payload = source or _update_source()
    source_path = _write_source(tmp_path, source_payload)
    receipt_path = _write_receipt(tmp_path, source_payload, source_path)
    authority = generate_resume_authority(
        source_path=source_path,
        source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        source_reference=".tmp/source.md",
        receipt_path=receipt_path,
        receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        receipt_reference=".tmp/receipt.json",
        control_paths=_control_paths(tmp_path),
        issued_at=ISSUED_AT,
    )
    return authority, source_path, receipt_path


def test_resume_package_uses_receipt_anchor_not_issue_time(tmp_path: Path) -> None:
    authority, _, _ = _generate(tmp_path)

    assert authority["schema_version"] == (
        "newcaostone.phase1-receipt-resume-authorization.v1"
    )
    assert authority["receipt_anchor_at"] == ANCHOR
    assert f"--not-before {ANCHOR}" in authority["commands"]["activate_fence"][0]
    assert f"--not-before {ANCHOR}" in authority["commands"]["deploy"][-1]
    assert "2026-08-15T23:00:00Z" not in authority["commands"]["activate_fence"][0]
    assert authority["execution_order"] == list(RESUME_STAGES)


def test_resume_package_excludes_completed_and_publication_stages(tmp_path: Path) -> None:
    authority, _, _ = _generate(tmp_path)
    commands = authority["commands"]

    assert set(commands) == set(RESUME_STAGES)
    assert "registry_publish" not in commands
    assert "provision" not in commands
    assert "migrate" not in commands
    assert "seed" not in commands
    assert len(commands["registry_verify"]) == 2
    assert len(commands["phase1_receipt"]) == 1


def test_resume_package_hash_binds_source_receipt_and_control_scripts(
    tmp_path: Path,
) -> None:
    authority, source, receipt = _generate(tmp_path)

    assert authority["source_launch_authorization_sha256"] == hashlib.sha256(
        source.read_bytes()
    ).hexdigest()
    assert authority["receipt_sha256"] == hashlib.sha256(
        receipt.read_bytes()
    ).hexdigest()
    assert set(authority["control_sha256"]) == {
        "phase1_receipt_sha256",
        "resume_generator_sha256",
        "resume_runner_sha256",
    }
    assert all(
        len(value) == 64 for value in authority["control_sha256"].values()
    )


def test_receipt_resume_accepts_valid_source_without_rewriting_it(
    tmp_path: Path,
) -> None:
    authority, source, _ = _generate(tmp_path)
    before = source.read_bytes()

    assert source.read_bytes() == before
    assert authority["source_authorization_id"] == (
        "22222222-2222-4222-8222-222222222222"
    )


def test_resume_generator_rejects_ai_enabled_source(tmp_path: Path) -> None:
    source = _update_source()
    _enable_paid_ai(source)
    _refresh_commands(source)

    with pytest.raises(
        ResumeAuthorityInvalid,
        match="resume_no_ai_boundary_invalid",
    ):
        _generate(tmp_path, source=source)


def test_resume_generator_rejects_receipt_release_mismatch(tmp_path: Path) -> None:
    source = _update_source()
    source_path = _write_source(tmp_path, source)
    receipt = _receipt(
        source, hashlib.sha256(source_path.read_bytes()).hexdigest()
    )
    receipt["release"]["image_digest"] = "sha256:" + "9" * 64
    receipt_path = tmp_path / "receipt.json"
    write_receipt(receipt_path, receipt)

    with pytest.raises(ResumeAuthorityInvalid, match="resume_receipt_mismatch"):
        generate_resume_authority(
            source_path=source_path,
            source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
            source_reference=".tmp/source.md",
            receipt_path=receipt_path,
            receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            receipt_reference=".tmp/receipt.json",
            control_paths=_control_paths(tmp_path),
            issued_at=ISSUED_AT,
        )


def test_resume_generator_rejects_unquoted_or_escaping_references(
    tmp_path: Path,
) -> None:
    source = _update_source()
    source_path = _write_source(tmp_path, source)
    receipt_path = _write_receipt(tmp_path, source, source_path)
    common = {
        "source_path": source_path,
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        "receipt_path": receipt_path,
        "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "receipt_reference": ".tmp/receipt.json",
        "control_paths": _control_paths(tmp_path),
        "issued_at": ISSUED_AT,
    }

    for reference in (".tmp/source file.md", "../source.md"):
        with pytest.raises(ResumeAuthorityInvalid, match="resume_reference_invalid"):
            generate_resume_authority(
                source_reference=reference,
                **common,
            )


def test_write_resume_authority_is_mode_600_and_no_overwrite(
    tmp_path: Path,
) -> None:
    authority, _, _ = _generate(tmp_path)
    path = tmp_path / "resume.md"

    digest = write_resume_authority(path, authority)

    assert len(digest) == 64
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text().split("```json\n", 1)[1].rsplit("\n```", 1)[0]) == authority
    with pytest.raises(FileExistsError):
        write_resume_authority(path, authority)


def test_resume_generator_cli_writes_exact_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = _update_source()
    source_path = _write_source(tmp_path, source)
    receipt_path = _write_receipt(tmp_path, source, source_path)
    controls = _control_paths(tmp_path)
    output = tmp_path / "resume.md"

    result = resume_generator.main(
        [
            "--source-authorization",
            str(source_path),
            "--source-sha256",
            hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "--source-reference",
            ".tmp/source.md",
            "--receipt",
            str(receipt_path),
            "--receipt-sha256",
            hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "--receipt-reference",
            ".tmp/receipt.json",
            "--phase1-receipt-script",
            str(controls["phase1_receipt_sha256"]),
            "--resume-generator-script",
            str(controls["resume_generator_sha256"]),
            "--resume-runner",
            str(controls["resume_runner_sha256"]),
            "--issued-at",
            "2026-08-15T23:00:00Z",
            "--output",
            str(output),
        ]
    )

    stdout = capsys.readouterr().out
    assert result == 0
    assert "resume_authorization=ok" in stdout
    assert f"output={output}" in stdout
    assert "sha256=" in stdout
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_resume_generator_cli_fails_with_value_safe_output(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = resume_generator.main(
        [
            "--source-authorization",
            str(tmp_path / "secret-source-name.md"),
            "--source-sha256",
            "0" * 64,
            "--source-reference",
            ".tmp/source.md",
            "--receipt",
            str(tmp_path / "receipt.json"),
            "--receipt-sha256",
            "0" * 64,
            "--receipt-reference",
            ".tmp/receipt.json",
            "--phase1-receipt-script",
            str(tmp_path / "phase1.py"),
            "--resume-generator-script",
            str(tmp_path / "generator.py"),
            "--resume-runner",
            str(tmp_path / "runner.py"),
            "--issued-at",
            "2026-08-15T23:00:00Z",
            "--output",
            str(tmp_path / "resume.md"),
        ]
    )

    assert result == 1
    assert capsys.readouterr().out == "resume_authorization=invalid\n"


def test_resume_generator_direct_script_resolves_project_modules(
    tmp_path: Path,
) -> None:
    source = _update_source()
    source_path = _write_source(tmp_path, source)
    receipt_path = _write_receipt(tmp_path, source, source_path)
    controls = _control_paths(tmp_path)
    output = tmp_path / "direct-resume.md"
    script = Path(resume_generator.__file__).resolve()

    completed = subprocess.run(
        (
            sys.executable,
            str(script),
            "--source-authorization",
            str(source_path),
            "--source-sha256",
            hashlib.sha256(source_path.read_bytes()).hexdigest(),
            "--source-reference",
            ".tmp/source.md",
            "--receipt",
            str(receipt_path),
            "--receipt-sha256",
            hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            "--receipt-reference",
            ".tmp/receipt.json",
            "--phase1-receipt-script",
            str(controls["phase1_receipt_sha256"]),
            "--resume-generator-script",
            str(controls["resume_generator_sha256"]),
            "--resume-runner",
            str(controls["resume_runner_sha256"]),
            "--issued-at",
            "2026-08-15T23:00:00Z",
            "--output",
            str(output),
        ),
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "resume_authorization=ok" in completed.stdout
    assert output.is_file()
