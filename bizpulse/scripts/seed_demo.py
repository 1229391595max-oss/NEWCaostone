"""Seed one verified synthetic fixture through configured PostgreSQL and Blob."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from uuid import UUID, uuid5

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SEED_NAMESPACE = UUID("cb794ce7-d3cf-516a-850b-643ab0c2ec91")


def validate_bundle_authority(
    bundle,
    *,
    expected_manifest_sha256: str | None,
    expected_dataset_version_id: UUID | None,
) -> None:
    actual_version_id = uuid5(
        SEED_NAMESPACE,
        f"version:{bundle.manifest_sha256}",
    )
    if (
        expected_manifest_sha256 is not None
        and bundle.manifest_sha256 != expected_manifest_sha256
    ) or (
        expected_dataset_version_id is not None
        and actual_version_id != expected_dataset_version_id
    ):
        raise RuntimeError("seed_authority_mismatch")


def validate_seed_authority(
    result,
    *,
    expected_manifest_sha256: str | None,
    expected_dataset_version_id: UUID | None,
) -> None:
    if (
        expected_manifest_sha256 is not None
        and result.manifest_sha256 != expected_manifest_sha256
    ) or (
        expected_dataset_version_id is not None
        and result.dataset_version_id != expected_dataset_version_id
    ):
        raise RuntimeError("seed_authority_mismatch")


def seed_verified_bundle(
    bundle,
    uow,
    storage,
    *,
    expected_manifest_sha256: str | None,
    expected_dataset_version_id: UUID | None,
    seed,
):
    validate_bundle_authority(
        bundle,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_dataset_version_id=expected_dataset_version_id,
    )
    result = seed(bundle, uow, storage)
    validate_seed_authority(
        result,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_dataset_version_id=expected_dataset_version_id,
    )
    return result


def seed_verified_hosted_bundle(
    bundle,
    uow,
    storage,
    *,
    expected_manifest_sha256: str | None,
    expected_dataset_version_id: UUID | None,
    seed,
    ensure_action,
    current_version_resolver=None,
):
    result = seed_verified_bundle(
        bundle,
        uow,
        storage,
        expected_manifest_sha256=expected_manifest_sha256,
        expected_dataset_version_id=expected_dataset_version_id,
        seed=seed,
    )
    resolver = current_version_resolver or current_release_version
    current_version_id = resolver(uow.engine)
    for dataset_version_id in dict.fromkeys(
        (result.dataset_version_id, current_version_id)
    ):
        if dataset_version_id is not None:
            ensure_action(uow.engine, storage, dataset_version_id)
    return result


def current_release_version(engine):
    from src.repositories.datasets import DatasetRepository  # noqa: PLC0415
    from src.synthetic.seed import WORKSPACE_ID  # noqa: PLC0415

    with engine.connect() as connection:
        current = DatasetRepository(connection).current_release(WORKSPACE_ID)
    return current.dataset_version_id if current is not None else None


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--expected-dataset-version-id", type=UUID)
    options = parser.parse_args(arguments)

    sys.path.insert(0, str(PROJECT_ROOT))
    from api.container import ApiContainer  # noqa: PLC0415
    from src.config import BizPulseSettings  # noqa: PLC0415
    from src.db.unit_of_work import PostgresUnitOfWork  # noqa: PLC0415
    from src.synthetic.manifest import load_bundle  # noqa: PLC0415
    from src.synthetic.seed import ensure_demo_action, seed_demo  # noqa: PLC0415

    settings = BizPulseSettings.from_env()
    bundle = load_bundle(options.bundle)
    validate_bundle_authority(
        bundle,
        expected_manifest_sha256=options.expected_manifest_sha256,
        expected_dataset_version_id=options.expected_dataset_version_id,
    )
    container = ApiContainer.build(settings)
    if (
        container.engine is None
        or container.workflow_storage is None
    ):
        parser.error("postgresql_and_blob_must_be_configured")
    try:
        result = seed_verified_hosted_bundle(
            bundle,
            PostgresUnitOfWork(container.engine),
            container.workflow_storage,
            expected_manifest_sha256=options.expected_manifest_sha256,
            expected_dataset_version_id=options.expected_dataset_version_id,
            seed=seed_demo,
            ensure_action=ensure_demo_action,
        )
        print(
            json.dumps(
                {
                    "dataset_version_id": str(result.dataset_version_id),
                    "public_release_id": str(result.public_release_id),
                    "manifest_sha256": result.manifest_sha256,
                    "created": result.created,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        container.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
