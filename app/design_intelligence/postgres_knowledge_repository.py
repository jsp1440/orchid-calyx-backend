from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .knowledge import (
    DesignRelationship,
    EducationalClassification,
    RelationshipType,
    SemanticDesignDomain,
    SemanticUnit,
    SemanticUnitType,
    SourceLocation,
)


class PostgresDesignKnowledgeRepository:
    """PostgreSQL-authoritative append-only BUILD-089B reasoning repository."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL_REQUIRED")
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(
            self.database_url, row_factory=dict_row, connect_timeout=10
        )

    @property
    def units(self) -> list[SemanticUnit]:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_design_intelligence.semantic_units ORDER BY document_id,ordinal"
            )
            return [self._unit(row) for row in cur.fetchall()]

    @property
    def relationships(self) -> list[DesignRelationship]:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_design_intelligence.semantic_relationships ORDER BY relationship_id"
            )
            return [
                DesignRelationship(
                    relationship_id=row["relationship_id"],
                    source_unit_id=row["source_unit_id"],
                    target_unit_id=row["target_unit_id"],
                    relationship_type=RelationshipType(row["relationship_type"]),
                    confidence=float(row["confidence"]),
                    rationale=row["rationale"],
                    provenance=dict(row["provenance"]),
                    generator_version=row["generator_version"],
                )
                for row in cur.fetchall()
            ]

    @staticmethod
    def _unit(row) -> SemanticUnit:
        location = dict(row["source_location"])
        return SemanticUnit(
            unit_id=row["unit_id"],
            document_id=row["document_id"],
            document_version=row["document_version"],
            ordinal=row["ordinal"],
            unit_type=SemanticUnitType(row["unit_type"]),
            text=row["authorized_text"],
            parent_unit_id=row["parent_unit_id"],
            source_location=SourceLocation(
                format=location["format"],
                start=location["start"],
                end=location["end"],
                locator=location["locator"],
                content_hash=location["content_hash"],
            ),
            domains=tuple(SemanticDesignDomain(value) for value in row["domains"]),
            educational_classifications=tuple(
                EducationalClassification(value)
                for value in row["educational_classifications"]
            ),
            knowledge_types=tuple(row["knowledge_types"]),
            classification_confidence=float(row["classification_confidence"]),
            classification_evidence=tuple(row["classification_evidence"]),
            classification_version=row["classification_version"],
            embedding=tuple(float(value) for value in row["embedding"]),
            embedding_metadata=dict(row["embedding_metadata"]),
        )

    def append_units(self, units: Iterable[SemanticUnit]) -> None:
        with self._connect() as con, con.cursor() as cur:
            for unit in units:
                cur.execute(
                    """INSERT INTO oc_design_intelligence.semantic_units(
                    unit_id,document_id,document_version,ordinal,parent_unit_id,unit_type,authorized_text,
                    source_location,domains,educational_classifications,knowledge_types,classification_confidence,
                    classification_evidence,classification_version,embedding,embedding_metadata)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(unit_id) DO NOTHING""",
                    (
                        unit.unit_id,
                        unit.document_id,
                        unit.document_version,
                        unit.ordinal,
                        unit.parent_unit_id,
                        unit.unit_type.value,
                        unit.text,
                        Jsonb(asdict(unit.source_location)),
                        Jsonb([value.value for value in unit.domains]),
                        Jsonb(
                            [value.value for value in unit.educational_classifications]
                        ),
                        Jsonb(list(unit.knowledge_types)),
                        unit.classification_confidence,
                        Jsonb(list(unit.classification_evidence)),
                        unit.classification_version,
                        Jsonb(list(unit.embedding)),
                        Jsonb(unit.embedding_metadata),
                    ),
                )
                if cur.rowcount:
                    cur.execute(
                        "INSERT INTO oc_design_intelligence.semantic_audit_events(unit_id,event_type,details) VALUES(%s,'SEMANTIC_UNIT_APPENDED',%s)",
                        (
                            unit.unit_id,
                            Jsonb(
                                {
                                    "document_id": unit.document_id,
                                    "ordinal": unit.ordinal,
                                }
                            ),
                        ),
                    )

    def append_relationships(self, values: Iterable[DesignRelationship]) -> None:
        with self._connect() as con, con.cursor() as cur:
            for value in values:
                cur.execute(
                    """INSERT INTO oc_design_intelligence.semantic_relationships(
                    relationship_id,source_unit_id,target_unit_id,relationship_type,confidence,rationale,provenance,generator_version)
                    VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(relationship_id) DO NOTHING""",
                    (
                        value.relationship_id,
                        value.source_unit_id,
                        value.target_unit_id,
                        value.relationship_type.value,
                        value.confidence,
                        value.rationale,
                        Jsonb(value.provenance),
                        value.generator_version,
                    ),
                )
                if cur.rowcount:
                    cur.execute(
                        "INSERT INTO oc_design_intelligence.semantic_audit_events(relationship_id,event_type,details) VALUES(%s,'DESIGN_RELATIONSHIP_APPENDED',%s)",
                        (
                            value.relationship_id,
                            Jsonb({"type": value.relationship_type.value}),
                        ),
                    )
