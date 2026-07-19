from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from app.missions.repositories import PostgresMissionRepository
from app.missions.services import MissionService


ROOT = Path(__file__).resolve().parents[1]


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def apply_migration(cur) -> None:
    cur.execute((ROOT / "migrations" / "079_controlled_mission_orchestration.sql").read_text(encoding="utf-8"))


def count_or_none(cur, table: str) -> int | None:
    cur.execute("SELECT to_regclass(%s) AS exists", (table,))
    if cur.fetchone()["exists"] is None:
        return None
    cur.execute(f"SELECT count(*) AS count FROM {table}")
    return int(cur.fetchone()["count"])


def marker_occurrences(cur, schema_name: str, table_name: str, marker: str) -> int:
    cur.execute(
        sql.SQL("SELECT count(*) AS count FROM {}.{} AS t WHERE row_to_json(t)::text LIKE %s").format(
            sql.Identifier(schema_name),
            sql.Identifier(table_name),
        ),
        (f"%{marker}%",),
    )
    return int(cur.fetchone()["count"])


def schema_marker_occurrences(cur, schema_name: str, table_names: list[str], marker: str) -> int:
    return sum(marker_occurrences(cur, schema_name, table_name, marker) for table_name in table_names)


def claim_validation_job(repository: PostgresMissionRepository, mission_id: int, worker_id: str) -> dict:
    with repository._connect() as conn, conn.cursor() as cur:
        repository.register_worker(cur, worker_id)
        cur.execute(
            """WITH candidate AS (
                SELECT job_id FROM oc_missions.mission_jobs
                WHERE mission_id=%s AND state IN ('available','retry_wait') AND available_at <= NOW()
                ORDER BY priority DESC, available_at ASC, job_id ASC
                LIMIT 1 FOR UPDATE SKIP LOCKED
            )
            UPDATE oc_missions.mission_jobs j
            SET state='claimed', claimed_at=NOW(), lease_expires_at=NOW() + interval '300 seconds',
                worker_id=%s, attempt_number=attempt_number + 1
            FROM candidate WHERE j.job_id=candidate.job_id
            RETURNING j.*""",
            (mission_id, worker_id),
        )
        job = cur.fetchone()
        if not job:
            raise AssertionError(f"controlled validation job was not claimable for mission_id={mission_id}")
        cur.execute("SELECT * FROM oc_missions.missions WHERE mission_id=%s", (mission_id,))
        mission = cur.fetchone()
        repository.audit(
            cur,
            actor=worker_id,
            actor_type="runtime_worker",
            event_type="job_claimed",
            mission=mission,
            job=job,
            previous_state="available",
            new_state="claimed",
            worker_id=worker_id,
        )
        return {**job, "mission": mission}


def execute_validation_mission(service: MissionService, mission_id: int, worker_id: str) -> dict:
    repository = service.repository
    if not isinstance(repository, PostgresMissionRepository):
        raise AssertionError("BUILD-079 PostgreSQL validation requires PostgresMissionRepository")
    job = claim_validation_job(repository, mission_id, worker_id)
    started = repository.start_job(job["job_id"], worker_id)
    try:
        output = service._execute_registered_handler(started)
        completed = repository.complete_job(started, output, worker_id)
        return {"status": "completed", "job": completed, "output": output}
    except Exception as exc:
        failed = repository.fail_job(started, exc.__class__.__name__, str(exc), worker_id)
        return {"status": "failed", "job": failed, "error_code": exc.__class__.__name__, "error_message": str(exc)}


