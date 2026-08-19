from __future__ import annotations

import os
import fcntl
from pathlib import Path
import hashlib
import json
import pty
import shlex
import subprocess
import sys
import sysconfig
import tempfile
import termios

import pytest

import scripts.admin_ai_exact_runtime as exact_runtime
from scripts.admin_ai_exact_runtime import (
    _ALLOWED_PROJECT_ROOT_ENTRIES,
    AdminAIExactRuntimeInvalid,
    capture_runtime_dependency_manifest,
    materialize_runtime_dependencies,
    run_from_exact_snapshot,
)
from scripts.create_admin_ai_release_package import (
    capture_operations_factory,
    capture_repository,
)


def _commit_fixture(project: Path, entrypoint: str) -> None:
    (project / "scripts").mkdir(parents=True)
    (project / "infra").mkdir()
    (project / "scripts" / "build_admin_ai_candidate.py").write_text(entrypoint)
    (project / "infra" / "ai_enablement.bicep").write_text(
        "// exact committed bicep\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"], cwd=project, check=True
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=project, check=True)


def _head(project: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD^{commit}"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_show_from_project(
    project: Path,
    object_path: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "show", object_path],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
    )


def test_documented_bootstrap_lookup_reads_captured_object_from_bizpulse_subdir(
) -> None:
    project = Path(__file__).resolve().parents[2]
    source_sha = _head(project)
    prefix = subprocess.run(
        ["git", "rev-parse", "--show-prefix"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    expected = subprocess.run(
        [
            "git",
            "show",
            f"{source_sha}:bizpulse/scripts/admin_ai_exact_runtime.py",
        ],
        cwd=project.parent,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert prefix == "bizpulse/\n"

    for mode in ("authority-refresh", "build", "package", "release"):
        completed = _git_show_from_project(
            project,
            f"{source_sha}:./scripts/admin_ai_exact_runtime.py",
        )
        assert completed.returncode == 0, mode
        assert completed.stdout == expected
        assert completed.stderr == ""

    wrong_root_relative = _git_show_from_project(
        project,
        f"{source_sha}:scripts/admin_ai_exact_runtime.py",
    )
    moved_path = _git_show_from_project(
        project,
        f"{source_sha}:./scripts/moved_admin_ai_exact_runtime.py",
    )

    for failed in (
        wrong_root_relative,
        moved_path,
    ):
        assert failed.returncode != 0
        assert failed.stdout == ""


def test_documented_bootstrap_pipelines_propagate_git_lookup_failure() -> None:
    project = Path(__file__).resolve().parents[2]
    runbook = (project / "docs/operations/AZURE_LAUNCH_RUNBOOK.md").read_text()
    blocks = tuple(
        section.split("```", 1)[0].splitlines()
        for section in runbook.split("```bash\n")[1:]
    )

    assert len(blocks) == 4
    for lines in blocks:
        assert lines[0] == "set -o pipefail"
        lookup = lines[2].removesuffix("\\")
        command = "\n".join(
            (
                lines[0],
                lines[1],
                f"{lookup} {shlex.quote(sys.executable)} -I -B -S - --help",
            )
        )
        completed = subprocess.run(
            ["bash", "-c", command],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
        )
        moved = subprocess.run(
            [
                "bash",
                "-c",
                command.replace(
                    "./scripts/admin_ai_exact_runtime.py",
                    "./scripts/moved_admin_ai_exact_runtime.py",
                ),
            ],
            cwd=project,
            check=False,
            capture_output=True,
            text=True,
        )

        assert completed.returncode == 0
        assert moved.returncode != 0


def test_runbook_places_exact_readonly_authority_refresh_before_candidate_build(
) -> None:
    project = Path(__file__).resolve().parents[2]
    runbook = (project / "docs/operations/AZURE_LAUNCH_RUNBOOK.md").read_text()

    refresh = runbook.index("--source-sha \"$ADMIN_AI_SOURCE_SHA\" authority-refresh")
    build = runbook.index("--source-sha \"$ADMIN_AI_SOURCE_SHA\" build")

    assert refresh < build
    refresh_block = runbook[:build].rsplit("```bash\n", 1)[-1].split("```", 1)[0]
    assert refresh_block.splitlines()[0] == "set -o pipefail"
    assert "git show \"${ADMIN_AI_SOURCE_SHA}:./scripts/admin_ai_exact_runtime.py\"" in refresh_block
    assert "--create-azure-authority-request" not in refresh_block
    assert "--candidate-artifact" not in refresh_block
    assert "<new-uuid>" not in refresh_block


def _fake_distribution(site_packages: Path, *, source: str = "VALUE = 'safe'\n") -> None:
    package = site_packages / "httpx"
    metadata = site_packages / "httpx-1.0.dist-info"
    package.mkdir(parents=True)
    metadata.mkdir()
    (package / "__init__.py").write_text(source)
    (metadata / "METADATA").write_text("Name: httpx\nVersion: 1.0\n")
    (metadata / "RECORD").write_text(
        "httpx/__init__.py,,\n"
        "httpx-1.0.dist-info/METADATA,,\n"
        "httpx-1.0.dist-info/RECORD,,\n"
    )


def _write_trusted_runtime_dependencies(project: Path) -> dict[str, object]:
    manifest = capture_runtime_dependency_manifest(
        Path(sysconfig.get_path("purelib"))
    )
    destination = project / "scripts" / "admin_ai_runtime_dependencies.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"))
    )
    destination.chmod(0o400)
    return manifest


