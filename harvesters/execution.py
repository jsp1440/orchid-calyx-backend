"""BUILD-093 execution adapter.

Bridges the governed BUILD-049 control plane to the mature production
harvesters (iNaturalist, GBIF, EOL/TraitBank). This module contains only
connective glue -- dispatch, checkpoint reporting, idempotent target-table
bootstrap, and the TraitBank persistence wiring reused from the source
run_harvests._run_traitbank. No harvesting logic is reimplemented here.

Each mature harvester is imported lazily inside its dispatch branch because
harvesters.gbif_api raises at import time when DATABASE_URL is unset.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

log = logging.getLogger("harvesters.execution")

TRAITBANK_SOURCE_KEY = "traitbank"

# Canonical control-plane harvester ids that map to a mature implementation.
INTEGRATED_HARVESTERS = {"inaturalist", "gbif", "eol_traitbank"}


def is_integrated(harvester_id: str) -> bool:
    return harvester_id in INTEGRATED_HARVESTERS


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _to_checkpoint(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def run_harvester(harvester_id: str, limit: Optional[int] = None,
                  family_key: Optional[int] = None) -> dict[str, Any]:
    """Dispatch a control-plane harvester id to its mature harvester.

    Returns normalized telemetry: starting_checkpoint, ending_checkpoint,
    records_examined, inserted, source_response_metadata.
    """
    if harvester_id == "inaturalist":
        return _run_inaturalist(limit=limit)
    if harvester_id == "gbif":
        return _run_gbif(limit=limit, family_key=family_key)
    if harvester_id == "eol_traitbank":
        return _run_traitbank(limit=limit)
    raise KeyError(harvester_id)


def _run_inaturalist(limit: Optional[int] = None) -> dict[str, Any]:
    from harvesters import inat

    start = None
    try:
        start = inat.get_state(inat.SOURCE_KEY).get("last_offset")
    except Exception as exc:  # checkpoint read is best-effort
        log.warning("iNat starting checkpoint read failed: %s", exc)

    result = inat.harvest_all(limit=limit or 1)
    return {
        "starting_checkpoint": _to_checkpoint(start),
        "ending_checkpoint": _to_checkpoint(result.get("cursor")),
        "records_examined": None,
        "inserted": result.get("images"),
        "source_response_metadata": {
            "batches": result.get("batches"),
            "harvester": "harvesters.inat.harvest_all",
        },
    }


def _run_gbif(limit: Optional[int] = None,
             family_key: Optional[int] = None) -> dict[str, Any]:
    from harvesters import gbif_api

    start = None
    try:
        conn = gbif_api.get_conn()
        try:
            start = gbif_api.load_state(conn).get("offset")
        finally:
            conn.close()
    except Exception as exc:  # checkpoint read is best-effort
        log.warning("GBIF starting checkpoint read failed: %s", exc)

    kwargs = {"family_key": family_key} if family_key else {}
    result = gbif_api.run(**kwargs)
    inserted = (result.get("occurrences_added") or 0) + (result.get("images_added") or 0)
    return {
        "starting_checkpoint": _to_checkpoint(start),
        "ending_checkpoint": _to_checkpoint(result.get("next_offset")),
        "records_examined": None,
        "inserted": inserted,
        "source_response_metadata": {
            "occurrences_added": result.get("occurrences_added"),
            "images_added": result.get("images_added"),
            "harvester": "harvesters.gbif_api.run",
        },
    }


def _ensure_trait_observations(conn) -> None:
    """Idempotently ensure the TraitBank target table exists.

    Mirrors the columns written by the source TraitBank persistence glue
    (run_harvests._run_traitbank / scripts/harvest_traits.py). Uses
    CREATE TABLE IF NOT EXISTS so it never alters an existing table.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS trait_observations (
                id bigserial PRIMARY KEY,
                taxonomy_id bigint,
                species_name text,
                trait_key text,
                value_text text,
                confidence double precision,
                method text,
                source_key text,
                source_record_id text,
                created_at timestamptz NOT NULL DEFAULT now()
            );
            """
        )
    conn.commit()


def _run_traitbank(limit: Optional[int] = None, allow_download: bool = False,
                  batch_commit: int = 200) -> dict[str, Any]:
    """TraitBank/EOL dispatch + persistence.

    Connective glue reused from the source run_harvests._run_traitbank:
    resumes from harvesters.state_helper, persists normalized records to
    trait_observations, and checkpoints. allow_download defaults to False so
    execution never triggers a network download unless explicitly enabled.
    """
    import psycopg2

    from harvesters.state_helper import get_state, save_state
    from harvesters.traitbank import TraitBankHarvester

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    state = get_state(TRAITBANK_SOURCE_KEY) or {}
    already = int(state.get("last_offset", 0) or 0)
    log.info("TraitBank resume: skipping first %s record(s) from prior runs", already)

    harvester = TraitBankHarvester()
    conn = psycopg2.connect(database_url)

    processed = already
    inserted_total = 0
    inserted_delta = 0
    pending = 0
    try:
        _ensure_trait_observations(conn)
        with conn.cursor() as cur:
            for idx, rec in enumerate(
                    harvester.iter_records(limit=limit, allow_download=allow_download)):
                if idx < already:
                    continue
                cur.execute(
                    """
                    INSERT INTO trait_observations
                        (taxonomy_id, species_name, trait_key, value_text,
                         confidence, method, source_key, source_record_id)
                    VALUES (0, %s, %s, %s, 0.7, 'harvested', 'TRAITBANK', %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        rec.get("scientific_name") or "",
                        rec.get("trait_raw") or "trait",
                        _as_text(rec.get("value_raw")),
                        rec.get("reference_raw") or None,
                    ),
                )
                if cur.rowcount and cur.rowcount > 0:
                    inserted_total += cur.rowcount
                    inserted_delta += cur.rowcount
                processed = idx + 1
                pending += 1
                if pending >= batch_commit:
                    conn.commit()
                    save_state(TRAITBANK_SOURCE_KEY, last_offset=processed,
                               increment_total=inserted_delta)
                    log.info("TraitBank checkpoint: processed=%s inserted_new=%s",
                             processed, inserted_total)
                    inserted_delta = 0
                    pending = 0
        conn.commit()
        save_state(TRAITBANK_SOURCE_KEY, last_offset=processed,
                   increment_total=inserted_delta)
    finally:
        conn.close()

    log.info("TraitBank done. processed=%s inserted_new=%s", processed, inserted_total)
    return {
        "starting_checkpoint": _to_checkpoint(already),
        "ending_checkpoint": _to_checkpoint(processed),
        "records_examined": processed,
        "inserted": inserted_total,
        "source_response_metadata": {
            "processed": processed,
            "harvester": "harvesters.traitbank.TraitBankHarvester",
        },
    }
