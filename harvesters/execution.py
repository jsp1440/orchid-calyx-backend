"""BUILD-093 execution adapter with BUILD-105 bounded safety controls.

Bridges the governed BUILD-049 control plane to the mature production
harvesters (iNaturalist, GBIF, EOL/TraitBank). Source-specific harvesting logic
remains in the mature harvesters; this module provides dispatch, telemetry,
checkpoint protection, bounded execution, and dry-run/audit-only modes.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from harvesters.safety import CursorGuard, WorkBudget, enforce_gbif_offset

log = logging.getLogger("harvesters.execution")

TRAITBANK_SOURCE_KEY = "traitbank"
INTEGRATED_HARVESTERS = {"inaturalist", "gbif", "eol_traitbank"}


def is_integrated(harvester_id: str) -> bool:
    return harvester_id in INTEGRATED_HARVESTERS


def _as_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    return value if isinstance(value, str) else str(value)


def _to_checkpoint(value: Any) -> Optional[str]:
    return None if value is None else str(value)


def _mode_metadata(*, dry_run: bool, audit_only: bool, budget: WorkBudget) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "audit_only": audit_only,
        "writes_enabled": not (dry_run or audit_only),
        "budget": budget.snapshot(),
    }


def _validate_cursor(start: Any, end: Any) -> Any:
    guard = CursorGuard(previous=start)
    return guard.validate(end)


def run_harvester(
    harvester_id: str,
    limit: Optional[int] = None,
    family_key: Optional[int] = None,
    *,
    dry_run: bool = False,
    audit_only: bool = False,
    budget: Optional[WorkBudget] = None,
) -> dict[str, Any]:
    """Dispatch one bounded harvester run and return normalized telemetry.

    ``dry_run`` and ``audit_only`` are fail-closed: source implementations that
    cannot guarantee no writes are not executed. This keeps the control-plane
    API safe while source-specific preview adapters are added incrementally.
    """
    active_budget = budget or WorkBudget()
    active_budget.check()

    if harvester_id == "inaturalist":
        return _run_inaturalist(limit=limit, dry_run=dry_run,
                                audit_only=audit_only, budget=active_budget)
    if harvester_id == "gbif":
        return _run_gbif(limit=limit, family_key=family_key, dry_run=dry_run,
                         audit_only=audit_only, budget=active_budget)
    if harvester_id == "eol_traitbank":
        return _run_traitbank(limit=limit, dry_run=dry_run,
                              audit_only=audit_only, budget=active_budget)
    raise KeyError(harvester_id)


def _run_inaturalist(
    limit: Optional[int] = None,
    *,
    dry_run: bool = False,
    audit_only: bool = False,
    budget: WorkBudget,
) -> dict[str, Any]:
    from harvesters import inat

    start = None
    try:
        start = inat.get_state(inat.SOURCE_KEY).get("last_offset")
    except Exception as exc:
        log.warning("iNat starting checkpoint read failed: %s", exc)

    if dry_run or audit_only:
        return {
            "starting_checkpoint": _to_checkpoint(start),
            "ending_checkpoint": _to_checkpoint(start),
            "records_examined": 0,
            "inserted": 0,
            "source_response_metadata": {
                "harvester": "harvesters.inat.harvest_all",
                "status": "preview_not_executed",
                "reason": "mature iNaturalist implementation does not yet expose a guaranteed no-write preview path",
                **_mode_metadata(dry_run=dry_run, audit_only=audit_only, budget=budget),
            },
        }

    budget.add_requests(1)
    result = inat.harvest_all(limit=limit or 1)
    batches = int(result.get("batches") or 0)
    inserted = int(result.get("images") or 0)
    budget.add_records(batches)
    budget.add_writes(inserted)
    end = _validate_cursor(start, result.get("cursor"))
    return {
        "starting_checkpoint": _to_checkpoint(start),
        "ending_checkpoint": _to_checkpoint(end),
        "records_examined": batches,
        "inserted": inserted,
        "source_response_metadata": {
            "batches": batches,
            "harvester": "harvesters.inat.harvest_all",
            **_mode_metadata(dry_run=dry_run, audit_only=audit_only, budget=budget),
        },
    }


def _run_gbif(
    limit: Optional[int] = None,
    family_key: Optional[int] = None,
    *,
    dry_run: bool = False,
    audit_only: bool = False,
    budget: WorkBudget,
) -> dict[str, Any]:
    from harvesters import gbif_api

    start = None
    try:
        conn = gbif_api.get_conn()
        try:
            start = gbif_api.load_state(conn).get("offset")
        finally:
            conn.close()
    except Exception as exc:
        log.warning("GBIF starting checkpoint read failed: %s", exc)

    requested_limit = int(limit or 300)
    enforce_gbif_offset(int(start or 0), requested_limit)

    if dry_run or audit_only:
        return {
            "starting_checkpoint": _to_checkpoint(start),
            "ending_checkpoint": _to_checkpoint(start),
            "records_examined": 0,
            "inserted": 0,
            "source_response_metadata": {
                "harvester": "harvesters.gbif_api.run",
                "status": "preview_not_executed",
                "reason": "mature GBIF implementation does not yet expose a guaranteed no-write preview path",
                "requested_limit": requested_limit,
                **_mode_metadata(dry_run=dry_run, audit_only=audit_only, budget=budget),
            },
        }

    budget.add_requests(1)
    kwargs = {"family_key": family_key} if family_key else {}
    result = gbif_api.run(**kwargs)
    occurrences = int(result.get("occurrences_added") or 0)
    images = int(result.get("images_added") or 0)
    inserted = occurrences + images
    end = _validate_cursor(start, result.get("next_offset"))
    examined = max(0, int(end or 0) - int(start or 0))
    budget.add_records(examined)
    budget.add_writes(inserted)
    return {
        "starting_checkpoint": _to_checkpoint(start),
        "ending_checkpoint": _to_checkpoint(end),
        "records_examined": examined,
        "inserted": inserted,
        "source_response_metadata": {
            "occurrences_added": occurrences,
            "images_added": images,
            "harvester": "harvesters.gbif_api.run",
            **_mode_metadata(dry_run=dry_run, audit_only=audit_only, budget=budget),
        },
    }


def _ensure_trait_observations(conn) -> None:
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


def _run_traitbank(
    limit: Optional[int] = None,
    allow_download: bool = False,
    batch_commit: int = 200,
    *,
    dry_run: bool = False,
    audit_only: bool = False,
    budget: WorkBudget,
) -> dict[str, Any]:
    import psycopg2

    from harvesters.state_helper import get_state, save_state
    from harvesters.traitbank import TraitBankHarvester

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set")

    state = get_state(TRAITBANK_SOURCE_KEY) or {}
    already = int(state.get("last_offset", 0) or 0)
    harvester = TraitBankHarvester()

    if dry_run or audit_only:
        examined = 0
        for idx, _rec in enumerate(harvester.iter_records(limit=limit, allow_download=False)):
            if idx < already:
                continue
            examined += 1
            budget.add_records(1)
        return {
            "starting_checkpoint": _to_checkpoint(already),
            "ending_checkpoint": _to_checkpoint(already),
            "records_examined": examined,
            "inserted": 0,
            "source_response_metadata": {
                "processed_preview": examined,
                "harvester": "harvesters.traitbank.TraitBankHarvester",
                **_mode_metadata(dry_run=dry_run, audit_only=audit_only, budget=budget),
            },
        }

    conn = psycopg2.connect(database_url)
    processed = already
    inserted_total = 0
    inserted_delta = 0
    pending = 0
    try:
        _ensure_trait_observations(conn)
        with conn.cursor() as cur:
            for idx, rec in enumerate(harvester.iter_records(limit=limit, allow_download=allow_download)):
                if idx < already:
                    continue
                budget.add_records(1)
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
                    budget.add_writes(cur.rowcount)
                processed = idx + 1
                pending += 1
                if pending >= batch_commit:
                    conn.commit()
                    save_state(TRAITBANK_SOURCE_KEY, last_offset=processed,
                               increment_total=inserted_delta)
                    inserted_delta = 0
                    pending = 0
        conn.commit()
        save_state(TRAITBANK_SOURCE_KEY, last_offset=processed,
                   increment_total=inserted_delta)
    finally:
        conn.close()

    _validate_cursor(already, processed)
    return {
        "starting_checkpoint": _to_checkpoint(already),
        "ending_checkpoint": _to_checkpoint(processed),
        "records_examined": max(0, processed - already),
        "inserted": inserted_total,
        "source_response_metadata": {
            "processed": processed,
            "harvester": "harvesters.traitbank.TraitBankHarvester",
            **_mode_metadata(dry_run=dry_run, audit_only=audit_only, budget=budget),
        },
    }