def _release_launcher_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str, str, str]:
    project = tmp_path / "release-project"
    project.mkdir()
    output = tmp_path / "release-stdin.txt"
    entrypoint = """
from pathlib import Path
import argparse
import sys
parser = argparse.ArgumentParser()
parser.add_argument("--package", type=Path, required=True)
parser.add_argument("--approved-sha256", required=True)
parser.add_argument("--output", type=Path, required=True)
options = parser.parse_args()
options.output.write_text("tty" if sys.stdin.isatty() else "not-tty")
raise SystemExit(0 if sys.stdin.isatty() else 7)
"""
    (project / "scripts").mkdir()
    (project / "scripts" / "admin_ai_exact_runtime.py").write_text(
        Path(exact_runtime.__file__).read_text()
    )
    (project / "scripts" / "run_admin_ai_release.py").write_text(entrypoint)
    trusted_dependencies = _write_trusted_runtime_dependencies(project)
    (project / ".gitignore").write_text(".tmp/\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"], cwd=project, check=True
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=project, check=True)
    source_sha = _head(project)
    artifact = project / ".tmp" / "candidate.oci.tar"
    artifact.parent.mkdir()
    artifact.write_text("exact approved OCI bytes")
    artifact.chmod(0o400)
    package = project / ".tmp" / "package.json"
    package_payload = {
        "repository": {
            "source_sha": source_sha,
            "runtime_dependency_manifest": trusted_dependencies,
        },
        "candidate": {
            "artifact_path": ".tmp/candidate.oci.tar",
            "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        },
    }
    package.write_text(json.dumps(package_payload))
    package.chmod(0o600)
    approved = hashlib.sha256(package.read_bytes()).hexdigest()
    launcher = _git_show_from_project(
        project,
        f"{source_sha}:./scripts/admin_ai_exact_runtime.py",
    ).stdout
    return project, output, package, approved, source_sha, launcher


def _release_launcher_command(
    project: Path,
    output: Path,
    package: Path,
    approved: str,
    source_sha: str,
) -> list[str]:
    return [
        sys.executable,
        "-I",
        "-B",
        "-S",
        "-",
        "--project-root",
        str(project),
        "--source-sha",
        source_sha,
        "release",
        "--package",
        str(package),
        "--approved-sha256",
        approved,
        "--output",
        str(output),
    ]


def test_dependency_snapshot_rejects_modified_installed_distribution(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    _fake_distribution(site_packages)
    expected = capture_runtime_dependency_manifest(
        site_packages,
        distribution_names=("httpx",),
    )
    (site_packages / "httpx" / "__init__.py").write_text(
        "VALUE = 'modified after approval'\n"
    )

    with pytest.raises(
        AdminAIExactRuntimeInvalid,
        match="runtime_dependency_hash_mismatch",
    ):
        materialize_runtime_dependencies(
            site_packages,
            tmp_path / "private-dependencies",
            expected=expected,
        )


def test_trusted_dependency_manifest_rejects_preexisting_modified_install(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    _fake_distribution(site_packages)
    trusted = capture_runtime_dependency_manifest(
        site_packages,
        distribution_names=("httpx",),
    )
    trusted_path = tmp_path / "trusted.json"
    trusted_path.write_text(json.dumps(trusted))
    trusted_path.chmod(0o400)
    (site_packages / "httpx" / "__init__.py").write_text(
        "VALUE = 'preexisting compromise'\n"
    )

    with pytest.raises(
        AdminAIExactRuntimeInvalid,
        match="runtime_dependency_trust_mismatch",
    ):
        exact_runtime.validate_trusted_runtime_dependencies(
            site_packages,
            trusted_path,
            distribution_names=("httpx",),
        )


def test_dependency_snapshot_copies_only_manifest_bound_files(
    tmp_path: Path,
) -> None:
    site_packages = tmp_path / "site-packages"
    _fake_distribution(site_packages)
    unexpected = site_packages / "httpx" / "shadow.py"
    unexpected.write_text("raise AssertionError('must not copy')\n")
    expected = capture_runtime_dependency_manifest(
        site_packages,
        distribution_names=("httpx",),
    )
    destination = tmp_path / "private-dependencies"

    materialize_runtime_dependencies(
        site_packages,
        destination,
        expected=expected,
    )

    assert (destination / "httpx" / "__init__.py").read_text() == "VALUE = 'safe'\n"
    assert not (destination / "httpx" / "shadow.py").exists()


def test_exact_runtime_executes_committed_snapshot_after_checkout_mutates(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "observed.txt"
    entrypoint = """
from pathlib import Path
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--mutable-project", type=Path, required=True)
options = parser.parse_args()
(options.mutable_project / "infra" / "ai_enablement.bicep").write_text("// swapped checkout\\n")
options.output.write_text(
    f"{Path(__file__).resolve()}\\n"
    + (Path(__file__).resolve().parents[1] / "infra" / "ai_enablement.bicep").read_text()
)
"""
    _commit_fixture(project, entrypoint)

    result = run_from_exact_snapshot(
        "build",
        ["--output", str(output), "--mutable-project", str(project)],
        project_root=project,
        source_sha=_head(project),
        environment={"PATH": os.environ["PATH"], "LANG": "C.UTF-8"},
        python_executable=sys.executable,
    )

    observed_path, observed_bicep = output.read_text().splitlines()
    assert result == 0
    assert observed_path != str(
        (project / "scripts" / "build_admin_ai_candidate.py").resolve()
    )
    assert "newcaostone-admin-ai-runtime-" in observed_path
    assert observed_bicep == "// exact committed bicep"
    assert (project / "infra" / "ai_enablement.bicep").read_text() == (
        "// swapped checkout\n"
    )


def test_exact_runtime_uses_one_canonical_root_across_macos_temp_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "canonical-paths.json"
    real_temp = tmp_path / "private" / "var"
    real_temp.mkdir(parents=True)
    temp_alias = tmp_path / "var"
    temp_alias.symlink_to(real_temp, target_is_directory=True)
    entrypoint = """
from collections.abc import Mapping
from pathlib import Path
import argparse
import json
import os
import stat
import sys

root = Path(__file__).resolve().parents[1]
marker = root / ".admin-ai-exact-runtime.json"
metadata = marker.lstat()
payload = json.loads(marker.read_text())
if (
    os.environ.get("BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT") != str(root)
    or not stat.S_ISREG(metadata.st_mode)
    or stat.S_IMODE(metadata.st_mode) != 0o400
    or not isinstance(payload, Mapping)
):
    raise SystemExit(17)
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
options = parser.parse_args()
options.output.write_text(json.dumps({
    "environment_root": os.environ["BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT"],
    "project_root": str(root),
    "entrypoint": str(Path(__file__)),
    "import_root": sys.path[0],
}))
"""
    _commit_fixture(project, entrypoint)
    monkeypatch.setattr(tempfile, "tempdir", str(temp_alias))

    result = run_from_exact_snapshot(
        "build",
        ["--output", str(output)],
        project_root=project,
        source_sha=_head(project),
        environment={"PATH": os.environ["PATH"]},
        python_executable=sys.executable,
    )

    observed = json.loads(output.read_text())
    canonical_prefix = str(real_temp.resolve())
    assert result == 0
    assert observed["environment_root"] == observed["project_root"]
    assert observed["entrypoint"].startswith(observed["project_root"] + "/")
    assert observed["import_root"] == observed["project_root"]
    assert observed["project_root"].startswith(canonical_prefix + "/")
    assert str(temp_alias) not in observed["project_root"]


def test_exact_runtime_rejects_a_different_canonical_environment_root(
    tmp_path: Path,
) -> None:
    snapshot = tmp_path / "snapshot"
    scripts = snapshot / "scripts"
    scripts.mkdir(parents=True)
    launcher = scripts / "build_admin_ai_candidate.py"
    launcher.write_text(
        (
            Path(__file__).resolve().parents[2]
            / "scripts"
            / "build_admin_ai_candidate.py"
        ).read_text()
    )
    marker = snapshot / ".admin-ai-exact-runtime.json"
    marker.write_text(
        json.dumps(
            {
                "schema_version": "newcaostone.admin-ai-exact-runtime.v1",
                "source_sha": "1" * 40,
                "source_tree": "2" * 40,
            }
        )
    )
    marker.chmod(0o400)
    different = tmp_path / "different-target"
    different.mkdir()

    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-S", str(launcher), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT": str(different.resolve()),
        },
    )

    assert completed.returncode == 1
    assert completed.stdout.splitlines() == [
        "admin_ai_exact_runtime=failed",
        "reason=runtime_snapshot_required",
    ]


def test_exact_runtime_does_not_follow_a_swapped_temp_root_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "observed.txt"
    _commit_fixture(
        project,
        "from pathlib import Path\n"
        f"Path({str(output)!r}).write_text('committed')\n",
    )
    original_temp = tmp_path / "original-temp"
    swapped_temp = tmp_path / "swapped-temp"
    original_temp.mkdir()
    swapped_temp.mkdir()
    temp_alias = tmp_path / "temp-alias"
    temp_alias.symlink_to(original_temp, target_is_directory=True)
    monkeypatch.setattr(tempfile, "tempdir", str(temp_alias))
    materialize = exact_runtime._materialize_exact_commit

    def materialize_then_swap(*args: object, **kwargs: object) -> None:
        materialize(*args, **kwargs)
        destination = Path(str(kwargs["destination"]))
        runtime_name = destination.parent.name
        temp_alias.unlink()
        temp_alias.symlink_to(swapped_temp, target_is_directory=True)
        decoy = (
            swapped_temp
            / runtime_name
            / "source"
            / "scripts"
            / "build_admin_ai_candidate.py"
        )
        decoy.parent.mkdir(parents=True)
        decoy.write_text(
            "from pathlib import Path\n"
            f"Path({str(output)!r}).write_text('swapped')\n"
        )

    monkeypatch.setattr(
        exact_runtime,
        "_materialize_exact_commit",
        materialize_then_swap,
    )

    result = run_from_exact_snapshot(
        "build",
        [],
        project_root=project,
        source_sha=_head(project),
        environment={"PATH": os.environ["PATH"]},
        python_executable=sys.executable,
    )

    assert result == 0
    assert output.read_text() == "committed"
    assert not tuple(original_temp.glob("newcaostone-admin-ai-runtime-*"))


@pytest.mark.parametrize(
    "shadow",
    (
        "scripts/sitecustomize.py",
        "scripts/__pycache__/create_admin_ai_release_package.cpython-313.pyc",
        "scripts/nested/runtime.pth",
    ),
)
def test_exact_runtime_isolates_ignored_checkout_import_shadows(
    tmp_path: Path,
    shadow: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "exact-entrypoint.txt"
    shadow_sentinel = tmp_path / "shadow-executed.txt"
    _commit_fixture(
        project,
        "from pathlib import Path\nPath(%r).write_text('exact')\n" % str(output),
    )
    (project / ".git" / "info" / "exclude").write_text(f"{shadow}\n")
    shadow_path = project / shadow
    shadow_path.parent.mkdir(parents=True, exist_ok=True)
    shadow_path.write_text(
        "import pathlib; "
        f"pathlib.Path({str(shadow_sentinel)!r}).write_text('shadow')\n"
    )

    result = run_from_exact_snapshot(
        "build",
        [],
        project_root=project,
        source_sha=_head(project),
        environment={"PATH": os.environ["PATH"]},
        python_executable=sys.executable,
    )

    assert result == 0
    assert output.read_text() == "exact"
    assert not shadow_sentinel.exists()


@pytest.mark.parametrize(
    "shadow_relative",
    (
        "scripts/__pycache__/runtime.cpython-313.pyc",
        "httpx.py",
    ),
)
def test_exact_runtime_rejects_import_shadows_committed_into_snapshot(
    tmp_path: Path,
    shadow_relative: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "must-not-execute.txt"
    _commit_fixture(
        project,
        "from pathlib import Path\nPath(%r).write_text('bad')\n" % str(output),
    )
    shadow = project / shadow_relative
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_bytes(b"committed executable shadow")
    subprocess.run(["git", "add", "-f", str(shadow)], cwd=project, check=True)
    subprocess.run(
        ["git", "commit", "--amend", "--no-edit", "-q"],
        cwd=project,
        check=True,
    )

    with pytest.raises(AdminAIExactRuntimeInvalid, match="runtime_import_shadow"):
        run_from_exact_snapshot(
            "build",
            [],
            project_root=project,
            source_sha=_head(project),
            environment={"PATH": os.environ["PATH"]},
            python_executable=sys.executable,
        )

    assert not output.exists()


def test_exact_runtime_drops_ambient_credentials_from_child(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "environment.txt"
    _commit_fixture(
        project,
        """
from pathlib import Path
import argparse
import os
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
options = parser.parse_args()
options.output.write_text("|".join(sorted(os.environ)))
""",
    )

    run_from_exact_snapshot(
        "build",
        ["--output", str(output)],
        project_root=project,
        source_sha=_head(project),
        environment={
            "PATH": os.environ["PATH"],
            "LANG": "C.UTF-8",
            "OPENAI_API_KEY": "must-not-cross-process",
            "OPERATOR_PASSWORD": "must-not-cross-process",
        },
        python_executable=sys.executable,
    )

    names = output.read_text().split("|")
    assert "PATH" in names
    assert "LANG" in names
    assert "OPENAI_API_KEY" not in names
    assert "OPERATOR_PASSWORD" not in names


def test_committed_stdin_bootstrap_rejects_corrupted_checkout_launcher(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    sentinel = tmp_path / "corrupt-launcher-executed.txt"
    (project / "scripts").mkdir()
    launcher = project / "scripts" / "admin_ai_exact_runtime.py"
    launcher.write_text(Path(exact_runtime.__file__).read_text())
    (project / "scripts" / "build_admin_ai_candidate.py").write_text(
        "raise AssertionError('dirty repository must stop before child')\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"], cwd=project, check=True
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=project, check=True)
    launcher.write_text(
        f"from pathlib import Path\nPath({str(sentinel)!r}).write_text('bad')\n"
    )
    committed_launcher = _git_show_from_project(
        project,
        f"{_head(project)}:./scripts/admin_ai_exact_runtime.py",
    ).stdout

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-S",
            "-",
            "--project-root",
            str(project),
            "--source-sha",
            _head(project),
            "build",
        ],
        input=committed_launcher,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"]},
    )

    assert completed.returncode == 1
    assert completed.stdout.splitlines() == [
        "admin_ai_exact_runtime=failed",
        "reason=runtime_repository_dirty",
    ]
    assert not sentinel.exists()


def test_committed_bootstrap_archives_only_the_single_captured_source_sha(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "observed.txt"
    (project / "scripts").mkdir()
    launcher = project / "scripts" / "admin_ai_exact_runtime.py"
    launcher.write_text(Path(exact_runtime.__file__).read_text())
    builder = project / "scripts" / "build_admin_ai_candidate.py"
    builder.write_text(
        "from pathlib import Path\n"
        f"Path({str(output)!r}).write_text('commit-a')\n"
    )
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"], cwd=project, check=True
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "commit a"], cwd=project, check=True)
    source_sha = _head(project)
    committed_launcher = _git_show_from_project(
        project,
        f"{source_sha}:./scripts/admin_ai_exact_runtime.py",
    ).stdout

    launcher.write_text("raise AssertionError('commit-b launcher executed')\n")
    builder.write_text(
        "from pathlib import Path\n"
        f"Path({str(output)!r}).write_text('commit-b')\n"
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "commit b"], cwd=project, check=True)
    assert _head(project) != source_sha

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-S",
            "-",
            "--project-root",
            str(project),
            "--source-sha",
            source_sha,
            "build",
        ],
        input=committed_launcher,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"]},
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert output.read_text() == "commit-a"


