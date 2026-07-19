from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .registry import MISSION_TYPES, SAFE_TEMPLATES


def mission_database_url() -> str:
    value = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for mission operations")
    return value


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value or {}, sort_keys=True, default=str).encode("utf-8")).hexdigest()


class PostgresMissionRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or mission_database_url()

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)

    def seed_registry(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            for mission_type in MISSION_TYPES.values():
                data = mission_type.as_dict()
                cur.execute(
                    """INSERT INTO oc_missions.mission_types
                    (mission_type,handler,input_schema,output_schema,required_authorization,risk_level,write_scope,
                     allowed_database_schemas,forbidden_database_schemas,timeout_seconds,retry_policy,
                     human_approval_required,dry_run_required,publication_authority_required,
                     canonical_graph_writes_permitted,taxonomy_writes_prohibited,audit_requirements)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (mission_type) DO UPDATE SET updated_at=NOW(), active=TRUE""",
                    (
                        data["mission_type"], data["handler"], Jsonb(data["input_schema"]), Jsonb(data["output_schema"]),
                        data["required_authorization"], data["risk_level"], data["write_scope"],
                        Jsonb(data["allowed_database_schemas"]), Jsonb(data["forbidden_database_schemas"]),
                        data["timeout_seconds"], Jsonb(data["retry_policy"]), data["human_approval_required"],
                        data["dry_run_required"], data["publication_authority_required"],
                        data["canonical_graph_writes_permitted"], data["taxonomy_writes_prohibited"],
                        Jsonb(data["audit_requirements"]),
                    ),
                )
            for template in SAFE_TEMPLATES:
                cur.execute(
                    """INSERT INTO oc_missions.mission_templates
                    (template_key,title,description,mission_type,default_priority,default_risk,input_schema,
                     default_inputs,required_approvals,allowed_actions,prohibited_actions,scheduling_defaults,retry_defaults,active,version)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE,1)
                    ON CONFLICT (template_key, version) DO NOTHING""",
                    (
                        template["template_key"], template["title"], template["description"], template["mission_type"],
                        template["default_priority"], template["default_risk"], Jsonb({}), Jsonb(template["default_inputs"]),
                        Jsonb(template["required_approvals"]), Jsonb(template["allowed_actions"]),
                        Jsonb(template["prohibited_actions"]), Jsonb({}), Jsonb({"maximum_attempts": 2}),
                    ),
                )

    def mission_type(self, mission_type: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_missions.mission_types WHERE mission_type=%s AND active", (mission_type,))
            return cur.fetchone()

    def create_mission(self, data: Mapping[str, Any], actor_type: str = "owner_session") -> dict[str, Any]:
        mission_type = self.mission_type(str(data["mission_type"]))
        if mission_type is None:
            raise ValueError("UNREGISTERED_MISSION_TYPE")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO oc_missions.missions
                (mission_key,title,description,mission_type,requested_by,priority,state,risk_level,authorization_level,
                 schedule_type,scheduled_at,recurrence_rule,next_run_at,maximum_runs,maximum_failures,retry_policy,
                 timeout_seconds,input_manifest,execution_policy,allowed_actions,prohibited_actions,target_services,
                 target_domains,created_from_template_id,idempotency_key)
                VALUES (%s,%s,%s,%s,%s,%s,'draft',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (idempotency_key) DO UPDATE SET updated_at=NOW()
                RETURNING *""",
                (
                    data["mission_key"], data["title"], data["description"], data["mission_type"], data["requested_by"],
                    data.get("priority", 50), mission_type["risk_level"], mission_type["required_authorization"],
                    data.get("schedule_type", "manual"), data.get("scheduled_at"), data.get("recurrence_rule"),
                    data.get("scheduled_at"), data.get("maximum_runs"), data.get("maximum_failures", 3),
                    Jsonb(mission_type["retry_policy"]), mission_type["timeout_seconds"], Jsonb(data.get("input_manifest") or {}),
                    Jsonb({"handler": mission_type["handler"], "write_scope": mission_type["write_scope"]}),
                    Jsonb(data.get("allowed_actions") or []), Jsonb(data.get("prohibited_actions") or []),
                    Jsonb(data.get("target_services") or []), Jsonb(data.get("target_domains") or []),
                    data.get("created_from_template_id"), data["idempotency_key"],
                ),
            )
            mission = cur.fetchone()
            self.audit(cur, actor=data["requested_by"], actor_type=actor_type, event_type="mission_created", mission=mission, previous_state=None, new_state=mission["state"], payload={"mission_type": data["mission_type"]})
            return mission

    def update_draft(self, mission_id: int, changes: Mapping[str, Any], actor: str, reason: str) -> dict[str, Any]:
        allowed = {k: v for k, v in changes.items() if k in {"title", "description", "priority", "input_manifest", "allowed_actions", "prohibited_actions"} and v is not None}
        if not allowed:
            raise ValueError("NO_MISSION_CHANGES")
        with self._connect() as conn, conn.cursor() as cur:
            mission = self._mission_for_update(cur, mission_id)
            if mission["state"] != "draft":
                raise ValueError("MISSION_NOT_DRAFT")
            sets, values = [], []
            for key, value in allowed.items():
                sets.append(f"{key}=%s")
                values.append(Jsonb(value) if isinstance(value, (dict, list)) else value)
            cur.execute(f"UPDATE oc_missions.missions SET {','.join(sets)} WHERE mission_id=%s RETURNING *", (*values, mission_id))
            updated = cur.fetchone()
            self.audit(cur, actor=actor, actor_type="owner_session", event_type="mission_updated", mission=updated, previous_state=mission["state"], new_state=updated["state"], payload={"reason": reason})
            return updated

    def transition_mission(self, mission_id: int, target: str, actor: str, reason: str, approval_reference: str | None = None, publication_authority: str | None = None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            mission = self._mission_for_update(cur, mission_id)
            extra = ""
            values: list[Any] = [target]
            if target == "approved":
                if not approval_reference and not mission.get("owner_approval_reference"):
                    raise ValueError("APPROVAL_REFERENCE_REQUIRED")
                if mission["mission_type"] == "controlled_publication" and not publication_authority:
                    raise ValueError("PUBLICATION_AUTHORITY_REQUIRED")
                extra = ", owner_approval_reference=COALESCE(%s, owner_approval_reference), approval_timestamp=COALESCE(approval_timestamp, NOW())"
                values.append(approval_reference)
            if target == "paused":
                extra = ", paused_at=NOW()"
            if target == "cancelled":
                extra = ", cancelled_at=NOW()"
            values.append(mission_id)
            cur.execute(f"UPDATE oc_missions.missions SET state=%s{extra} WHERE mission_id=%s RETURNING *", tuple(values))
            updated = cur.fetchone()
            self.audit(cur, actor=actor, actor_type="owner_session", event_type=f"mission_{target}", mission=updated, previous_state=mission["state"], new_state=target, payload={"reason": reason, "approval_reference": approval_reference, "publication_authority_present": bool(publication_authority)})
            return updated

    def queue_mission(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            mission = self._mission_for_update(cur, mission_id)
            if mission["state"] != "approved":
                raise ValueError("ONLY_APPROVED_MISSIONS_CAN_QUEUE")
            cur.execute("UPDATE oc_missions.missions SET state='queued' WHERE mission_id=%s RETURNING *", (mission_id,))
            updated = cur.fetchone()
            self._enqueue_job(cur, updated)
            self.audit(cur, actor=actor, actor_type="owner_session", event_type="mission_queued", mission=updated, previous_state=mission["state"], new_state="queued", payload={"reason": reason})
            return updated

    def enqueue_due_missions(self, actor: str = "runtime") -> dict[str, Any]:
        created = 0
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_missions.missions WHERE state='approved' AND (next_run_at IS NULL OR next_run_at <= NOW()) ORDER BY priority DESC, mission_id FOR UPDATE SKIP LOCKED")
            for mission in cur.fetchall():
                cur.execute("UPDATE oc_missions.missions SET state='queued' WHERE mission_id=%s RETURNING *", (mission["mission_id"],))
                queued = cur.fetchone()
                if self._enqueue_job(cur, queued):
                    created += 1
                self.audit(cur, actor=actor, actor_type="runtime_worker", event_type="mission_auto_queued", mission=queued, previous_state="approved", new_state="queued", payload={})
        return {"status": "ok" if created else "no_jobs", "jobs_created": created, "queue_depth": self.queue_depth()}

    def claim_job(self, worker_id: str, lease_seconds: int = 300) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            self.register_worker(cur, worker_id)
            cur.execute(
                """WITH candidate AS (
                    SELECT job_id FROM oc_missions.mission_jobs
                    WHERE state IN ('available','retry_wait') AND available_at <= NOW()
                    ORDER BY priority DESC, available_at ASC, job_id ASC
                    LIMIT 1 FOR UPDATE SKIP LOCKED
                )
                UPDATE oc_missions.mission_jobs j
                SET state='claimed', claimed_at=NOW(), lease_expires_at=NOW() + (%s || ' seconds')::interval,
                    worker_id=%s, attempt_number=attempt_number + 1
                FROM candidate WHERE j.job_id=candidate.job_id
                RETURNING j.*""",
                (lease_seconds, worker_id),
            )
            job = cur.fetchone()
            if not job:
                return None
            cur.execute("SELECT * FROM oc_missions.missions WHERE mission_id=%s", (job["mission_id"],))
            mission = cur.fetchone()
            self.audit(cur, actor=worker_id, actor_type="runtime_worker", event_type="job_claimed", mission=mission, job=job, previous_state="available", new_state="claimed", worker_id=worker_id)
            return {**job, "mission": mission}

    def start_job(self, job_id: int, worker_id: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE oc_missions.mission_jobs SET state='running', started_at=COALESCE(started_at,NOW()) WHERE job_id=%s AND worker_id=%s RETURNING *", (job_id, worker_id))
            job = cur.fetchone()
            if not job:
                raise LookupError("JOB_NOT_CLAIMED")
            cur.execute("UPDATE oc_missions.missions SET state='running' WHERE mission_id=%s AND state='queued' RETURNING *", (job["mission_id"],))
            mission = cur.fetchone() or self.get_mission(job["mission_id"])
            return {**job, "mission": mission}

    def complete_job(self, job: Mapping[str, Any], output: Mapping[str, Any], worker_id: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE oc_missions.mission_jobs SET state='succeeded', output_payload=%s, finished_at=NOW(), lease_expires_at=NULL WHERE job_id=%s RETURNING *", (Jsonb(dict(output)), job["job_id"]))
            updated_job = cur.fetchone()
            cur.execute("UPDATE oc_missions.missions SET state='completed', completed_runs=completed_runs+1, completed_at=NOW(), output_manifest=%s WHERE mission_id=%s RETURNING *", (Jsonb(dict(output)), job["mission_id"]))
            mission = cur.fetchone()
            cur.execute("INSERT INTO oc_missions.job_attempts(job_id,attempt_number,worker_id,state,finished_at,output_payload) VALUES (%s,%s,%s,'succeeded',NOW(),%s) ON CONFLICT (job_id,attempt_number) DO UPDATE SET state='succeeded', finished_at=NOW(), output_payload=EXCLUDED.output_payload", (job["job_id"], updated_job["attempt_number"], worker_id, Jsonb(dict(output))))
            self.audit(cur, actor=worker_id, actor_type="runtime_worker", event_type="job_succeeded", mission=mission, job=updated_job, previous_state="running", new_state="succeeded", output=output, worker_id=worker_id)
            return {**updated_job, "mission": mission}

    def fail_job(self, job: Mapping[str, Any], error_code: str, error_message: str, worker_id: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            final = int(job["attempt_number"]) >= int(job["maximum_attempts"])
            state = "dead_lettered" if final else "retry_wait"
            cur.execute(
                """UPDATE oc_missions.mission_jobs
                SET state=%s, error_code=%s, error_message=%s, finished_at=NOW(), lease_expires_at=NULL,
                    available_at=CASE WHEN %s THEN available_at ELSE NOW() + interval '60 seconds' END
                WHERE job_id=%s RETURNING *""",
                (state, error_code, error_message, final, job["job_id"]),
            )
            updated_job = cur.fetchone()
            mission_state = "failed" if final else "queued"
            cur.execute("UPDATE oc_missions.missions SET state=%s, failure_count=failure_count+1, last_error=%s WHERE mission_id=%s RETURNING *", (mission_state, error_message, job["mission_id"]))
            mission = cur.fetchone()
            if final:
                cur.execute("INSERT INTO oc_missions.dead_letter_jobs(job_id,mission_id,final_error_code,final_error_message,payload) VALUES (%s,%s,%s,%s,%s) ON CONFLICT (job_id) DO NOTHING", (job["job_id"], job["mission_id"], error_code, error_message, Jsonb(dict(job))))
            cur.execute("INSERT INTO oc_missions.job_attempts(job_id,attempt_number,worker_id,state,finished_at,error_code,error_message,traceback_digest) VALUES (%s,%s,%s,%s,NOW(),%s,%s,%s) ON CONFLICT (job_id,attempt_number) DO NOTHING", (job["job_id"], updated_job["attempt_number"], worker_id, "dead_lettered" if final else "failed", error_code, error_message, json_digest(error_message)))
            self.audit(cur, actor=worker_id, actor_type="runtime_worker", event_type="job_failed", mission=mission, job=updated_job, previous_state="running", new_state=state, error=error_message, worker_id=worker_id)
            return {**updated_job, "mission": mission}

    def recover_expired_leases(self, worker_id: str) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE oc_missions.mission_jobs SET state='available', worker_id=NULL, lease_expires_at=NULL WHERE state IN ('claimed','running') AND lease_expires_at < NOW() RETURNING job_id")
            recovered = len(cur.fetchall())
            self.register_worker(cur, worker_id, recovered)
            return recovered

    def telemetry(self) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT state, count(*) AS count FROM oc_missions.missions GROUP BY state")
            missions_by_state = {row["state"]: int(row["count"]) for row in cur.fetchall()}
            cur.execute("SELECT state, count(*) AS count FROM oc_missions.mission_jobs GROUP BY state")
            jobs_by_state = {row["state"]: int(row["count"]) for row in cur.fetchall()}
            cur.execute("SELECT min(available_at) AS oldest FROM oc_missions.mission_jobs WHERE state IN ('available','retry_wait')")
            oldest = cur.fetchone()["oldest"]
            cur.execute("SELECT * FROM oc_missions.runtime_workers ORDER BY heartbeat_at DESC LIMIT 1")
            worker = cur.fetchone()
            cur.execute("SELECT * FROM oc_missions.missions WHERE state='running' ORDER BY priority DESC, mission_id LIMIT 1")
            active = cur.fetchone()
            cur.execute("SELECT * FROM oc_missions.missions WHERE state='completed' ORDER BY completed_at DESC NULLS LAST, mission_id DESC LIMIT 1")
            completed = cur.fetchone()
            cur.execute("SELECT * FROM oc_missions.missions WHERE state='failed' ORDER BY updated_at DESC LIMIT 1")
            failed = cur.fetchone()
            cur.execute("SELECT count(*) AS count FROM oc_missions.dead_letter_jobs")
            dead = int(cur.fetchone()["count"])
            return {
                "total_missions": sum(missions_by_state.values()),
                "missions_by_state": missions_by_state,
                "active_mission": active,
                "queued_missions": missions_by_state.get("queued", 0),
                "queue_depth": self.queue_depth(cur),
                "jobs_by_state": jobs_by_state,
                "oldest_waiting_job": str(oldest) if oldest else None,
                "failed_jobs": jobs_by_state.get("failed", 0),
                "dead_letter_jobs": dead,
                "next_scheduled_mission": None,
                "last_completed_mission": completed,
                "last_failed_mission": failed,
                "worker_heartbeat": worker,
                "lease_recovery_count": int(worker["lease_recovery_count"]) if worker else 0,
                "runtime_blocker": worker["runtime_blocker"] if worker else None,
                "authorization_readiness": "owner_session_or_api_key_required",
                "publication_control_readiness": "build_078_publication_controls_preserved",
            }

    def list_missions(self) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_missions.missions ORDER BY priority DESC, mission_id DESC LIMIT 100")
            return list(cur.fetchall())

    def get_mission(self, mission_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_missions.missions WHERE mission_id=%s", (mission_id,))
            return cur.fetchone()

    def list_jobs(self, mission_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_missions.mission_jobs WHERE mission_id=%s ORDER BY sequence, job_id", (mission_id,))
            return list(cur.fetchall())

    def list_events(self, mission_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_missions.mission_events WHERE mission_id=%s ORDER BY event_id", (mission_id,))
            return list(cur.fetchall())

    def dead_letters(self) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_missions.dead_letter_jobs ORDER BY dead_lettered_at DESC LIMIT 100")
            return list(cur.fetchall())

    def templates(self) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_missions.mission_templates WHERE active ORDER BY default_priority DESC, template_key")
            return list(cur.fetchall())

    def queue_depth(self, cur=None) -> int:
        if cur is not None:
            cur.execute("SELECT count(*) AS count FROM oc_missions.mission_jobs WHERE state IN ('available','retry_wait')")
            return int(cur.fetchone()["count"])
        with self._connect() as conn, conn.cursor() as own_cur:
            return self.queue_depth(own_cur)

    def _mission_for_update(self, cur, mission_id: int) -> dict[str, Any]:
        cur.execute("SELECT * FROM oc_missions.missions WHERE mission_id=%s FOR UPDATE", (mission_id,))
        mission = cur.fetchone()
        if mission is None:
            raise LookupError("MISSION_NOT_FOUND")
        return mission

    def _enqueue_job(self, cur, mission: Mapping[str, Any]) -> bool:
        cur.execute(
            """INSERT INTO oc_missions.mission_jobs
            (mission_id,job_type,state,sequence,priority,scheduled_at,available_at,maximum_attempts,input_payload,idempotency_key)
            VALUES (%s,%s,'available',1,%s,%s,COALESCE(%s,NOW()),%s,%s,%s)
            ON CONFLICT (idempotency_key) DO NOTHING RETURNING job_id""",
            (
                mission["mission_id"], mission["mission_type"], mission["priority"], mission.get("scheduled_at"),
                mission.get("next_run_at"), int((mission.get("retry_policy") or {}).get("maximum_attempts", 2)),
                Jsonb(mission["input_manifest"]), f"mission:{mission['mission_id']}:job:1",
            ),
        )
        return cur.fetchone() is not None

    def register_worker(self, cur, worker_id: str, recovered: int = 0) -> None:
        cur.execute(
            """INSERT INTO oc_missions.runtime_workers(worker_id,status,heartbeat_at,lease_recovery_count)
            VALUES (%s,'alive',NOW(),%s)
            ON CONFLICT (worker_id) DO UPDATE SET status='alive', heartbeat_at=NOW(),
              lease_recovery_count=oc_missions.runtime_workers.lease_recovery_count + EXCLUDED.lease_recovery_count,
              updated_at=NOW()""",
            (worker_id, recovered),
        )

    def audit(self, cur, *, actor: str, actor_type: str, event_type: str, mission: Mapping[str, Any] | None = None, job: Mapping[str, Any] | None = None, previous_state: str | None = None, new_state: str | None = None, payload: Mapping[str, Any] | None = None, output: Mapping[str, Any] | None = None, error: str | None = None, worker_id: str | None = None) -> None:
        cur.execute(
            """INSERT INTO oc_missions.mission_events
            (actor,actor_type,event_type,mission_id,job_id,previous_state,new_state,approval_reference,
             input_digest,output_digest,error_digest,worker_id,commit_sha,event_payload)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                actor, actor_type, event_type, mission["mission_id"] if mission else None, job["job_id"] if job else None,
                previous_state, new_state, mission.get("owner_approval_reference") if mission else None,
                json_digest((job or mission or {}).get("input_payload") or (mission or {}).get("input_manifest") or {}),
                json_digest(output) if output is not None else None,
                json_digest(error) if error is not None else None,
                worker_id, os.getenv("RENDER_GIT_COMMIT") or os.getenv("GIT_COMMIT_SHA"), Jsonb(dict(payload or {})),
            ),
        )


class InMemoryMissionRepository:
    def __init__(self) -> None:
        self.mission_types = {key: value.as_dict() | {"active": True} for key, value in MISSION_TYPES.items()}
        self.templates_rows = [{**template, "id": index, "version": 1, "active": True} for index, template in enumerate(SAFE_TEMPLATES, 1)]
        self.missions: dict[int, dict[str, Any]] = {}
        self.jobs: dict[int, dict[str, Any]] = {}
        self.events: list[dict[str, Any]] = []
        self.dead: list[dict[str, Any]] = []
        self.workers: dict[str, dict[str, Any]] = {}
        self.next_mission_id = 1
        self.next_job_id = 1

    def seed_registry(self) -> None:
        return None

    def mission_type(self, mission_type: str) -> dict[str, Any] | None:
        return deepcopy(self.mission_types.get(mission_type))

    def create_mission(self, data: Mapping[str, Any], actor_type: str = "owner_session") -> dict[str, Any]:
        for mission in self.missions.values():
            if mission["idempotency_key"] == data["idempotency_key"]:
                return deepcopy(mission)
        mt = self.mission_type(str(data["mission_type"]))
        if not mt:
            raise ValueError("UNREGISTERED_MISSION_TYPE")
        mission = {
            **dict(data), "mission_id": self.next_mission_id, "state": "draft", "risk_level": mt["risk_level"],
            "authorization_level": mt["required_authorization"], "retry_policy": mt["retry_policy"],
            "timeout_seconds": mt["timeout_seconds"], "execution_policy": {"handler": mt["handler"]},
            "output_manifest": {}, "completed_runs": 0, "failure_count": 0, "owner_approval_reference": None,
            "approval_timestamp": None, "last_error": None,
        }
        self.next_mission_id += 1
        self.missions[mission["mission_id"]] = mission
        self._event("mission_created", mission, actor=data["requested_by"], actor_type=actor_type)
        return deepcopy(mission)

    def update_draft(self, mission_id: int, changes: Mapping[str, Any], actor: str, reason: str) -> dict[str, Any]:
        mission = self.missions[mission_id]
        if mission["state"] != "draft":
            raise ValueError("MISSION_NOT_DRAFT")
        mission.update({k: v for k, v in changes.items() if v is not None and k in {"title", "description", "priority", "input_manifest", "allowed_actions", "prohibited_actions"}})
        self._event("mission_updated", mission, actor=actor)
        return deepcopy(mission)

    def transition_mission(self, mission_id: int, target: str, actor: str, reason: str, approval_reference: str | None = None, publication_authority: str | None = None) -> dict[str, Any]:
        mission = self.missions[mission_id]
        if target == "approved":
            if not approval_reference and not mission.get("owner_approval_reference"):
                raise ValueError("APPROVAL_REFERENCE_REQUIRED")
            if mission["mission_type"] == "controlled_publication" and not publication_authority:
                raise ValueError("PUBLICATION_AUTHORITY_REQUIRED")
            mission["owner_approval_reference"] = approval_reference or mission.get("owner_approval_reference")
            mission["approval_timestamp"] = mission.get("approval_timestamp") or utc_now()
        mission["state"] = target
        self._event(f"mission_{target}", mission, actor=actor)
        return deepcopy(mission)

    def queue_mission(self, mission_id: int, actor: str, reason: str) -> dict[str, Any]:
        mission = self.missions[mission_id]
        if mission["state"] != "approved":
            raise ValueError("ONLY_APPROVED_MISSIONS_CAN_QUEUE")
        mission["state"] = "queued"
        self._enqueue_job(mission)
        self._event("mission_queued", mission, actor=actor)
        return deepcopy(mission)

    def enqueue_due_missions(self, actor: str = "runtime") -> dict[str, Any]:
        created = 0
        for mission in self.missions.values():
            if mission["state"] == "approved":
                mission["state"] = "queued"
                created += 1 if self._enqueue_job(mission) else 0
        return {"status": "ok" if created else "no_jobs", "jobs_created": created, "queue_depth": self.queue_depth()}

    def claim_job(self, worker_id: str, lease_seconds: int = 300) -> dict[str, Any] | None:
        self.workers[worker_id] = {"worker_id": worker_id, "status": "alive", "heartbeat_at": utc_now(), "lease_recovery_count": 0}
        available = sorted([j for j in self.jobs.values() if j["state"] in {"available", "retry_wait"}], key=lambda j: (-j["priority"], j["job_id"]))
        if not available:
            return None
        job = available[0]
        job["state"] = "claimed"; job["worker_id"] = worker_id; job["attempt_number"] += 1; job["lease_expires_at"] = utc_now()
        return deepcopy({**job, "mission": self.missions[job["mission_id"]]})

    def start_job(self, job_id: int, worker_id: str) -> dict[str, Any]:
        job = self.jobs[job_id]; job["state"] = "running"; self.missions[job["mission_id"]]["state"] = "running"
        return deepcopy({**job, "mission": self.missions[job["mission_id"]]})

    def complete_job(self, job: Mapping[str, Any], output: Mapping[str, Any], worker_id: str) -> dict[str, Any]:
        stored = self.jobs[job["job_id"]]; stored["state"] = "succeeded"; stored["output_payload"] = dict(output)
        mission = self.missions[stored["mission_id"]]; mission["state"] = "completed"; mission["output_manifest"] = dict(output); mission["completed_runs"] += 1
        self._event("job_succeeded", mission, stored, actor=worker_id, actor_type="runtime_worker")
        return deepcopy({**stored, "mission": mission})

    def fail_job(self, job: Mapping[str, Any], error_code: str, error_message: str, worker_id: str) -> dict[str, Any]:
        stored = self.jobs[job["job_id"]]
        final = stored["attempt_number"] >= stored["maximum_attempts"]
        stored["state"] = "dead_lettered" if final else "retry_wait"; stored["error_code"] = error_code; stored["error_message"] = error_message
        mission = self.missions[stored["mission_id"]]; mission["state"] = "failed" if final else "queued"; mission["failure_count"] += 1; mission["last_error"] = error_message
        if final:
            self.dead.append({"job_id": stored["job_id"], "mission_id": mission["mission_id"], "final_error_message": error_message})
        self._event("job_failed", mission, stored, actor=worker_id, actor_type="runtime_worker")
        return deepcopy({**stored, "mission": mission})

    def recover_expired_leases(self, worker_id: str) -> int:
        recovered = 0
        for job in self.jobs.values():
            if job["state"] in {"claimed", "running"}:
                job["state"] = "available"; recovered += 1
        self.workers[worker_id] = {"worker_id": worker_id, "status": "alive", "heartbeat_at": utc_now(), "lease_recovery_count": recovered}
        return recovered

    def telemetry(self) -> dict[str, Any]:
        missions_by_state: dict[str, int] = {}
        jobs_by_state: dict[str, int] = {}
        for mission in self.missions.values(): missions_by_state[mission["state"]] = missions_by_state.get(mission["state"], 0) + 1
        for job in self.jobs.values(): jobs_by_state[job["state"]] = jobs_by_state.get(job["state"], 0) + 1
        return {"total_missions": len(self.missions), "missions_by_state": missions_by_state, "queue_depth": self.queue_depth(), "jobs_by_state": jobs_by_state, "dead_letter_jobs": len(self.dead), "worker_heartbeat": next(iter(self.workers.values()), None), "authorization_readiness": "owner_session_or_api_key_required", "publication_control_readiness": "build_078_publication_controls_preserved", "runtime_blocker": None}

    def list_missions(self) -> list[dict[str, Any]]: return list(deepcopy(self.missions).values())
    def get_mission(self, mission_id: int) -> dict[str, Any] | None: return deepcopy(self.missions.get(mission_id))
    def list_jobs(self, mission_id: int) -> list[dict[str, Any]]: return [deepcopy(j) for j in self.jobs.values() if j["mission_id"] == mission_id]
    def list_events(self, mission_id: int) -> list[dict[str, Any]]: return [deepcopy(e) for e in self.events if e["mission_id"] == mission_id]
    def dead_letters(self) -> list[dict[str, Any]]: return deepcopy(self.dead)
    def templates(self) -> list[dict[str, Any]]: return deepcopy(self.templates_rows)
    def queue_depth(self, cur=None) -> int: return sum(1 for j in self.jobs.values() if j["state"] in {"available", "retry_wait"})

    def _enqueue_job(self, mission: Mapping[str, Any]) -> bool:
        key = f"mission:{mission['mission_id']}:job:1"
        if any(job["idempotency_key"] == key for job in self.jobs.values()):
            return False
        job = {"job_id": self.next_job_id, "mission_id": mission["mission_id"], "job_type": mission["mission_type"], "state": "available", "priority": mission["priority"], "attempt_number": 0, "maximum_attempts": int(mission["retry_policy"].get("maximum_attempts", 2)), "input_payload": mission.get("input_manifest") or {}, "output_payload": {}, "idempotency_key": key}
        self.next_job_id += 1
        self.jobs[job["job_id"]] = job
        return True

    def _event(self, event_type: str, mission: Mapping[str, Any], job: Mapping[str, Any] | None = None, actor: str = "owner", actor_type: str = "owner_session") -> None:
        self.events.append({"event_id": len(self.events) + 1, "event_type": event_type, "mission_id": mission["mission_id"], "job_id": job["job_id"] if job else None, "actor": actor, "actor_type": actor_type, "occurred_at": utc_now()})
