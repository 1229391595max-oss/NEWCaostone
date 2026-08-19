#!/usr/bin/env python3
"""Build the exact AI-disabled then AI-enabled launch authorization wrapper."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
from typing import Any
from uuid import uuid4, uuid5

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tests.hosted.verify_azure_demo import (  # noqa: E402
    APPROVED_AI_LIMITS,
    AuthorizationInvalid,
    BASE_OPERATIONS,
    CANDIDATE_HASH_PATHS,
    EXPECTED_SERVER_SETTINGS,
    EXPECTED_STOP_CONDITIONS,
    QUALIFICATION_RECEIPT_PATH,
    SEED_NAMESPACE,
    TWO_STAGE_HEADER,
    _expected_commands,
    _expected_execution_order,
    _expected_ai_transition_commands,
    _timestamp,
    data_authority_sha256,
    load_authorization,
    load_two_stage_authorization,
)


class TwoStagePackageInvalid(RuntimeError):
    """The two-stage package cannot enforce the approved release boundary."""


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_data_stage_authority(
    *,
    attestation_path: Path,
    attestation_git_sha: str,
    authorization_id: str,
    issued_at: str,
    expires_at: str,
    subscription_id: str,
    region: str,
    resource_group: str,
    public_url: str,
    name_prefix: str,
    registry_name: str,
    image_repository: str,
    storage_account: str,
    postgres_server: str,
    postgres_administrator_login: str,
    observed_current_image_digest: str,
    hard_cap_usd: str,
    one_time_estimate_usd: str,
    monthly_estimate_usd: str,
    registry_publish: bool = True,
) -> dict[str, Any]:
    """Build one value-complete update authority from the immutable attestation."""

    try:
        manifest = json.loads(attestation_path.read_text())
        candidate = str(manifest["candidate_git_sha"])
        candidate_image = str(manifest["candidate_image"]["digest"])
        image_input = str(manifest["image_input_sha256"])
        migration = str(manifest["migration_head"])
        rollback_sha = str(manifest["rollback_compatible_prior_sha"])
        rollback_digest = str(manifest["rollback_image_digest"])
        rollback_image_input = str(manifest["rollback_image_input_sha256"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise TwoStagePackageInvalid("release_attestation_invalid") from error
    if any(
        re.fullmatch(pattern, value) is None
        for pattern, value in (
            (r"[0-9a-f]{40}", candidate),
            (r"[0-9a-f]{40}", attestation_git_sha),
            (r"[0-9a-f]{40}", rollback_sha),
            (r"sha256:[0-9a-f]{64}", candidate_image),
            (r"sha256:[0-9a-f]{64}", rollback_digest),
            (r"sha256:[0-9a-f]{64}", observed_current_image_digest),
            (r"[0-9a-f]{64}", image_input),
            (r"[0-9a-f]{64}", rollback_image_input),
            (r"[0-9]{4}_[a-z0-9_]+", migration),
        )
    ):
        raise TwoStagePackageInvalid("release_attestation_invalid")

    synthetic_manifest = (
        _PROJECT_ROOT / "tests/fixtures/synthetic/v1/manifest.json"
    )
    synthetic_sha256 = _sha256_file(synthetic_manifest)
    application = f"{name_prefix}-app"
    generated = {
        "application_insights": f"{name_prefix}-insights",
        "application_revision": f"{application}--{candidate_image[7:19]}",
        "container_app": application,
        "container_environment": f"{name_prefix}-env",
        "image_repository": image_repository,
        "log_workspace": f"{name_prefix}-logs",
        "migration_job": f"{name_prefix}-prepare",
        "name_prefix": name_prefix,
        "postgres_administrator_login": postgres_administrator_login,
        "postgres_dns_zone": "private.postgres.database.azure.com",
        "postgres_server": postgres_server,
        "registry_identity": f"{name_prefix}-registry",
        "registry_name": registry_name,
        "seed_job": f"{name_prefix}-seed",
        "session_maintenance_job": f"{name_prefix}-sessions",
        "storage_account": storage_account,
        "storage_maintenance_job": f"{name_prefix}-storage",
        "virtual_network": f"{name_prefix}-vnet",
    }
    release: dict[str, Any] = {
        "attestation_git_sha": attestation_git_sha,
        "git_sha": candidate,
        "image_digest": candidate_image,
        "image_input_sha256": image_input,
        "local_manifest_sha256": _sha256_file(attestation_path),
        "migration_head": migration,
        "rollback_git_sha": rollback_sha,
        "rollback_image_digest": rollback_digest,
        "rollback_image_input_sha256": rollback_image_input,
        "synthetic_dataset_version_id": str(
            uuid5(SEED_NAMESPACE, f"version:{synthetic_sha256}")
        ),
        "synthetic_manifest_sha256": synthetic_sha256,
    }
    for field, relative in CANDIDATE_HASH_PATHS.items():
        release[field] = _sha256_file(_PROJECT_ROOT.parent / relative)
    authority: dict[str, Any] = {
        "schema_version": "newcaostone.launch-authorization.v4",
        "authorization_id": authorization_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "subscription_id": subscription_id,
        "region": region,
        "resource_group": resource_group,
        "public_url": public_url,
        "public_url_source": "exact",
        "generated_names": generated,
        "release": release,
        "resources": {
            "application": {
                "count": 1,
                "cpu": "0.5",
                "max_replicas": 1,
                "memory": "1Gi",
                "min_replicas": 1,
                "sku": "Consumption",
            },
            "monitoring": {"log_retention_days": 30},
            "postgres": {
                "backup_retention_days": 7,
                "count": 1,
                "public_network": False,
                "sku": "Standard_B1ms",
                "storage_gb": 32,
                "tier": "Burstable",
                "version": "16",
            },
            "storage": {
                "container": "synthetic-demo",
                "count": 1,
                "public_access": False,
                "sku": "Standard_LRS",
            },
        },
        "limits_usd": {
            "one_time_estimate": one_time_estimate_usd,
            "monthly_estimate": monthly_estimate_usd,
            "hard_cap": hard_cap_usd,
            "openai_smoke_cap": "0.00",
        },
        "ai_limits": {"enabled": False, **APPROVED_AI_LIMITS},
        "secret_presence": {
            "blob_credential": True,
            "openai_api_key": False,
            "operator_password_hash": True,
            "postgres_password": True,
            "registry_password": False,
            "session_pepper": True,
        },
        "server_settings": list(EXPECTED_SERVER_SETTINGS),
        "external_publication": {
            "dns_change": False,
            "github_push": False,
            "paid_ai_smoke": False,
            "registry_publish": registry_publish,
        },
        "recovery": {
            "blob_soft_delete_days": 7,
            "observed_current_image_digest": observed_current_image_digest,
            "postgres_backup_retention_days": 7,
            "restart_readback": True,
            "rollback_digest_preflight": True,
            "rollback_rehearsal": True,
            "target_mode": "update",
        },
        "commands": {},
        "execution_order": [],
        "retry_limits": {"read": 1, "deploy": 0, "paid_provider": 0},
        "allowed_operations": [
            BASE_OPERATIONS[0],
            *(["registry_publish"] if registry_publish else []),
            *BASE_OPERATIONS[1:],
        ],
        "stop_conditions": list(EXPECTED_STOP_CONDITIONS),
    }
    expected_commands = _expected_commands(authority)
    authority["commands"] = {
        stage: [shlex.join(command) for command in commands]
        for stage, commands in expected_commands.items()
    }
    authority["execution_order"] = list(_expected_execution_order(authority))
    return authority


def build_two_stage_package(
    *,
    data_authority: dict[str, Any],
    tenant_id: str,
    package_id: str,
    hard_cap_usd: str,
    qualification_cap_usd: str,
    hosted_smoke_cap_usd: str,
) -> dict[str, Any]:
    try:
        generated = data_authority["generated_names"]
        release = data_authority["release"]
        ai_limits = data_authority["ai_limits"]
        secrets = data_authority["secret_presence"]
        publication = data_authority["external_publication"]
        issued_at = str(data_authority["issued_at"])
        expires_at = str(data_authority["expires_at"])
    except (KeyError, TypeError) as error:
        raise TwoStagePackageInvalid("data_stage_authority_invalid") from error
    if ai_limits.get("enabled") is not False:
        raise TwoStagePackageInvalid("data_stage_ai_must_be_disabled")
    if secrets.get("openai_api_key") is not False:
        raise TwoStagePackageInvalid("data_stage_openai_secret_forbidden")
    if publication != {
        "dns_change": False,
        "github_push": False,
        "paid_ai_smoke": False,
        "registry_publish": True,
    }:
        raise TwoStagePackageInvalid("data_stage_publication_invalid")
    if (
        re.fullmatch(r"[0-9a-f-]{36}", tenant_id) is None
        or re.fullmatch(r"[0-9a-f-]{36}", package_id) is None
    ):
        raise TwoStagePackageInvalid("package_identity_invalid")
    data_hash = data_authority_sha256(data_authority)
    data_revision = str(generated["application_revision"])
    ai_revision = (
        f"{generated['container_app']}--ai-{str(release['image_digest'])[7:14]}"
    )
    package: dict[str, Any] = {
        "schema_version": "newcaostone.two-stage-launch.v1",
        "package_id": package_id,
        "issued_at": issued_at,
        "expires_at": expires_at,
        "tenant_id": tenant_id,
        "stage_order": ["data_scope_revision", "ai_revision"],
        "cost_cap_usd": {
            "hard_cap": hard_cap_usd,
            "qualification_cap": qualification_cap_usd,
            "hosted_smoke_cap": hosted_smoke_cap_usd,
        },
        "data_authority_sha256": data_hash,
        "data_scope_revision": {
            "revision": data_revision,
            "authority": data_authority,
            "receipt_contract": {
                "schema_version": "newcaostone.data-scope-receipt.v1",
                "required_checks": [
                    "health",
                    "browser_core",
                    "capacity_exact_15",
                    "expiry",
                    "restart_readback",
                    "rollback_compatibility",
                ],
            },
        },
        "ai_revision": {
            "revision": ai_revision,
            "candidate_image_digest": release["image_digest"],
            "data_authority_sha256": data_hash,
            "depends_on": [
                "data_scope_revision_receipt",
                "model_qualification_receipt",
            ],
            "model_snapshot": {
                "model": "gpt-5.4-nano-2026-03-17",
                "reasoning_effort": "low",
                "max_output_tokens": 2800,
            },
            "qualification_contract": {
                "case_count": 12,
                "receipt_schema_version": 1,
                "receipt_path": QUALIFICATION_RECEIPT_PATH,
                "must_pass": True,
            },
            "secret_presence": {
                "blob_credential": True,
                "openai_api_key": True,
                "operator_password_hash": True,
                "postgres_password": True,
                "registry_password": False,
                "session_pepper": True,
            },
            "commands": {},
            "execution_order": [
                "model_qualification",
                "receipt_verification",
                "deploy",
                "paid_ai_smoke",
                "rollback_on_failure",
            ],
            "retry_limits": {"deploy": 0, "paid_provider": 0, "read": 1},
            "stop_conditions": [
                "stage1_receipt_missing_or_invalid",
                "model_qualification_failed",
                "target_digest_or_data_authority_changed",
                "secret_boundary_failed",
                "cost_cap_exceeded",
            ],
            "rollback_revision": data_revision,
        },
    }
    package["ai_revision"]["commands"] = _expected_ai_transition_commands(package)
    return package


def render_two_stage_package(package: dict[str, Any]) -> bytes:
    return (
        TWO_STAGE_HEADER
        + "\n\n```json\n"
        + json.dumps(package, indent=2, sort_keys=True)
        + "\n```\n"
    ).encode()


def write_two_stage_package(path: Path, package: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render_two_stage_package(package)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--data-authorization", type=Path)
    source.add_argument("--release-attestation", type=Path)
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--package-id")
    parser.add_argument("--authorization-id")
    parser.add_argument("--attestation-git-sha")
    parser.add_argument("--subscription-id")
    parser.add_argument("--region")
    parser.add_argument("--resource-group")
    parser.add_argument("--public-url")
    parser.add_argument("--name-prefix")
    parser.add_argument("--registry-name")
    parser.add_argument("--image-repository", default="bizpulse")
    parser.add_argument("--storage-account")
    parser.add_argument("--postgres-server")
    parser.add_argument("--postgres-administrator-login")
    parser.add_argument("--observed-current-image-digest")
    parser.add_argument("--hard-cap-usd", default="100.00")
    parser.add_argument("--one-time-estimate-usd", default="10.00")
    parser.add_argument("--monthly-estimate-usd", default="80.00")
    parser.add_argument("--qualification-cap-usd", default="1.00")
    parser.add_argument("--hosted-smoke-cap-usd", default="0.25")
    parser.add_argument("--expires-hours", type=int, default=48)
    parser.add_argument(
        "--output",
        type=Path,
        default=_PROJECT_ROOT / ".tmp/LAUNCH_AUTHORIZATION_TWO_STAGE_V1.md",
    )
    options = parser.parse_args(arguments)
    try:
        if options.data_authorization is not None:
            authority = load_authorization(options.data_authorization)
        else:
            exact_target = (
                options.attestation_git_sha,
                options.subscription_id,
                options.region,
                options.resource_group,
                options.public_url,
                options.name_prefix,
                options.registry_name,
                options.storage_account,
                options.postgres_server,
                options.postgres_administrator_login,
                options.observed_current_image_digest,
            )
            if any(not value for value in exact_target):
                raise TwoStagePackageInvalid("exact_target_arguments_required")
            generated_at = datetime.now(UTC).replace(microsecond=0)
            if not 1 <= options.expires_hours <= 168:
                raise TwoStagePackageInvalid("package_expiry_invalid")
            authority = build_data_stage_authority(
                attestation_path=options.release_attestation,
                attestation_git_sha=options.attestation_git_sha,
                authorization_id=options.authorization_id or str(uuid4()),
                issued_at=generated_at.isoformat().replace("+00:00", "Z"),
                expires_at=(generated_at + timedelta(hours=options.expires_hours))
                .isoformat()
                .replace("+00:00", "Z"),
                subscription_id=options.subscription_id,
                region=options.region,
                resource_group=options.resource_group,
                public_url=options.public_url,
                name_prefix=options.name_prefix,
                registry_name=options.registry_name,
                image_repository=options.image_repository,
                storage_account=options.storage_account,
                postgres_server=options.postgres_server,
                postgres_administrator_login=options.postgres_administrator_login,
                observed_current_image_digest=(
                    options.observed_current_image_digest
                ),
                hard_cap_usd=options.hard_cap_usd,
                one_time_estimate_usd=options.one_time_estimate_usd,
                monthly_estimate_usd=options.monthly_estimate_usd,
            )
        issued = _timestamp(authority["issued_at"])
        expires = _timestamp(authority["expires_at"])
        if expires - issued > timedelta(days=7):
            raise TwoStagePackageInvalid("package_expiry_invalid")
        package = build_two_stage_package(
            data_authority=authority,
            tenant_id=options.tenant_id,
            package_id=options.package_id or str(uuid4()),
            hard_cap_usd=options.hard_cap_usd,
            qualification_cap_usd=options.qualification_cap_usd,
            hosted_smoke_cap_usd=options.hosted_smoke_cap_usd,
        )
        write_two_stage_package(options.output, package)
        load_two_stage_authorization(options.output)
    except (AuthorizationInvalid, OSError, TwoStagePackageInvalid, ValueError):
        options.output.unlink(missing_ok=True)
        print("two_stage_package=failed")
        return 1
    print("two_stage_package=ok")
    print(f"output={options.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
