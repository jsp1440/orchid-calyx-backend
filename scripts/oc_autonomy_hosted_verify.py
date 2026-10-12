"""Read-only verification of a hosted (Render + Neon) autonomy acceptance run.

Connects with a least-privilege, SELECT-only role to the acceptance database
the Render worker wrote, inside a READ ONLY transaction, and checks the durable
record. It never writes, never creates schema, and never contacts the worker.

Checks (all must hold for ``"passed": true``):

* ``ten_consecutive_productive``: at least ``--min-consecutive`` consecutive
  productive cycle receipts (default 10).
* ``no_defect_cycles``: no receipt classified unhealthy.
* ``restart_observed``: the worker started at least twice (cycle sequence
  restarted at 1), i.e. a Render restart happened mid-run.
* ``replay_without_reexecution``: after the restart Brain resubmitted
  finished work and Calyx answered ``idempotent_replay``.
* ``no_duplicate_execution``: one row per job key, every job ``completed`` /
  ``DELIVERED`` with exactly one delivered receipt; reports the maximum
  attempt count (2 would mean a lease was recovered, still delivered once).
* ``traitbank_verdict``: the Darwin 1862 batch delivered ``valid: true`` with
  no violations, from the read-only executor (no database, network,
  ingestion or publication).
* ``status_consistent``: ``autonomy_status`` (the Mission Control computation)
  reads ``productive`` or ``healthy_waiting``, never ``defect``.
* ``drained``: the latest receipts are healthy ``no_eligible_work``.
* ``verifier_role_read_only``: the connecting role cannot insert, update or
  delete in the judged tables.

Prints one JSON report; exit 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DARWIN_BATCH = "data/traitbank/darwin_1862_batch.json"


def _consecutive_productive(flags: list[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def verify(db: Session, *, owner: str, min_consecutive: int) -> dict[str, Any]:
    from app.calyx_orchestrator.autonomy_cycles import autonomy_status

    cycles = db.execute(
        text(
            "SELECT sequence, productive, healthy, category, replenishment_json "
            "FROM calyx_program_autonomy_cycles WHERE owner = :owner "
            "ORDER BY finished_at"
        ),
        {"owner": owner},
    ).all()
    jobs = db.execute(
        text(
            "SELECT job_key, role_key, status, outcome, attempt_count, evidence_json "
            "FROM calyx_engineering_program_jobs ORDER BY created_at"
        )
    ).all()

    checks: dict[str, dict[str, Any]] = {}

    def check(name: str, passed: bool, **detail: Any) -> None:
        checks[name] = {"passed": bool(passed), **detail}

    productive = [bool(c.productive) for c in cycles]
    longest = _consecutive_productive(productive)
    check(
        "ten_consecutive_productive",
        longest >= min_consecutive,
        longest_run=longest,
        required=min_consecutive,
        cycles=len(cycles),
        productive_cycles=sum(productive),
    )
    unhealthy = [c.category for c in cycles if not c.healthy]
    check("no_defect_cycles", not unhealthy, unhealthy_categories=unhealthy)
    starts = sum(1 for c in cycles if c.sequence == 1)
    check("restart_observed", starts >= 2, worker_starts=starts)

    replays = 0
    for c in cycles:
        summary = json.loads(c.replenishment_json) if c.replenishment_json else {}
        replays += sum(
            1
            for item in summary.get("submitted") or []
            if item.get("outcome") == "idempotent_replay"
        )
    check("replay_without_reexecution", replays >= 1, idempotent_replays=replays)

    keys = [j.job_key for j in jobs]
    undelivered = [
        j.job_key for j in jobs if (j.status, j.outcome) != ("completed", "DELIVERED")
    ]
    receipts_not_delivered = []
    for j in jobs:
        evidence = json.loads(j.evidence_json) if j.evidence_json else {}
        if evidence.get("state") != "delivered":
            receipts_not_delivered.append(j.job_key)
    check(
        "no_duplicate_execution",
        bool(jobs)
        and len(keys) == len(set(keys))
        and not undelivered
        and not receipts_not_delivered,
        jobs=len(jobs),
        distinct_job_keys=len(set(keys)),
        undelivered=undelivered,
        receipts_not_delivered=receipts_not_delivered,
        max_attempt_count=max((j.attempt_count for j in jobs), default=0),
    )

    verdicts = []
    for j in jobs:
        if j.role_key != "traitbank_batch_validator" or not j.evidence_json:
            continue
        output = (json.loads(j.evidence_json).get("output")) or {}
        for result in output.get("results") or []:
            verdicts.append(
                {
                    "path": result.get("path"),
                    "valid": result.get("valid"),
                    "assertions": result.get("assertions"),
                    "environment_relations": result.get("environment_relations"),
                    "violations": result.get("violations"),
                    "side_effects_off": all(
                        output.get(flag) is False
                        for flag in (
                            "database_used",
                            "network_used",
                            "traitbank_ingestion",
                            "publication",
                        )
                    ),
                }
            )
    darwin = [v for v in verdicts if v["path"] == DARWIN_BATCH]
    check(
        "traitbank_verdict",
        len(darwin) == 1
        and darwin[0]["valid"] is True
        and darwin[0]["violations"] == []
        and darwin[0]["side_effects_off"],
        verdicts=verdicts,
    )

    status = autonomy_status(db, owner=owner)
    check(
        "status_consistent",
        status["state"] in {"productive", "healthy_waiting"},
        state=status["state"],
        recent=status.get("recent"),
    )
    tail = cycles[-2:]
    check(
        "drained",
        len(tail) == 2
        and all(c.category == "no_eligible_work" and c.healthy for c in tail),
        last_categories=[c.category for c in tail],
    )
    return {
        "schema": "oc-autonomy-hosted-verify.v1",
        "passed": all(item["passed"] for item in checks.values()),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", required=True, help="read-only role connection URL")
    parser.add_argument("--owner", default="backend_api_key")
    parser.add_argument("--min-consecutive", type=int, default=10)
    args = parser.parse_args()
    dsn = args.dsn.replace("postgres://", "postgresql://", 1)
    engine = create_engine(dsn, pool_pre_ping=True)
    with Session(engine) as db:
        db.execute(text("SET TRANSACTION READ ONLY"))
        # Least privilege is part of the evidence: the verifying role must not
        # be able to change the record it is judging.
        can_write = (
            db.execute(
                text(
                    "SELECT has_table_privilege(current_user, t, 'INSERT') "
                    "OR has_table_privilege(current_user, t, 'UPDATE') "
                    "OR has_table_privilege(current_user, t, 'DELETE') "
                    "FROM unnest(ARRAY['calyx_engineering_program_jobs', "
                    "'calyx_program_autonomy_cycles']) AS t"
                )
            )
            .scalars()
            .all()
        )
        report = verify(db, owner=args.owner, min_consecutive=args.min_consecutive)
        db.rollback()
    report["checks"]["verifier_role_read_only"] = {"passed": not any(can_write)}
    report["passed"] = all(item["passed"] for item in report["checks"].values())
    print(json.dumps(report, indent=1, sort_keys=True, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
