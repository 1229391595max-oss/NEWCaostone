"""Run the guarded server-owned operator credential rotation inside an Azure Job."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_SHA256 = re.compile(r"[0-9a-f]{64}")


class OperatorRotationJobConfigurationError(RuntimeError):
    """Raised for malformed job-only authority inputs without echoing values."""


@dataclass(frozen=True, slots=True)
class RotationJobSettings:
    expected_hash_fingerprint: str
    replacement_password_hash: str
    rotation_id: str


class RotationService(Protocol):
    def rotate(
        self,
        *,
        expected_hash_fingerprint: str,
        replacement_password_hash: str,
    ): ...


def read_rotation_job_settings(
    settings,
    *,
    environ: Mapping[str, str],
) -> RotationJobSettings:
    """Validate the Job-scoped inputs and return them only for in-process use."""

    if settings.runtime_environment != "cloud":
        raise OperatorRotationJobConfigurationError("rotation_job_requires_cloud")
    from src.config import validate_operator_password_hash  # noqa: PLC0415

    replacement = validate_operator_password_hash(
        settings.operator_password_hash,
        source="operator_rotation_job",
    )
    expected = environ.get("BIZPULSE_EXPECTED_OPERATOR_PASSWORD_HASH_SHA256", "")
    if _SHA256.fullmatch(expected) is None:
        raise OperatorRotationJobConfigurationError(
            "expected_hash_fingerprint_invalid"
        )
    rotation_id = environ.get("BIZPULSE_OPERATOR_ROTATION_ID", "")
    if _SHA256.fullmatch(rotation_id) is None:
        raise OperatorRotationJobConfigurationError("rotation_id_invalid")
    return RotationJobSettings(
        expected_hash_fingerprint=expected,
        replacement_password_hash=replacement,
        rotation_id=rotation_id,
    )


def run_rotation(
    service: RotationService,
    settings: RotationJobSettings,
) -> dict[str, object]:
    """Return a deliberately redacted job result suitable for Azure logs."""

    result = service.rotate(
        expected_hash_fingerprint=settings.expected_hash_fingerprint,
        replacement_password_hash=settings.replacement_password_hash,
    )
    return {
        "rotation_id": settings.rotation_id,
        "status": result.status,
        "revoked_session_count": result.revoked_session_count,
        "deleted_ephemeral_chat_count": result.deleted_ephemeral_chat_count,
    }


def _parse_args(arguments: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(arguments)


def main(arguments: list[str] | None = None) -> int:
    _parse_args(arguments)
    sys.path.insert(0, str(PROJECT_ROOT))
    from src.config import BizPulseSettings, ConfigError  # noqa: PLC0415
    from src.db.engine import create_postgres_engine  # noqa: PLC0415
    from src.services.operator_password_rotation_service import (  # noqa: PLC0415
        OperatorPasswordRotationAuthorityError,
        OperatorPasswordRotationConflict,
        OperatorPasswordRotationInvalid,
        OperatorPasswordRotationService,
    )

    engine = None
    try:
        app_settings = BizPulseSettings.from_env()
        job_settings = read_rotation_job_settings(app_settings, environ=os.environ)
        engine = create_postgres_engine(app_settings.database_url)
        result = run_rotation(
            OperatorPasswordRotationService(
                engine=engine,
                workspace_id="synthetic-demo",
                login_name="operator",
            ),
            job_settings,
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    except (
        ConfigError,
        OperatorRotationJobConfigurationError,
        OperatorPasswordRotationAuthorityError,
        OperatorPasswordRotationConflict,
        OperatorPasswordRotationInvalid,
    ) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
