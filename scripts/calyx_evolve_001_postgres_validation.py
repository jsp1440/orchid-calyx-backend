"""CALYX-EVOLVE-001 durable-memory validation against an ephemeral PostgreSQL.

Runs the full LEARN -> DESIGN -> EXPERIMENT -> ANALYZE -> REMEMBER cycle twice
against a real database and asserts that the second cycle reuses every stored
run instead of duplicating work.

This script writes only to ``oc_admin.calyx_evolve_*``.  It refuses to run
unless ``CALYX_EVOLVE_STAGING_VALIDATION=1`` is set explicitly, so it cannot be
pointed at a production database by an inherited environment variable.
"""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg.rows import dict_row

from runtime.calyx_evolve.campaign import CampaignRunner
from runtime.calyx_evolve.defaults import (
    CANDIDATE_BASELINE,
    CANDIDATE_FUZZY_GUARDED,
    CANDIDATE_FUZZY_UNGUARDED,
    DEFAULT_CAMPAIGN_ID,
    default_campaign,
    default_candidates,
    default_cognition,
)
from runtime.calyx_evolve.memory import PostgresExperimentMemory
from runtime.calyx_evolve.status import campaign_status

OPT_IN = "CALYX_EVOLVE_STAGING_VALIDATION"

TABLES = (
    "campaigns",
    "cognition_items",
    "candidates",
    "runs",
    "metrics",
    "findings",
    "promotion_proposals",
)


def build_execute(dsn: str):
    def execute(callback):
        with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                result = callback(cur)
            conn.commit()
            return result

    return execute


def table_counts(execute) -> dict[str, int]:
    def _read(cur):
        counts: dict[str, int] = {}
        for table in TABLES:
            cur.execute(f"SELECT count(*) AS c FROM oc_admin.calyx_evolve_{table}")
            counts[table] = cur.fetchone()["c"]
        return counts

    return execute(_read)


def main() -> int:
    if os.environ.get(OPT_IN) != "1":
        print(f"refusing to run: set {OPT_IN}=1 to validate against a staging database")
        return 2

    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("refusing to run: DATABASE_URL is not set")
        return 2

    execute = build_execute(dsn)
    memory = PostgresExperimentMemory(execute=execute)
    runner = CampaignRunner(memory=memory)
    campaign = default_campaign()

    first = runner.cycle(campaign, default_cognition(), default_candidates())
    assert all(not result.reused for result in first.results), "first cycle reused a run"
    after_first = table_counts(execute)

    second = runner.cycle(campaign, default_cognition(), default_candidates())
    assert all(result.reused for result in second.results), "second cycle re-executed"
    after_second = table_counts(execute)

    assert after_first == after_second, (
        f"replay duplicated durable rows: {after_first} -> {after_second}"
    )
    assert after_first["runs"] == len(default_candidates())

    status = campaign_status(memory, DEFAULT_CAMPAIGN_ID)
    assert status is not None
    assert status["governance"]["execution_scope"] == "STAGING_ONLY"
    assert status["governance"]["taxonomy_activation_permitted"] is False

    by_candidate = {row["candidate_id"]: row for row in status["runs"]}
    assert by_candidate[CANDIDATE_FUZZY_UNGUARDED]["false_merge_count"] == 1
    assert by_candidate[CANDIDATE_FUZZY_UNGUARDED]["promotion"]["state"] == "blocked"
    assert by_candidate[CANDIDATE_FUZZY_GUARDED]["promotion"]["state"] == "review_pending"
    assert by_candidate[CANDIDATE_FUZZY_UNGUARDED]["lineage"] == [
        CANDIDATE_FUZZY_GUARDED,
        CANDIDATE_BASELINE,
    ]
    assert all(row["replay_deterministic"] for row in status["runs"])

    print("CALYX-EVOLVE-001 PostgreSQL validation passed")
    print(f"selected candidate: {first.selected_candidate_id}")
    print(f"durable rows: {after_second}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
