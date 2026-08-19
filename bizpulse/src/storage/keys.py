"""Validated workspace/session/version/run Blob key builders."""

from __future__ import annotations

import re
from hashlib import sha256
from pathlib import PurePosixPath

SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
LOWER_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def normalize_storage_key(key: str) -> str:
    raw = str(key)
    normalized = PurePosixPath(raw)
    if (
        "\x00" in raw
        or normalized.is_absolute()
        or not normalized.parts
        or ".." in normalized.parts
        or str(normalized) != raw
    ):
        raise ValueError("invalid_storage_key")
    return str(normalized)


def workspace_token(workspace_id: str) -> str:
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise ValueError("workspace_id_invalid")
    return sha256(workspace_id.encode()).hexdigest()[:24]


def staging_upload_key(workspace_id: str, session_id: str, upload_id: str) -> str:
    return normalize_storage_key(
        f"workspaces/{workspace_token(workspace_id)}/sessions/"
        f"{_safe_id(session_id, 'session_id')}/staging/"
        f"{_safe_id(upload_id, 'upload_id')}.part"
    )


def dataset_object_key(workspace_id: str, version_id: str, digest: str) -> str:
    return normalize_storage_key(
        f"workspaces/{workspace_token(workspace_id)}/versions/"
        f"{_safe_id(version_id, 'version_id')}/datasets/{_digest(digest)}.bin"
    )


def evidence_object_key(workspace_id: str, run_id: str, digest: str) -> str:
    return normalize_storage_key(
        f"workspaces/{workspace_token(workspace_id)}/runs/"
        f"{_safe_id(run_id, 'run_id')}/evidence/{_digest(digest)}.json"
    )


def export_object_key(workspace_id: str, run_id: str, digest: str) -> str:
    return normalize_storage_key(
        f"workspaces/{workspace_token(workspace_id)}/runs/"
        f"{_safe_id(run_id, 'run_id')}/exports/{_digest(digest)}.xlsx"
    )


def _safe_id(value: str, name: str) -> str:
    if not isinstance(value, str) or SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name}_invalid")
    return value


def _digest(value: str) -> str:
    if not isinstance(value, str) or LOWER_SHA256.fullmatch(value) is None:
        raise ValueError("sha256_invalid")
    return value
