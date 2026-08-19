from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid5

import pytest

from scripts.seed_demo import (
    SEED_NAMESPACE,
    seed_verified_hosted_bundle,
    seed_verified_bundle,
    validate_seed_authority,
)

VERSION_ID = UUID("e08f87ee-7993-5708-b9c7-74c7f8ae7725")
CURRENT_VERSION_ID = UUID("51d0e5f2-92d0-50db-bf87-c7b2fabdcfc5")


def test_seed_script_requires_exact_manifest_and_dataset_authority() -> None:
    result = SimpleNamespace(
        manifest_sha256="a" * 64,
        dataset_version_id=VERSION_ID,
    )

    validate_seed_authority(
        result,
        expected_manifest_sha256="a" * 64,
        expected_dataset_version_id=VERSION_ID,
    )

    with pytest.raises(RuntimeError, match="seed_authority_mismatch"):
        validate_seed_authority(
            result,
            expected_manifest_sha256="b" * 64,
            expected_dataset_version_id=VERSION_ID,
        )


def test_seed_script_rejects_wrong_bundle_before_any_write() -> None:
    bundle = SimpleNamespace(manifest_sha256="a" * 64)
    expected_version = UUID("e08f87ee-7993-5708-b9c7-74c7f8ae7725")
    called = False

    def seed(*_args):
        nonlocal called
        called = True

    with pytest.raises(RuntimeError, match="seed_authority_mismatch"):
        seed_verified_bundle(
            bundle,
            object(),
            object(),
            expected_manifest_sha256="b" * 64,
            expected_dataset_version_id=expected_version,
            seed=seed,
        )
    assert called is False

    actual_version = uuid5(
        SEED_NAMESPACE,
        f"version:{bundle.manifest_sha256}",
    )
    result = SimpleNamespace(
        manifest_sha256=bundle.manifest_sha256,
        dataset_version_id=actual_version,
    )
    assert seed_verified_bundle(
        bundle,
        object(),
        object(),
        expected_manifest_sha256=bundle.manifest_sha256,
        expected_dataset_version_id=actual_version,
        seed=lambda *_args: result,
    ) is result


def test_hosted_seed_prepares_action_only_after_exact_seed_authority() -> None:
    bundle = SimpleNamespace(manifest_sha256="a" * 64)
    version_id = uuid5(SEED_NAMESPACE, f"version:{bundle.manifest_sha256}")
    result = SimpleNamespace(
        manifest_sha256=bundle.manifest_sha256,
        dataset_version_id=version_id,
    )
    engine = object()
    storage = object()
    calls: list[tuple[object, ...]] = []

    assert seed_verified_hosted_bundle(
        bundle,
        SimpleNamespace(engine=engine),
        storage,
        expected_manifest_sha256=bundle.manifest_sha256,
        expected_dataset_version_id=version_id,
        seed=lambda *_args: calls.append(("seed",)) or result,
        ensure_action=lambda *args: calls.append(("action", *args)),
        current_version_resolver=lambda _engine: CURRENT_VERSION_ID,
    ) is result
    assert calls == [
        ("seed",),
        ("action", engine, storage, version_id),
        ("action", engine, storage, CURRENT_VERSION_ID),
    ]


def test_hosted_seed_deduplicates_seeded_and_current_action_authority() -> None:
    bundle = SimpleNamespace(manifest_sha256="a" * 64)
    version_id = uuid5(SEED_NAMESPACE, f"version:{bundle.manifest_sha256}")
    result = SimpleNamespace(
        manifest_sha256=bundle.manifest_sha256,
        dataset_version_id=version_id,
    )
    engine = object()
    storage = object()
    calls: list[tuple[object, ...]] = []

    seed_verified_hosted_bundle(
        bundle,
        SimpleNamespace(engine=engine),
        storage,
        expected_manifest_sha256=bundle.manifest_sha256,
        expected_dataset_version_id=version_id,
        seed=lambda *_args: result,
        ensure_action=lambda *args: calls.append(args),
        current_version_resolver=lambda _engine: version_id,
    )

    assert calls == [(engine, storage, version_id)]
