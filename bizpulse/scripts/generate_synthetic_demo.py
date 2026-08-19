"""Generate a deterministic pure-synthetic BizPulse fixture bundle."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20260813)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args(arguments)

    sys.path.insert(0, str(PROJECT_ROOT))
    from src.synthetic.generator import generate_and_write  # noqa: PLC0415

    bundle = generate_and_write(options.output, seed=options.seed)
    print(
        json.dumps(
            {
                "manifest_sha256": bundle.manifest_sha256,
                "file_count": len(bundle.files),
                "seed": bundle.manifest.seed,
                "source_classification": bundle.manifest.source_classification,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
