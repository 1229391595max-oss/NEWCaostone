"""Immutable contracts for generated pure-synthetic bundles."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from src.services.canonical_contracts import StoreDescriptor


@dataclass(frozen=True, slots=True)
class SyntheticFile:
    relative_path: str
    content: bytes
    media_type: str
    row_count: int

    @property
    def sha256(self) -> str:
        return sha256(self.content).hexdigest()


@dataclass(frozen=True, slots=True)
class SyntheticManifest:
    schema_version: str
    generator_version: str
    generator_source_sha256: str
    seed: int
    source_classification: str
    currency: str
    date_range: tuple[str, str]
    reporting_period: tuple[str, str]
    scenario_ids: tuple[str, ...]
    store_catalog: tuple[StoreDescriptor, ...]
    files: tuple[SyntheticFile, ...]


@dataclass(frozen=True, slots=True)
class SyntheticBundle:
    manifest: SyntheticManifest
    manifest_bytes: bytes
    files: tuple[SyntheticFile, ...]

    @property
    def file_hashes(self) -> dict[str, str]:
        return {file.relative_path: file.sha256 for file in self.files}

    @property
    def manifest_sha256(self) -> str:
        return sha256(self.manifest_bytes).hexdigest()
