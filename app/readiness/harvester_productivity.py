"""HARVESTER-PRODUCTIVITY-001: read-only per-source harvester telemetry.

Mission Control reports ``rows_processed: 0`` and ``rows_inserted: 0`` for every
harvester regardless of what actually ran. Those are literals in
``app/routers/mission_control.py``, not measurements, so a harvester that
inserted nothing and a harvester nobody instrumented look identical, and both
look like measured zero.

This module reads what is actually recorded and says which of those it found.
It issues SELECT statements only.

Two distinctions carry the whole design:

*Unavailable is not zero.* Every counter is reported as a state plus a value.
``measured`` means a number was read from a recorded run. ``unavailable`` means
nothing recorded it. A caller that renders ``unavailable`` as ``0`` is claiming
a measurement nobody made, so the value is ``None`` in that case and cannot be
formatted as a number by accident.

*Activity is not yield.* A run that processed 500,000 known records and retained
none did work and produced nothing. ``runs`` and ``records_fetched`` describe
activity; ``records_new`` and ``records_linked`` describe yield and integration.
They are never summed together.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

JOBS_TABLE = "oc_admin.ocp_execution_jobs"

MEASURED = "measured"
UNAVAILABLE = "unavailable"

#: Windows the owner asked for, in days.
WINDOWS: tuple[tuple[str, int], ...] = (("24h", 1), ("7d", 7), ("30d", 30))

SUCCESS_STATUSES = frozenset({"completed", "success", "succeeded"})
FAILURE_STATUSES = frozenset({"failed", "error"})


@dataclass(frozen=True, slots=True)
class HarvesterBinding:
    """Which recorded job a harvester's telemetry is read from.

    ``confidence`` is the honest part. The Mission Control registry binds
    several harvesters to audit jobs that are only adjacent to what the
    harvester does, and binds six harvesters to three shared job names. Two
    harvesters reading one job do not have two independent measurements, and
    reporting the same numbers under both names would invent agreement that
    was never observed.
    """

    harvester_id: str
    job_name: str
    confidence: str  # "exact" | "shared" | "approximate"
    note: str


#: Bindings as they exist today, with the mapping quality stated rather than assumed.
BINDINGS: tuple[HarvesterBinding, ...] = (
    HarvesterBinding("inaturalist", "audit_image_species_evidence_coverage", "shared",
                     "Shares its job with image_media; the job measures image evidence coverage, not iNaturalist ingestion."),
    HarvesterBinding("gbif", "audit_ecological_relationship_graph_gaps", "approximate",
                     "Bound to a graph-gap audit. That audit does not record GBIF occurrence ingestion counters."),
    HarvesterBinding("world_plants_hassler", "audit_frontend_relationship_cards", "approximate",
                     "Bound to a frontend relationship-card audit, which does not record taxonomic backbone ingestion."),
    HarvesterBinding("eol_traitbank", "audit_traitbank_trait_coverage", "exact",
                     "The trait coverage audit is the TraitBank surface."),
    HarvesterBinding("globi", "audit_missing_pollinator_data", "shared",
                     "Shares its job with pollinator_datasets."),
    HarvesterBinding("pollinator_datasets", "audit_missing_pollinator_data", "shared",
                     "Shares its job with globi."),
    HarvesterBinding("mycorrhizal_data", "audit_missing_mycorrhizal_data", "exact",
                     "The mycorrhizal gap audit is the mycorrhizal surface."),
    HarvesterBinding("image_media", "audit_image_species_evidence_coverage", "shared",
                     "Shares its job with inaturalist."),
    HarvesterBinding("literature", "audit_literature_extraction_coverage", "exact",
                     "The literature extraction audit is the literature surface."),
    HarvesterBinding("climate_elevation", "audit_conservation_habitat_gaps", "shared",
                     "Shares its job with conservation_status; the job measures habitat gaps, not climate/elevation enrichment."),
    HarvesterBinding("conservation_status", "audit_conservation_habitat_gaps", "shared",
                     "Shares its job with climate_elevation."),
)

#: Keys a run's ``details`` payload may carry for each counter, most specific first.
#: Nothing is derived from a key that is not listed: an unrecognised payload
#: reports unavailable rather than guessing which number means what.
COUNTER_KEYS: dict[str, tuple[str, ...]] = {
    "records_fetched": ("records_fetched", "rows_fetched", "fetched", "records_scanned", "rows_scanned", "scanned"),
    "records_accepted": ("records_accepted", "rows_accepted", "accepted"),
    "records_rejected": ("records_rejected", "rows_rejected", "rejected"),
    "records_duplicate": ("records_duplicate", "rows_duplicate", "duplicates", "already_known"),
    "records_new": ("records_inserted", "rows_inserted", "inserted", "records_new", "new_records"),
    "records_updated": ("records_updated", "rows_updated", "updated"),
    "records_linked": ("records_linked", "rows_linked", "taxonomy_linked", "linked_to_taxonomy"),
    "records_unlinked": ("records_unlinked", "rows_unlinked", "unresolved", "unlinked"),
    "graph_elements": ("graph_edges_created", "graph_nodes_created", "edges_created", "nodes_created"),
}


def _metric(value: int | None) -> dict[str, Any]:
    """A counter is a state plus a value; unavailable carries no number."""
    if value is None:
        return {"state": UNAVAILABLE, "value": None}
    return {"state": MEASURED, "value": int(value)}


def _coerce_count(raw: Any) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    if isinstance(raw, float) and raw.is_integer():
        return int(raw) if raw >= 0 else None
    if isinstance(raw, str):
        text = raw.strip()
        if text.isdigit():
            return int(text)
    return None


def read_counter(details: Any, counter: str) -> int | None:
    """Pull one counter out of a run's details payload, or report nothing found.

    A malformed payload - not a mapping, or a value that is not a count - is
    treated as nothing recorded. It must not take the endpoint down and it must
    not become a zero.
    """
    if not isinstance(details, dict):
        return None
    for key in COUNTER_KEYS.get(counter, ()):
        if key in details:
            value = _coerce_count(details[key])
            if value is not None:
                return value
    return None


def _sum_counter(runs: list[dict[str, Any]], counter: str) -> int | None:
    """Sum a counter across runs, or report unavailable if no run recorded it.

    Runs that did not record the counter are skipped rather than counted as
    zero: a total of 5 across one instrumented run and four silent ones is
    still the only thing anybody measured.
    """
    values = [v for v in (read_counter(r.get("details"), counter) for r in runs) if v is not None]
    if not values:
        return None
    return sum(values)


def _normalise_status(status: Any) -> str:
    return str(status or "unknown").strip().lower()


def summarise_window(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Activity, yield and failure for one window, each kept separate."""
    succeeded = sum(1 for r in runs if _normalise_status(r.get("status")) in SUCCESS_STATUSES)
    failed = sum(1 for r in runs if _normalise_status(r.get("status")) in FAILURE_STATUSES)
    counters = {name: _metric(_sum_counter(runs, name)) for name in COUNTER_KEYS}
    summary: dict[str, Any] = {
        "runs_attempted": len(runs),
        "runs_succeeded": succeeded,
        "runs_failed": failed,
        **counters,
    }
    summary["failure_rate"] = round(failed / len(runs), 4) if runs else None

    fetched = counters["records_fetched"]["value"]
    new = counters["records_new"]["value"]
    # Only defensible when both ends were actually measured, and only when
    # something was fetched: 0/0 is not a yield of zero, it is no observation.
    if fetched is not None and new is not None and fetched > 0:
        summary["marginal_yield_per_1000_fetched"] = round((new / fetched) * 1000, 3)
    else:
        summary["marginal_yield_per_1000_fetched"] = None
    return summary


