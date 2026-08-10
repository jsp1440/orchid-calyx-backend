from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class MissionEnvelope:
    mission_key: str
    owner: str
    project_id: str
    question: str
    limits: dict[str, Any]


class BrainMissionPersistence(Protocol):
    def create_or_get(self, envelope: MissionEnvelope) -> dict[str, Any]: ...

    def get(self, mission_key: str, owner: str) -> dict[str, Any] | None: ...

    def checkpoint(
        self,
        mission_key: str,
        owner: str,
        *,
        expected_version: int,
        state: str,
        output: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]: ...


class MemoryBrainMissionPersistence:
    def __init__(self) -> None:
        self._rows: dict[str, dict[str, Any]] = {}

    def create_or_get(self, envelope: MissionEnvelope) -> dict[str, Any]:
        existing = self.get(envelope.mission_key, envelope.owner)
        if existing is not None:
            return existing
        if envelope.mission_key in self._rows:
            raise LookupError("MISSION_NOT_FOUND")
        row = {
            "mission_key": envelope.mission_key,
            "requested_by": envelope.owner,
            "state": "running",
            "version": 1,
            "input_manifest": {
                "project_id": envelope.project_id,
                "question": envelope.question,
                "limits": deepcopy(envelope.limits),
            },
            "output_manifest": {},
        }
        self._rows[envelope.mission_key] = row
        return deepcopy(row)

    def get(self, mission_key: str, owner: str) -> dict[str, Any] | None:
        row = self._rows.get(mission_key)
        return deepcopy(row) if row is not None and row["requested_by"] == owner else None

    def checkpoint(
        self,
        mission_key: str,
        owner: str,
        *,
        expected_version: int,
        state: str,
        output: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        row = self._rows.get(mission_key)
        if row is None or row["requested_by"] != owner:
            raise LookupError("MISSION_NOT_FOUND")
        if row["version"] != expected_version:
            raise RuntimeError("MISSION_VERSION_CONFLICT")
        row.update(
            state=state,
            version=expected_version + 1,
            output_manifest={**deepcopy(output), "checkpoint_stage": stage},
        )
        return deepcopy(row)


class PostgresBrainMissionPersistence:
    """Owner-scoped Brain envelope over the existing BUILD-079 mission tables."""

    def __init__(self, database_url: str) -> None:
        if not database_url.strip():
            raise RuntimeError("DATABASE_URL is required for Brain mission persistence")
        self.database_url = database_url

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)

    def create_or_get(self, envelope: MissionEnvelope) -> dict[str, Any]:
        input_manifest = {
            "project_id": envelope.project_id,
            "question": envelope.question,
            "limits": envelope.limits,
        }
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO oc_missions.missions
                (mission_key,title,description,mission_type,requested_by,priority,state,risk_level,
                 authorization_level,schedule_type,retry_policy,timeout_seconds,input_manifest,
                 execution_policy,allowed_actions,prohibited_actions,target_services,target_domains,
                 idempotency_key)
                SELECT %s,%s,%s,'brain_scientific_mission',%s,70,'running','medium',
                       'owner_session','manual','{}'::jsonb,%s,%s,%s,'[]'::jsonb,
                       '["automatic_publication","taxonomy_write","direct_graph_write"]'::jsonb,
                       '["brain","reasoning_ledger"]'::jsonb,
                       '["taxonomy","literature","occurrences","ecology","conservation"]'::jsonb,%s
                WHERE EXISTS (
                    SELECT 1 FROM oc_missions.mission_types
                    WHERE mission_type='brain_scientific_mission' AND active
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING *""",
                (
                    envelope.mission_key,
                    f"Brain mission {envelope.mission_key}",
                    envelope.question,
                    envelope.owner,
                    max(1, math.ceil(float(envelope.limits.get("timeout_seconds", 30)))),
                    Jsonb(input_manifest),
                    Jsonb({"handler": "brain_scientific_mission", "checkpointed": True}),
                    envelope.mission_key,
                ),
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    """SELECT * FROM oc_missions.missions
                    WHERE mission_key=%s AND requested_by=%s""",
                    (envelope.mission_key, envelope.owner),
                )
                row = cur.fetchone()
            if row is None:
                raise RuntimeError("BRAIN_MISSION_TYPE_NOT_REGISTERED_OR_OWNER_MISMATCH")
            return row

    def get(self, mission_key: str, owner: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """SELECT * FROM oc_missions.missions
                WHERE mission_key=%s AND requested_by=%s""",
                (mission_key, owner),
            )
            return cur.fetchone()

    def checkpoint(
        self,
        mission_key: str,
        owner: str,
        *,
        expected_version: int,
        state: str,
        output: dict[str, Any],
        stage: str,
    ) -> dict[str, Any]:
        allowed_states = {"running", "awaiting_approval", "completed", "blocked", "failed"}
        if state not in allowed_states:
            raise ValueError("INVALID_BRAIN_MISSION_STATE")
        manifest = {**output, "checkpoint_stage": stage}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """UPDATE oc_missions.missions
                SET state=%s, output_manifest=%s, version=version+1,
                    completed_at=CASE WHEN %s='completed' THEN NOW() ELSE completed_at END
                WHERE mission_key=%s AND requested_by=%s AND version=%s
                RETURNING *""",
                (state, Jsonb(manifest), state, mission_key, owner, expected_version),
            )
            row = cur.fetchone()
            if row is not None:
                cur.execute(
                    """INSERT INTO oc_missions.mission_events
                    (actor,actor_type,event_type,mission_id,previous_state,new_state,
                     output_digest,event_payload)
                    VALUES (%s,'brain_mission','mission_checkpointed',%s,NULL,%s,NULL,%s)""",
                    (owner, row["mission_id"], state, Jsonb({"stage": stage, "version": row["version"]})),
                )
                return row
            cur.execute(
                """SELECT version FROM oc_missions.missions
                WHERE mission_key=%s AND requested_by=%s""",
                (mission_key, owner),
            )
            existing = cur.fetchone()
            if existing is None:
                raise LookupError("MISSION_NOT_FOUND")
            raise RuntimeError("MISSION_VERSION_CONFLICT")


class DurableMissionRepository:
    """BrainMissionService repository backed by the governed mission envelope."""

    def __init__(self, persistence: BrainMissionPersistence) -> None:
        self.persistence = persistence

    def save(self, mission: dict[str, Any]) -> None:
        owner = str(mission["tenant_id"])
        envelope = MissionEnvelope(
            mission_key=str(mission["mission_id"]), owner=owner,
            project_id=str(mission["project_id"]), question=str(mission["question"]),
            limits=dict(mission["limits"]),
        )
        row = self.persistence.create_or_get(envelope)
        current = row.get("output_manifest") or {}
        if current == mission:
            return
        self.persistence.checkpoint(
            envelope.mission_key, owner, expected_version=int(row["version"]),
            state=self._state(mission), output=mission,
            stage=str(mission["current_stage"]),
        )

    def get(self, mission_id: str, tenant_id: str | None = None) -> dict[str, Any] | None:
        if tenant_id is None:
            return None
        row = self.persistence.get(mission_id, tenant_id)
        if row is None:
            return None
        output = row.get("output_manifest") or {}
        if not output or output.get("mission_id") != mission_id:
            return None
        result = deepcopy(output)
        checkpoint_stage = result.pop("checkpoint_stage", None)
        if result.get("state") == "RUNNING":
            result["_checkpoint_stage"] = checkpoint_stage
        return result

    @staticmethod
    def _state(mission: dict[str, Any]) -> str:
        return {
            "RUNNING": "running", "AWAITING_HUMAN_REVIEW": "awaiting_approval",
            "COMPLETE": "completed", "BLOCKED": "blocked",
        }.get(str(mission.get("state") or "RUNNING"), "failed")
