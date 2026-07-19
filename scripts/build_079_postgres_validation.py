from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
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
    result = service.execute_cycle("build-079-worker", 1)
    if result["status"] != "completed":
        raise AssertionError(f"safe mission did not complete: {result}")

    blocked = service.create(
        {
            "mission_key": f"build-079-blocked-{marker}",
            "title": "BUILD-079 retry validation",
            "description": "Controlled blocked-handler validation mission.",
            "mission_type": "intake_batch_review",
            "requested_by": "build-079-ci",
            "priority": 50,
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
    service.execute_cycle("build-079-worker", 1)
    service.execute_cycle("build-079-worker", 1)
    if not service.dead_letters():
        raise AssertionError("expected dead-letter record was not created")

    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        graph_after = {"nodes": count_or_none(cur, "oc_graph.kg_nodes"), "edges": count_or_none(cur, "oc_graph.kg_edges")}
        taxonomy_after = {name: count_or_none(cur, f"oc_taxonomy.{name}") for name in taxonomy_tables}
        cur.execute("SELECT count(*) AS count FROM oc_missions.mission_events WHERE actor IN ('build-079-ci','build-079-worker')")
        audit_count = int(cur.fetchone()["count"])
    if graph_after != graph_before:
        raise AssertionError(f"canonical graph changed unexpectedly: {graph_before} -> {graph_after}")
    if taxonomy_after != taxonomy_before:
        raise AssertionError("taxonomy tables changed unexpectedly")
    if audit_count < 4:
        raise AssertionError("mission audit events were not recorded")

    print("BUILD-079 PostgreSQL validation succeeded")
    print(f"safe_mission_id={mission['mission_id']} blocked_mission_id={blocked['mission_id']} worker=build-079-worker")
    print(f"graph_preserved={graph_before == graph_after} taxonomy_preserved={taxonomy_before == taxonomy_after}")
    print(f"audit_events={audit_count}")


if __name__ == "__main__":
    main()
