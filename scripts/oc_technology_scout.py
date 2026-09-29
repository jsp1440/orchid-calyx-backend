"""Preview bounded metadata scouting; persist only through explicit --persist."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.intake.technology_scout import (
    SCOUT_VERSION,
    ScoutBatch,
    ingest_scout_batch,
    scout_intelligence_item,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()
    if args.input.stat().st_size > 512_000:
        parser.error("metadata batch exceeds 512 KB")
    batch = ScoutBatch.model_validate_json(args.input.read_bytes())
    if args.persist:
        result = ingest_scout_batch(batch)
    else:
        result = {
            "schema": SCOUT_VERSION,
            "mode": "preview",
            "items": [scout_intelligence_item(item) for item in batch.items],
            "canonical_graph_mutated": False,
            "provider_calls": 0,
        }
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