def _instrumentation_state(windows: dict[str, Any]) -> str:
    """Did any window measure any counter at all?"""
    for window in windows.values():
        for name in COUNTER_KEYS:
            if window[name]["state"] == MEASURED:
                return "instrumented"
    return "uninstrumented"


def _review_flags(windows: dict[str, Any], last_success: str | None, now: datetime) -> list[str]:
    """Owner decision aids. Recommendations only - never authority to act."""
    flags: list[str] = []
    week = windows.get("7d", {})
    if week.get("runs_attempted"):
        rate = week.get("failure_rate")
        if rate is not None and rate >= 0.5:
            flags.append("high_failure_rate")
        new = week["records_new"]["value"]
        if new == 0 and week.get("runs_succeeded", 0) >= 2:
            flags.append("repeated_runs_zero_new_records")
        fetched = week["records_fetched"]["value"]
        if fetched is not None and new is not None and fetched >= 1000 and new == 0:
            flags.append("high_throughput_no_new_records")
    if last_success:
        try:
            seen = datetime.fromisoformat(last_success)
            if seen.tzinfo is None:
                seen = seen.replace(tzinfo=timezone.utc)
            if (now - seen) > timedelta(days=30):
                flags.append("stale_beyond_30d")
        except ValueError:
            pass
    return flags


