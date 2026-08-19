"""Explicit PostgreSQL transaction ownership."""

from __future__ import annotations

from types import TracebackType
from typing import Any

from sqlalchemy import Connection, Engine
from sqlalchemy.engine import Transaction
from sqlalchemy.sql import Executable


class PostgresUnitOfWork:
    """Own one connection and one explicit root transaction."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._connection: Connection | None = None
        self._transaction: Transaction | None = None

    @property
    def connection(self) -> Connection:
        if self._connection is None:
            raise RuntimeError("unit_of_work_not_started")
        return self._connection

    @property
    def engine(self) -> Engine:
        return self._engine

    def begin(self) -> PostgresUnitOfWork:
        if self._connection is not None:
            raise RuntimeError("unit_of_work_already_started")
        self._connection = self._engine.connect()
        self._transaction = self._connection.begin()
        return self

    def execute(self, statement: Executable, parameters: dict[str, Any] | None = None):
        return self.connection.execute(statement, parameters or {})

    def commit(self) -> None:
        if self._transaction is None:
            raise RuntimeError("unit_of_work_not_started")
        try:
            self._transaction.commit()
        finally:
            self._close()

    def rollback(self) -> None:
        if self._transaction is None:
            raise RuntimeError("unit_of_work_not_started")
        try:
            self._transaction.rollback()
        finally:
            self._close()

    def _close(self) -> None:
        if self._connection is not None:
            self._connection.close()
        self._connection = None
        self._transaction = None

    def __enter__(self) -> PostgresUnitOfWork:
        return self.begin()

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exception, traceback
        if exception_type is None:
            self.commit()
        else:
            self.rollback()
        return False
