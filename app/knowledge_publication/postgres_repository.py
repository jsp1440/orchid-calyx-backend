from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import CandidateRequest, PublicationPolicy
from .policy import PublicationAuthority


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


class PostgresPublicationRegistry:
    """Production registry. All writes are append-only, transactional and audited."""

    def __init__(self, database_url: str) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL_REQUIRED")
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(
            self.database_url, row_factory=dict_row, connect_timeout=10
        )

    def create_policy(self, policy: PublicationPolicy, actor: str) -> dict[str, Any]:
        payload = {
            "policy_id": policy.policy_id,
            "version": policy.version,
            "name": policy.name,
            "rules": policy.rules(),
            "provenance": policy.provenance,
            "approval_metadata": policy.approval_metadata,
        }
        fingerprint = _fingerprint(payload)
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,88))",
                (f"policy:{policy.policy_id}:{policy.version}",),
            )
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.policy_versions WHERE fingerprint=%s",
                (fingerprint,),
            )
            if row := cur.fetchone():
                return dict(row)
            cur.execute(
                "INSERT INTO oc_knowledge_publication.policy_versions(policy_id,version,name,rules,provenance,approval_metadata,fingerprint) VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    policy.policy_id,
                    policy.version,
                    policy.name,
                    Jsonb(policy.rules()),
                    Jsonb(policy.provenance),
                    Jsonb(policy.approval_metadata),
                    fingerprint,
                ),
            )
            row = dict(cur.fetchone())
            cur.execute(
                "INSERT INTO oc_knowledge_publication.policy_lifecycle_events(policy_version_id,state,actor) VALUES(%s,'DRAFT',%s)",
                (row["policy_version_id"], actor),
            )
            self._event(
                cur,
                "POLICY",
                row["policy_version_id"],
                "POLICY_DRAFTED",
                actor,
                payload,
            )
            return row

    def activate_policy(self, policy_id: str, version: int, actor: str) -> None:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,88))",
                (f"policy-active:{policy_id}",),
            )
            cur.execute(
                "SELECT policy_version_id FROM oc_knowledge_publication.policy_versions WHERE policy_id=%s AND version=%s",
                (policy_id, version),
            )
            row = cur.fetchone()
            if not row:
                raise ValueError("POLICY_VERSION_NOT_FOUND")
            cur.execute(
                "SELECT 1 FROM oc_knowledge_publication.policy_lifecycle_events WHERE policy_version_id=%s AND state='ACTIVE'",
                (row["policy_version_id"],),
            )
            if cur.fetchone():
                return
            cur.execute(
                "SELECT DISTINCT ON (p.policy_version_id) p.policy_version_id,e.state FROM oc_knowledge_publication.policy_versions p JOIN oc_knowledge_publication.policy_lifecycle_events e USING(policy_version_id) WHERE p.policy_id=%s ORDER BY p.policy_version_id,e.policy_event_id DESC",
                (policy_id,),
            )
            for active in cur.fetchall():
                if (
                    active["state"] == "ACTIVE"
                    and active["policy_version_id"] != row["policy_version_id"]
                ):
                    cur.execute(
                        "INSERT INTO oc_knowledge_publication.policy_lifecycle_events(policy_version_id,state,actor) VALUES(%s,'RETIRED',%s)",
                        (active["policy_version_id"], actor),
                    )
            cur.execute(
                "INSERT INTO oc_knowledge_publication.policy_lifecycle_events(policy_version_id,state,actor) VALUES(%s,'ACTIVE',%s)",
                (row["policy_version_id"], actor),
            )
            self._event(
                cur,
                "POLICY",
                row["policy_version_id"],
                "POLICY_ACTIVATED",
                actor,
                {"version": version},
            )

    def create_candidate(self, request: CandidateRequest) -> dict[str, Any]:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,88))",
                (f"candidate:{request.idempotency_key}",),
            )
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.publication_candidates WHERE idempotency_key=%s",
                (request.idempotency_key,),
            )
            if row := cur.fetchone():
                return dict(row)
            assertion = self._assertion(
                cur, request.assertion_id, request.assertion_version
            )
            policy = self._active_policy(cur, request.policy_id, request.policy_version)
            routing_id = assertion.get("routing_decision_id")
            cur.execute(
                "SELECT * FROM oc_scientific_interpretation.routing_decisions WHERE routing_decision_id=%s",
                (routing_id,),
            )
            routing_row = cur.fetchone()
            if not routing_row:
                raise ValueError("TRUSTED_ELIGIBILITY_DECISION_NOT_FOUND")
            routing = dict(routing_row["payload"])
            routing.update(
                {
                    "routing_decision_id": routing_row["routing_decision_id"],
                    "path": routing_row["path"],
                }
            )
            provenance = self._provenance(cur, assertion)
            trusted = {
                "assertion": assertion,
                "eligibility_decision": routing,
                "provenance_roots": provenance,
            }
            identity = {
                "assertion_id": request.assertion_id,
                "assertion_version": request.assertion_version,
                "policy_id": request.policy_id,
                "policy_version": request.policy_version,
                "requested_pathway": request.requested_pathway.value,
                "trusted": trusted,
            }
            scope = assertion.get("scientific_scope", {})
            statement = assertion.get("normalized_statement", {})
            cur.execute(
                "INSERT INTO oc_knowledge_publication.publication_candidates(assertion_id,assertion_version,eligibility_decision_id,eligibility_decision_version,policy_version_id,requested_pathway,idempotency_key,fingerprint,correlation_id,created_by,assertion_type,scientific_domain,taxonomy_concept_id,taxonomy_version,scientific_scope,qualifiers,supporting_evidence_refs,conflicting_evidence_refs,provenance_root_refs,immutable_metadata,trusted_snapshot) VALUES(%s,%s,%s,1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    request.assertion_id,
                    request.assertion_version,
                    routing_id,
                    policy["policy_version_id"],
                    request.requested_pathway.value,
                    request.idempotency_key,
                    _fingerprint(identity),
                    request.correlation_id,
                    request.actor,
                    statement.get("assertion_type") or "UNCLASSIFIED",
                    scope.get("scientific_domain") or "UNCLASSIFIED",
                    scope.get("taxonomy_concept_id"),
                    scope.get("taxonomy_version"),
                    Jsonb(scope),
                    Jsonb(assertion.get("qualifiers", {})),
                    Jsonb(assertion.get("supporting_interpretation_ids", [])),
                    Jsonb(assertion.get("conflicting_interpretation_ids", [])),
                    Jsonb(provenance),
                    Jsonb({"source": "BUILD-087_TRUSTED_REGISTRY"}),
                    Jsonb(trusted),
                ),
            )
            row = dict(cur.fetchone())
            self._transition(
                cur, row["publication_id"], "PUBLICATION_CANDIDATE", request.actor, {}
            )
            self._event(
                cur,
                "PUBLICATION_CANDIDATE",
                row["publication_id"],
                "CANDIDATE_CREATED",
                request.actor,
                {"correlation_id": request.correlation_id},
            )
            return row

    def authorize(
        self,
        publication_id: int,
        actor: str,
        authority: PublicationAuthority | None = None,
    ) -> dict[str, Any]:
        authority = authority or PublicationAuthority()
        with self._connect() as con, con.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (publication_id,))
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.authorization_decisions WHERE publication_id=%s ORDER BY decision_id DESC LIMIT 1",
                (publication_id,),
            )
            if row := cur.fetchone():
                return dict(row)
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.publication_candidates WHERE publication_id=%s",
                (publication_id,),
            )
            candidate_row = cur.fetchone()
            if not candidate_row:
                raise ValueError("PUBLICATION_CANDIDATE_NOT_FOUND")
            candidate = dict(candidate_row)
            trusted = dict(candidate.pop("trusted_snapshot"))
            candidate.update(trusted)
            policy = self._active_policy_by_pk(cur, candidate["policy_version_id"])
            self._transition(cur, publication_id, "VALIDATING", actor, {})
            decision = authority.evaluate(candidate, policy)
            cur.execute(
                "INSERT INTO oc_knowledge_publication.authorization_decisions(publication_id,publication_version,assertion_id,assertion_version,eligibility_decision_id,eligibility_decision_version,policy_version_id,requested_pathway,resolved_pathway,outcome,decision,fingerprint,actor,correlation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    publication_id,
                    candidate["publication_version"],
                    candidate["assertion_id"],
                    candidate["assertion_version"],
                    candidate["eligibility_decision_id"],
                    candidate["eligibility_decision_version"],
                    candidate["policy_version_id"],
                    candidate["requested_pathway"],
                    decision["resolved_pathway"],
                    decision["outcome"],
                    Jsonb(decision),
                    _fingerprint(decision),
                    actor,
                    candidate["correlation_id"],
                ),
            )
            row = dict(cur.fetchone())
            self._transition(
                cur,
                publication_id,
                decision["state"],
                actor,
                {"decision_id": row["decision_id"]},
            )
            self._event(
                cur,
                "PUBLICATION_CANDIDATE",
                publication_id,
                "AUTHORITY_EVALUATED",
                actor,
                decision,
            )
            return row

    def candidate(self, publication_id: int) -> dict[str, Any] | None:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT c.*,t.state FROM oc_knowledge_publication.publication_candidates c JOIN LATERAL (SELECT state FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=c.publication_id ORDER BY transition_id DESC LIMIT 1)t ON true WHERE c.publication_id=%s",
                (publication_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def audit_history(
        self, artifact_type: str, artifact_id: int
    ) -> list[dict[str, Any]]:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.audit_events WHERE artifact_type=%s AND artifact_id=%s ORDER BY audit_event_id",
                (artifact_type, artifact_id),
            )
            return [dict(row) for row in cur.fetchall()]

    def _assertion(self, cur, assertion_id: int, version: int) -> dict[str, Any]:
        cur.execute(
            "SELECT * FROM oc_scientific_interpretation.canonical_assertions WHERE assertion_id=%s AND version=%s",
            (assertion_id, version),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("EXACT_CANONICAL_ASSERTION_NOT_FOUND")
        value = dict(row["payload"])
        value.update({"assertion_id": row["assertion_id"], "version": row["version"]})
        return value

    def _provenance(self, cur, assertion: dict[str, Any]) -> list[dict[str, Any]]:
        ids = assertion.get("supporting_interpretation_ids", []) + assertion.get(
            "conflicting_interpretation_ids", []
        )
        if not ids:
            return []
        cur.execute(
            "SELECT payload FROM oc_scientific_interpretation.machine_interpretations WHERE interpretation_id=ANY(%s)",
            (ids,),
        )
        packet_ids = sorted(
            {
                pid
                for row in cur.fetchall()
                for pid in row["payload"].get("packet_ids", [])
            }
        )
        cur.execute(
            "SELECT payload FROM oc_scientific_interpretation.evidence_packets WHERE packet_id=ANY(%s)",
            (packet_ids,),
        )
        return [
            source
            for row in cur.fetchall()
            for source in row["payload"].get("sources", [])
        ]

    def _active_policy(self, cur, policy_id: str, version: int) -> dict[str, Any]:
        cur.execute(
            "SELECT * FROM oc_knowledge_publication.policy_versions WHERE policy_id=%s AND version=%s",
            (policy_id, version),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("POLICY_VERSION_NOT_FOUND")
        return self._active_policy_by_pk(cur, row["policy_version_id"])

    def _active_policy_by_pk(self, cur, pk: int) -> dict[str, Any]:
        cur.execute(
            "SELECT p.* FROM oc_knowledge_publication.policy_versions p WHERE p.policy_version_id=%s AND (SELECT state FROM oc_knowledge_publication.policy_lifecycle_events WHERE policy_version_id=p.policy_version_id ORDER BY policy_event_id DESC LIMIT 1)='ACTIVE'",
            (pk,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("POLICY_VERSION_NOT_ACTIVE")
        value = dict(row)
        value["rules"] = dict(value["rules"])
        return value

    @staticmethod
    def _transition(
        cur, publication_id: int, state: str, actor: str, details: dict[str, Any]
    ) -> None:
        cur.execute(
            "INSERT INTO oc_knowledge_publication.lifecycle_transitions(publication_id,state,actor,details) VALUES(%s,%s,%s,%s)",
            (publication_id, state, actor, Jsonb(details)),
        )

    @staticmethod
    def _event(
        cur,
        artifact_type: str,
        artifact_id: int,
        event_type: str,
        actor: str,
        details: dict[str, Any],
    ) -> None:
        cur.execute(
            "INSERT INTO oc_knowledge_publication.audit_events(artifact_type,artifact_id,event_type,actor,details) VALUES(%s,%s,%s,%s,%s)",
            (artifact_type, artifact_id, event_type, actor, Jsonb(details)),
        )