def test_committed_bootstrap_requires_system_site_packages_disabled(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _commit_fixture(project, "raise AssertionError('must not execute')\n")

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-",
            "--project-root",
            str(project),
            "--source-sha",
            _head(project),
            "build",
        ],
        input=Path(exact_runtime.__file__).read_text(),
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"]},
    )

    assert completed.returncode == 1
    assert completed.stdout.splitlines() == [
        "admin_ai_exact_runtime=failed",
        "reason=runtime_isolation_required",
    ]


def test_exact_runtime_rejects_source_sha_that_is_not_an_exact_commit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _commit_fixture(project, "raise AssertionError('must not execute')\n")

    with pytest.raises(AdminAIExactRuntimeInvalid, match="runtime_source_invalid"):
        run_from_exact_snapshot(
            "build",
            [],
            project_root=project,
            source_sha="HEAD",
            environment={"PATH": os.environ["PATH"]},
            python_executable=sys.executable,
        )


def test_repository_capture_uses_exact_snapshot_marker_without_git(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.create_admin_ai_release_package as release_package

    build_file = tmp_path / "Dockerfile"
    runtime_file = tmp_path / "scripts" / "runtime.py"
    runtime_file.parent.mkdir()
    build_file.write_text("FROM scratch\n")
    runtime_file.write_text("# exact runtime\n")
    build_file.chmod(0o400)
    runtime_file.chmod(0o400)
    marker = tmp_path / ".admin-ai-exact-runtime.json"
    marker.write_text(
        '{"schema_version":"newcaostone.admin-ai-exact-runtime.v1",'
        '"source_sha":"1111111111111111111111111111111111111111",'
        '"source_tree":"2222222222222222222222222222222222222222"}'
    )
    marker.chmod(0o400)
    monkeypatch.setattr(release_package, "BUILD_CONTEXT_PATHS", ("Dockerfile",))
    monkeypatch.setattr(
        release_package, "RUNTIME_TOOL_PATHS", ("scripts/runtime.py",)
    )

    def fail_runner(*_args, **_kwargs):
        raise AssertionError("snapshot capture must not call git")

    result = capture_repository(project_root=tmp_path, runner=fail_runner)

    assert result["source_sha"] == "1" * 40
    assert result["source_tree"] == "2" * 40
    assert result["tracked_tree_clean"] is True
    assert result["build_context_manifest"]["entries"][0]["path"] == "Dockerfile"
    assert result["runtime_tool_manifest"]["entries"][0]["path"] == (
        "scripts/runtime.py"
    )


def test_candidate_builder_adds_only_snapshot_root_before_project_imports() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "build_admin_ai_candidate.py"
    ).read_text()

    assert source.index("sys.path.insert(0, str(PROJECT_ROOT))") < source.index(
        "from scripts.admin_ai_oci_artifact import"
    )


