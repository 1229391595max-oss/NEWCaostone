from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from src.storage.protocol import AvailableObject, InventoryObject, StagedObject

FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "synthetic" / "v1"
WORKSPACE_ID = "synthetic-demo"


@dataclass
class MemoryBlob:
    content: bytes
    etag: str


class MemoryWorkflowStorage:
    def __init__(self) -> None:
        self.objects: dict[str, MemoryBlob] = {}

    def put_staging(self, stream, *, max_bytes: int, media_type: str) -> StagedObject:
        del media_type
        content = stream.read()
        if len(content) > max_bytes:
            raise ValueError("too_large")
        key = f"workspaces/staging/{uuid4().hex}.part"
        digest = sha256(content).hexdigest()
        etag = uuid4().hex
        self.objects[key] = MemoryBlob(content, etag)
        return StagedObject(key, len(content), digest, etag, "application/octet-stream")

    def promote(self, staged_key, final_key, expected_sha256) -> AvailableObject:
        source = self.objects[staged_key]
        assert sha256(source.content).hexdigest() == expected_sha256
        created = final_key not in self.objects
        if created:
            self.objects[final_key] = MemoryBlob(source.content, uuid4().hex)
        target = self.objects[final_key]
        assert sha256(target.content).hexdigest() == expected_sha256
        return AvailableObject(
            final_key,
            len(target.content),
            expected_sha256,
            target.etag,
            created,
        )

    def open_verified(self, key, expected_sha256, max_bytes):
        content = self.objects[key].content
        assert len(content) <= max_bytes
        assert sha256(content).hexdigest() == expected_sha256
        return BytesIO(content)

    def delete(self, key, *, expected_etag=None) -> None:
        current = self.objects.get(key)
        if current is None:
            return
        assert expected_etag is None or expected_etag == current.etag
        del self.objects[key]

    def inventory(self, prefix):
        return tuple(
            InventoryObject(key, len(item.content), item.etag)
            for key, item in sorted(self.objects.items())
            if key.startswith(prefix)
        )


def fixture_bytes(name: str) -> bytes:
    return (FIXTURE_ROOT / name).read_bytes()
