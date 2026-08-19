from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, func, select

from src.db.schema import operator_accounts, workspaces
from src.db.unit_of_work import PostgresUnitOfWork
from src.services.foundation_bootstrap_service import (
    FoundationBootstrapConflict,
    FoundationBootstrapService,
)
from src.services.operator_auth_service import OperatorAuthService, RequestMeta
from src.synthetic.generator import generate_demo
from src.synthetic.seed import seed_demo
from tests.import_support import MemoryWorkflowStorage

WORKSPACE_ID = "synthetic-demo"
PASSWORD = "synthetic-demo-test-password"
PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$"
    "dspPsWevmFQvVX8T5BXmFA$"
    "ayB1yKL+3347+SAAe59WoJsD4u1eZvHySBBiSx1jfIk"
)
NOW = datetime(2026, 8, 14, 15, 0, tzinfo=UTC)


class CommitAcknowledgementLostUnitOfWork(PostgresUnitOfWork):
    def commit(self) -> None:
        super().commit()
        raise RuntimeError("injected_bootstrap_commit_acknowledgement_lost")


def _service(
    engine: Engine,
    *,
    password_hash: str = PASSWORD_HASH,
    uow_factory=PostgresUnitOfWork,
) -> FoundationBootstrapService:
    return FoundationBootstrapService(
        engine=engine,
        workspace_id=WORKSPACE_ID,
        login_name="operator",
        password_hash=password_hash,
        uow_factory=uow_factory,
        clock=lambda: NOW,
    )


def test_fresh_bootstrap_is_idempotent_and_enables_seed_login_and_restart(
    migrated_engine: Engine,
) -> None:
    first = _service(migrated_engine).bootstrap()
    second = _service(migrated_engine).bootstrap()

    assert first.workspace_created is True
    assert first.operator_created is True
    assert second.workspace_created is False
    assert second.operator_created is False
    with migrated_engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(workspaces)) == 1
        assert (
            connection.scalar(select(func.count()).select_from(operator_accounts))
            == 1
        )

    storage = MemoryWorkflowStorage()
    seeded = seed_demo(
        generate_demo(),
        PostgresUnitOfWork(migrated_engine),
        storage,
        now=NOW,
    )
    assert seeded.dataset_version_id is not None

    for _ in range(2):
        auth = OperatorAuthService(
            engine=migrated_engine,
            workspace_id=WORKSPACE_ID,
            session_pepper="synthetic-session-pepper-with-32-characters",
            clock=lambda: NOW,
        )
        issued = auth.login(
            "operator",
            SecretStr(PASSWORD),
            RequestMeta(source_address_hash="source", now=NOW),
        )
        assert issued.principal.workspace_id == WORKSPACE_ID


def test_bootstrap_never_overwrites_an_existing_different_credential(
    migrated_engine: Engine,
) -> None:
    other_hash = PASSWORD_HASH.replace("ayB1", "byB1", 1)
    _service(migrated_engine, password_hash=other_hash).bootstrap()

    with pytest.raises(FoundationBootstrapConflict, match="bootstrap_authority_conflict"):
        _service(migrated_engine).bootstrap()


def test_bootstrap_recovers_exact_authority_after_commit_acknowledgement_loss(
    migrated_engine: Engine,
) -> None:
    result = _service(
        migrated_engine,
        uow_factory=CommitAcknowledgementLostUnitOfWork,
    ).bootstrap()

    assert result.workspace_created is True
    assert result.operator_created is True
    assert _service(migrated_engine).bootstrap().operator_created is False
