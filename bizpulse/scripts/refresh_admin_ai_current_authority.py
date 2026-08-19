#!/usr/bin/env python3
"""Refresh current authority from one exact read-only hosted observation."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
from uuid import uuid4


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _require_exact_runtime_for_script() -> None:
    marker = PROJECT_ROOT / ".admin-ai-exact-runtime.json"
    try:
        metadata = marker.lstat()
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        metadata = None
        payload = None
    if (
        os.environ.get("BIZPULSE_ADMIN_AI_EXACT_RUNTIME_ROOT")
        != str(PROJECT_ROOT)
        or not sys.flags.isolated
        or not sys.dont_write_bytecode
        or not sys.flags.no_site
        or metadata is None
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o400
        or not isinstance(payload, Mapping)
        or payload.get("schema_version")
        != "newcaostone.admin-ai-exact-runtime.v1"
    ):
        print("admin_ai_authority_refresh=failed")
        print("reason=runtime_snapshot_required")
        raise SystemExit(1)


if __name__ == "__main__":
    _require_exact_runtime_for_script()


from scripts.create_ai_enablement_package import (  # noqa: E402
    AZURE_TARGET,
    PRIOR_AI_ATTEMPTS,
    collect_control_sha256,
)
from scripts.admin_ai_current_successor import (  # noqa: E402
    CURRENT_IDENTITY_STATE,
    CURRENT_RECOVERY_REVISION,
    R19_REGISTRY_TAG,
    R19_TERMINAL_REVISION,
    derive_current_admin_ai_successor,
)
from scripts.create_admin_ai_release_package import (  # noqa: E402
    build_fresh_task10_authority_request,
    collect_current_azure_baseline,
)
from scripts.refresh_current_authority import (  # noqa: E402
    repository_ai_capability,
    repository_migration_head,
)
from scripts.release_authority import (  # noqa: E402
    AuthorityInvalid,
    CurrentAuthority,
    _parse_authority,
    apply_authority_bundle_atomic,
    check_authority_documents,
    load_current_authority,
    load_document_policy,
    refresh_current_authority,
)


OBSERVED_DATABASE_REVISION = "0014_import_base_lineage"
AUTHORITY_FRESHNESS = timedelta(hours=1)
R19_PREDECESSOR_REVISION = (
    "newcaostone-demo-app--recover-b-22767486-20f39c8"
)
R19_PREDECESSOR_IMAGE = (
    "sellernorthbpacr.azurecr.io/bizpulse@sha256:"
    "20f39c82b499c98ba10c68129531a46b4fb7fe3a6c4e91a87ddcdff99bfc18c1"
)
R19_PREDECESSOR_TAG = "ai-790b71a7b95e-22767486"
_SHA = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_IMAGE_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class CurrentAuthorityRefreshInvalid(ValueError):
    """The read-only current-authority refresh failed closed."""


def _invalid(code: str) -> CurrentAuthorityRefreshInvalid:
    return CurrentAuthorityRefreshInvalid(code)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _invalid("authority_refresh_r19_provenance_invalid")
        result[key] = value
    return result


def _read_bound_json(path: Path, *, expected_sha256: object) -> object:
    if not isinstance(expected_sha256, str) or _SHA256.fullmatch(
        expected_sha256
    ) is None:
        raise _invalid("authority_refresh_r19_provenance_invalid")
    try:
        metadata = path.lstat()
        encoded = path.read_bytes()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or path.is_symlink()
            or stat.S_IMODE(metadata.st_mode) not in {0o400, 0o600}
            or not 0 < len(encoded) <= 2_000_000
            or hashlib.sha256(encoded).hexdigest() != expected_sha256
        ):
            raise _invalid("authority_refresh_r19_provenance_invalid")
        return json.loads(encoded, object_pairs_hook=_unique_object)
    except CurrentAuthorityRefreshInvalid:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise _invalid("authority_refresh_r19_provenance_invalid") from error


def validate_r19_deployment_provenance(
    package_path: Path,
    receipt_path: Path,
    *,
    expected: Mapping[str, object] | None = None,
) -> dict[str, str]:
    """Bind the current expected deployment to retired R19 evidence only."""

    source_contract = PRIOR_AI_ATTEMPTS["r19"] if expected is None else expected
    try:
        contract = {
            key: source_contract[key]
            for key in (
                "package_sha256",
                "receipt_sha256",
                "receipt_contract",
            )
        }
    except KeyError as error:
        raise _invalid("authority_refresh_r19_provenance_invalid") from error
    if set(contract) != {
        "package_sha256",
        "receipt_sha256",
        "receipt_contract",
    }:
        raise _invalid("authority_refresh_r19_provenance_invalid")
    package = _read_bound_json(
        package_path,
        expected_sha256=contract["package_sha256"],
    )
    receipt = _read_bound_json(
        receipt_path,
        expected_sha256=contract["receipt_sha256"],
    )
    if receipt != contract["receipt_contract"]:
        raise _invalid("authority_refresh_r19_provenance_invalid")
    try:
        repository = package["repository"]
        candidate = package["candidate"]
        predecessor = package["azure_target"]
        old_tag = package["prepackage_gate"]["rollback_registry_tag"]
        reconciliation = receipt["reconciliations"]
        if not isinstance(reconciliation, list) or len(reconciliation) != 1:
            raise TypeError
        terminal = reconciliation[0]
        candidate_sha = repository["head_sha"]
        candidate_tree = repository["tree_sha"]
        image_input = candidate["image_input_sha256"]
        revision = terminal["target_revision"]
        image_digest = terminal["target_image_digest"]
        package_sha = contract["package_sha256"]
        receipt_sha = contract["receipt_sha256"]
    except (KeyError, TypeError) as error:
        raise _invalid("authority_refresh_r19_provenance_invalid") from error
    registry_tag = f"ai-{candidate_sha[:12]}-{package_sha[:8]}"
    if (
        repository.get("branch") != "codex/newcaostone-authoritative-v1"
        or repository.get("clean") is not True
        or not isinstance(candidate_sha, str)
        or _SHA.fullmatch(candidate_sha) is None
        or not isinstance(candidate_tree, str)
        or _SHA.fullmatch(candidate_tree) is None
        or candidate.get("source_tree_sha") != candidate_tree
        or candidate.get("candidate_image_digest") is not None
        or candidate.get("image_repository") != "bizpulse"
        or not isinstance(image_input, str)
        or _SHA256.fullmatch(image_input) is None
        or predecessor.get("rollback_revision")
        != terminal.get("predecessor_revision")
        or predecessor.get("rollback_revision") != R19_PREDECESSOR_REVISION
        or predecessor.get("rollback_image") != R19_PREDECESSOR_IMAGE
        or old_tag != R19_PREDECESSOR_TAG
        or old_tag == registry_tag
        or terminal.get("role") != "ai_disabled_candidate"
        or terminal.get("final_state") != "healthy_target"
        or terminal.get("acknowledgement") != "accepted"
        or revision != AZURE_TARGET["rollback_revision"]
        or image_digest != AZURE_TARGET["rollback_image"].rsplit("@", 1)[-1]
        or not isinstance(image_digest, str)
        or _IMAGE_DIGEST.fullmatch(image_digest) is None
    ):
        raise _invalid("authority_refresh_r19_provenance_invalid")
    return {
        "candidate_git_sha": candidate_sha,
        "candidate_git_tree": candidate_tree,
        "candidate_image_input_sha256": image_input,
        "image_digest": image_digest,
        "revision": revision,
        "registry_tag": registry_tag,
        "r19_package_sha256": str(package_sha),
        "r19_receipt_sha256": str(receipt_sha),
    }


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise _invalid("authority_refresh_freshness_invalid")
    return value.astimezone(UTC).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def build_authority_observation(
    *,
    source_sha: str,
    provenance: Mapping[str, object],
    successor: Mapping[str, object],
    baseline: Mapping[str, object],
    observed_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    """Convert one exact safe baseline into the authority observation schema."""

    if (
        observed_at.tzinfo is None
        or expires_at.tzinfo is None
        or expires_at.astimezone(UTC) - observed_at.astimezone(UTC)
        != AUTHORITY_FRESHNESS
    ):
        raise _invalid("authority_refresh_freshness_invalid")
    expected_digest = AZURE_TARGET["rollback_image"].rsplit("@", 1)[-1]
    expected = {
        "required_azure_reads": 12,
        "health_state": "Healthy",
        "ready": True,
        "revision": CURRENT_RECOVERY_REVISION,
        "image_digest": expected_digest,
        "traffic_weight": 100,
        "operator_ai_enabled": False,
        "demo_ai_enabled": False,
        "role_assignment_phase": "officer_only",
        "database_revision": OBSERVED_DATABASE_REVISION,
    }
    if (
        _SHA.fullmatch(source_sha) is None
        or any(baseline.get(key) != value for key, value in expected.items())
        or baseline.get("observed_at") != _utc_text(observed_at)
        or not isinstance(baseline.get("observation_sha256"), str)
        or _SHA256.fullmatch(str(baseline["observation_sha256"])) is None
        or provenance.get("revision") != successor.get("historical_revision")
        or provenance.get("revision") != R19_TERMINAL_REVISION
        or provenance.get("image_digest") != expected_digest
        or successor.get("revision") != expected["revision"]
        or successor.get("image_digest") != expected_digest
        or successor.get("image") != AZURE_TARGET["rollback_image"]
        or successor.get("registry_tag") != provenance.get("registry_tag")
        or successor.get("registry_tag") != R19_REGISTRY_TAG
        or successor.get("identity_state") != CURRENT_IDENTITY_STATE
        or not isinstance(provenance.get("candidate_git_sha"), str)
        or _SHA.fullmatch(str(provenance["candidate_git_sha"])) is None
    ):
        raise _invalid("authority_refresh_observation_invalid")
    return {
        "ai_runtime_state": "disabled",
        "attestation_git_sha": source_sha,
        "candidate_git_sha": provenance["candidate_git_sha"],
        "database_migration_head": OBSERVED_DATABASE_REVISION,
        "evidence_kind": "sanitized_azure_readback",
        "evidence_sha256": baseline["observation_sha256"],
        "expires_at": _utc_text(expires_at),
        "image_digest": expected_digest,
        "observed_at": _utc_text(observed_at),
        "revision": CURRENT_RECOVERY_REVISION,
    }


def _build_fresh_observation_request(
    **kwargs: object,
) -> dict[str, object]:
    return build_fresh_task10_authority_request(**kwargs)


def run_readonly_authority_refresh(
    *,
    r19_package: Path,
    r19_receipt: Path,
    authority_output_root: Path,
    source_sha: str,
    source_tree: str,
    artifact_id: str,
    now: datetime,
    current_authority: CurrentAuthority,
    document_policy: Mapping[str, object],
    r19_expected: Mapping[str, object] | None = None,
    request_builder: Callable[..., dict[str, object]] = (
        _build_fresh_observation_request
    ),
    baseline_reader: Callable[..., dict[str, object]] = (
        collect_current_azure_baseline
    ),
    bundle_writer: Callable[..., tuple[Path, ...]] = (
        apply_authority_bundle_atomic
    ),
    preflight: Callable[[], None] = lambda: None,
    postread_fence: Callable[[], None] = lambda: None,
    successor_deriver: Callable[..., dict[str, str]] = (
        derive_current_admin_ai_successor
    ),
    provenance_validator: Callable[..., dict[str, str]] = (
        validate_r19_deployment_provenance
    ),
) -> dict[str, object]:
    """Observe once, then apply one validated authority/document bundle."""

    if (
        _SHA.fullmatch(source_sha) is None
        or _SHA.fullmatch(source_tree) is None
        or now.tzinfo is None
    ):
        raise _invalid("authority_refresh_source_invalid")
    preflight()
    provenance = provenance_validator(
        r19_package,
        r19_receipt,
        expected=r19_expected,
    )
    receipt_contract = (
        PRIOR_AI_ATTEMPTS["r19"]["receipt_contract"]
        if r19_expected is None
        else r19_expected.get("receipt_contract")
    )
    successor = successor_deriver(
        provenance,
        receipt_contract=receipt_contract,
    )
    try:
        from scripts.create_release_manifest import (  # noqa: PLC0415
            DEPENDENCY_FILES,
            image_input_sha256,
        )

        dependency_hashes = {
            path: hashlib.sha256((PROJECT_ROOT / path).read_bytes()).hexdigest()
            for path in DEPENDENCY_FILES
        }
        candidate_image_input = image_input_sha256(
            git_tree=source_tree,
            dependency_hashes=dependency_hashes,
        )
        request = request_builder(
            repository={
                "source_sha": source_sha,
                "source_tree": source_tree,
                "tracked_tree_clean": True,
            },
            candidate_artifact={"image_input_sha256": candidate_image_input},
            generated_at=now,
            role_assignment_state="officer_only",
            artifact_id=artifact_id,
            project_root=PROJECT_ROOT,
            control_sha256=collect_control_sha256(project_root=PROJECT_ROOT),
            prior_attempts=PRIOR_AI_ATTEMPTS,
        )
    except CurrentAuthorityRefreshInvalid:
        raise
    except Exception as error:
        raise _invalid("authority_refresh_request_invalid") from error
    baseline = baseline_reader(
        request,
        observed_at=now,
        source_sha=source_sha,
        source_tree=source_tree,
        image_input_sha256=candidate_image_input,
        verified_prior_attempts=PRIOR_AI_ATTEMPTS,
    )
    observation = build_authority_observation(
        source_sha=source_sha,
        provenance=provenance,
        successor=successor,
        baseline=baseline,
        observed_at=now,
        expires_at=now + AUTHORITY_FRESHNESS,
    )
    postread_fence()
    payload = refresh_current_authority(
        {
            key: value
            for key, value in observation.items()
            if key not in {"observed_at", "expires_at"}
        },
        None,
        observed_at=now,
        expires_at=now + AUTHORITY_FRESHNESS,
        current_authority=current_authority,
        verified_provenance={
            "attestation_git_sha": source_sha,
            "candidate_git_sha": provenance["candidate_git_sha"],
            "image_digest": provenance["image_digest"],
            "revision": successor["revision"],
        },
    )
    authority = _parse_authority(payload).with_development(
        repository_migration_head=repository_migration_head(PROJECT_ROOT),
        ai_capability_state=repository_ai_capability(PROJECT_ROOT),
    )
    bundle_writer(
        authority_path=authority_output_root / "release/current_authority.json",
        authority=authority,
        policy=document_policy,
        repository_root=authority_output_root.parent,
    )
    return {
        "azure_read_count": 12,
        "database_revision": observation["database_migration_head"],
        "evidence_sha256": observation["evidence_sha256"],
        "expires_at": observation["expires_at"],
        "revision": observation["revision"],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--r19-package", type=Path, required=True)
    parser.add_argument("--r19-receipt", type=Path, required=True)
    parser.add_argument("--authority-output-root", type=Path, required=True)
    return parser


def _git_binding(project_root: Path) -> tuple[str, str, str]:
    values: list[str] = []
    for arguments in (
        ("rev-parse", "--verify", "HEAD^{commit}"),
        ("rev-parse", "HEAD^{tree}"),
        ("status", "--porcelain=v1", "--untracked-files=all"),
    ):
        try:
            completed = subprocess.run(
                ["git", *arguments],
                cwd=project_root,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
                shell=False,
                env={
                    name: value
                    for name in (
                        "HOME",
                        "LANG",
                        "LC_ALL",
                        "PATH",
                        "TMPDIR",
                    )
                    if isinstance((value := os.environ.get(name)), str)
                },
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise _invalid("authority_refresh_source_invalid") from error
        if completed.returncode != 0 or not isinstance(completed.stdout, str):
            raise _invalid("authority_refresh_source_invalid")
        values.append(completed.stdout.strip())
    return values[0], values[1], values[2]


def _target_hashes(
    authority_path: Path,
    policy: Mapping[str, object],
    repository_root: Path,
) -> dict[Path, str]:
    try:
        documents = policy["documents"]
        if not isinstance(documents, list):
            raise TypeError
        paths = [authority_path]
        paths.extend(repository_root / str(item["path"]) for item in documents)
        result: dict[Path, str] = {}
        for path in paths:
            metadata = path.lstat()
            if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
                raise OSError
            result[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        return result
    except (KeyError, TypeError, OSError) as error:
        raise _invalid("authority_refresh_document_drift") from error


def load_refresh_runtime_context(
    snapshot_root: Path,
    output_root: Path,
) -> dict[str, object]:
    """Bind the clean original checkout and its authority bundle before reads."""

    try:
        from scripts.admin_ai_exact_runtime import (  # noqa: PLC0415
            load_exact_runtime_marker,
        )

        marker = load_exact_runtime_marker(snapshot_root)
        canonical_output = output_root.resolve(strict=True)
        metadata = canonical_output.lstat()
    except Exception as error:
        raise _invalid("authority_refresh_source_invalid") from error
    if (
        marker is None
        or canonical_output.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
    ):
        raise _invalid("authority_refresh_source_invalid")
    repository_root = canonical_output.parent
    authority_path = canonical_output / "release/current_authority.json"
    policy_path = canonical_output / "release/authority-document-policy.json"
    try:
        current = load_current_authority(authority_path)
        policy = load_document_policy(policy_path)
    except AuthorityInvalid as error:
        raise _invalid("authority_refresh_document_drift") from error
    initial_hashes = _target_hashes(authority_path, policy, repository_root)

    def fence() -> None:
        head, tree, status = _git_binding(canonical_output)
        if (
            head != marker["source_sha"]
            or tree != marker["source_tree"]
            or status
            or _target_hashes(authority_path, policy, repository_root)
            != initial_hashes
            or check_authority_documents(current, policy, repository_root)
        ):
            raise _invalid("authority_refresh_document_drift")

    def bundle_writer(**kwargs: object) -> tuple[Path, ...]:
        try:
            return apply_authority_bundle_atomic(
                **kwargs,
                expected_sha256=initial_hashes,
            )
        except AuthorityInvalid as error:
            raise _invalid("authority_refresh_bundle_write_failed") from error

    return {
        "source_sha": marker["source_sha"],
        "source_tree": marker["source_tree"],
        "current_authority": current,
        "document_policy": policy,
        "preflight": fence,
        "postread_fence": fence,
        "bundle_writer": bundle_writer,
    }


def main(
    arguments: list[str] | None = None,
    *,
    now_factory: Callable[[], datetime] = lambda: datetime.now(UTC),
    artifact_id_factory: Callable[[], object] = uuid4,
    refresh_runner: Callable[..., dict[str, object]] = (
        run_readonly_authority_refresh
    ),
    runtime_context_loader: Callable[[Path, Path], Mapping[str, object]] = (
        load_refresh_runtime_context
    ),
) -> int:
    options = _parser().parse_args(arguments)
    try:
        context = runtime_context_loader(PROJECT_ROOT, options.authority_output_root)
        result = refresh_runner(
            r19_package=options.r19_package,
            r19_receipt=options.r19_receipt,
            authority_output_root=options.authority_output_root.resolve(strict=True),
            source_sha=context["source_sha"],
            source_tree=context["source_tree"],
            artifact_id=str(artifact_id_factory()),
            now=now_factory(),
            current_authority=context["current_authority"],
            document_policy=context["document_policy"],
            preflight=context["preflight"],
            postread_fence=context["postread_fence"],
            bundle_writer=context["bundle_writer"],
        )
    except Exception as error:
        code = str(error)
        if re.fullmatch(r"[a-z0-9_]{3,96}", code) is None:
            code = "authority_refresh_failed"
        print("admin_ai_authority_refresh=failed")
        print(f"reason={code}")
        return 1
    print("admin_ai_authority_refresh=updated")
    for field in (
        "azure_read_count",
        "revision",
        "database_revision",
        "expires_at",
        "evidence_sha256",
    ):
        print(f"{field}={result[field]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
