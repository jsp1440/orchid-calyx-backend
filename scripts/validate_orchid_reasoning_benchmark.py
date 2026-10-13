"""Validate the real-question orchid reasoning benchmark and report readiness.

Provider-free and read-only. Exit 0 when the suite is valid (including an
empty suite that is awaiting cases); exit 1 with every violation otherwise.

    PYTHONPATH=. python scripts/validate_orchid_reasoning_benchmark.py [--dir benchmarks/orchid_reasoning_real]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.graph_grounded_reasoning.real_benchmark import (
    REAL_BENCHMARK_DIR,
    load_suite,
    validate_suite,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", type=Path, default=REAL_BENCHMARK_DIR)
    args = parser.parse_args(argv)
    suite = load_suite(args.dir)
    report = validate_suite(suite)
    print(
        json.dumps(
            {
                "valid": report.valid,
                "status": suite.get("status"),
                "cases": len(suite["cases"]),
                "sources": len(suite["sources"]),
                "reviews": len(suite["reviews"]),
                "label_counts": report.counts(),
                "violations": list(report.violations),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if report.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
