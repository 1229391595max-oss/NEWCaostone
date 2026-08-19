"""Verify a generated fixture has only declared pure-synthetic content."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    options = parser.parse_args(arguments)

    sys.path.insert(0, str(PROJECT_ROOT))
    from src.synthetic.manifest import verify_bundle_directory  # noqa: PLC0415

    violations = verify_bundle_directory(options.bundle)
    if violations:
        for violation in violations:
            print(violation)
        return 1
    print("synthetic_source_boundary=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
