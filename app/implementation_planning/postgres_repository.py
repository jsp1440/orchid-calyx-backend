from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from enum import Enum
from typing import Any

from psycopg.types.json import Jsonb

from .models import (
    ApiContractSpecification,
    ArtifactReference,
    AuditEvent,
    ComponentSpecification,
    ConflictImpact,
    CrossCuttingContract,
    DataContractSpecification,
    ImplementationPhase,
    ImplementationSpecificationSet,
    NavigationSpecification,
    PageSpecification,
    ReadinessRecord,
    ReadinessStatus,
    SpecificationLifecycle,
    SpecificationReview,
    StateSpecification,
)


class PostgresImplementationPlanningRepository:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url)

    def append(self, artifact: ImplementationSpecificationSet):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (artifact.logical_key,),
            )
            cur.execute(
                "SELECT payload FROM implementation_planning.specification_sets WHERE integrity_hash=%s",
                (artifact.integrity_hash,),
            )
            if row := cur.fetchone():
                return self._hydrate(row[0])
            cur.execute(
                "INSERT INTO implementation_planning.specification_sets (specification_id,logical_key,version,integrity_hash,lifecycle_state,payload) VALUES (%s,%s,%s,%s,%s,%s)",
                (
                    artifact.specification_id,
                    artifact.logical_key,
                    artifact.version,
                    artifact.integrity_hash,
                    artifact.lifecycle_state.value,
                    Jsonb(self._json(artifact)),
                ),
            )
            for kind, values in self._children(artifact):
                for value in values:
                    identity = self._child_id(value)
                    cur.execute(
                        "INSERT INTO implementation_planning.artifact_records (specification_id,artifact_type,artifact_id,payload) VALUES (%s,%s,%s,%s)",
                        (
                            artifact.specification_id,
                            kind,
                            identity,
                            Jsonb(self._json(value)),
                        ),
                    )
        return artifact

    def get(self, specification_id: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM implementation_planning.specification_sets WHERE specification_id=%s",
                (specification_id,),
            )
            row = cur.fetchone()
        return self._hydrate(row[0]) if row else None

    def history(self, logical_key: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM implementation_planning.specification_sets WHERE logical_key=%s ORDER BY version",
                (logical_key,),
            )
            return tuple(self._hydrate(row[0]) for row in cur.fetchall())

    def append_review(self, review: SpecificationReview):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO implementation_planning.reviews (review_id,specification_id,integrity_hash,payload) VALUES (%s,%s,%s,%s) ON CONFLICT (integrity_hash) DO NOTHING",
                (
                    review.review_id,
                    review.specification_id,
                    review.integrity_hash,
                    Jsonb(self._json(review)),
                ),
            )
        return review

    def reviews(self, specification_id: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM implementation_planning.reviews WHERE specification_id=%s ORDER BY created_at,review_id",
                (specification_id,),
            )
            return tuple(row[0] for row in cur.fetchall())

    def append_audit(self, event: AuditEvent):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO implementation_planning.audit_events (event_id,specification_id,integrity_hash,payload) VALUES (%s,%s,%s,%s) ON CONFLICT (integrity_hash) DO NOTHING",
                (
                    event.event_id,
                    event.specification_id,
                    event.integrity_hash,
                    Jsonb(self._json(event)),
                ),
            )
        return event

    def audits(self, specification_id: str | None = None):
        with self._connect() as conn, conn.cursor() as cur:
            if specification_id:
                cur.execute(
                    "SELECT payload FROM implementation_planning.audit_events WHERE specification_id=%s ORDER BY created_at,event_id",
                    (specification_id,),
                )
            else:
                cur.execute(
                    "SELECT payload FROM implementation_planning.audit_events ORDER BY created_at,event_id"
                )
            return tuple(row[0] for row in cur.fetchall())

    @staticmethod
    def _children(value):
        return (
            ("PAGE", value.pages),
            ("COMPONENT", value.components),
            ("NAVIGATION", (value.navigation,)),
            ("STATE", value.states),
            ("API_CONTRACT", value.api_contracts),
            ("DATA_CONTRACT", value.data_contracts),
            ("CROSS_CUTTING", value.cross_cutting_contracts),
            ("CONFLICT_IMPACT", value.conflict_impacts),
            ("SEQUENCE", value.sequence),
            ("READINESS", value.readiness),
            ("SOURCE_REFERENCE", value.source_artifacts),
        )

    @staticmethod
    def _child_id(value):
        for key in (
            "page_id",
            "component_id",
            "navigation_id",
            "state_id",
            "contract_id",
            "conflict_id",
            "phase_id",
            "readiness_id",
            "artifact_id",
        ):
            if hasattr(value, key):
                return getattr(value, key)
        raise TypeError("UNSUPPORTED_IMPLEMENTATION_ARTIFACT")

    @classmethod
    def _json(cls, value: Any):
        if hasattr(value, "__dataclass_fields__"):
            value = asdict(value)
        if isinstance(value, dict):
            return {k: cls._json(v) for k, v in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._json(v) for v in value]
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, Enum):
            return value.value
        return value

    @staticmethod
    def _hydrate(payload):
        value = dict(payload)
        value["created_at"] = datetime.fromisoformat(value["created_at"])
        value["source_artifacts"] = tuple(
            ArtifactReference(**x) for x in value["source_artifacts"]
        )
        value["pages"] = tuple(
            PageSpecification(
                **{**x, "readiness_status": ReadinessStatus(x["readiness_status"])}
            )
            for x in value["pages"]
        )
        value["components"] = tuple(
            ComponentSpecification(
                **{**x, "readiness_status": ReadinessStatus(x["readiness_status"])}
            )
            for x in value["components"]
        )
        value["navigation"] = NavigationSpecification(**value["navigation"])
        value["states"] = tuple(StateSpecification(**x) for x in value["states"])
        value["api_contracts"] = tuple(
            ApiContractSpecification(
                **{**x, "readiness_status": ReadinessStatus(x["readiness_status"])}
            )
            for x in value["api_contracts"]
        )
        value["data_contracts"] = tuple(
            DataContractSpecification(
                **{**x, "readiness_status": ReadinessStatus(x["readiness_status"])}
            )
            for x in value["data_contracts"]
        )
        value["cross_cutting_contracts"] = tuple(
            CrossCuttingContract(**x) for x in value["cross_cutting_contracts"]
        )
        value["conflict_impacts"] = tuple(
            ConflictImpact(**x) for x in value["conflict_impacts"]
        )
        value["sequence"] = tuple(
            ImplementationPhase(
                **{**x, "readiness_status": ReadinessStatus(x["readiness_status"])}
            )
            for x in value["sequence"]
        )
        value["readiness"] = tuple(
            ReadinessRecord(**{**x, "status": ReadinessStatus(x["status"])})
            for x in value["readiness"]
        )
        value["lifecycle_state"] = SpecificationLifecycle(value["lifecycle_state"])
        return ImplementationSpecificationSet(**value)
