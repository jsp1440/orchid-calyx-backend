#!/usr/bin/env python3
"""Adaptive Orchid Continuum harvest worker.

Each cycle has independent scientific lanes:
1. guaranteed literature acquisition;
2. periodic review-bound interaction discovery;
3. biodiversity acquisition with iNaturalist -> global GBIF -> EOL TraitBank
   fall-through.

High-volume occurrence/image work therefore cannot starve literature or
interaction discovery.
"""

from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from harvesters.execution import run_harvester
from harvesters.gbif_global_api import run as run_global_gbif
from runtime.interaction_harvester import harvest_interactions_once
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
        historical = result.get("historical_books") or {}
        historical_fulltext = result.get("historical_fulltext") or {}
        crossref = result.get("scholarly_metadata") or {}
        log.info(
            "literature topic=%s discovered=%s indexed=%s status=%s crossref=%s bhl=%s bhl_ocr=%s",
            result.get("topic"),
            result.get("discovered"),
            result.get("indexed"),
            result.get("status"),
            crossref.get("status"),
            historical.get("status"),
            historical_fulltext.get("status"),
        )
        return {"status": "completed", "result": result}
    except Exception as exc:
        log.exception("literature lane failed; continuing other lanes")
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _run_interaction_lane(limit: int) -> dict[str, Any]:
    try:
        result = harvest_interactions_once(limit=max(1, min(limit, 25)))
        log.info(
            "interactions provider=%s role=%s discovered=%s indexed=%s status=%s",
            result.get("provider"),
            result.get("query_role"),
            result.get("discovered"),
            result.get("indexed"),
            result.get("status"),
        )
        return {"status": "completed", "result": result}
    except Exception as exc:
        log.exception("interaction discovery lane failed; continuing biodiversity lane")
        return {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}


def _run_source(source: str, *, limit: int) -> dict[str, Any]:
    if source != "gbif":
        return run_harvester(source, limit=limit)

    # Keep GBIF deliberately short on the shared Render web instance. The
    # harvester checkpoints every successful page, so a later cycle can resume
    # without replaying completed work if a deployment interrupts execution.
    raw = run_global_gbif(
        max_pages=max(1, min(int(limit), 10)),
        max_runtime_seconds=120.0,
    )
    inserted = int(raw.get("occurrences_added") or 0) + int(raw.get("images_added") or 0)
    return {
        "starting_checkpoint": None,
        "ending_checkpoint": str(raw.get("next_offset")) if raw.get("next_offset") is not None else None,
        "records_examined": int(raw.get("records_examined") or 0),
        "inserted": inserted,
        "source_response_metadata": {
            **raw,
            "harvester": "harvesters.gbif_global_api.run",
            "global_occurrence_stream": True,
            "media_filter": None,
            "shared_web_runtime_budget_seconds": 120.0,
        },
    }


def _run_biodiversity_lane(limit: int) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    for source in SOURCE_ORDER:
        try:
            result = _run_source(source, limit=limit)
            attempts.append({"source": source, "result": result})
            inserted = int(result.get("inserted") or 0)
            examined = int(result.get("records_examined") or 0)
            metadata = result.get("source_response_metadata") or {}
            log.info(
                "source=%s examined=%s inserted=%s bulk_download_required=%s",
                source,
                examined,
                inserted,
                metadata.get("bulk_download_required", False),
            )
            if _useful(result):
                return {"status": "worked", "selected_source": source, "attempts": attempts}
        except Exception as exc:
            log.exception("source=%s failed; falling through", source)
            attempts.append({"source": source, "error": f"{type(exc).__name__}: {exc}"})

    return {"status": "idle", "selected_source": None, "attempts": attempts}


def run_once(limit: int = 10) -> dict[str, Any]:
    bounded_limit = max(1, int(limit))
    literature = _run_literature_lane(bounded_limit)
    interactions = _run_interaction_lane(bounded_limit)
    biodiversity = _run_biodiversity_lane(bounded_limit)
    worked = (
        literature.get("status") == "completed"
        or interactions.get("status") == "completed"
        or biodiversity.get("status") == "worked"
    )
    return {
        "status": "worked" if worked else "idle",
        "literature": literature,
        "interactions": interactions,
        "biodiversity": biodiversity,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    print(json.dumps(run_once(limit=max(1, args.limit)), default=str))


if __name__ == "__main__":
    main()