def _fetch_runs(cur, job_name: str, since: datetime) -> list[dict[str, Any]]:
    cur.execute(
        f"""
        SELECT status, started_at, finished_at, updated_at, error_text, details
        FROM {JOBS_TABLE}
        WHERE job_name = %s
          AND COALESCE(finished_at, updated_at, started_at) >= %s
        ORDER BY COALESCE(finished_at, updated_at, started_at) DESC
        LIMIT 500
        """,
        (job_name, since),
    )
    return [
        {
            "status": row[0],
            "started_at": row[1],
            "finished_at": row[2],
            "updated_at": row[3],
            "error_text": row[4],
            "details": row[5],
        }
        for row in cur.fetchall()
    ]


def _last_successful_yield(cur, job_name: str) -> str | None:
    cur.execute(
        f"""
        SELECT COALESCE(finished_at, updated_at, started_at)
        FROM {JOBS_TABLE}
        WHERE job_name = %s AND lower(status) IN ('completed', 'success', 'succeeded')
        ORDER BY COALESCE(finished_at, updated_at, started_at) DESC
        LIMIT 1
        """,
        (job_name,),
    )
    row = cur.fetchone()
    if not row or row[0] is None:
        return None
    return row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0])


def harvester_productivity(cur, table_exists, now: datetime | None = None) -> dict[str, Any]:
    """Per-source productivity across the 24h/7d/30d windows.

    Fails closed: if the jobs table is not present, every harvester reports
    unavailable rather than a row of zeros.
    """
    now = now or datetime.now(timezone.utc)
    generated_at = now.isoformat()

    if not table_exists(cur, JOBS_TABLE):
        return {
            "schema_version": "harvester-productivity-001",
            "generated_at": generated_at,
            "telemetry_state": UNAVAILABLE,
            "reason": f"{JOBS_TABLE} is not present; no harvester run history can be read.",
            "harvesters": [
                {
                    "harvester_id": b.harvester_id,
                    "job_name": b.job_name,
                    "binding_confidence": b.confidence,
                    "binding_note": b.note,
                    "telemetry_state": UNAVAILABLE,
                    "windows": {},
                    "review_flags": [],
                }
                for b in BINDINGS
            ],
        }

    harvesters: list[dict[str, Any]] = []
    for binding in BINDINGS:
        windows: dict[str, Any] = {}
        for label, days in WINDOWS:
            windows[label] = summarise_window(_fetch_runs(cur, binding.job_name, now - timedelta(days=days)))
        last_success = _last_successful_yield(cur, binding.job_name)
        harvesters.append(
            {
                "harvester_id": binding.harvester_id,
                "job_name": binding.job_name,
                "binding_confidence": binding.confidence,
                "binding_note": binding.note,
                "telemetry_state": _instrumentation_state(windows),
                "last_successful_run": last_success,
                "windows": windows,
                "review_flags": _review_flags(windows, last_success, now),
            }
        )

    shared = sorted({b.job_name for b in BINDINGS if b.confidence == "shared"})
    return {
        "schema_version": "harvester-productivity-001",
        "generated_at": generated_at,
        "telemetry_state": "available",
        "source_table": JOBS_TABLE,
        "harvesters": harvesters,
        "warnings": [
            (
                "Six harvesters read three shared job names "
                f"({', '.join(shared)}); their counters are the same measurement reported twice, "
                "not two agreeing observations."
            ),
            (
                "Harvesters whose telemetry_state is 'uninstrumented' record no counters in any "
                "run details payload. That is missing instrumentation, not measured zero."
            ),
        ],
    }
