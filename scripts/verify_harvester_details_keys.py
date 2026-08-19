"""Verify, against real recorded runs, which COUNTER_KEYS aliases actually occur.

HARVESTER-PRODUCTIVITY-001 (#1008) reads each run's `details` payload through a
documented candidate key list in app/readiness/harvester_productivity.py,
because no code in this repository writes those payloads -- the eleven bound
jobs are executed out-of-repo and only their `details` column is visible here.
The candidate list is therefore a guess about production, not a measurement of
it, until something samples what a real run actually recorded.

This script is that sample. For each job name bound in BINDINGS it reads the
most recent runs' `details` payloads and reports, per payload: which counter
each candidate alias actually matched, and which top-level keys matched none
of them. A job with zero matches across its whole sample is exactly what
`harvester_productivity()` calls "uninstrumented" -- this confirms whether that
call is correct or whether the candidate list is missing the real key name.

Safety: read-only. The connection is opened read-only and every statement runs
inside a `SET TRANSACTION READ ONLY` block that is rolled back; PostgreSQL
rejects any write attempted in such a transaction, so this cannot mutate
scientific or operational data even if a query were wrong about what it does.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.readiness.harvester_productivity import BINDINGS, COUNTER_KEYS, JOBS_TABLE, read_counter

DATABASE_URL = os.environ.get("DATABASE_URL", "")
SAMPLE_SIZE = int(os.environ.get("HARVESTER_DETAILS_SAMPLE_SIZE", "50"))
OUT_PATH = os.environ.get(
    "HARVESTER_DETAILS_EVIDENCE_PATH", "harvester-details-key-evidence.json"
)


def classify_payload(details: Any) -> dict[str, Any]:
    """Which counters one payload actually carries, and by which alias.

    Reuses ``read_counter`` rather than re-implementing key lookup, so this
    script can never disagree with what the production module would read from
    the same payload.
    """
    if not isinstance(details, dict):
        return {"is_mapping": False, "matched": {}, "unmatched_keys": []}
    matched: dict[str, str] = {}
    for counter, aliases in COUNTER_KEYS.items():
        for alias in aliases:
            if alias in details and read_counter(details, counter) is not None:
                matched[counter] = alias
                break
    matched_keys = set(matched.values())
    unmatched_keys = sorted(set(details.keys()) - matched_keys)
    return {"is_mapping": True, "matched": matched, "unmatched_keys": unmatched_keys}


def summarise_job(cur, job_name: str) -> dict[str, Any]:
    cur.execute(
        f"""
        SELECT details
        FROM {JOBS_TABLE}
        WHERE job_name = %s
        ORDER BY COALESCE(finished_at, updated_at, started_at) DESC
        LIMIT %s
        """,
        (job_name, SAMPLE_SIZE),
    )
    samples = [row["details"] for row in cur.fetchall()]
    classified = [classify_payload(d) for d in samples]

    counter_hits: Counter[str] = Counter()
    unmatched_key_hits: Counter[str] = Counter()
    non_mapping_count = 0
    for c in classified:
        if not c["is_mapping"]:
            non_mapping_count += 1
            continue
        for counter, alias in c["matched"].items():
            counter_hits[f"{counter}={alias}"] += 1
        for key in c["unmatched_keys"]:
            unmatched_key_hits[key] += 1

    return {
        "job_name": job_name,
        "sample_size": len(samples),
        "non_mapping_payloads": non_mapping_count,
        "matched_counter_aliases": dict(counter_hits),
        "unmatched_top_level_keys": dict(unmatched_key_hits),
        "instrumented": bool(counter_hits),
    }


def main() -> int:
    if not DATABASE_URL:
        print(
            "DATABASE_URL is not set; cannot verify harvester details keys "
            "against production from this environment."
        )
        return 1

    # Imported here, not at module load: classify_payload/summarise_job carry
    # no database dependency and must stay importable (and testable) without
    # psycopg installed, so only the path that actually connects requires it.
    import psycopg
    from psycopg.rows import dict_row

    started = datetime.now(timezone.utc).isoformat()
    job_names = sorted({b.job_name for b in BINDINGS})
    with psycopg.connect(DATABASE_URL, connect_timeout=15) as conn:
        conn.read_only = True
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            per_job = [summarise_job(cur, name) for name in job_names]
        conn.rollback()

    evidence = {
        "contract": "OCU-HARVESTER-PRODUCTIVITY-DETAILS-KEY-VERIFICATION-001",
        "captured_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "access": "read_only_transaction_rolled_back",
        "sample_size_per_job": SAMPLE_SIZE,
        "candidate_keys": COUNTER_KEYS,
        "jobs": per_job,
    }
    with open(OUT_PATH, "w") as fh:
        json.dump(evidence, fh, indent=2)

    for row in per_job:
        print(
            f"  {row['job_name']:42s} sample={row['sample_size']:4d} "
            f"instrumented={row['instrumented']}"
        )
        if row["unmatched_top_level_keys"]:
            print(f"      unmatched keys seen: {row['unmatched_top_level_keys']}")
    print(f"evidence written: {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
