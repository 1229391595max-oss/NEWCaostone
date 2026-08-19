"""Refresh checked-in current authority from local sanitized inputs only."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import sys
from typing import Mapping

_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_DEFAULT_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_DEFAULT_PROJECT_ROOT))

from scripts.release_authority import (  # noqa: E402
    AuthorityInvalid,
    load_current_authority,
    load_document_policy,
    refresh_current_authority,
    render_authority_blocks,
    write_authority,
    _parse_authority,
    _parse_time,
)


def _assignment(tree: ast.Module, name: str) -> object | None:
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        if isinstance(target, ast.Name) and target.id == name and value is not None:
            try:
                return ast.literal_eval(value)
            except (ValueError, SyntaxError) as error:
                raise AuthorityInvalid(
                    f"repository_migration_assignment_invalid:{name}"
                ) from error
    return None


def repository_migration_head(project_root: Path) -> str:
    versions = project_root / "alembic/versions"
    revisions: set[str] = set()
    parents: set[str] = set()
    for path in sorted(versions.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _assignment(tree, "revision")
        down_revision = _assignment(tree, "down_revision")
        if not isinstance(revision, str):
            raise AuthorityInvalid(f"repository_migration_revision_invalid:{path.name}")
        revisions.add(revision)
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, tuple):
            if not all(isinstance(item, str) for item in down_revision):
                raise AuthorityInvalid(
                    f"repository_migration_down_revision_invalid:{path.name}"
                )
            parents.update(down_revision)
        elif down_revision is not None:
            raise AuthorityInvalid(
                f"repository_migration_down_revision_invalid:{path.name}"
            )
    heads = sorted(revisions - parents)
    if len(heads) != 1:
        raise AuthorityInvalid(f"repository_migration_head_invalid:{','.join(heads)}")
    return heads[0]


def repository_ai_capability(project_root: Path) -> str:
    required = (
        project_root / "src/ai/openai_gateway.py",
        project_root / "src/ai/query_catalog.py",
        project_root / "src/services/ai_chat_service.py",
    )
    return "implemented" if all(path.is_file() for path in required) else "absent"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--repository-only", action="store_true")
    source.add_argument("--observation-json", type=Path)
    parser.add_argument("--attestation-dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--document-policy", type=Path)
    parser.add_argument("--write-documents", action="store_true")
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=_DEFAULT_PROJECT_ROOT.parent,
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=_DEFAULT_PROJECT_ROOT,
    )
    return parser


def _load_observation(path: Path) -> tuple[Mapping[str, object], object, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuthorityInvalid("authority_observation_invalid") from error
    if not isinstance(payload, Mapping):
        raise AuthorityInvalid("authority_observation_invalid")
    if set(payload) != {
        "ai_runtime_state",
        "attestation_git_sha",
        "candidate_git_sha",
        "database_migration_head",
        "evidence_kind",
        "evidence_sha256",
        "expires_at",
        "image_digest",
        "observed_at",
        "revision",
    }:
        raise AuthorityInvalid("authority_observation_invalid")
    observed_at = payload["observed_at"]
    expires_at = payload["expires_at"]
    observation = {
        key: value
        for key, value in payload.items()
        if key not in {"observed_at", "expires_at"}
    }
    return observation, observed_at, expires_at


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.repository_only:
            authority = load_current_authority(arguments.output)
            authority = authority.with_development(
                repository_migration_head=repository_migration_head(
                    arguments.project_root
                ),
                ai_capability_state=repository_ai_capability(arguments.project_root),
            )
        else:
            if arguments.attestation_dir is None:
                raise AuthorityInvalid("authority_attestation_directory_required")
            observation, observed_at, expires_at = _load_observation(
                arguments.observation_json
            )
            payload = refresh_current_authority(
                observation,
                arguments.attestation_dir,
                observed_at=_parse_time(observed_at, field="observed_at"),
                expires_at=_parse_time(expires_at, field="expires_at"),
            )
            authority = _parse_authority(payload)
            authority = authority.with_development(
                repository_migration_head=repository_migration_head(
                    arguments.project_root
                ),
                ai_capability_state=repository_ai_capability(arguments.project_root),
            )
        write_authority(arguments.output, authority)
        if arguments.write_documents:
            if arguments.document_policy is None:
                raise AuthorityInvalid("authority_document_policy_required")
            policy = load_document_policy(arguments.document_policy)
            render_authority_blocks(authority, policy, arguments.repository_root)
    except AuthorityInvalid as error:
        print(str(error))
        return 1
    print("current_authority=updated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
