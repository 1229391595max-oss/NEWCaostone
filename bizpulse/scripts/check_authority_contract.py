"""Validate the machine authority and generated active document blocks."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path
import sys

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.release_authority import (  # noqa: E402
    AuthorityInvalid,
    check_authority_documents,
    load_current_authority,
    load_document_policy,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("docs", "release"), required=True)
    parser.add_argument(
        "--authority",
        type=Path,
        default=_PROJECT_ROOT / "release/current_authority.json",
    )
    parser.add_argument(
        "--document-policy",
        type=Path,
        default=_PROJECT_ROOT / "release/authority-document-policy.json",
    )
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=_PROJECT_ROOT.parent,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        authority = load_current_authority(
            arguments.authority,
            now=datetime.now(UTC),
            require_fresh_observation=arguments.mode == "release",
        )
        policy = load_document_policy(arguments.document_policy)
        violations = check_authority_documents(
            authority,
            policy,
            arguments.repository_root,
        )
    except AuthorityInvalid as error:
        print(str(error))
        return 1
    if violations:
        for violation in violations:
            print(violation.render())
        return 1
    print("authority_contract=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
