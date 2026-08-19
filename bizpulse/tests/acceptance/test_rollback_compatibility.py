from __future__ import annotations

import json
import subprocess
import sys
import tarfile
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import Engine, text

from src.db.readiness import EXPECTED_SCHEMA_REVISION

from scripts.release_authority import load_current_authority
from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import OperatorRepository
from src.services.analysis_service import AnalysisService
from src.services.demo_session_service import DemoSessionService
from src.services.public_release_service import PublicReleaseService
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.auth_support import SESSION_PEPPER, initial_clock
from tests.import_support import MemoryWorkflowStorage, WORKSPACE_ID

PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="session")
def rollback_identity() -> tuple[str, str]:
    authority = load_current_authority(
        PROJECT_ROOT / "release/current_authority.json"
    )
    return (
        authority.attested_rollback.git_sha,
        authority.attested_rollback.image_digest,
    )


def test_prior_app_reads_forward_schema_after_release_pointer_rollback(
    migrated_engine: Engine,
    rollback_identity: tuple[str, str],
) -> None:
    rollback_sha, rollback_image_digest = rollback_identity
    assert rollback_image_digest.startswith("sha256:")
    with migrated_engine.connect() as connection:
        migration_before = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    assert migration_before == EXPECTED_SCHEMA_REVISION
    storage = MemoryWorkflowStorage()
    clock = initial_clock()
    with PostgresUnitOfWork(migrated_engine) as uow:
        OperatorRepository(uow.connection).create_workspace(WORKSPACE_ID)
    analyses = AnalysisService(
        migrated_engine,
        storage,
        WORKSPACE_ID,
        clock=clock,
    )
    releases = PublicReleaseService(
        migrated_engine,
        WORKSPACE_ID,
        idempotency_pepper=SESSION_PEPPER,
        clock=clock,
        analysis_service=analyses,
    )
    sessions = DemoSessionService(
        engine=migrated_engine,
        workspace_id=WORKSPACE_ID,
        session_pepper=SESSION_PEPPER,
        clock=clock,
    )
    first = seed_demo(
        generate_demo(seed=20260813),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 13, 18, tzinfo=UTC),
    )
    second = seed_demo(
        generate_demo(seed=20260814),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=datetime(2026, 8, 14, 18, tzinfo=UTC),
    )
    pinned_to_second = sessions.create("source-b", clock())

    rolled_back = releases.publish(
        first.dataset_version_id,
        expected_current_id=second.dataset_version_id,
        idempotency_key="acceptance-rollback-to-prior-release",
    )
    pinned_to_first = sessions.create("source-a", clock())

    projection = _read_with_prior_app(
        migrated_engine,
        pinned_to_second.session_token,
        pinned_to_first.session_token,
        rollback_sha,
    )
    with migrated_engine.connect() as connection:
        migration_after = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )

    assert migration_after == migration_before
    assert rolled_back.dataset_version_id == first.dataset_version_id
    assert rolled_back.previous_dataset_version_id == second.dataset_version_id
    assert projection == {
        "current": str(first.dataset_version_id),
        "first_session": str(second.dataset_version_id),
        "second_session": str(first.dataset_version_id),
    }


def _read_with_prior_app(
    engine: Engine,
    first_session_token: str,
    second_session_token: str,
    rollback_sha: str,
) -> dict[str, str]:
    probe = """
import json
import sys
from datetime import UTC, datetime
from sqlalchemy import create_engine
from src.services.demo_session_service import DemoSessionService
from src.services.public_release_service import PublicReleaseService

database_url, workspace_id, pepper, first_token, second_token = sys.argv[1:]
engine = create_engine(database_url)
clock = lambda: datetime(2026, 8, 13, 18, tzinfo=UTC)
releases = PublicReleaseService(
    engine,
    workspace_id,
    idempotency_pepper=pepper,
    clock=clock,
)
sessions = DemoSessionService(
    engine=engine,
    workspace_id=workspace_id,
    session_pepper=pepper,
    clock=clock,
)
current = releases.current()
first = sessions.resolve(first_token, clock())
second = sessions.resolve(second_token, clock())
assert current is not None and first is not None and second is not None
print(json.dumps({
    'current': str(current.dataset_version_id),
    'first_session': str(first.dataset_version_id),
    'second_session': str(second.dataset_version_id),
}, sort_keys=True))
"""
    with tempfile.TemporaryDirectory(prefix="newcaostone-rollback-") as temporary:
        archive = Path(temporary) / "prior.tar"
        with archive.open("wb") as stream:
            subprocess.run(
                ["git", "archive", rollback_sha, "bizpulse/src"],
                cwd=REPOSITORY_ROOT,
                check=True,
                stdout=stream,
            )
        with tarfile.open(archive) as contents:
            contents.extractall(temporary, filter="data")
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                probe,
                str(engine.url),
                WORKSPACE_ID,
                SESSION_PEPPER,
                first_session_token,
                second_session_token,
            ],
            cwd=Path(temporary) / "bizpulse",
            check=True,
            capture_output=True,
            text=True,
        )
    return json.loads(completed.stdout)
