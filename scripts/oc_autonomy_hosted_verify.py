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
* ``dedicated_acceptance_database``: the database holds only ``calyx_*``
  tables (a production database would hold many others).
* ``resumed_after_midrun_restart`` (with ``--require-midrun``): productive
  cycles before and after the last worker start, with idempotent replay.

``--export PATH`` writes a non-secret copy of the cycle and job records.

Prints one JSON report; exit 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from sqlalchemy import create_engine, text
from sqlalchemy.exc import ArgumentError, ProgrammingError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DARWIN_BATCH = "data/traitbank/darwin_1862_batch.json"


def _consecutive_productive(flags: list[bool]) -> int:
    best = run = 0
    for flag in flags:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best


def verify(
    db: Session, *, owner: str, min_consecutive: int, require_midrun: bool = False
) -> dict[str, Any]:
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
    if require_midrun:
        # A mid-run restart: the last worker start must have resumed real work
        # (productive cycles after it) and replayed finished work idempotently.
        last_start = max(
            (i for i, c in enumerate(cycles) if c.sequence == 1), default=None
        )
        after = cycles[last_start:] if last_start is not None else []
        resumed = sum(1 for c in after if c.productive)
        replayed = 0
        for c in after:
            summary = json.loads(c.replenishment_json) if c.replenishment_json else {}
            replayed += sum(
                1
                for item in summary.get("submitted") or []
                if item.get("outcome") == "idempotent_replay"
            )
        check(
            "resumed_after_midrun_restart",
            last_start is not None
            and last_start > 0
            and any(c.productive for c in cycles[:last_start])
            and resumed >= 1
            and replayed >= 1,
            productive_before_restart=sum(
                1 for c in cycles[: last_start or 0] if c.productive
            ),
            productive_after_restart=resumed,
            replays_after_restart=replayed,
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


def normalize_dsn(raw: str) -> str:
    """Accept the forms a connection string is usually pasted in.

    Neon's Connect panel offers ``psql 'postgresql://...'``; secrets are often
    saved with quotes or a trailing newline; generated passwords may contain
    URL-reserved characters. The password is percent-encoded so any of them
    parses. Nothing here is logged.
    """
    value = raw.strip()
    if value.startswith("psql "):
        value = value[len("psql ") :].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
        value = value[1:-1].strip()
    for prefix in ("postgres://", "postgresql+psycopg2://", "postgresql+psycopg://"):
        if value.startswith(prefix):
            value = "postgresql://" + value[len(prefix) :]
    if not value.startswith("postgresql://"):
        return value
    rest = value[len("postgresql://") :]
    if "@" not in rest:
        return value
    userinfo, hostpart = rest.rsplit("@", 1)  # the host part never contains '@'
    user, sep, password = userinfo.partition(":")
    if sep:
        password = quote(unquote(password), safe="")
        userinfo = f"{user}:{password}"
    return f"postgresql://{userinfo}@{hostpart}"


def dsn_shape(value: str) -> dict[str, Any]:
    """Non-secret description of why a DSN may not parse."""
    return {
        "length": len(value),
        "scheme": value.split("://", 1)[0] if "://" in value else None,
        "has_whitespace": any(ch.isspace() for ch in value),
        "at_signs": value.count("@"),
        "has_query": "?" in value.rsplit("@", 1)[-1],
    }


def environment_facts(db: Session) -> dict[str, Any]:
    """Shows the database is dedicated to acceptance: only calyx_* tables."""
    database = db.execute(text("SELECT current_database()")).scalar_one()
    tables = (
        db.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "ORDER BY tablename"
            )
        )
        .scalars()
        .all()
    )
    other = [t for t in tables if not t.startswith("calyx_")]
    return {
        "database": database,
        "calyx_tables": sum(1 for t in tables if t.startswith("calyx_")),
        "non_calyx_tables": other,
    }


def export_records(db: Session, *, owner: str) -> dict[str, Any]:
    """Durable, non-secret copy of the judged record (no evidence payloads)."""
    cycles = db.execute(
        text(
            "SELECT cycle_id, worker_id, sequence, started_at, finished_at, "
            "productive, category, healthy, productive_jobs, failed_jobs, "
            "reason_code, replenishment_json, deployment_commit "
            "FROM calyx_program_autonomy_cycles WHERE owner = :owner "
            "ORDER BY finished_at"
        ),
        {"owner": owner},
    ).mappings()
    jobs = db.execute(
        text(
            "SELECT job_key, role_key, status, outcome, attempt_count, "
            "created_at, completed_at FROM calyx_engineering_program_jobs "
            "ORDER BY created_at"
        )
    ).mappings()
    rows = []
    for row in cycles:
        item = dict(row)
        item["replenishment"] = (
            json.loads(item.pop("replenishment_json"))
            if row["replenishment_json"]
            else None
        )
        rows.append(item)
    return {
        "schema": "oc-autonomy-hosted-records.v1",
        "cycles": rows,
        "jobs": [dict(row) for row in jobs],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dsn", required=True, help="read-only role connection URL")
    parser.add_argument("--owner", default="backend_api_key")
    parser.add_argument("--min-consecutive", type=int, default=10)
    parser.add_argument(
        "--require-midrun",
        action="store_true",
        help="also require work resumed after a mid-run restart",
    )
    parser.add_argument(
        "--export", type=Path, help="write a non-secret copy of the records here"
    )
    args = parser.parse_args()
    dsn = normalize_dsn(args.dsn)
    try:
        engine = create_engine(dsn, pool_pre_ping=True)
    except ArgumentError:
        print(
            json.dumps(
                {
                    "schema": "oc-autonomy-hosted-verify.v1",
                    "passed": False,
                    "error": "VERIFY_DSN_UNPARSEABLE",
                    "dsn_shape": dsn_shape(dsn),
                    "expected": "postgresql://oc_verify:<password>@<host>/neondb?sslmode=require",
                },
                sort_keys=True,
            )
        )
        return 1
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
        try:
            report = verify(
                db,
                owner=args.owner,
                min_consecutive=args.min_consecutive,
                require_midrun=args.require_midrun,
            )
            report["environment"] = environment_facts(db)
            if args.export is not None:
                args.export.write_text(
                    json.dumps(
                        export_records(db, owner=args.owner),
                        indent=1,
                        sort_keys=True,
                        default=str,
                    ),
                    encoding="utf-8",
                )
        except ProgrammingError as exc:
            # Typically the role was granted in another database, or by a role
            # that does not own the tables. Report what to fix, not a trace.
            db.rollback()
            print(
                json.dumps(
                    {
                        "schema": "oc-autonomy-hosted-verify.v1",
                        "passed": False,
                        "error": "VERIFY_ROLE_CANNOT_READ",
                        "detail": str(getattr(exc, "orig", exc)).splitlines()[0][:200],
                        "fix": "As the table owner, in the acceptance database: "
                        "GRANT USAGE ON SCHEMA public TO oc_verify; "
                        "GRANT SELECT ON ALL TABLES IN SCHEMA public TO oc_verify;",
                    },
                    sort_keys=True,
                )
            )
            return 1
        db.rollback()
    report["checks"]["verifier_role_read_only"] = {"passed": not any(can_write)}
    # Acceptance databases hold only Calyx orchestrator tables; anything else
    # means this is not the dedicated acceptance database.
    report["checks"]["dedicated_acceptance_database"] = {
        "passed": not report["environment"]["non_calyx_tables"],
        **report["environment"],
    }
    report["passed"] = all(item["passed"] for item in report["checks"].values())
    print(json.dumps(report, indent=1, sort_keys=True, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