def test_runtime_root_allowlist_matches_every_committed_top_level_entry() -> None:
    project_root = Path(__file__).resolve().parents[2]
    committed = subprocess.run(
        ["git", "ls-tree", "--name-only", "HEAD"],
        cwd=project_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()

    assert set(committed) == set(_ALLOWED_PROJECT_ROOT_ENTRIES)


def test_operations_factory_binding_reads_snapshot_bytes_without_git(
    tmp_path: Path,
) -> None:
    factory = tmp_path / "scripts" / "admin_ai_release_operations.py"
    factory.parent.mkdir()
    factory.write_text("def create_operations(): pass\n")
    factory.chmod(0o400)
    marker = tmp_path / ".admin-ai-exact-runtime.json"
    marker.write_text(
        '{"schema_version":"newcaostone.admin-ai-exact-runtime.v1",'
        '"source_sha":"1111111111111111111111111111111111111111",'
        '"source_tree":"2222222222222222222222222222222222222222"}'
    )
    marker.chmod(0o400)

    def fail_runner(*_args, **_kwargs):
        raise AssertionError("snapshot factory binding must not call git")

    result = capture_operations_factory(
        "scripts.admin_ai_release_operations:create_operations",
        source_sha="1" * 40,
        project_root=tmp_path,
        runner=fail_runner,
    )

    assert result["source_path"] == "scripts/admin_ai_release_operations.py"
    assert len(result["source_sha256"]) == 64


def test_package_snapshot_copies_exact_inputs_and_executes_private_entrypoint(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "package-observation.json"
    entrypoint = """
from pathlib import Path
import argparse
import json
import os
from scripts.azure_ai_enablement_actions import DEPENDENCY_FILES
parser = argparse.ArgumentParser()
parser.add_argument("--candidate-artifact", type=Path, required=True)
parser.add_argument("--azure-authority-request", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
options = parser.parse_args()
options.output.write_text(json.dumps({
    "entrypoint": str(Path(__file__).resolve()),
    "project_root": str(Path(__file__).resolve().parents[1]),
    "environment_root": os.environ["BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT"],
    "artifact_path": str(options.candidate_artifact),
    "authority_path": str(options.azure_authority_request),
    "output_path": str(options.output),
    "artifact": options.candidate_artifact.read_text(),
    "authority": options.azure_authority_request.read_text(),
    "dependencies": DEPENDENCY_FILES,
}))
"""
    (project / "scripts").mkdir()
    (project / "scripts" / "admin_ai_exact_runtime.py").write_text(
        Path(exact_runtime.__file__).read_text()
    )
    (project / "scripts" / "azure_ai_enablement_actions.py").write_text(
        "from pathlib import Path\n"
        "import azure.identity\n"
        "import requests\n"
        "DEPENDENCY_FILES = [\n"
        "    str(Path(azure.identity.__file__).resolve()),\n"
        "    str(Path(requests.__file__).resolve()),\n"
        "]\n"
    )
    (project / "scripts" / "create_admin_ai_release_package.py").write_text(
        entrypoint
    )
    _write_trusted_runtime_dependencies(project)
    (project / ".gitignore").write_text(".tmp/\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"], cwd=project, check=True
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=project, check=True)
    artifact = project / ".tmp" / "candidate.oci.tar"
    artifact.parent.mkdir()
    artifact.write_text("exact candidate archive")
    artifact.chmod(0o400)
    authority = project / ".tmp" / "task10.json"
    authority.write_text("exact Task10 request")
    authority.chmod(0o600)

    source_sha = _head(project)
    committed_launcher = _git_show_from_project(
        project,
        f"{source_sha}:./scripts/admin_ai_exact_runtime.py",
    ).stdout
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-S",
            "-",
            "--project-root",
            str(project),
            "--source-sha",
            source_sha,
            "package",
            "--candidate-artifact",
            str(artifact),
            "--azure-authority-request",
            str(authority),
            "--output",
            str(output),
        ],
        input=committed_launcher,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"]},
    )

    observed = json.loads(output.read_text())
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "newcaostone-admin-ai-runtime-" in observed["entrypoint"]
    assert observed["entrypoint"] != str(
        (project / "scripts" / "create_admin_ai_release_package.py").resolve()
    )
    assert observed["environment_root"] == observed["project_root"]
    assert observed["artifact_path"] == str(
        Path(observed["artifact_path"]).resolve()
    )
    assert observed["artifact_path"].startswith(observed["project_root"] + "/")
    assert observed["authority_path"] == str(
        Path(observed["authority_path"]).resolve()
    )
    assert observed["authority_path"].startswith(observed["project_root"] + "/")
    assert Path(observed["output_path"]).resolve() == output.resolve()
    assert not observed["output_path"].startswith(observed["project_root"] + "/")
    assert observed["artifact"] == "exact candidate archive"
    assert observed["authority"] == "exact Task10 request"
    assert all(
        "newcaostone-admin-ai-runtime-" in path
        and "/.runtime-dependencies/" in path
        for path in observed["dependencies"]
    )


