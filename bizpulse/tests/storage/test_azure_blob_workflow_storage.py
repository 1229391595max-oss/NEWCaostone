from __future__ import annotations

import os
from contextlib import contextmanager
from io import BytesIO
from uuid import uuid4

import pytest
from azure.core.exceptions import ServiceRequestError
from azure.storage.blob import ContainerClient

import api.container as container_module
from api.container import ApiContainer
from src.config import BizPulseSettings
from src.storage.azure_blob_workflow_storage import (
    AzureBlobWorkflowStorage,
    build_storage,
)
from src.storage.protocol import (
    StorageConcurrency,
    StorageIntegrityError,
    StorageTooLarge,
    StorageUnavailable,
)


class NoopEntryLocks:
    @contextmanager
    def acquire(self, keys, *, blocking=True):
        del blocking
        yield tuple(sorted(keys))


@pytest.fixture
def azurite_container():
    connection_string = os.getenv("BIZPULSE_TEST_AZURITE_CONNECTION_STRING")
    if connection_string is None:
        pytest.skip("requires the controlled Azurite test process")
    container = ContainerClient.from_connection_string(
        connection_string,
        container_name=f"newcaostone-{uuid4().hex}",
    )
    container.create_container()
    try:
        yield container
    finally:
        container.delete_container()


def storage(container: ContainerClient) -> AzureBlobWorkflowStorage:
    return AzureBlobWorkflowStorage(
        container_client=container,
        workspace_id="synthetic-demo",
        staging_scope="viewer-session",
        entry_locks=NoopEntryLocks(),
        object_id_factory=lambda: uuid4().hex,
    )


def test_azurite_staging_promotion_verified_open_and_teardown(
    azurite_container: ContainerClient,
) -> None:
    target = storage(azurite_container)
    staged = target.put_staging(
        BytesIO(b"pure synthetic csv"),
        max_bytes=64,
        media_type="text/csv",
    )
    final_key = f"workspaces/final/{staged.sha256}.csv"

    available = target.promote(staged.key, final_key, staged.sha256)
    with target.open_verified(final_key, staged.sha256, 64) as opened:
        assert opened.read() == b"pure synthetic csv"

    assert available.created is True
    assert target.exists(staged.key) is True
    assert target.exists(final_key) is True
    target.delete(staged.key, expected_etag=staged.etag)
    assert target.exists(staged.key) is False


def test_azurite_enforces_size_hash_and_etag_boundaries(
    azurite_container: ContainerClient,
) -> None:
    target = storage(azurite_container)
    with pytest.raises(StorageTooLarge, match="blob_size_limit_exceeded"):
        target.put_staging(
            BytesIO(b"too-large"),
            max_bytes=4,
            media_type="text/csv",
        )
    assert target.inventory("workspaces/") == ()

    staged = target.put_staging(BytesIO(b"abc"), max_bytes=3, media_type="text/csv")
    with pytest.raises(StorageIntegrityError, match="blob_integrity_failed"):
        target.open_verified(staged.key, "0" * 64, 3)

    azurite_container.get_blob_client(staged.key).set_blob_metadata(
        {"changed": "true"}
    )
    with pytest.raises(StorageConcurrency, match="blob_state_changed"):
        target.delete(staged.key, expected_etag=staged.etag)


class FailingContainer:
    def get_container_properties(self, **kwargs):
        del kwargs
        raise ServiceRequestError("credential-and-endpoint-details-must-not-escape")


class RecordingContainer:
    def __init__(self) -> None:
        self.readiness_options = None

    def get_container_properties(self, **kwargs):
        self.readiness_options = kwargs
        return object()


def test_blob_readiness_uses_a_short_transport_deadline() -> None:
    container = RecordingContainer()
    target = storage(container)

    target.check_readiness()

    assert container.readiness_options == {
        "connection_timeout": 1,
        "read_timeout": 1,
        "timeout": 1,
    }


def test_cloud_storage_never_falls_back_to_disk() -> None:
    settings = BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://db/bizpulse",
        blob_endpoint="https://blob.test",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        session_pepper="x" * 32,
    )

    with pytest.raises(StorageUnavailable, match="blob_unavailable") as captured:
        build_storage(
            settings,
            FailingContainer(),
            entry_locks=NoopEntryLocks(),
        )

    assert "credential" not in str(captured.value)
    assert "endpoint" not in str(captured.value)


def test_cloud_dependency_container_fails_closed_when_blob_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingContainerClient(FailingContainer):
        def __init__(self, *, account_url, container_name):
            del account_url, container_name

    monkeypatch.setattr(container_module, "ContainerClient", FailingContainerClient)
    settings = BizPulseSettings(
        runtime_environment="cloud",
        database_url="postgresql+psycopg://db/bizpulse",
        blob_endpoint="https://blob.test?sig=server-owned",
        blob_container="synthetic-demo",
        allowed_origin="https://demo.test",
        cookie_secure=True,
        session_pepper="x" * 32,
    )

    with pytest.raises(StorageUnavailable, match="blob_unavailable"):
        ApiContainer.build(settings)
