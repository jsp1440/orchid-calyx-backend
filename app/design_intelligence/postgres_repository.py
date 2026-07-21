from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import (
    DesignDocument,
    DesignDomain,
    DesignKnowledgeType,
    DesignProvenance,
    DesignReviewDecision,
    PublicationStatus,
    ReviewState,
)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class PostgresDesignCorpusRepository:
    """PostgreSQL-authoritative append-only BUILD-089A corpus repository."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL_REQUIRED")
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(
            self.database_url, row_factory=dict_row, connect_timeout=10
        )

    @property
    def documents(self) -> list[DesignDocument]:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                """SELECT d.*,
                COALESCE((SELECT jsonb_agg(DISTINCT c.domain) FROM oc_design_intelligence.classifications c WHERE c.document_id=d.document_id),'[]') domains,
                COALESCE((SELECT jsonb_agg(DISTINCT c.knowledge_type) FROM oc_design_intelligence.classifications c WHERE c.document_id=d.document_id),'[]') knowledge_types,
                COALESCE((SELECT max(c.confidence) FROM oc_design_intelligence.classifications c WHERE c.document_id=d.document_id),0) classification_confidence,
                COALESCE((SELECT max(c.classifier_version) FROM oc_design_intelligence.classifications c WHERE c.document_id=d.document_id),'') classification_version,
                COALESCE((SELECT jsonb_agg(t.topic) FROM oc_design_intelligence.topics t WHERE t.document_id=d.document_id),'[]') topics,
                (SELECT p.source_system FROM oc_design_intelligence.document_provenance p WHERE p.document_id=d.document_id ORDER BY provenance_id LIMIT 1) source_system,
                (SELECT p.source_id FROM oc_design_intelligence.document_provenance p WHERE p.document_id=d.document_id ORDER BY provenance_id LIMIT 1) source_id,
                COALESCE((SELECT jsonb_agg(p.anchor_id ORDER BY p.anchor_id) FROM oc_design_intelligence.document_provenance p WHERE p.document_id=d.document_id),'[]') anchor_ids,
                COALESCE((SELECT p.evidence_link_ids FROM oc_design_intelligence.document_provenance p WHERE p.document_id=d.document_id ORDER BY provenance_id LIMIT 1),'[]') evidence_link_ids,
                COALESCE((SELECT r.authorized_text FROM oc_design_intelligence.retrieval_documents r WHERE r.document_id=d.document_id ORDER BY retrieval_document_id LIMIT 1),'') content
                FROM oc_design_intelligence.documents d ORDER BY d.logical_key,d.version"""
            )
            return [self._document(row) for row in cur.fetchall()]

    @staticmethod
    def _document(row) -> DesignDocument:
        return DesignDocument(
            document_id=row["document_id"],
            logical_key=row["logical_key"],
            version=row["version"],
            title=row["title"],
            content=row["content"],
            document_type=row["document_type"],
            authors=tuple(row["authors"]),
            publication_date=row["publication_date"],
            license_metadata=dict(row["license_metadata"]),
            provenance=DesignProvenance(
                source_system=row["source_system"],
                source_id=row["source_id"],
                revision_id=row["revision_id"],
                extraction_run_id=row["extraction_run_id"],
                anchor_ids=tuple(row["anchor_ids"]),
                content_hash=row["content_hash"],
                evidence_link_ids=tuple(row["evidence_link_ids"]),
            ),
            domains=tuple(sorted((DesignDomain(item) for item in row["domains"]), key=str)),
            knowledge_types=tuple(
                sorted(
                    (DesignKnowledgeType(item) for item in row["knowledge_types"]),
                    key=str,
                )
            ),
            topics=tuple(sorted(row["topics"])),
            classification_confidence=float(row["classification_confidence"]),
            classification_version=row["classification_version"],
            source_metadata=dict(row["source_metadata"]),
            created_at=row["created_at"],
        )

    def latest(self, logical_key: str) -> DesignDocument | None:
        matches = [item for item in self.documents if item.logical_key == logical_key]
        return max(matches, key=lambda item: item.version) if matches else None

    def document(self, document_id: int) -> DesignDocument | None:
        return next((item for item in self.documents if item.document_id == document_id), None)

    def append_document(self, document: DesignDocument) -> DesignDocument:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,89))",
                (f"design:{document.logical_key}",),
            )
            cur.execute(
                "SELECT COALESCE(max(version),0)+1 expected FROM oc_design_intelligence.documents WHERE logical_key=%s",
                (document.logical_key,),
            )
            if cur.fetchone()["expected"] != document.version:
                raise ValueError("DESIGN_DOCUMENT_VERSION_NOT_MONOTONIC")
            cur.execute(
                """INSERT INTO oc_design_intelligence.documents(
                logical_key,version,title,document_type,authors,publication_date,license_metadata,
                source_metadata,revision_id,extraction_run_id,content_hash) VALUES(
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING document_id""",
                (
                    document.logical_key,
                    document.version,
                    document.title,
                    document.document_type,
                    Jsonb(list(document.authors)),
                    document.publication_date,
                    Jsonb(document.license_metadata),
                    Jsonb(document.source_metadata),
                    document.provenance.revision_id,
                    document.provenance.extraction_run_id,
                    document.provenance.content_hash,
                ),
            )
            document_id = cur.fetchone()["document_id"]
            for domain in document.domains:
                for knowledge_type in document.knowledge_types:
                    identity = {
                        "document": document_id,
                        "domain": domain,
                        "type": knowledge_type,
                        "version": document.classification_version,
                    }
                    cur.execute(
                        "INSERT INTO oc_design_intelligence.classifications(document_id,domain,knowledge_type,confidence,classifier_version,evidence,fingerprint) VALUES(%s,%s,%s,%s,%s,%s,%s)",
                        (
                            document_id,
                            domain.value,
                            knowledge_type.value,
                            document.classification_confidence,
                            document.classification_version,
                            Jsonb(document.source_metadata.get("classification_evidence", [])),
                            digest(identity),
                        ),
                    )
            for topic in document.topics:
                cur.execute(
                    "INSERT INTO oc_design_intelligence.topics(document_id,topic,confidence) VALUES(%s,%s,%s)",
                    (document_id, topic, document.classification_confidence),
                )
            for anchor_id in document.provenance.anchor_ids:
                identity = {"document": document_id, "anchor": anchor_id}
                cur.execute(
                    "INSERT INTO oc_design_intelligence.document_provenance(document_id,source_system,source_id,revision_id,extraction_run_id,anchor_id,evidence_link_ids,fingerprint) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
                    (
                        document_id,
                        document.provenance.source_system,
                        document.provenance.source_id,
                        document.provenance.revision_id,
                        document.provenance.extraction_run_id,
                        anchor_id,
                        Jsonb(list(document.provenance.evidence_link_ids)),
                        digest(identity),
                    ),
                )
            display_policy = document.license_metadata.get(
                "display", "UNKNOWN_REQUIRES_REVIEW"
            )
            if display_policy not in {"FULL_TEXT_ALLOWED", "INTERNAL_RESEARCH_ONLY"}:
                raise ValueError("DESIGN_RETRIEVAL_LICENSE_NOT_AUTHORIZED")
            cur.execute(
                "INSERT INTO oc_design_intelligence.retrieval_documents(document_id,anchor_id,authorized_text,display_policy,confidence,fingerprint) VALUES(%s,%s,%s,%s,%s,%s)",
                (
                    document_id,
                    document.provenance.anchor_ids[0],
                    document.content,
                    display_policy,
                    document.classification_confidence,
                    digest({"document": document_id, "content": document.provenance.content_hash}),
                ),
            )
            self._audit(cur, document_id, "DOCUMENT_VERSION_APPENDED", "corpus-import", {"version": document.version})
        return self.document(document_id)

    def add_review(self, document_id: int, decision: DesignReviewDecision):
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "INSERT INTO oc_design_intelligence.review_events(document_id,state,actor,rationale,evidence) VALUES(%s,%s,%s,%s,%s) RETURNING *",
                (document_id, decision.state.value, decision.actor, decision.rationale, Jsonb(decision.evidence)),
            )
            result = dict(cur.fetchone())
            self._audit(cur, document_id, "REVIEW_DECISION_APPENDED", decision.actor, {"state": decision.state})
            return result

    def review_state(self, document_id: int) -> ReviewState:
        with self._connect() as con, con.cursor() as cur:
            cur.execute("SELECT state FROM oc_design_intelligence.review_events WHERE document_id=%s ORDER BY review_event_id DESC LIMIT 1", (document_id,))
            row = cur.fetchone()
            return ReviewState(row["state"]) if row else ReviewState.PENDING

    def publish(self, document_id, status, actor, rationale):
        current = self.publication_status(document_id)
        allowed = {PublicationStatus.DRAFT: {PublicationStatus.PUBLISHED}, PublicationStatus.PUBLISHED: {PublicationStatus.RETIRED, PublicationStatus.RETRACTED}}
        if status not in allowed.get(current, set()):
            raise ValueError("INVALID_DESIGN_PUBLICATION_TRANSITION")
        if status is PublicationStatus.PUBLISHED and self.review_state(document_id) is not ReviewState.APPROVED:
            raise ValueError("DESIGN_REVIEW_APPROVAL_REQUIRED")
        with self._connect() as con, con.cursor() as cur:
            cur.execute("INSERT INTO oc_design_intelligence.publication_events(document_id,status,actor,rationale) VALUES(%s,%s,%s,%s) RETURNING *", (document_id, status.value, actor, rationale))
            result = dict(cur.fetchone())
            self._audit(cur, document_id, "PUBLICATION_STATUS_APPENDED", actor, {"status": status})
            return result

    def publication_status(self, document_id: int) -> PublicationStatus:
        with self._connect() as con, con.cursor() as cur:
            cur.execute("SELECT status FROM oc_design_intelligence.publication_events WHERE document_id=%s ORDER BY publication_event_id DESC LIMIT 1", (document_id,))
            row = cur.fetchone()
            return PublicationStatus(row["status"]) if row else PublicationStatus.DRAFT

    def published_latest(self) -> list[DesignDocument]:
        documents = self.documents
        latest = {item.logical_key: item for item in documents}
        return [item for item in latest.values() if self.publication_status(item.document_id) is PublicationStatus.PUBLISHED]

    @staticmethod
    def _audit(cur, document_id, event_type, actor, details):
        cur.execute("INSERT INTO oc_design_intelligence.audit_events(document_id,event_type,actor,details) VALUES(%s,%s,%s,%s)", (document_id, event_type, actor, Jsonb(details)))
