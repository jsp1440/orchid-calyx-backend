#!/usr/bin/env python3
"""Adaptive Orchid Continuum harvest worker.

Uses the existing governed harvester execution layer and spends each invocation
on the first source that has useful work. iNaturalist is checked first; when it
is at the live edge the worker immediately falls through to GBIF and then EOL
TraitBank instead of wasting the invocation.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from harvesters.execution import run_harvester

log = logging.getLogger("adaptive_harvest_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

SOURCE_ORDER = ("inaturalist", "gbif", "eol_traitbank")


def _useful(result: dict[str, Any]) -> bool:
    return int(result.get("inserted") or 0) > 0 or int(result.get("records_examined") or 0) > 0


def run_once(limit: int = 10) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for source in SOURCE_ORDER:
        try:
            result = run_harvester(source, limit=limit)
            attempts.append({"source": source, "result": result})
            inserted = int(result.get("inserted") or 0)
            examined = int(result.get("records_examined") or 0)
            log.info("source=%s examined=%s inserted=%s", source, examined, inserted)
            if _useful(result):
                return {"status": "worked", "selected_source": source, "attempts": attempts}
        except Exception as exc:
            log.exception("source=%s failed; falling through", source)
            attempts.append({"source": source, "error": f"{type(exc).__name__}: {exc}"})

    return {"status": "idle", "selected_source": None, "attempts": attempts}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run_once(limit=max(1, args.limit)), default=str))


if __name__ == "__main__":
    main()
