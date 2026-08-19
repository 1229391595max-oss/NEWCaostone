"""Run checked-in verification selected from Git changed paths."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Mapping

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_REPOSITORY_ROOT = _PROJECT_ROOT.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.select_required_checks import (  # noqa: E402
    EVIDENCE_SCHEMA,
    Check,
    VerificationPolicy,
    VerificationPolicyError,
    can_reuse,
    domain_fingerprint,
    load_verification_policy,
    select_required_checks,
)


class FullReleaseRequired(RuntimeError):
    """Raised when immutable release paths require the non-cacheable final gate."""


def _timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def combined_domain_fingerprint(
    repository_root: Path,
    policy: VerificationPolicy,
    check: Check,
) -> str:
    domains = policy.domains_for_check(check.name)
    if not domains:
        raise VerificationPolicyError(
            f"verification_policy_check_without_domain:{check.name}"
        )
    digest = hashlib.sha256()
    for domain in sorted(domains, key=lambda item: item.name):
        digest.update(domain.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(domain_fingerprint(repository_root, domain).encode("ascii"))
    return digest.hexdigest()


def _evidence_path(evidence_dir: Path, check: Check) -> Path:
    if re.fullmatch(r"[a-z0-9_]+", check.name) is None:
        raise VerificationPolicyError(
            f"verification_policy_invalid_check_name:{check.name}"
        )
    return evidence_dir / f"{check.name}.json"


def _load_evidence(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, Mapping) else {}


def execute_check(
    check: Check,
    *,
    fingerprint: str,
    project_root: Path,
    evidence_dir: Path,
) -> int:
    if check.reuse == "never" or not check.argv:
        raise FullReleaseRequired(f"full_release_gate_required:{check.name}")
    started_at = _timestamp()
    try:
        completed = subprocess.run(
            list(check.argv),
            cwd=project_root,
            check=False,
        )
        exit_code = completed.returncode
    except OSError as error:
        print(f"verification_check_launch_failed:{check.name}:{error}")
        exit_code = 127
    ended_at = _timestamp()
    evidence = {
        "argv": list(check.argv),
        "check": check.name,
        "domain_fingerprint": fingerprint,
        "ended_at": ended_at,
        "exit_code": exit_code,
        "passed": exit_code == 0,
        "schema_version": EVIDENCE_SCHEMA,
        "started_at": started_at,
    }
    evidence_dir.mkdir(parents=True, exist_ok=True)
    _evidence_path(evidence_dir, check).write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return exit_code


def _git_lines(repository_root: Path, argv: list[str]) -> tuple[str, ...]:
    completed = subprocess.run(
        ["git", *argv],
        cwd=repository_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise VerificationPolicyError(f"verification_git_failed:{detail}")
    return tuple(line for line in completed.stdout.splitlines() if line)


def changed_paths(repository_root: Path, base: str) -> tuple[str, ...]:
    sources = (
        _git_lines(
            repository_root,
            ["diff", "--name-only", f"{base}...HEAD"],
        ),
        _git_lines(
            repository_root,
            ["diff", "--name-only", "HEAD"],
        ),
        _git_lines(
            repository_root,
            ["diff", "--cached", "--name-only"],
        ),
        _git_lines(repository_root, ["ls-files", "--others", "--exclude-standard"]),
    )
    return tuple(sorted({path for source in sources for path in source}))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--no-reuse", action="store_true")
    parser.add_argument(
        "--policy",
        type=Path,
        default=_PROJECT_ROOT / "release/verification-policy.json",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=_REPOSITORY_ROOT,
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_PROJECT_ROOT,
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=_PROJECT_ROOT / ".artifacts/verification",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        policy = load_verification_policy(arguments.policy)
        paths = changed_paths(arguments.repository_root, arguments.base)
        if not paths:
            print("verification_changed=no_changes")
            return 0
        checks = select_required_checks(paths, policy)
        if any(check.reuse == "never" for check in checks):
            names = ",".join(
                check.name for check in checks if check.reuse == "never"
            )
            raise FullReleaseRequired(f"full_release_gate_required:{names}")
        for check in checks:
            fingerprint = combined_domain_fingerprint(
                arguments.repository_root,
                policy,
                check,
            )
            evidence_path = _evidence_path(arguments.evidence_dir, check)
            evidence = _load_evidence(evidence_path)
            if not arguments.no_reuse and can_reuse(
                evidence,
                check=check,
                fingerprint=fingerprint,
            ):
                print(f"{check.name}=reuse")
                continue
            print(f"{check.name}=run")
            if execute_check(
                check,
                fingerprint=fingerprint,
                project_root=arguments.project_root,
                evidence_dir=arguments.evidence_dir,
            ) != 0:
                print(f"{check.name}=failed")
                return 1
            print(f"{check.name}=passed")
    except (FullReleaseRequired, VerificationPolicyError) as error:
        print(str(error))
        return 2
    print("verification_changed=passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