def main() -> None:
    dsn = database_url()
    marker = uuid.uuid4().hex[:12]
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        graph_before = {"nodes": count_or_none(cur, "oc_graph.kg_nodes"), "edges": count_or_none(cur, "oc_graph.kg_edges")}
        cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='oc_taxonomy'")
        taxonomy_tables = [row["table_name"] for row in cur.fetchall()]
        taxonomy_before = {name: count_or_none(cur, f"oc_taxonomy.{name}") for name in taxonomy_tables}
        apply_migration(cur)
        apply_migration(cur)
        conn.commit()

    service = MissionService(PostgresMissionRepository(dsn))
    service.initialize()
    mission = service.create(
        {
            "mission_key": f"build-079-health-{marker}",
            "title": "BUILD-079 PostgreSQL validation health audit",
            "description": "Controlled read-only validation mission.",
            "mission_type": "system_health_check",
            "requested_by": "build-079-ci",
            "priority": 91,
            "maximum_runs": 1,
            "input_manifest": {"marker": marker},
            "allowed_actions": ["read_health", "inspect_queue"],
            "prohibited_actions": ["taxonomy_write", "canonical_graph_publish", "external_api_call", "arbitrary_code"],
            "target_services": ["backend"],
            "target_domains": ["runtime"],
            "idempotency_key": f"build-079-health-{marker}",
        },
        {"auth_type": "api_key"},
    )
    service.submit(mission["mission_id"], "build-079-ci", "submit validation mission")
    service.approve(mission["mission_id"], "build-079-ci", "approve validation mission", f"ci-{marker}")
    service.queue(mission["mission_id"], "build-079-ci", "queue validation mission")
    result = execute_validation_mission(service, mission["mission_id"], "build-079-worker")
    if result["status"] != "completed":
        raise AssertionError(f"safe mission did not complete: {result}")

    blocked = service.create(
        {
            "mission_key": f"build-079-blocked-{marker}",
            "title": "BUILD-079 retry validation",
            "description": "Controlled blocked-handler validation mission.",
            "mission_type": "intake_batch_review",
            "requested_by": "build-079-ci",
            "priority": 100,
            "maximum_runs": 1,
            "input_manifest": {"marker": marker},
            "allowed_actions": ["review"],
            "prohibited_actions": ["taxonomy_write", "external_api_call"],
            "target_services": ["intake"],
            "target_domains": ["intake"],
            "idempotency_key": f"build-079-blocked-{marker}",
        },
        {"auth_type": "api_key"},
    )
    service.submit(blocked["mission_id"], "build-079-ci", "submit retry validation")
    service.approve(blocked["mission_id"], "build-079-ci", "approve retry validation", f"ci-{marker}-retry")
    service.queue(blocked["mission_id"], "build-079-ci", "queue retry validation")
    execute_validation_mission(service, blocked["mission_id"], "build-079-worker")
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            """
            UPDATE oc_missions.mission_jobs
            SET available_at=NOW(), priority=100
            WHERE mission_id=%s AND state='retry_wait'
            """,
            (blocked["mission_id"],),
        )
        conn.commit()
    execute_validation_mission(service, blocked["mission_id"], "build-079-worker")

    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) AS count FROM oc_missions.dead_letter_jobs WHERE mission_id=%s",
            (blocked["mission_id"],),
        )
        dead_letter_count = int(cur.fetchone()["count"])
        graph_after = {"nodes": count_or_none(cur, "oc_graph.kg_nodes"), "edges": count_or_none(cur, "oc_graph.kg_edges")}
        taxonomy_after = {name: count_or_none(cur, f"oc_taxonomy.{name}") for name in taxonomy_tables}
        graph_marker_count = schema_marker_occurrences(cur, "oc_graph", ["kg_nodes", "kg_edges"], marker)
        taxonomy_marker_count = schema_marker_occurrences(cur, "oc_taxonomy", taxonomy_tables, marker)
        cur.execute("SELECT count(*) AS count FROM oc_missions.mission_events WHERE actor IN ('build-079-ci','build-079-worker')")
        audit_count = int(cur.fetchone()["count"])
    if dead_letter_count < 1:
        raise AssertionError("expected dead-letter record was not created for the controlled validation mission")
    if graph_marker_count:
        raise AssertionError("BUILD-079 validation marker appeared in canonical graph tables")
    if taxonomy_marker_count:
        raise AssertionError("BUILD-079 validation marker appeared in taxonomy tables")
    if audit_count < 4:
        raise AssertionError("mission audit events were not recorded")

    print("BUILD-079 PostgreSQL validation succeeded")
    print(f"safe_mission_id={mission['mission_id']} blocked_mission_id={blocked['mission_id']} worker=build-079-worker")
    print(f"graph_marker_count={graph_marker_count} taxonomy_marker_count={taxonomy_marker_count}")
    print(f"graph_counts_before={graph_before} graph_counts_after={graph_after}")
    print(f"taxonomy_counts_preserved={taxonomy_before == taxonomy_after}")
    print(f"audit_events={audit_count}")


if __name__ == "__main__":
    main()
