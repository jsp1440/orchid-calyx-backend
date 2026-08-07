from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any, ClassVar

from psycopg.types.json import Jsonb

from .models import (
    AuditEvent,
    ContextItem,
    CoverageOutcome,
    DesignEvidencePackage,
    DesignReasoningRecord,
    EvidenceResult,
    InterfacePlan,
    LifecycleState,
    MaterialConflictRecord,
    ProductRequest,
    ProjectContextSnapshot,
    ProvenanceRef,
    Requirement,
    RequirementStatus,
    ReviewDecision,
    ReviewRecord,
    ReviewRole,
)
from .repository import ImmutableConflictError


class PostgresDesignPlanningRepository:
    """PostgreSQL-authoritative append-only planning repository."""

    TABLES: ClassVar[dict[str, str]] = {
        "context": "project_context_snapshots",
        "evidence": "design_evidence_packages",
        "reasoning": "design_reasoning_records",
        "conflict": "material_conflict_records",
        "plan": "interface_plans",
    }

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url)

    def append(self, kind: str, artifact: Any, logical_key: str, digest: str) -> Any:
        table = self.TABLES[kind]
        identity = self._identity(artifact)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"{kind}:{logical_key}",),
            )
            cur.execute(
                f"SELECT payload FROM design_planning.{table} WHERE integrity_hash=%s",
                (digest,),
            )
            if existing := cur.fetchone():
                return self._hydrate(kind, existing[0])
            try:
                cur.execute(
                    f"INSERT INTO design_planning.{table} (artifact_id, logical_key, version, integrity_hash, payload) VALUES (%s,%s,%s,%s,%s)",
                    (
                        identity,
                        logical_key,
                        artifact.version,
                        digest,
                        Jsonb(self._json_payload(artifact)),
                    ),
                )
            except Exception as exc:
                raise ImmutableConflictError(
                    f"{kind.upper()}_VERSION_CONFLICT"
                ) from exc
        return artifact

    def get(self, kind: str, identity: str) -> Any | None:
        table = self.TABLES[kind]
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT payload FROM design_planning.{table} WHERE artifact_id=%s",
                (identity,),
            )
            row = cur.fetchone()
        return self._hydrate(kind, row[0]) if row else None

    def history(self, kind: str, logical_key: str) -> tuple[Any, ...]:
        table = self.TABLES[kind]
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT payload FROM design_planning.{table} WHERE logical_key=%s ORDER BY version",
                (logical_key,),
            )
            return tuple(self._hydrate(kind, row[0]) for row in cur.fetchall())

    def append_review(self, review: ReviewRecord) -> ReviewRecord:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"review:{review.artifact_hash}:{review.reviewer_role.value}",),
            )
            cur.execute(
                "INSERT INTO design_planning.review_records (review_id, artifact_id, artifact_hash, reviewer_role, decision, integrity_hash, payload) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (integrity_hash) DO NOTHING",
                (
                    review.review_id,
                    review.artifact_id,
                    review.artifact_hash,
                    review.reviewer_role.value,
                    review.decision.value,
                    review.integrity_hash,
                    Jsonb(self._json_payload(review)),
                ),
            )
        return review

    def reviews(self, artifact_id: str) -> tuple[dict, ...]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM design_planning.review_records WHERE artifact_id=%s ORDER BY created_at, review_id",
                (artifact_id,),
            )
            return tuple(self._hydrate("review", row[0]) for row in cur.fetchall())

    def append_audit(self, event: AuditEvent) -> AuditEvent:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO design_planning.audit_events (event_id, artifact_id, integrity_hash, payload) VALUES (%s,%s,%s,%s) ON CONFLICT (integrity_hash) DO NOTHING",
                (
                    event.event_id,
                    event.artifact_id,
                    event.integrity_hash,
                    Jsonb(self._json_payload(event)),
                ),
            )
        return event

    def audits(self, artifact_id: str | None = None) -> tuple[dict, ...]:
        with self._connect() as conn, conn.cursor() as cur:
            if artifact_id:
                cur.execute(
                    "SELECT payload FROM design_planning.audit_events WHERE artifact_id=%s ORDER BY created_at, event_id",
                    (artifact_id,),
                )
            else:
                cur.execute(
                    "SELECT payload FROM design_planning.audit_events ORDER BY created_at, event_id"
                )
            return tuple(self._hydrate("audit", row[0]) for row in cur.fetchall())

    @staticmethod
    def _hydrate(kind: str, payload: dict[str, Any]) -> Any:
        from datetime import datetime

        value = dict(payload)
        for key in ("created_at", "freshness_deadline"):
            if isinstance(value.get(key), str):
                value[key] = datetime.fromisoformat(value[key])
        if kind == "product_request":
            value["requirements"] = tuple(
                Requirement(
                    **{
                        **item,
                        "status": RequirementStatus(item["status"]),
                        "provenance": tuple(
                            ProvenanceRef(**p) for p in item["provenance"]
                        ),
                    }
                )
                for item in value["requirements"]
            )
            value["lifecycle_state"] = LifecycleState(value["lifecycle_state"])
            return ProductRequest(**value)
        if kind == "context":
            value["items"] = tuple(ContextItem(**item) for item in value["items"])
            return ProjectContextSnapshot(**value)
        if kind == "evidence":
            value["ranked_results"] = tuple(
                EvidenceResult(**item) for item in value["ranked_results"]
            )
            value["coverage"] = {
                key: CoverageOutcome(item) for key, item in value["coverage"].items()
            }
            return DesignEvidencePackage(**value)
        if kind == "reasoning":
            value["lifecycle_state"] = LifecycleState(value["lifecycle_state"])
            return DesignReasoningRecord(**value)
        if kind == "conflict":
            from .models import ConflictType

            value["conflict_type"] = ConflictType(value["conflict_type"])
            value["required_decision_owner_role"] = ReviewRole(
                value["required_decision_owner_role"]
            )
            return MaterialConflictRecord(**value)
        if kind == "plan":
            value["lifecycle_state"] = LifecycleState(value["lifecycle_state"])
            value["required_review_roles"] = tuple(
                ReviewRole(item) for item in value["required_review_roles"]
            )
            return InterfacePlan(**value)
        if kind == "review":
            value["reviewer_role"] = ReviewRole(value["reviewer_role"])
            value["decision"] = ReviewDecision(value["decision"])
            return ReviewRecord(**value)
        if kind == "audit":
            return AuditEvent(**value)
        raise TypeError("UNSUPPORTED_ARTIFACT")

    @staticmethod
    def _identity(artifact: Any) -> str:
        for name in (
            "request_id",
            "snapshot_id",
            "evidence_package_id",
            "reasoning_record_id",
            "conflict_id",
            "interface_plan_id",
        ):
            if hasattr(artifact, name):
                return getattr(artifact, name)
        raise TypeError("UNSUPPORTED_ARTIFACT")

    @classmethod
    def _json_payload(cls, artifact: Any) -> Any:
        value = (
            asdict(artifact) if hasattr(artifact, "__dataclass_fields__") else artifact
        )
        if isinstance(value, dict):
            return {key: cls._json_payload(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._json_payload(item) for item in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        return value
