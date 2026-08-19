"""Idempotently establish the single-operator cloud foundation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid5

from sqlalchemy import Engine, text

from src.db.unit_of_work import PostgresUnitOfWork
from src.repositories.operators import FoundationAuthority, OperatorRepository
from src.storage.postgres_entry_locks import advisory_lock_id

BOOTSTRAP_NAMESPACE = UUID("74f8d54f-b09c-5f12-b32a-a44e4091cc01")
BOOTSTRAP_LOCK = text("SELECT pg_advisory_xact_lock(:lock_id)")


class FoundationBootstrapConflict(RuntimeError):
    def __init__(self) -> None:
        super().__init__("bootstrap_authority_conflict")


@dataclass(frozen=True, slots=True)
class FoundationBootstrapResult:
    workspace_id: str
    operator_id: UUID
    workspace_created: bool
    operator_created: bool


class FoundationBootstrapService:
    def __init__(
        self,
        *,
        engine: Engine,
        workspace_id: str,
        login_name: str,
        password_hash: str,
        uow_factory=PostgresUnitOfWork,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._engine = engine
        self._workspace_id = workspace_id
        self._login_name = login_name
        self._password_hash = password_hash
        self._uow_factory = uow_factory
        self._clock = clock or (lambda: datetime.now(UTC))
        self._operator_id = uuid5(
            BOOTSTRAP_NAMESPACE,
            f"{workspace_id}:{login_name}",
        )

    def bootstrap(self) -> FoundationBootstrapResult:
        workspace_created = False
        operator_created = False
        try:
            with self._uow_factory(self._engine) as uow:
                uow.connection.execute(
                    BOOTSTRAP_LOCK,
                    {
                        "lock_id": advisory_lock_id(
                            f"foundation/bootstrap/{self._workspace_id}"
                        )
                    },
                )
                repository = OperatorRepository(uow.connection)
                authority = self._authority(repository)
                if authority.workspace_kind is None:
                    repository.create_workspace(
                        self._workspace_id,
                        now=self._clock(),
                    )
                    workspace_created = True
                    authority = self._authority(repository)
                elif authority.workspace_kind != "single_operator_demo":
                    raise FoundationBootstrapConflict
                if authority.active_operator is None:
                    if authority.operator_count != 0:
                        raise FoundationBootstrapConflict
                    repository.create_operator(
                        workspace_id=self._workspace_id,
                        login_name=self._login_name,
                        password_hash=self._password_hash,
                        operator_id=self._operator_id,
                        now=self._clock(),
                    )
                    operator_created = True
                elif not self._matches(authority):
                    raise FoundationBootstrapConflict
        except Exception:
            recovered = self._read_authority()
            if not self._matches(recovered):
                raise
        return FoundationBootstrapResult(
            workspace_id=self._workspace_id,
            operator_id=self._operator_id,
            workspace_created=workspace_created,
            operator_created=operator_created,
        )

    def ready(self) -> bool:
        """Read the exact configured authority without mutating it."""

        with self._engine.begin() as connection:
            connection.execute(text("SET LOCAL statement_timeout = '1s'"))
            connection.execute(text("SET LOCAL lock_timeout = '1s'"))
            return self._matches(
                self._authority(OperatorRepository(connection))
            )

    def _read_authority(self) -> FoundationAuthority:
        with self._engine.connect() as connection:
            return self._authority(OperatorRepository(connection))

    def _authority(self, repository: OperatorRepository) -> FoundationAuthority:
        return repository.foundation_authority(
            workspace_id=self._workspace_id,
            login_name=self._login_name,
            password_hash=self._password_hash,
        )

    def _matches(self, authority: FoundationAuthority) -> bool:
        operator = authority.active_operator
        return bool(
            authority.workspace_kind == "single_operator_demo"
            and authority.operator_count == 1
            and operator is not None
            and operator.id == self._operator_id
            and operator.workspace_id == self._workspace_id
            and operator.login_name == self._login_name
            and operator.status == "active"
            and authority.credential_matches
        )
