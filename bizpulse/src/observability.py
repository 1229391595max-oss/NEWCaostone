"""Allowlisted structured telemetry for the public Demo boundary."""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping

REQUEST_LOGGER = logging.getLogger("bizpulse.request")
AI_LOGGER = logging.getLogger("bizpulse.ai")
HTTP_EVENT_FIELDS = frozenset(
    {
        "duration_ms",
        "error_code",
        "event",
        "method",
        "request_id",
        "route",
        "status",
    }
)
AI_EVENT_FIELDS = frozenset(
    {
        "dataset_version_hash_prefix",
        "error_code",
        "event",
        "input_tokens",
        "output_tokens",
        "replayed",
        "request_id",
        "status",
        "tool_name",
    }
)
SAFE_NAME = re.compile(r"[a-z][a-z0-9_]{0,63}")
SAFE_ERROR = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{0,63}")
HANDLER_MARKER = "_bizpulse_safe_json_handler"


def configure_observability_logging() -> None:
    """Make allowlisted JSON telemetry visible under Uvicorn's default config."""

    for logger in (REQUEST_LOGGER, AI_LOGGER):
        logger.disabled = False
        logger.setLevel(logging.INFO)
        logger.propagate = True
        if not any(
            getattr(handler, HANDLER_MARKER, False) for handler in logger.handlers
        ):
            handler = logging.StreamHandler(sys.stdout)
            handler.setLevel(logging.INFO)
            handler.setFormatter(logging.Formatter("%(message)s"))
            setattr(handler, HANDLER_MARKER, True)
            logger.addHandler(handler)


def log_http_request(fields: Mapping[str, object]) -> None:
    """Emit one JSON event after enforcing the exact public allowlist."""

    if set(fields) != HTTP_EVENT_FIELDS:
        raise ValueError("http_log_fields_invalid")
    REQUEST_LOGGER.info(
        json.dumps(dict(fields), sort_keys=True, separators=(",", ":"))
    )


def log_ai_turn(fields: Mapping[str, object]) -> None:
    """Emit bounded AI usage metadata without questions, answers, or raw IDs."""

    if set(fields) != AI_EVENT_FIELDS:
        raise ValueError("ai_log_fields_invalid")
    if fields.get("event") != "ai_turn":
        raise ValueError("ai_log_event_invalid")
    if not re.fullmatch(r"[0-9a-f]{32}", str(fields.get("request_id", ""))):
        raise ValueError("ai_log_request_id_invalid")
    dataset_prefix = fields.get("dataset_version_hash_prefix")
    if dataset_prefix is not None and not re.fullmatch(
        r"[0-9a-f]{12}", str(dataset_prefix)
    ):
        raise ValueError("ai_log_dataset_hash_invalid")
    for name in ("input_tokens", "output_tokens"):
        value = fields.get(name)
        if type(value) is not int or value < 0:
            raise ValueError("ai_log_token_count_invalid")
    if type(fields.get("replayed")) is not bool:
        raise ValueError("ai_log_replay_invalid")
    for name in ("status", "tool_name"):
        value = fields.get(name)
        if value is not None and SAFE_NAME.fullmatch(str(value)) is None:
            raise ValueError("ai_log_name_invalid")
    error_code = fields.get("error_code")
    if error_code is not None and SAFE_ERROR.fullmatch(str(error_code)) is None:
        raise ValueError("ai_log_error_code_invalid")
    AI_LOGGER.info(
        json.dumps(dict(fields), sort_keys=True, separators=(",", ":"))
    )
