#!/usr/bin/env python3
"""Adaptive Orchid Continuum harvest worker.

Each cycle has two independent scientific lanes:
1. a guaranteed literature lane that runs first so GBIF/image backfills can
   never starve the Brain of scientific evidence;
2. a biodiversity lane that falls through iNaturalist -> GBIF -> EOL TraitBank
   until it finds useful work.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from harvesters.execution import run_harvester
from runtime.literature_harvester import harvest_literature_once

log = logging.getLogger("adaptive_harvest_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SOURCE_ORDER = ("inaturalist", "gbif", "eol_traitbank")


def _useful(result: dict[str, Any]) -> bool:
    return int(result.get("inserted") or 0) > 0 or int(result.get("records_examined") or 0) > 0


def _run_literature_lane(limit: int) -> dict[str, Any]:
    literature_limit = max(1, min(limit, 5))
    try:
        result = harvest_literature_once(limit=literature_limit)
        log.info(
            "literature topic=%s discovered=%s indexed=%s status=%s",
            result.get("topic"),
            result.get("discovered"),
            result.get("indexed"),
            result.get("status"),
        )
        return {"status": "completed", "result": result}
    except Exception as exc:
        # Literature failure must not prevent occurrence/trait work, and
        # biodiversity failure must never be able to suppress literature.
        log.exception("literature lane failed; continuing biodiversity lane")
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _run_biodiversity_lane(limit: int) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for source in SOURCE_ORDER:
        try:
            result = run_harvester(source, limit=limit)
            attempts.append({"source": source, "result": result})
            inserted = int(result.get("inserted") or 0)
            examined = int(result.get("records_examined") or 0)
            log.info("source=%s examined=%s inserted=%s", source, examined, inserted)
            if _useful(result):
                return {
                    "status": "worked",
                    "selected_source": source,
                    "attempts": attempts,
                }
        except Exception as exc:
            log.exception("source=%s failed; falling through", source)
            attempts.append({"source": source, "error": f"{type(exc).__name__}: {exc}"})

    return {"status": "idle", "selected_source": None, "attempts": attempts}


def run_once(limit: int = 10) -> dict[str, Any]:
    bounded_limit = max(1, int(limit))
    literature = _run_literature_lane(bounded_limit)
    biodiversity = _run_biodiversity_lane(bounded_limit)
    worked = literature.get("status") == "completed" or biodiversity.get("status") == "worked"
    return {
        "status": "worked" if worked else "idle",
        "literature": literature,
        "biodiversity": biodiversity,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run_once(limit=max(1, args.limit)), default=str))


if __name__ == "__main__":
    main()
