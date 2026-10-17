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
* ``persistent_state_across_restart`` (with ``--require-midrun``): no job is
  executed on both sides of the restart.
* ``no_outstanding_leases``: every lease is released and nothing is left
  running.

``--export PATH`` writes a non-secret copy of the cycle, job (lease and
receipt identity) and program records. ``--database NAME`` verifies another
database on the same server with the same read-only role.

``--production`` judges a long-running worker on live ``main`` rather than an
acceptance run fed with inputs: ``ten_consecutive_productive`` is still
reported but marked ``"advisory": true`` and left out of ``"passed"``, because
real work arrives in bursts and a healthy worker is idle between them. Every
other check stays a hard gate.

Prints one JSON report; exit 0 only if every check passed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, ProgrammingError
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

DARWIN_BATCH = "data/traitbank/darwin_1862_batch.json"
DATABASE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,62}")


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
            "SELECT sequence, productive, healthy, category, replenishment_json, "
            "job_keys_json FROM calyx_program_autonomy_cycles WHERE owner = :owner "
            "ORDER BY finished_at"
        ),
        {"owner": owner},
    ).all()
    jobs = db.execute(
        text(
            "SELECT job_key, role_key, status, outcome, attempt_count, evidence_json, "
            "lease_owner, lease_expires_at "
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

    # Leases are fenced claims. Every one must be released when its job
    # settles: a lease left behind after the run would block or duplicate work.
    held = [
        j.job_key
        for j in jobs
        if j.lease_owner is not None
        or j.lease_expires_at is not None
        or j.status in {"running", "completing"}
    ]
    check("no_outstanding_leases", not held, held_or_running=held)

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

        def executed(rows: list[Any]) -> list[str]:
            return [
                key for c in rows for key in json.loads(c.job_keys_json or "[]") if key
            ]

        before_keys = executed(cycles[: last_start or 0])
        after_keys = executed(after)
        rerun = sorted(set(before_keys) & set(after_keys))
        # Work finished before the restart must survive it in the database and
        # must not be executed again by the restarted worker.
        check(
            "persistent_state_across_restart",
            bool(before_keys) and bool(after_keys) and not rerun,
            jobs_executed_before_restart=len(before_keys),
            jobs_executed_after_restart=len(after_keys),
            executed_on_both_sides=rerun,
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


#: Manifest-run checks that do not apply to a continuous-loop run.
MANIFEST_ONLY_CHECKS = ("restart_observed", "replay_without_reexecution", "drained")
# Throughput, not safety: on live main a healthy worker idles between merges.
ADVISORY_IN_PRODUCTION = ("ten_consecutive_productive",)


def apply_production_profile(checks: dict[str, dict[str, Any]]) -> None:
    """Mark throughput checks advisory; nothing else changes."""
    for name in ADVISORY_IN_PRODUCTION:
        if name in checks:
            checks[name]["advisory"] = True


def overall_passed(checks: Mapping[str, Mapping[str, Any]]) -> bool:
    """Every non-advisory check must pass; an empty report never passes."""
    gating = [item for item in checks.values() if not item.get("advisory")]
    return bool(gating) and all(item["passed"] for item in gating)


def verify_loop(db: Session, *, owner: str) -> dict[str, dict[str, Any]]:
    """Continuous-loop acceptance: genuinely new input, executed once, learned.

    * ``new_input_discovered_and_executed``: after the first workspace refresh
      that brought in new commits, the loop submitted work it had not
      submitted before, and a productive cycle followed.
    * ``work_created_once``: no work id was freshly submitted twice.
    * ``loop_learned_from_outcomes``: the durable ledger holds a verified
      baseline and settled candidates.
    * ``idle_cycles_name_their_cause``: every cycle that neither submitted
      nor executed carries an explicit reason.
    * ``idle_polling_backs_off``: a long idle run waited longer than the base
      poll interval (not applicable when no long idle run happened).
    * ``paid_execution_gated``: cycle receipts record the paid coding lane's
      gate, and no recorded cycle had it open (``queued``). Fails closed when
      no cycle recorded the gate.
    """
    checks: dict[str, dict[str, Any]] = {}
    cycles = db.execute(
        text(
            "SELECT sequence, productive, healthy, poll_seconds, replenishment_json "
            "FROM calyx_program_autonomy_cycles WHERE owner = :owner "
            "ORDER BY finished_at"
        ),
        {"owner": owner},
    ).all()
    summaries = [
        json.loads(c.replenishment_json) if c.replenishment_json else {} for c in cycles
    ]

    def submitted(rows: list[dict[str, Any]]) -> list[str]:
        return [
            item.get("work_id")
            for summary in rows
            for item in summary.get("submitted") or []
            if item.get("outcome") == "submitted"
        ]

    refreshed_at = next(
        (
            index
            for index, summary in enumerate(summaries)
            if (summary.get("workspace_refresh") or {}).get("status") == "updated"
        ),
        None,
    )
    if refreshed_at is None:
        checks["new_input_discovered_and_executed"] = {
            "passed": False,
            "detail": "NO_WORKSPACE_REFRESH_BROUGHT_NEW_COMMITS",
        }
    else:
        before = set(submitted(summaries[:refreshed_at]))
        new = sorted(set(submitted(summaries[refreshed_at:])) - before)
        productive_after = sum(1 for c in cycles[refreshed_at:] if c.productive)
        checks["new_input_discovered_and_executed"] = {
            "passed": bool(new) and productive_after >= 1,
            "refresh": summaries[refreshed_at].get("workspace_refresh"),
            "new_work_ids": new,
            "productive_cycles_after_refresh": productive_after,
        }
    # Every refresh that brought in new commits, and whether new work followed
    # before the next one: the loop must keep discovering, not just once.
    updates = [
        index
        for index, summary in enumerate(summaries)
        if (summary.get("workspace_refresh") or {}).get("status") == "updated"
    ]
    discovered = []
    for position, index in enumerate(updates):
        end = updates[position + 1] if position + 1 < len(updates) else len(summaries)
        earlier = set(submitted(summaries[:index]))
        fresh = sorted(set(submitted(summaries[index:end])) - earlier)
        discovered.append(
            {
                "refresh": summaries[index].get("workspace_refresh"),
                "new_work_ids": fresh,
            }
        )
    checks["subsequent_new_input_discovered"] = {
        "passed": sum(1 for item in discovered if item["new_work_ids"]) >= 2,
        "refreshes_with_new_work": sum(
            1 for item in discovered if item["new_work_ids"]
        ),
        "refreshes": discovered[:10],
    }
    starts = [index for index, c in enumerate(cycles) if c.sequence == 1]
    after_restart = cycles[starts[-1] :] if len(starts) >= 2 else []
    checks["restart_recovered"] = {
        "passed": len(starts) >= 2
        and bool(after_restart)
        and all(c.healthy for c in after_restart),
        "worker_starts": len(starts),
        "cycles_after_last_restart": len(after_restart),
    }
    best = run_length = 0
    for c in cycles:
        run_length = run_length + 1 if c.healthy else 0
        best = max(best, run_length)
    checks["ten_consecutive_healthy_cycles"] = {
        "passed": best >= 10,
        "longest_healthy_run": best,
        "cycles": len(cycles),
        "productive_cycles": sum(1 for c in cycles if c.productive),
    }
    all_submitted = submitted(summaries)
    duplicates = sorted({w for w in all_submitted if all_submitted.count(w) > 1})
    checks["work_created_once"] = {
        "passed": bool(all_submitted) and not duplicates,
        "submitted": len(all_submitted),
        "duplicates": duplicates,
    }
    loop_state: dict[str, Any] = {}
    for (state_json,) in db.execute(
        text("SELECT state_json FROM calyx_brain_pulse_ledgers")
    ).all():
        state = json.loads(state_json) if state_json else {}
        if isinstance(state.get("loop"), dict):
            loop_state = state["loop"]
            break
    settled = [
        c for c in (loop_state.get("candidates") or {}).values() if c.get("settled")
    ]
    checks["loop_learned_from_outcomes"] = {
        "passed": bool(loop_state.get("verified")) and bool(settled),
        "verified_files": len(loop_state.get("verified") or {}),
        "settled_candidates": len(settled),
        "proposals": dict(
            Counter(
                p.get("state") for p in (loop_state.get("proposals") or {}).values()
            )
        ),
    }
    silent = [
        index
        for index, (cycle, summary) in enumerate(zip(cycles, summaries, strict=True))
        if not cycle.productive
        and not summary.get("submitted")
        and not summary.get("detail")
    ]
    checks["idle_cycles_name_their_cause"] = {
        "passed": not silent,
        "silent_cycle_positions": silent[:20],
    }
    longest_idle: list[Any] = []
    run: list[Any] = []
    for cycle in cycles:
        if not cycle.productive and cycle.healthy:
            run.append(cycle)
            if len(run) > len(longest_idle):
                longest_idle = list(run)
        else:
            run = []
    polls = [c.poll_seconds for c in longest_idle]
    applicable = len(longest_idle) > 10
    checks["idle_polling_backs_off"] = {
        "passed": (not applicable) or max(polls) > min(polls),
        "applicable": applicable,
        "longest_idle_run": len(longest_idle),
        "poll_seconds_range": [min(polls), max(polls)] if polls else None,
    }
    lanes = [
        s["coding_lane"] for s in summaries if isinstance(s.get("coding_lane"), dict)
    ]
    open_lane = [lane for lane in lanes if lane.get("state") != "provider_blocked"]
    checks["paid_execution_gated"] = {
        "passed": bool(lanes) and not open_lane,
        "cycles_recording_gate": len(lanes),
        "cycles": len(cycles),
        "gates": sorted({str(lane.get("gate")) for lane in lanes}),
        "open": open_lane[:5],
    }
    return checks


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


def operational_snapshot(db: Session, *, owner: str) -> dict[str, Any]:
    """Timestamped operational facts for a live worker. Never a check.

    Read inside the same READ ONLY transaction as the checks: last heartbeat,
    cycle counts by kind, worker starts, job outcomes, and proposals awaiting
    the owner. It changes no check and no ``passed`` value.
    """
    cycles = (
        db.execute(
            text(
                "SELECT worker_id, sequence, started_at, finished_at, productive, "
                "healthy, category, deployment_commit "
                "FROM calyx_program_autonomy_cycles WHERE owner = :owner "
                "ORDER BY finished_at"
            ),
            {"owner": owner},
        )
        .mappings()
        .all()
    )
    jobs = (
        db.execute(
            text(
                "SELECT job_key, status, outcome, attempt_count, lease_owner, "
                "completed_at FROM calyx_engineering_program_jobs"
            )
        )
        .mappings()
        .all()
    )
    loop_state: dict[str, Any] = {}
    for (state_json,) in db.execute(
        text("SELECT state_json FROM calyx_brain_pulse_ledgers")
    ).all():
        state = json.loads(state_json) if state_json else {}
        if isinstance(state.get("loop"), dict):
            loop_state = state["loop"]
            break
    proposals = [
        {**p, "fingerprint": p.get("fingerprint") or key}
        for key, p in (loop_state.get("proposals") or {}).items()
    ]
    last = cycles[-1] if cycles else None
    completed = [j["completed_at"] for j in jobs if j["completed_at"] is not None]

    def stamp(value: Any) -> str | None:
        return value.isoformat() if hasattr(value, "isoformat") else value

    return {
        "cycles": {
            "total": len(cycles),
            "first_started_at": stamp(cycles[0]["started_at"]) if cycles else None,
            "last_finished_at": stamp(last["finished_at"]) if last else None,
            "productive": sum(1 for c in cycles if c["productive"]),
            "waiting": sum(1 for c in cycles if c["healthy"] and not c["productive"]),
            "unhealthy": sum(1 for c in cycles if not c["healthy"]),
            "by_category": dict(Counter(c["category"] or "productive" for c in cycles)),
            "worker_starts": sum(1 for c in cycles if c["sequence"] == 1),
        },
        "last_cycle": (
            {
                "worker_id": last["worker_id"],
                "sequence": last["sequence"],
                "category": last["category"],
                "healthy": bool(last["healthy"]),
                "productive": bool(last["productive"]),
                "deployment_commit": last["deployment_commit"],
            }
            if last
            else None
        ),
        "jobs": {
            "total": len(jobs),
            "distinct_keys": len({j["job_key"] for j in jobs}),
            "by_status": dict(Counter(j["status"] for j in jobs)),
            "by_outcome": dict(Counter(j["outcome"] for j in jobs)),
            "max_attempt_count": max(
                (j["attempt_count"] or 0 for j in jobs), default=0
            ),
            "leases_held": sum(1 for j in jobs if j["lease_owner"]),
            "last_completed_at": stamp(max(completed)) if completed else None,
        },
        "proposals": {
            "by_state": dict(Counter(p.get("state") for p in proposals)),
            "by_class": dict(Counter(p.get("work_class") for p in proposals)),
            "awaiting_approval": sorted(
                str(p.get("fingerprint"))
                for p in proposals
                if p.get("state") == "awaiting_approval"
            ),
        },
    }


def export_records(db: Session, *, owner: str) -> dict[str, Any]:
    """Durable, non-secret copy of the judged record (no evidence payloads)."""
    cycles = db.execute(
        text(
            "SELECT cycle_id, worker_id, sequence, started_at, finished_at, "
            "productive, category, healthy, productive_jobs, failed_jobs, "
            "reason_code, replenishment_json, job_keys_json, deployment_commit "
            "FROM calyx_program_autonomy_cycles WHERE owner = :owner "
            "ORDER BY finished_at"
        ),
        {"owner": owner},
    ).mappings()
    # Lease tokens are fencing secrets for live claims and are never exported;
    # the lease owner and expiry show whether a claim is still held.
    jobs = db.execute(
        text(
            "SELECT program_job_id, program_id, job_key, role_key, status, outcome, "
            "attempt_count, max_attempts, lease_owner, lease_expires_at, "
            "created_at, updated_at, completed_at, evidence_json "
            "FROM calyx_engineering_program_jobs ORDER BY created_at"
        )
    ).mappings()
    programs = db.execute(
        text(
            "SELECT program_id, status, created_at, completed_at "
            "FROM calyx_engineering_programs WHERE owner = :owner "
            "ORDER BY created_at"
        ),
        {"owner": owner},
    ).mappings()
    rows = []
    executed_in: dict[str, str] = {}
    for row in cycles:
        item = dict(row)
        item["replenishment"] = (
            json.loads(item.pop("replenishment_json"))
            if row["replenishment_json"]
            else None
        )
        item["job_keys"] = json.loads(item.pop("job_keys_json") or "[]")
        for key in item["job_keys"]:
            executed_in.setdefault(key, item["cycle_id"])
        rows.append(item)
    job_rows = []
    for row in jobs:
        item = dict(row)
        evidence = json.loads(item.pop("evidence_json") or "null") or {}
        # Receipt identity only; executor output payloads stay in the database.
        item["receipt"] = {
            key: evidence.get(key)
            for key in (
                "receipt_type",
                "executor_key",
                "state",
                "input_checksum",
                "output_checksum",
            )
        }
        item["executed_in_cycle_id"] = executed_in.get(item["job_key"])
        job_rows.append(item)
    return {
        "schema": "oc-autonomy-hosted-records.v2",
        "cycles": rows,
        "jobs": job_rows,
        "programs": [dict(row) for row in programs],
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
        "--require-loop",
        action="store_true",
        help="verify a continuous-loop run (new input discovered, executed once, "
        "learned) instead of a finite manifest run",
    )
    parser.add_argument(
        "--export", type=Path, help="write a non-secret copy of the records here"
    )
    parser.add_argument(
        "--database",
        help="verify this database on the same server with the same read-only "
        "role (e.g. autonomy_midrun beside the preserved neondb)",
    )
    parser.add_argument(
        "--production",
        action="store_true",
        help="long-running worker on live main: throughput checks are advisory",
    )
    args = parser.parse_args()
    if args.database is not None and not DATABASE_NAME.fullmatch(args.database):
        print(json.dumps({"passed": False, "error": "VERIFY_DATABASE_NAME_INVALID"}))
        return 1
    dsn = normalize_dsn(args.dsn)
    try:
        if args.database:
            dsn = (
                make_url(dsn)
                .set(database=args.database)
                .render_as_string(hide_password=False)
            )
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
            if args.require_loop:
                for name in MANIFEST_ONLY_CHECKS:
                    report["checks"].pop(name, None)
                report["checks"].update(verify_loop(db, owner=args.owner))
                report["passed"] = all(
                    item["passed"] for item in report["checks"].values()
                )
            report["environment"] = environment_facts(db)
            if args.production:
                report["snapshot"] = operational_snapshot(db, owner=args.owner)
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
    if args.production:
        apply_production_profile(report["checks"])
        report["profile"] = "production"
    report["passed"] = overall_passed(report["checks"])
    print(json.dumps(report, indent=1, sort_keys=True, default=str))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
