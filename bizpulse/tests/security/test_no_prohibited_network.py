from __future__ import annotations

import re
from pathlib import Path


FRONTEND_ROOT = Path(__file__).resolve().parents[2] / "frontend"
EXTERNAL_URL = re.compile(r"https?://", re.IGNORECASE)


def test_browser_runtime_contains_no_external_network_target() -> None:
    violations: list[str] = []
    for path in sorted(FRONTEND_ROOT.rglob("*")):
        if path.suffix not in {".html", ".css", ".mjs", ".svg"}:
            continue
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if EXTERNAL_URL.search(line) and not any(
                allowed in line
                for allowed in (
                    "http://www.w3.org/2000/svg",
                    '"http://local.invalid"',
                )
            ):
                violations.append(f"{path.relative_to(FRONTEND_ROOT)}:{line_number}")
    assert violations == []
