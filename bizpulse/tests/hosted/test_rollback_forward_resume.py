from __future__ import annotations

import hashlib
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.generate_phase1_receipt_resume import (
    generate_resume_authority,
    write_resume_authority,
)
from scripts.generate_rollback_forward_resume import (
    ForwardResumeInvalid,
    generate_forward_resume,
    validate_forward_resume,
    write_forward_resume,
)
from scripts.phase1_receipt import write_receipt
from tests.hosted.test_phase1_receipt_resume import (
    _control_paths,
    _receipt,
    _update_source,
)
from tests.hosted.test_verify_azure_demo import _write


ISSUED_AT = datetime(2026, 8, 16, 1, 0, tzinfo=UTC)


def _materialize_resume_source(tmp_path: Path) -> tuple[Path, str, dict[str, Path]]:
    source = _update_source()
    authority_root = tmp_path / ".tmp"
    authority_root.mkdir()
    source_path = authority_root / "source.md"
    _write(source_path, source)
    source_path.chmod(0o600)
    receipt_path = authority_root / "receipt.json"
    write_receipt(
        receipt_path,
        _receipt(source, hashlib.sha256(source_path.read_bytes()).hexdigest()),
    )
    controls = _control_paths(tmp_path)
    resume = generate_resume_authority(
        source_path=source_path,
        source_sha256=hashlib.sha256(source_path.read_bytes()).hexdigest(),
        source_reference=".tmp/source.md",
        receipt_path=receipt_path,
        receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        receipt_reference=".tmp/receipt.json",
        control_paths=controls,
        issued_at=datetime(2026, 8, 15, 23, 0, tzinfo=UTC),
    )
    resume_path = authority_root / "resume.md"
    write_resume_authority(resume_path, resume)
    forward_controls = {
        "azure_readback_sha256": tmp_path / "azure_readback.py",
        "forward_generator_sha256": tmp_path / "forward_generator.py",
        "forward_runner_sha256": tmp_path / "forward_runner.py",
    }
    for name, path in forward_controls.items():
        path.write_text(name, encoding="utf-8")
    return (
        resume_path,
        hashlib.sha256(resume_path.read_bytes()).hexdigest(),
        forward_controls,
    )


def _generate(tmp_path: Path) -> dict[str, object]:
    resume_path, resume_sha256, controls = _materialize_resume_source(tmp_path)
    return generate_forward_resume(
        source_resume_path=resume_path,
        source_resume_sha256=resume_sha256,
        source_resume_reference=".tmp/resume.md",
        rollback_revision="bp-approved-app--rollback-22222222-ddddddd",
        control_paths=controls,
        issued_at=ISSUED_AT,
        project_root=tmp_path,
    )


def test_forward_resume_authorizes_only_preflight_registry_recover_and_health(
    tmp_path: Path,
) -> None:
    authority = _generate(tmp_path)

    assert authority["schema_version"] == (
        "newcaostone.rollback-forward-resume-authorization.v1"
    )
    assert authority["execution_order"] == [
        "rollback_preflight",
        "registry_verify",
        "recover",
        "health",
    ]
    assert "--operation recover" in authority["commands"]["recover"][0]
    health_tokens = shlex.split(authority["commands"]["health"][0])
    assert health_tokens[health_tokens.index("--expected-revision-suffix") + 1] == (
        "recover-"
        f"{authority['source_authorization_id'].replace('-', '')[:8]}-"
        f"{authority['candidate_image'].rsplit('@sha256:', 1)[1][:7]}"
    )
    assert authority["no_ai"] is True
    assert set(authority["commands"]) == set(authority["execution_order"])


def test_forward_resume_accepts_hash_bound_historical_source_after_control_change(
    tmp_path: Path,
) -> None:
    resume_path, resume_sha256, controls = _materialize_resume_source(tmp_path)
    for name in (
        "phase1_receipt.py",
        "resume_generator.py",
        "resume_runner.py",
    ):
        (tmp_path / name).write_text("changed-after-phase1", encoding="utf-8")

    authority = generate_forward_resume(
        source_resume_path=resume_path,
        source_resume_sha256=resume_sha256,
        source_resume_reference=".tmp/resume.md",
        rollback_revision="bp-approved-app--rollback-22222222-ddddddd",
        control_paths=controls,
        issued_at=ISSUED_AT,
        project_root=tmp_path,
    )

    assert authority["no_ai"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("rollback_revision", "bp-approved-app--rollback-22222222-aaaaaaa"),
        ("source_resume_sha256", "0" * 64),
    ],
)
def test_forward_resume_rejects_tampered_identity(
    tmp_path: Path, field: str, value: str
) -> None:
    resume_path, resume_sha256, controls = _materialize_resume_source(tmp_path)
    arguments = {
        "source_resume_path": resume_path,
        "source_resume_sha256": resume_sha256,
        "source_resume_reference": ".tmp/resume.md",
        "rollback_revision": "bp-approved-app--rollback-22222222-ddddddd",
        "control_paths": controls,
        "issued_at": ISSUED_AT,
        "project_root": tmp_path,
    }
    arguments[field] = value

    with pytest.raises(ForwardResumeInvalid):
        generate_forward_resume(**arguments)


def test_validate_forward_resume_rejects_wrong_approved_sha(tmp_path: Path) -> None:
    authority = _generate(tmp_path)
    path = tmp_path / "forward.md"
    digest = write_forward_resume(path, authority)

    with pytest.raises(ForwardResumeInvalid, match="forward_approval_hash_mismatch"):
        validate_forward_resume(
            authorization_path=path,
            approved_sha256=("0" * 64 if digest != "0" * 64 else "1" * 64),
            project_root=tmp_path,
            now=ISSUED_AT,
        )


def test_forward_generator_direct_script_resolves_project_modules(
    tmp_path: Path,
) -> None:
    from scripts import generate_rollback_forward_resume as generator

    completed = subprocess.run(
        [sys.executable, str(Path(generator.__file__).resolve()), "--help"],
        cwd=tmp_path,
        env={"PATH": "/usr/bin:/bin", "PYTHONPATH": ""},
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
