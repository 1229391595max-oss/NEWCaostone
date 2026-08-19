from __future__ import annotations

import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_dockerfile_is_digest_pinned_non_root_and_revision_labelled() -> None:
    source = (PROJECT_ROOT / "Dockerfile").read_text()

    assert re.search(r"^FROM python:3\.12[^\s]*@sha256:[0-9a-f]{64}", source, re.M)
    assert "ARG SOURCE_REVISION" in source
    assert "ARG SOURCE_TREE_SHA" in source
    assert "ARG IMAGE_INPUT_SHA256" in source
    assert "ARG BUILD_CONTEXT_SHA256" in source
    assert "org.opencontainers.image.revision=$SOURCE_REVISION" in source
    assert (
        "org.opencontainers.image.bizpulse.source-tree-sha=$SOURCE_TREE_SHA"
        in source
    )
    assert (
        "org.opencontainers.image.bizpulse.image-input-sha256=$IMAGE_INPUT_SHA256"
        in source
    )
    assert (
        "org.opencontainers.image.bizpulse.build-context-sha256=$BUILD_CONTEXT_SHA256"
        in source
    )
    assert "USER bizpulse" in source
    assert "EXPOSE 8000" in source
    assert '--workers", "1", "--no-access-log"]' in source
    assert "--require-hashes" in source


def test_container_context_is_allowlisted_and_contains_no_runtime_secret() -> None:
    dockerfile = (PROJECT_ROOT / "Dockerfile").read_text()
    ignore = (PROJECT_ROOT / ".dockerignore").read_text()
    ignore_lines = set(ignore.splitlines())

    assert "COPY ." not in dockerfile
    for parent in ("alembic", "api", "frontend", "scripts", "src", "tests"):
        assert f"!{parent}/" in ignore_lines
    for path in ("api", "src", "frontend", "alembic", "tests/fixtures/synthetic/v1"):
        assert f"COPY --chown=bizpulse:bizpulse {path}" in dockerfile
    for script in (
        "scripts/maintain_sessions.py",
        "scripts/maintain_storage.py",
        "scripts/phase1_fence_server.py",
        "scripts/prepare_cloud.py",
        "scripts/rotate_operator_password.py",
        "scripts/seed_demo.py",
    ):
        assert f"COPY --chown=bizpulse:bizpulse {script}" in dockerfile
        assert f"!{script}" in ignore
    assert ".env" not in dockerfile
    assert "CAPTSONE" not in dockerfile
    assert "sqlite" not in dockerfile.lower()
    for pattern in (".env", "*.pem", "*.key", ".git", ".venv", "node_modules", ".tmp"):
        assert pattern in ignore


def test_linux_runtime_transitive_dependencies_are_hash_locked() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text()

    assert "greenlet==3.5.5" in requirements
    assert (
        "sha256:147b25a42e5ca5be3d42356e8f608b37af715a1c196e9bf9d1627f3341adfe1d"
        in requirements
    )


def test_key_vault_runtime_dependencies_are_exact_and_hash_locked() -> None:
    requirements = (PROJECT_ROOT / "requirements.txt").read_text()

    assert "azure-identity==1.25.3" in requirements
    assert "azure-keyvault-secrets==4.11.0" in requirements
    for package in ("azure-identity", "azure-keyvault-secrets"):
        package_block = requirements.split(f"{package}==", 1)[1].split("\n\n", 1)[0]
        assert "--hash=sha256:" in package_block
