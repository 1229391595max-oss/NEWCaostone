#!/usr/bin/env python3
"""Verify stage-1 and model receipts before the AI revision is authorized."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.qualify_openai_model import build_cases  # noqa: E402
from tests.hosted.verify_azure_demo import (  # noqa: E402
    load_two_stage_authorization,
)


class StageReceiptInvalid(RuntimeError):
    """A required sanitized receipt is absent, incomplete, or drifted."""


def validate_stage_receipts(
    package: dict[str, Any],
    *,
    data_receipt: dict[str, Any],
    qualification_receipt: dict[str, Any],
) -> None:
    try:
        data_stage = package["data_scope_revision"]
        authority = data_stage["authority"]
        expected_checks = data_stage["receipt_contract"]["required_checks"]
        checks = data_receipt["checks"]
    except (KeyError, TypeError) as error:
        raise StageReceiptInvalid("data_receipt_invalid") from error
    if (
        set(data_receipt)
        != {
            "ai_enabled",
            "checks",
            "data_authority_sha256",
            "image_digest",
            "openai_api_key_present",
            "package_id",
            "revision",
            "schema_version",
        }
        or data_receipt["schema_version"]
        != "newcaostone.data-scope-receipt.v1"
        or data_receipt["package_id"] != package["package_id"]
        or data_receipt["data_authority_sha256"]
        != package["data_authority_sha256"]
        or data_receipt["revision"] != data_stage["revision"]
        or data_receipt["image_digest"] != authority["release"]["image_digest"]
        or data_receipt["ai_enabled"] is not False
        or data_receipt["openai_api_key_present"] is not False
        or not isinstance(checks, list)
        or checks
        != [{"name": name, "passed": True} for name in expected_checks]
    ):
        raise StageReceiptInvalid("data_receipt_invalid")

    expected_case_ids = [case.case_id for case in build_cases()]
    try:
        case_ids = qualification_receipt["case_ids"]
        cases = qualification_receipt["cases"]
    except (KeyError, TypeError) as error:
        raise StageReceiptInvalid("qualification_receipt_invalid") from error
    if (
        qualification_receipt.get("schema_version") != 1
        or qualification_receipt.get("passed") is not True
        or qualification_receipt.get("model_snapshot")
        != package["ai_revision"]["model_snapshot"]
        or case_ids != expected_case_ids
        or not isinstance(cases, list)
        or len(cases) != 12
        or [item.get("case_id") for item in cases] != expected_case_ids
        or any(item.get("passed") is not True for item in cases)
    ):
        raise StageReceiptInvalid("qualification_receipt_invalid")
    serialized = json.dumps(
        {"data": data_receipt, "qualification": qualification_receipt},
        sort_keys=True,
    )
    if re.search(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{12,}\b", serialized):
        raise StageReceiptInvalid("receipt_secret_value_forbidden")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise StageReceiptInvalid("receipt_file_invalid") from error
    if not isinstance(payload, dict):
        raise StageReceiptInvalid("receipt_file_invalid")
    return payload


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", required=True, type=Path)
    parser.add_argument("--data-receipt", required=True, type=Path)
    parser.add_argument("--qualification-receipt", required=True, type=Path)
    options = parser.parse_args(arguments)
    try:
        validate_stage_receipts(
            load_two_stage_authorization(options.authorization),
            data_receipt=_read_json(options.data_receipt),
            qualification_receipt=_read_json(options.qualification_receipt),
        )
    except StageReceiptInvalid:
        print("stage_receipts=invalid")
        return 1
    print("stage_receipts=valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