def test_authority_refresh_snapshot_copies_only_verified_r19_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "authority-refresh-observation.json"
    entrypoint = """
from pathlib import Path
import argparse
import json
import os
parser = argparse.ArgumentParser()
parser.add_argument("--r19-package", type=Path, required=True)
parser.add_argument("--r19-receipt", type=Path, required=True)
parser.add_argument("--authority-output-root", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
options = parser.parse_args()
options.output.write_text(json.dumps({
    "entrypoint": str(Path(__file__).resolve()),
    "environment_root": os.environ["BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT"],
    "package_path": str(options.r19_package),
    "receipt_path": str(options.r19_receipt),
    "output_root": str(options.authority_output_root),
    "package": options.r19_package.read_text(),
    "receipt": options.r19_receipt.read_text(),
}))
"""
    (project / "scripts").mkdir()
    (project / "scripts" / "refresh_admin_ai_current_authority.py").write_text(
        entrypoint
    )
    _write_trusted_runtime_dependencies(project)
    (project / ".gitignore").write_text(".tmp/\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"], cwd=project, check=True
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=project, check=True)
    private = project / ".tmp"
    private.mkdir()
    r19_package = private / "LAUNCH_AUTHORIZATION_AI_ENABLEMENT_R19_2026-08-17.json"
    r19_receipt = private / "AI_ENABLEMENT_RECEIPT_R19_2026-08-17.json"
    r19_package.write_text("exact retired R19 package")
    r19_receipt.write_text("exact retired R19 receipt")
    r19_package.chmod(0o600)
    r19_receipt.chmod(0o600)
    monkeypatch.setattr(
        exact_runtime,
        "R19_PACKAGE_SHA256",
        hashlib.sha256(r19_package.read_bytes()).hexdigest(),
        raising=False,
    )
    monkeypatch.setattr(
        exact_runtime,
        "R19_RECEIPT_SHA256",
        hashlib.sha256(r19_receipt.read_bytes()).hexdigest(),
        raising=False,
    )

    result = run_from_exact_snapshot(
        "authority-refresh",
        ["--output", str(output)],
        project_root=project,
        source_sha=_head(project),
        environment={"PATH": os.environ["PATH"]},
        python_executable=sys.executable,
    )

    observed = json.loads(output.read_text())
    assert result == 0
    assert "newcaostone-admin-ai-runtime-" in observed["entrypoint"]
    assert observed["environment_root"] in observed["entrypoint"]
    assert observed["package_path"].startswith(observed["environment_root"] + "/")
    assert observed["receipt_path"].startswith(observed["environment_root"] + "/")
    assert observed["output_root"] == str(project.resolve())
    assert observed["package"] == "exact retired R19 package"
    assert observed["receipt"] == "exact retired R19 receipt"
    assert Path(observed["package_path"]) != r19_package
    assert Path(observed["receipt_path"]) != r19_receipt


