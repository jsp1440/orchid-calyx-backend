import json
import os
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import EntityDraft, EvidenceDraft, ExtractionStage, RelationshipDraft, validate_transition


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def semantic_database_url() -> str:
    value = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for semantic extraction")
    return value


class PostgresCandidateRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or semantic_database_url()

    def _connect(self):
        return psycopg.connect(self._database_url, row_factory=dict_row)

    @staticmethod
    def _audit(cur, session_id: int, actor: str, action: str, target_type: str, target_id: int | None, previous: Any = None, resulting: Any = None) -> None:
        cur.execute(
            """INSERT INTO oc_semantic.audit_events
            (session_id, actor, action, target_type, target_id, previous_state, resulting_state)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (session_id, actor, action, target_type, target_id, Jsonb(_json_safe(previous)) if previous is not None else None, Jsonb(_json_safe(resulting)) if resulting is not None else None),
        )

    def create_session(self, document_id: int, actor: str, provenance: dict[str, Any]) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """INSERT INTO oc_semantic.extraction_sessions(document_id, stage, created_by, provenance)
                VALUES (%s,'QUEUED',%s,%s) RETURNING *""",
                (document_id, actor, Jsonb(provenance)),
            )
            session = cur.fetchone()
            self._audit(cur, session["id"], actor, "SESSION_CREATED", "SESSION", session["id"], resulting=session)
            return session

    def get_session(self, session_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_semantic.extraction_sessions WHERE id=%s", (session_id,))
            return cur.fetchone()

    def transition_session(self, session_id: int, target: ExtractionStage, actor: str, error: str | None = None) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_semantic.extraction_sessions WHERE id=%s FOR UPDATE", (session_id,))
            previous = cur.fetchone()
            if previous is None:
                raise LookupError("SESSION_NOT_FOUND")
            validate_transition(ExtractionStage(previous["stage"]), target)
            cur.execute(
                """UPDATE oc_semantic.extraction_sessions SET stage=%s, error_message=%s,
                updated_at=NOW(), completed_at=CASE WHEN %s IN ('READY_FOR_REVIEW','FAILED') THEN NOW() ELSE completed_at END
                WHERE id=%s RETURNING *""",
                (target.value, error, target.value, session_id),
            )
            result = cur.fetchone()
            self._audit(cur, session_id, actor, "STAGE_TRANSITION", "SESSION", session_id, previous, result)
            return result

    def load_document(self, document_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id, extracted_text, sha256, provenance FROM oc_intake.documents WHERE id=%s", (document_id,))
            return cur.fetchone()

    def save_candidates(self, session_id: int, entities: Sequence[EntityDraft], relationships: Sequence[RelationshipDraft], evidence: Sequence[EvidenceDraft], actor: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            entity_ids: list[int] = []
            for entity in entities:
                cur.execute("INSERT INTO oc_semantic.candidates(session_id, kind, confidence) VALUES (%s,'ENTITY',%s) RETURNING id", (session_id, entity.confidence))
                candidate_id = cur.fetchone()["id"]
                entity_ids.append(candidate_id)
                cur.execute(
                    """INSERT INTO oc_semantic.candidate_entities(candidate_id, entity_type, name, normalized_name, start_offset, end_offset, attributes)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (candidate_id, entity.entity_type, entity.name, entity.normalized_name, entity.start_offset, entity.end_offset, Jsonb(entity.attributes)),
                )
                self._audit(cur, session_id, actor, "CANDIDATE_CREATED", "ENTITY", candidate_id, resulting={"name": entity.name})
            for relationship, proof in zip(relationships, evidence, strict=True):
                cur.execute(
                    """INSERT INTO oc_semantic.evidence_objects(session_id, evidence_type, exact_text, start_offset, end_offset, source_sha256, provenance)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
                    (session_id, proof.evidence_type, proof.exact_text, proof.start_offset, proof.end_offset, proof.source_sha256, Jsonb(proof.provenance)),
                )
                evidence_id = cur.fetchone()["id"]
                cur.execute("INSERT INTO oc_semantic.candidates(session_id, kind, confidence) VALUES (%s,'RELATIONSHIP',%s) RETURNING id", (session_id, relationship.confidence))
                candidate_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO oc_semantic.candidate_relationships(candidate_id, subject_candidate_id, predicate, object_candidate_id, evidence_id)
                    VALUES (%s,%s,%s,%s,%s)""",
                    (candidate_id, entity_ids[relationship.subject_index], relationship.predicate, entity_ids[relationship.object_index], evidence_id),
                )
                self._audit(cur, session_id, actor, "CANDIDATE_CREATED", "RELATIONSHIP", candidate_id, resulting={"predicate": relationship.predicate, "evidence_id": evidence_id})

    def get_evidence(self, evidence_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_semantic.evidence_objects WHERE id=%s", (evidence_id,))
            return cur.fetchone()

    def get_candidates(self, session_id: int) -> dict[str, Any] | None:
        if self.get_session(session_id) is None:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT c.*, e.entity_type, e.name, e.normalized_name, e.start_offset, e.end_offset, e.attributes
                FROM oc_semantic.candidates c JOIN oc_semantic.candidate_entities e ON e.candidate_id=c.id
                WHERE c.session_id=%s ORDER BY c.id""", (session_id,))
            entities = list(cur.fetchall())
            cur.execute("""SELECT c.*, r.subject_candidate_id, r.predicate, r.object_candidate_id, r.evidence_id
                FROM oc_semantic.candidates c JOIN oc_semantic.candidate_relationships r ON r.candidate_id=c.id
                WHERE c.session_id=%s ORDER BY c.id""", (session_id,))
            return {"session_id": session_id, "entities": entities, "relationships": list(cur.fetchall()), "canonical_graph_mutated": False}

    def update_candidate(self, candidate_id: int, changes: dict[str, Any], actor: str, reason: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_semantic.candidates WHERE id=%s FOR UPDATE", (candidate_id,))
            previous = cur.fetchone()
            if previous is None:
                return None
            if previous["kind"] == "ENTITY" and "predicate" in changes:
                raise ValueError("INVALID_ENTITY_CHANGE")
            if previous["kind"] == "RELATIONSHIP" and any(key in changes for key in ("name", "entity_type")):
                raise ValueError("INVALID_RELATIONSHIP_CHANGE")
            if "confidence" in changes or "review_status" in changes:
                cur.execute("UPDATE oc_semantic.candidates SET confidence=COALESCE(%s,confidence), review_status=COALESCE(%s,review_status), version=version+1, updated_at=NOW() WHERE id=%s", (changes.get("confidence"), changes.get("review_status"), candidate_id))
            if previous["kind"] == "ENTITY" and any(key in changes for key in ("name", "entity_type")):
                cur.execute("UPDATE oc_semantic.candidate_entities SET name=COALESCE(%s,name), normalized_name=COALESCE(LOWER(%s),normalized_name), entity_type=COALESCE(%s,entity_type) WHERE candidate_id=%s", (changes.get("name"), changes.get("name"), changes.get("entity_type"), candidate_id))
            if previous["kind"] == "RELATIONSHIP" and "predicate" in changes:
                cur.execute("UPDATE oc_semantic.candidate_relationships SET predicate=%s WHERE candidate_id=%s", (changes["predicate"], candidate_id))
            cur.execute("SELECT * FROM oc_semantic.candidates WHERE id=%s", (candidate_id,))
            result = cur.fetchone()
            self._audit(cur, previous["session_id"], actor, "CANDIDATE_MODIFIED", previous["kind"], candidate_id, previous, {**result, "reason": reason, "changes": changes})
            return {**result, **changes}


class PostgresReviewRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self._database_url = database_url or semantic_database_url()

    def record_review(self, session_id: int, candidate_ids: Sequence[int], decision: str, actor: str, notes: str | None) -> dict[str, Any]:
        status = {"ACCEPT": "ACCEPTED", "REJECT": "REJECTED", "NEEDS_REVISION": "PENDING"}[decision]
        with psycopg.connect(self._database_url, row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM oc_semantic.extraction_sessions WHERE id=%s FOR UPDATE", (session_id,))
            if cur.fetchone() is None:
                raise LookupError("SESSION_NOT_FOUND")
            cur.execute("SELECT id FROM oc_semantic.candidates WHERE session_id=%s AND id=ANY(%s) FOR UPDATE", (session_id, list(candidate_ids)))
            found = {row["id"] for row in cur.fetchall()}
            if found != set(candidate_ids):
                raise ValueError("CANDIDATE_SESSION_MISMATCH")
            cur.execute("INSERT INTO oc_semantic.reviews(session_id, decision, actor, notes, candidate_ids) VALUES (%s,%s,%s,%s,%s) RETURNING *", (session_id, decision, actor, notes, list(candidate_ids)))
            review = cur.fetchone()
            cur.execute("UPDATE oc_semantic.candidates SET review_status=%s, version=version+1, updated_at=NOW() WHERE id=ANY(%s)", (status, list(candidate_ids)))
            cur.execute("""INSERT INTO oc_semantic.audit_events(session_id, actor, action, target_type, target_id, resulting_state)
                VALUES (%s,%s,'REVIEW_RECORDED','REVIEW',%s,%s)""", (session_id, actor, review["id"], Jsonb({"decision": decision, "candidate_ids": list(candidate_ids), "canonical_graph_mutated": False})))
            return {**review, "canonical_graph_mutated": False}
