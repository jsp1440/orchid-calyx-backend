import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .normalizers import normalize_ontology_text


def ontology_database_url() -> str:
    value = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for ontology operations")
    return value


def _safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


class PostgresOntologyRepository:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or ontology_database_url()

    def _connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    @staticmethod
    def _audit(cur, actor: str, action: str, target_type: str, target_id: int, reason: str | None = None, previous: Any = None, resulting: Any = None) -> None:
        cur.execute("""INSERT INTO oc_ontology.ontology_audit_events
            (actor,action,target_type,target_id,previous_state,resulting_state,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s)""", (actor, action, target_type, target_id, Jsonb(_safe(previous)) if previous is not None else None, Jsonb(_safe(resulting)) if resulting is not None else None, reason))

    def create_registry(self, data: Mapping[str, Any], actor: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_ontology.ontology_registries
                (namespace,name,description,authority,source_uri,version,ontology_type,status,checksum,provenance,created_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'DRAFT',%s,%s,%s) RETURNING *""",
                (data["namespace"], data["name"], data.get("description"), data["authority"], str(data["source_uri"]) if data.get("source_uri") else None, data["version"], data["ontology_type"], data["checksum"].lower(), Jsonb(data["provenance"]), actor))
            result = cur.fetchone(); self._audit(cur, actor, "REGISTRY_CREATED", "REGISTRY", result["id"], resulting=result); return result

    def update_registry(self, registry_id: int, changes: Mapping[str, Any], actor: str, reason: str) -> dict[str, Any] | None:
        allowed = {key: changes[key] for key in ("name", "description", "authority", "source_uri", "provenance") if key in changes and changes[key] is not None}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.ontology_registries WHERE id=%s FOR UPDATE", (registry_id,)); previous = cur.fetchone()
            if previous is None: return None
            if previous["status"] != "DRAFT": raise ValueError("REGISTRY_IDENTITY_LOCKED")
            if not allowed: raise ValueError("NO_REGISTRY_CHANGES")
            sets = ",".join(f"{key}=%s" for key in allowed) + ",updated_at=NOW()"
            values = [Jsonb(value) if key == "provenance" else str(value) if key == "source_uri" else value for key, value in allowed.items()]
            cur.execute(f"UPDATE oc_ontology.ontology_registries SET {sets} WHERE id=%s RETURNING *", (*values, registry_id)); result = cur.fetchone()
            self._audit(cur, actor, "REGISTRY_UPDATED", "REGISTRY", registry_id, reason, previous, result); return result

    def set_registry_status(self, registry_id: int, status: str, actor: str, reason: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.ontology_registries WHERE id=%s FOR UPDATE", (registry_id,)); previous = cur.fetchone()
            if previous is None: return None
            allowed = {"DRAFT": {"ACTIVE"}, "ACTIVE": {"DEPRECATED"}, "DEPRECATED": {"RETIRED"}, "RETIRED": set()}
            if status not in allowed[previous["status"]]: raise ValueError("INVALID_REGISTRY_STATUS_TRANSITION")
            if status == "ACTIVE":
                cur.execute("SELECT COUNT(*) AS count FROM oc_ontology.ontology_terms WHERE registry_id=%s", (registry_id,))
                if cur.fetchone()["count"] == 0: raise ValueError("EMPTY_REGISTRY_CANNOT_ACTIVATE")
            cur.execute("UPDATE oc_ontology.ontology_registries SET status=%s,updated_at=NOW() WHERE id=%s RETURNING *", (status, registry_id)); result = cur.fetchone()
            self._audit(cur, actor, f"REGISTRY_{status}", "REGISTRY", registry_id, reason, previous, result); return result

    def list_registries(self) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.ontology_registries ORDER BY namespace,created_at DESC"); return list(cur.fetchall())

    def get_registry(self, registry_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.ontology_registries WHERE id=%s", (registry_id,)); registry = cur.fetchone()
            if registry is None: return None
            cur.execute("SELECT * FROM oc_ontology.ontology_terms WHERE registry_id=%s ORDER BY canonical_key", (registry_id,)); return {**registry, "terms": list(cur.fetchall())}

    def create_term(self, data: Mapping[str, Any], actor: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM oc_ontology.ontology_registries WHERE id=%s FOR UPDATE", (data["registry_id"],)); registry = cur.fetchone()
            if registry is None: raise LookupError("REGISTRY_NOT_FOUND")
            if registry["status"] != "DRAFT": raise ValueError("REGISTRY_NOT_DRAFT")
            cur.execute("""INSERT INTO oc_ontology.ontology_terms
                (registry_id,canonical_key,preferred_label,normalized_label,definition,term_type,parent_term_id,external_ids,metadata,status)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'DRAFT') RETURNING *""",
                (data["registry_id"], data["canonical_key"], data["preferred_label"], data.get("normalized_label") or str(data["preferred_label"]).casefold(), data.get("definition"), data["term_type"], data.get("parent_term_id"), Jsonb(data.get("external_ids", {})), Jsonb(data.get("metadata", {}))))
            result = cur.fetchone(); self._audit(cur, actor, "TERM_CREATED", "TERM", result["id"], resulting=result); return result

    def update_term(self, term_id: int, changes: Mapping[str, Any], actor: str, reason: str) -> dict[str, Any] | None:
        allowed = {key: changes[key] for key in ("preferred_label", "definition", "parent_term_id", "external_ids", "metadata", "replacement_term_id", "status") if key in changes and changes[key] is not None}
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT t.*,r.status AS registry_status FROM oc_ontology.ontology_terms t
                JOIN oc_ontology.ontology_registries r ON r.id=t.registry_id WHERE t.id=%s FOR UPDATE OF t""", (term_id,)); previous = cur.fetchone()
            if previous is None: return None
            if previous["registry_status"] != "DRAFT" and changes.get("status") != "DEPRECATED": raise ValueError("TERM_VERSION_LOCKED")
            if not allowed: raise ValueError("NO_TERM_CHANGES")
            if "preferred_label" in allowed: allowed["normalized_label"] = normalize_ontology_text(str(allowed["preferred_label"]), scientific_name=previous["term_type"] == "TAXON")
            sets = ",".join(f"{key}=%s" for key in allowed) + ",updated_at=NOW()"
            values = [Jsonb(value) if key in {"external_ids", "metadata"} else value for key, value in allowed.items()]
            cur.execute(f"UPDATE oc_ontology.ontology_terms SET {sets} WHERE id=%s RETURNING *", (*values, term_id)); result = cur.fetchone()
            self._audit(cur, actor, "TERM_UPDATED", "TERM", term_id, reason, previous, result); return result

    def get_term(self, term_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT t.*,r.namespace,r.version,r.status AS registry_status FROM oc_ontology.ontology_terms t
                JOIN oc_ontology.ontology_registries r ON r.id=t.registry_id WHERE t.id=%s""", (term_id,)); term = cur.fetchone()
            if term is None: return None
            cur.execute("SELECT * FROM oc_ontology.ontology_synonyms WHERE term_id=%s ORDER BY normalized_synonym", (term_id,)); return {**term, "synonyms": list(cur.fetchall())}

    def add_synonym(self, term_id: int, data: Mapping[str, Any], actor: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_ontology.ontology_synonyms(term_id,synonym,normalized_synonym,synonym_type,provenance)
                VALUES (%s,%s,%s,%s,%s) RETURNING *""", (term_id, data["synonym"], data["normalized_synonym"], data["synonym_type"], Jsonb(data["provenance"])))
            result = cur.fetchone(); self._audit(cur, actor, "SYNONYM_CREATED", "SYNONYM", result["id"], resulting=result); return result

    def search_terms(self, query: str, registry_id: int | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT t.id,t.registry_id,t.canonical_key,t.preferred_label,t.normalized_label,t.term_type,
                r.namespace,r.version,r.status AS registry_status,s.synonym,s.normalized_synonym
                FROM oc_ontology.ontology_terms t JOIN oc_ontology.ontology_registries r ON r.id=t.registry_id
                LEFT JOIN oc_ontology.ontology_synonyms s ON s.term_id=t.id
                WHERE r.status='ACTIVE' AND t.status IN ('DRAFT','ACTIVE') AND (%s::bigint IS NULL OR t.registry_id=%s::bigint)
                ORDER BY t.id,s.id LIMIT 2000""", (registry_id, registry_id)); return list(cur.fetchall())

    def hierarchy_ancestors(self, term_id: int) -> list[int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""WITH RECURSIVE ancestors AS (SELECT id,parent_term_id FROM oc_ontology.ontology_terms WHERE id=%s
                UNION ALL SELECT t.id,t.parent_term_id FROM oc_ontology.ontology_terms t JOIN ancestors a ON t.id=a.parent_term_id)
                SELECT id FROM ancestors""", (term_id,)); return [row["id"] for row in cur.fetchall()]

    def get_entity_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT c.*,e.name,e.entity_type,s.provenance AS session_provenance FROM oc_semantic.candidates c
                JOIN oc_semantic.candidate_entities e ON e.candidate_id=c.id JOIN oc_semantic.extraction_sessions s ON s.id=c.session_id
                WHERE c.id=%s AND c.kind='ENTITY'""", (candidate_id,)); return cur.fetchone()

    def get_session_entity_candidates(self, session_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT c.id,e.name FROM oc_semantic.candidates c JOIN oc_semantic.candidate_entities e ON e.candidate_id=c.id
                WHERE c.session_id=%s AND c.kind='ENTITY' AND NOT EXISTS
                (SELECT 1 FROM oc_ontology.candidate_resolutions r WHERE r.candidate_id=c.id AND r.status='ACCEPTED') ORDER BY c.id""", (session_id,)); return list(cur.fetchall())

    def create_resolution(self, candidate_id: int, suggestion: Mapping[str, Any], actor: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_ontology.candidate_resolutions
                (candidate_id,ontology_term_id,resolution_method,confidence,status,normalized_input,matched_label,ontology_namespace,ontology_version,explanation,provenance)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (candidate_id, suggestion.get("ontology_term_id"), suggestion["resolution_method"], suggestion["confidence"], suggestion["status"], suggestion["normalized_input"], suggestion.get("matched_label"), suggestion.get("ontology_namespace"), suggestion.get("ontology_version"), Jsonb(suggestion["explanation"]), Jsonb(suggestion["provenance"])))
            result = cur.fetchone(); self._audit(cur, actor, "RESOLUTION_PROPOSED", "RESOLUTION", result["id"], resulting=result); return result

    def list_resolutions(self, candidate_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.candidate_resolutions WHERE candidate_id=%s ORDER BY created_at,id", (candidate_id,)); return list(cur.fetchall())

    def decide_resolution(self, resolution_id: int, status: str, actor: str, reason: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.candidate_resolutions WHERE id=%s FOR UPDATE", (resolution_id,)); previous = cur.fetchone()
            if previous is None: return None
            if status == "ACCEPTED" and previous["ontology_term_id"] is None: raise ValueError("ACCEPTED_RESOLUTION_REQUIRES_TERM")
            cur.execute("""UPDATE oc_ontology.candidate_resolutions SET status=%s,resolved_by=%s,resolved_at=NOW(),updated_at=NOW()
                WHERE id=%s RETURNING *""", (status, actor, resolution_id)); result = cur.fetchone()
            self._audit(cur, actor, "RESOLUTION_DECIDED", "RESOLUTION", resolution_id, reason, previous, result); return result

    def evidence_source(self, evidence_object_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT e.*,s.document_id,d.sha256 AS document_sha256 FROM oc_semantic.evidence_objects e
                JOIN oc_semantic.extraction_sessions s ON s.id=e.session_id LEFT JOIN oc_intake.documents d ON d.id=s.document_id
                WHERE e.id=%s""", (evidence_object_id,)); return cur.fetchone()

    def create_evidence_entry(self, evidence_object_id: int, data: Mapping[str, Any], actor: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""INSERT INTO oc_ontology.evidence_registry
                (evidence_object_id,evidence_hash,source_document_id,source_sha256,validation_status,validation_details,validator_version,registered_by)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""", (evidence_object_id, data["evidence_hash"], data["source_document_id"], data["source_sha256"], data["validation_status"], Jsonb(data["validation_details"]), data["validator_version"], actor))
            result = cur.fetchone(); self._audit(cur, actor, "EVIDENCE_REGISTERED", "EVIDENCE_REGISTRY", result["id"], resulting=result); return result

    def get_evidence_entry(self, evidence_object_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.evidence_registry WHERE evidence_object_id=%s", (evidence_object_id,)); return cur.fetchone()

    def validate_evidence_entry(self, evidence_object_id: int, status: str, details: Mapping[str, Any], actor: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.evidence_registry WHERE evidence_object_id=%s FOR UPDATE", (evidence_object_id,)); previous = cur.fetchone()
            if previous is None: return None
            cur.execute("""UPDATE oc_ontology.evidence_registry SET validation_status=%s,validation_details=%s,last_validated_at=NOW()
                WHERE evidence_object_id=%s RETURNING *""", (status, Jsonb(details), evidence_object_id)); result = cur.fetchone()
            self._audit(cur, actor, "EVIDENCE_VALIDATED", "EVIDENCE_REGISTRY", result["id"], previous=previous, resulting=result); return result

    def readiness_context(self, candidate_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("""SELECT c.id,c.kind,c.review_status AS candidate_review_status,s.stage AS session_stage,s.provenance AS candidate_provenance,
                cr.id AS resolution_id,cr.status AS resolution_status,r.status AS registry_status,
                rel.evidence_id,er.validation_status AS evidence_validation_status,
                COALESCE(sr.ready_for_publication,FALSE) AS subject_ready,COALESCE(orx.ready_for_publication,FALSE) AS object_ready
                FROM oc_semantic.candidates c JOIN oc_semantic.extraction_sessions s ON s.id=c.session_id
                LEFT JOIN oc_ontology.candidate_resolutions cr ON cr.candidate_id=c.id AND cr.status='ACCEPTED'
                LEFT JOIN oc_ontology.ontology_terms t ON t.id=cr.ontology_term_id LEFT JOIN oc_ontology.ontology_registries r ON r.id=t.registry_id
                LEFT JOIN oc_semantic.candidate_relationships rel ON rel.candidate_id=c.id
                LEFT JOIN oc_ontology.evidence_registry er ON er.evidence_object_id=rel.evidence_id
                LEFT JOIN oc_ontology.publication_readiness sr ON sr.candidate_id=rel.subject_candidate_id AND sr.is_current
                LEFT JOIN oc_ontology.publication_readiness orx ON orx.candidate_id=rel.object_candidate_id AND orx.is_current
                WHERE c.id=%s""", (candidate_id,)); return cur.fetchone()

    def session_candidate_ids(self, session_id: int) -> list[int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM oc_semantic.candidates WHERE session_id=%s ORDER BY CASE kind WHEN 'ENTITY' THEN 0 ELSE 1 END,id", (session_id,)); return [row["id"] for row in cur.fetchall()]

    def save_readiness(self, candidate_id: int, result: Mapping[str, Any], actor: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE oc_ontology.publication_readiness SET is_current=FALSE WHERE candidate_id=%s AND is_current", (candidate_id,))
            cur.execute("""INSERT INTO oc_ontology.publication_readiness
                (candidate_id,evidence_complete,ontology_resolved,review_complete,provenance_complete,ready_for_publication,blockers,evaluated_by,evaluation_version,is_current)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,TRUE) RETURNING *""", (candidate_id, result["evidence_complete"], result["ontology_resolved"], result["review_complete"], result["provenance_complete"], result["ready_for_publication"], Jsonb(result["blockers"]), actor, result["evaluation_version"]))
            saved = cur.fetchone(); self._audit(cur, actor, "READINESS_EVALUATED", "READINESS", saved["id"], resulting=saved); return {**saved, "canonical_graph_mutated": False}

    def get_readiness(self, candidate_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_ontology.publication_readiness WHERE candidate_id=%s AND is_current", (candidate_id,)); return cur.fetchone()