def test_release_snapshot_copies_only_the_package_bound_oci_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "artifact.txt"
    entrypoint = """
from pathlib import Path
import argparse
import json
import httpx
parser = argparse.ArgumentParser()
parser.add_argument("--package", type=Path, required=True)
parser.add_argument("--approved-sha256", required=True)
parser.add_argument("--output", type=Path, required=True)
options = parser.parse_args()
package = json.loads(options.package.read_text())
artifact = Path(__file__).resolve().parents[1] / package["candidate"]["artifact_path"]
options.output.write_text(
    f"{Path(__file__).resolve()}\\n{artifact.read_text()}\\n{Path(httpx.__file__).resolve()}"
)
"""
    (project / "scripts").mkdir()
    (project / "scripts" / "run_admin_ai_release.py").write_text(entrypoint)
    trusted_dependencies = _write_trusted_runtime_dependencies(project)
    (project / ".gitignore").write_text(".tmp/\n")
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    subprocess.run(
        ["git", "config", "user.email", "tests@example.invalid"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tests"], cwd=project, check=True
    )
    subprocess.run(["git", "add", "."], cwd=project, check=True)
    subprocess.run(["git", "commit", "-qm", "fixture"], cwd=project, check=True)
    artifact = project / ".tmp" / "candidate.oci.tar"
    artifact.parent.mkdir()
    artifact.write_text("exact approved OCI bytes")
    artifact.chmod(0o400)
    package = project / ".tmp" / "package.json"
    package_payload = {
        "repository": {
            "source_sha": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=project, check=True,
                capture_output=True, text=True,
            ).stdout.strip(),
            "runtime_dependency_manifest": trusted_dependencies,
        },
        "candidate": {
            "artifact_path": ".tmp/candidate.oci.tar",
            "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        },
    }
    package.write_text(json.dumps(package_payload))
    package.chmod(0o600)
    approved = hashlib.sha256(package.read_bytes()).hexdigest()

    master, slave = pty.openpty()
    release_tty = os.fdopen(os.dup(slave), "r")
    monkeypatch.setattr(exact_runtime, "_open_release_tty", lambda: release_tty)
    try:
        result = run_from_exact_snapshot(
            "release",
            [
                "--package",
                str(package),
                "--approved-sha256",
                approved,
                "--output",
                str(output),
            ],
            project_root=project,
            source_sha=_head(project),
            environment={"PATH": os.environ["PATH"]},
            python_executable=sys.executable,
        )
    finally:
        os.close(master)
        os.close(slave)

    assert result == 0
    observed_path, observed_artifact, observed_httpx = output.read_text().splitlines()
    assert "newcaostone-admin-ai-runtime-" in observed_path
    assert observed_path != str(
        (project / "scripts" / "run_admin_ai_release.py").resolve()
    )
    assert observed_artifact == "exact approved OCI bytes"
    assert "newcaostone-admin-ai-runtime-" in observed_httpx
    assert "/.runtime-dependencies/httpx/" in observed_httpx
    assert str(Path(sysconfig.get_path("purelib"))) not in observed_httpx


def test_exact_release_launcher_routes_child_stdin_to_controlling_tty(
    tmp_path: Path,
) -> None:
    project, output, package, approved, source_sha, launcher = (
        _release_launcher_fixture(tmp_path)
    )
    master, slave = pty.openpty()

    def establish_controlling_tty() -> None:
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

    try:
        process = subprocess.Popen(
            _release_launcher_command(
                project,
                output,
                package,
                approved,
                source_sha,
            ),
            cwd=project,
            stdin=subprocess.PIPE,
            stdout=slave,
            stderr=slave,
            text=True,
            env={"PATH": os.environ["PATH"]},
            preexec_fn=establish_controlling_tty,
        )
        process.communicate(input=launcher, timeout=30)
    finally:
        os.close(master)
        os.close(slave)

    assert process.returncode == 0
    assert output.read_text() == "tty"


def test_exact_release_launcher_without_tty_stops_before_entrypoint(
    tmp_path: Path,
) -> None:
    project, output, package, approved, source_sha, launcher = (
        _release_launcher_fixture(tmp_path)
    )

    completed = subprocess.run(
        _release_launcher_command(
            project,
            output,
            package,
            approved,
            source_sha,
        ),
        cwd=project,
        input=launcher,
        capture_output=True,
        text=True,
        check=False,
        env={"PATH": os.environ["PATH"]},
    )

    assert completed.returncode == 1
    assert "reason=runtime_release_tty_unavailable" in completed.stdout
    assert not output.exists()
