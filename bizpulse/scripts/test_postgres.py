"""Run selected tests against a task-owned ephemeral PostgreSQL cluster."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

EPHEMERAL_MARKER = "managed-by-newcaostone-test-runner"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def available_port() -> int:
    """Ask the operating system for an unused local TCP port."""

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def required_command(name: str) -> str:
    """Resolve a required PostgreSQL executable."""

    command = shutil.which(name)
    if command is None:
        raise RuntimeError(f"postgres_test_command_not_found:{name}")
    return command


def main(arguments: list[str]) -> int:
    """Start PostgreSQL, run pytest, and stop only the created cluster."""

    initdb = required_command("initdb")
    pg_ctl = required_command("pg_ctl")
    port = available_port()
    sys.path.insert(0, str(PROJECT_ROOT))

    with tempfile.TemporaryDirectory(prefix="newcaostone-postgres-") as temporary:
        data_directory = Path(temporary) / "data"
        subprocess.run(
            [initdb, "-A", "trust", "-U", "postgres", "-D", str(data_directory)],
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [
                pg_ctl,
                "-D",
                str(data_directory),
                "-o",
                f"-F -p {port} -h 127.0.0.1",
                "-w",
                "start",
            ],
            check=True,
            text=True,
        )
        try:
            os.environ["BIZPULSE_TEST_POSTGRES_URL"] = (
                f"postgresql+psycopg://postgres@127.0.0.1:{port}/postgres"
            )
            os.environ["BIZPULSE_TEST_POSTGRES_EPHEMERAL"] = EPHEMERAL_MARKER
            return pytest.main(arguments)
        finally:
            subprocess.run(
                [pg_ctl, "-D", str(data_directory), "-m", "fast", "-w", "stop"],
                check=True,
                text=True,
            )


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
