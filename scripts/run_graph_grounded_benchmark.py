"""Run the graph-grounded reasoning contract benchmark and write JSON results.

Provider-free and read-only: builds the frozen synthetic fixture in memory,
answers every case with the literature-only baseline and with the
graph-grounded pilot, and writes machine-readable results.

    PYTHONPATH=. python scripts/run_graph_grounded_benchmark.py \
        [--output benchmarks/graph_grounded_reasoning/results/latest.json]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.graph_grounded_reasoning.benchmark import BENCHMARK_DIR, run_benchmark


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BENCHMARK_DIR / "results" / "latest.json")
    args = parser.parse_args(argv)
    results = run_benchmark(clock=lambda: datetime.now(UTC).isoformat())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    for name, system in results["systems"].items():
        print(name, json.dumps(system["summary"], sort_keys=True))
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
