#!/usr/bin/env python3
"""Reproducible cost-control evaluation command for engineering memory.

Usage:
    python scripts/eval_engineering_memory_savings.py [--telemetry path.json] [--json]

Runs the fixed evaluation task set under a memory-disabled baseline and a
memory-enabled condition and prints relevance, elapsed time, and — only when a
measured telemetry fixture is supplied — token/turn savings.  Unmeasured cost
metrics are reported as "unavailable"; they are never fabricated.

Exits non-zero if enabled retrieval does not improve relevance over baseline.
"""

from __future__ import annotations

import argparse
import json
import sys

# Ensure the repository root is importable when run directly.
sys.path.insert(
    0, __import__("os").path.dirname(__import__("os").path.dirname(__file__))
)

from app.engineering_memory.evaluation import (
    format_report,
    run_evaluation,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--telemetry", help="path to measured telemetry JSON", default=None
    )
    parser.add_argument("--json", action="store_true", help="emit the raw JSON report")
    args = parser.parse_args(argv)

    telemetry = None
    if args.telemetry:
        with open(args.telemetry, encoding="utf-8") as fh:
            telemetry = json.load(fh)

    report = run_evaluation(telemetry=telemetry)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

    baseline = report["conditions"]["baseline"]["relevance_hit_rate"]
    enabled = report["conditions"]["enabled"]["relevance_hit_rate"]
    if enabled is None or baseline is None or enabled <= baseline:
        print(
            "FAIL: enabled retrieval did not improve relevance over baseline",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
