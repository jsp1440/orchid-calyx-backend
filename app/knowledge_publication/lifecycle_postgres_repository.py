from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .lifecycle_models import LifecycleAuthority, LifecycleReason, RetractionReason


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


CONSUMERS = (
    "AUTHORITATIVE_GRAPH",
    "HISTORICAL_GRAPH",
    "PROVENANCE_VIEW",
    "PUBLIC_SEARCH",
    "SPECIES_PAGES",
    "GENUS_TRAVERSAL",
    "REASONING",
    "CONSERVATION",
    "BREEDING",
    "SCIENTIFIC_REVIEW",
    "ILLUSTRATED_GLOSSARY",
    "EDUCATIONAL_PATHWAYS",
    "AI_EXPLANATIONS",
    "CACHES",
    "MATERIALIZED_VIEWS",
)


class PostgresPublicationLifecycleRepository:
    def __init__(self, database_url: str):
        if not database_url:
            raise ValueError("DATABASE_URL_REQUIRED")
        self.database_url = database_url

    def _connect(self):
        return psycopg.connect(
            self.database_url, row_factory=dict_row, connect_timeout=10
        )

    def supersede(
        self,
        predecessor_id: int,
        successor_id: int,
        authority: LifecycleAuthority,
        reason: LifecycleReason,
        correction_record_id: int | None = None,
    ):
        with self._connect() as con, con.cursor() as cur:
            self._lock(cur, predecessor_id, successor_id)
            prior = self._published(cur, predecessor_id)
            successor = self._published(cur, successor_id)
            if (
                successor["assertion_id"] == prior["assertion_id"]
                and successor["assertion_version"] <= prior["assertion_version"]
            ):
                raise ValueError("NEW_ASSERTION_VERSION_REQUIRED")
            if correction_record_id is not None:
                cur.execute(
                    "SELECT 1 FROM oc_scientific_interpretation.correction_records WHERE correction_id=%s",
                    (correction_record_id,),
                )
                if not cur.fetchone():
                    raise ValueError("CORRECTION_RECORD_NOT_FOUND")
            identity = {
                "predecessor": predecessor_id,
                "successor": successor_id,
                "type": "CORRECTION" if correction_record_id else "SUPERSESSION",
                "reason": reason.reason_code,
            }
            cur.execute(
                "INSERT INTO oc_knowledge_publication.publication_lineage(predecessor_publication_id,successor_publication_id,lineage_type,prior_assertion_id,prior_assertion_version,successor_assertion_id,successor_assertion_version,correction_record_id,reason_code,rationale,authority,fingerprint,correlation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
                (
                    predecessor_id,
                    successor_id,
                    identity["type"],
                    prior["assertion_id"],
                    prior["assertion_version"],
                    successor["assertion_id"],
                    successor["assertion_version"],
                    correction_record_id,
                    reason.reason_code,
                    reason.rationale,
                    authority.authority_reference,
                    digest(identity),
                    authority.correlation_id,
                ),
            )
            lineage = dict(cur.fetchone())
            self._transition(
                cur,
                predecessor_id,
                "SUPERSEDED",
                authority,
                {
                    "reason_code": reason.reason_code,
                    "lineage_id": lineage["lineage_id"],
                },
            )
            self._projection(
                cur,
                predecessor_id,
                prior.get("graph_version_id"),
                "HISTORICAL",
                True,
                identity["type"],
                lineage["lineage_id"],
                authority,
            )
            self._projection(
                cur,
                successor_id,
                successor.get("graph_version_id"),
                "AUTHORITATIVE_CURRENT",
                True,
                identity["type"],
                lineage["lineage_id"],
                authority,
            )
            self._impacts(
                cur,
                identity["type"],
                lineage["lineage_id"],
                predecessor_id,
                self._object_keys(cur, predecessor_id),
                authority,
            )
            self._audit(
                cur,
                "SUPERSESSION_COMPLETED",
                predecessor_id,
                authority,
                {"successor": successor_id, "lineage_id": lineage["lineage_id"]},
            )
            return lineage

    def withdraw(self, publication_id, authority, reason):
        return self._status_action(
            publication_id, "WITHDRAWAL", "WITHDRAWN", authority, reason, {}
        )

    def retract(self, publication_id, authority, reason, invalidation_source):
        if reason.reason_code not in {item.value for item in RetractionReason}:
            raise ValueError("INVALID_RETRACTION_REASON")
        return self._status_action(
            publication_id,
            "RETRACTION",
            "RETRACTED",
            authority,
            reason,
            invalidation_source,
            propagate=True,
        )

    def restore(self, publication_id, authority, reason):
        with self._connect() as con, con.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (publication_id,))
            current = self._state(cur, publication_id)
            if current == "RETRACTED":
                raise ValueError("RETRACTED_PUBLICATION_REQUIRES_REPUBLICATION")
            if current != "WITHDRAWN":
                raise ValueError("ONLY_WITHDRAWN_PUBLICATION_CAN_BE_RESTORED")
            publication = self._publication(cur, publication_id)
            identity = {
                "publication": publication_id,
                "action": "RESTORATION",
                "reason": reason.reason_code,
            }
            action = self._action(
                cur,
                publication_id,
                "RESTORATION",
                authority,
                reason,
                {},
                publication,
                digest(identity),
            )
            self._transition(
                cur,
                publication_id,
                "PUBLISHED",
                authority,
                {"reason_code": reason.reason_code, "action_id": action["action_id"]},
            )
            self._projection(
                cur,
                publication_id,
                publication.get("graph_version_id"),
                "AUTHORITATIVE_CURRENT",
                True,
                "RESTORATION",
                action["action_id"],
                authority,
            )
            self._impacts(
                cur,
                "RESTORATION",
                action["action_id"],
                publication_id,
                self._object_keys(cur, publication_id),
                authority,
            )
            self._audit(
                cur,
                "RESTORATION_COMPLETED",
                publication_id,
                authority,
                {"action_id": action["action_id"]},
            )
            return action

    def require_reevaluation(
        self, publication_id, authority, reason, trigger_reference, batch_size=100
    ):
        if not 1 <= batch_size <= 500:
            raise ValueError("INVALID_PROPAGATION_BATCH_SIZE")
        with self._connect() as con, con.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (publication_id,))
            self._publication(cur, publication_id)
            if self._state(cur, publication_id) == "PUBLISHED":
                self._transition(
                    cur,
                    publication_id,
                    "REEVALUATION_REQUIRED",
                    authority,
                    {"reason_code": reason.reason_code},
                )
            identity = {
                "trigger": publication_id,
                "affected": publication_id,
                "reason": reason.reason_code,
                "reference": trigger_reference,
            }
            cur.execute(
                "INSERT INTO oc_knowledge_publication.reevaluation_records(trigger_publication_id,affected_publication_id,trigger_type,trigger_reference,affected_object_keys,status,fingerprint,correlation_id) VALUES(%s,%s,%s,%s,%s,'OPEN',%s,%s) ON CONFLICT(fingerprint) DO UPDATE SET fingerprint=EXCLUDED.fingerprint RETURNING *",
                (
                    publication_id,
                    publication_id,
                    reason.reason_code,
                    Jsonb(trigger_reference),
                    Jsonb(self._object_keys(cur, publication_id)),
                    digest(identity),
                    authority.correlation_id,
                ),
            )
            root = dict(cur.fetchone())
            cur.execute(
                "SELECT dependent_publication_id FROM oc_knowledge_publication.publication_dependencies WHERE source_publication_id=%s ORDER BY dependency_id LIMIT %s",
                (publication_id, batch_size),
            )
            dependents = [
                row["dependent_publication_id"]
                for row in cur.fetchall()
                if row["dependent_publication_id"] != publication_id
            ]
            for dependent in dependents:
                if self._state(cur, dependent) == "PUBLISHED":
                    self._transition(
                        cur,
                        dependent,
                        "REEVALUATION_REQUIRED",
                        authority,
                        {
                            "reason_code": "DEPENDENCY_REEVALUATION",
                            "trigger_publication_id": publication_id,
                        },
                    )
                dep_identity = {
                    "trigger": publication_id,
                    "affected": dependent,
                    "reason": reason.reason_code,
                }
                cur.execute(
                    "INSERT INTO oc_knowledge_publication.reevaluation_records(trigger_publication_id,affected_publication_id,trigger_type,trigger_reference,affected_object_keys,status,fingerprint,correlation_id) VALUES(%s,%s,%s,%s,%s,'PROPAGATED',%s,%s) ON CONFLICT(fingerprint) DO NOTHING",
                    (
                        publication_id,
                        dependent,
                        reason.reason_code,
                        Jsonb(trigger_reference),
                        Jsonb(self._object_keys(cur, dependent)),
                        digest(dep_identity),
                        authority.correlation_id,
                    ),
                )
            checkpoint_identity = {
                "root": root["reevaluation_id"],
                "visited": [publication_id, *dependents],
            }
            cur.execute(
                "INSERT INTO oc_knowledge_publication.propagation_checkpoints(trigger_action_id,batch_number,visited_publication_ids,next_publication_ids,completed,fingerprint,correlation_id) VALUES(%s,1,%s,'[]',TRUE,%s,%s) ON CONFLICT(fingerprint) DO NOTHING",
                (
                    root["reevaluation_id"],
                    Jsonb(checkpoint_identity["visited"]),
                    digest(checkpoint_identity),
                    authority.correlation_id,
                ),
            )
            self._impacts(
                cur,
                "REEVALUATION_REQUIRED",
                root["reevaluation_id"],
                publication_id,
                self._object_keys(cur, publication_id),
                authority,
            )
            self._audit(
                cur,
                "DEPENDENCY_PROPAGATION_COMPLETED",
                publication_id,
                authority,
                {"affected_count": len(dependents)},
            )
            return {"reevaluation": root, "affected_publication_ids": dependents}

    def prepare_rollback(self, publication_id, authority, reason, detection_source):
        allowed = {
            "INCOMPLETE_COMMIT",
            "PROJECTION_INCONSISTENCY",
            "AUDIT_INTEGRITY_FAILURE",
            "PROVENANCE_INTEGRITY_FAILURE",
            "CURRENT_POINTER_FAILURE",
            "IMMEDIATE_TECHNICAL_INVALIDITY",
        }
        if reason.reason_code not in allowed:
            raise ValueError("ROLLBACK_RESTRICTED_TO_TECHNICAL_FAILURE")
        with self._connect() as con, con.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (publication_id,))
            publication = self._publication(cur, publication_id)
            state = self._state(cur, publication_id)
            if state not in {"PUBLISHED", "PUBLICATION_FAILED", "ROLLBACK_REQUIRED"}:
                raise ValueError("ROLLBACK_STATE_NOT_ELIGIBLE")
            cur.execute(
                "SELECT g.* FROM oc_knowledge_publication.graph_versions g WHERE publication_id=%s ORDER BY sequence DESC LIMIT 1",
                (publication_id,),
            )
            failed = cur.fetchone()
            if not failed:
                raise ValueError("ORIGINAL_TRANSACTION_NOT_FOUND")
            cur.execute(
                "SELECT object_kind,legacy_object_id,object_key FROM oc_knowledge_publication.graph_object_versions WHERE graph_version_id=%s ORDER BY object_version_id",
                (failed["graph_version_id"],),
            )
            objects = list(cur.fetchall())
            cur.execute(
                "SELECT provenance_link_id FROM oc_knowledge_publication.graph_provenance_links WHERE graph_transaction_id=%s ORDER BY provenance_link_id",
                (failed["graph_transaction_id"],),
            )
            provenance = [r["provenance_link_id"] for r in cur.fetchall()]
            identity = {
                "transaction": failed["graph_transaction_id"],
                "failed": failed["graph_version_id"],
                "coherent": failed["parent_graph_version_id"],
                "reason": reason.reason_code,
            }
            cur.execute(
                "INSERT INTO oc_knowledge_publication.rollback_manifests(original_graph_transaction_id,publication_id,publication_version,failed_graph_version_id,coherent_graph_version_id,rollback_reason,detection_source,inverse_operations,affected_node_ids,affected_edge_ids,affected_provenance_link_ids,affected_projections,preconditions,status,fingerprint,service_identity,correlation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PREPARED',%s,%s,%s) ON CONFLICT(original_graph_transaction_id) DO UPDATE SET original_graph_transaction_id=EXCLUDED.original_graph_transaction_id RETURNING *",
                (
                    failed["graph_transaction_id"],
                    publication_id,
                    publication["publication_version"],
                    failed["graph_version_id"],
                    failed["parent_graph_version_id"],
                    reason.reason_code,
                    detection_source,
                    Jsonb(
                        [
                            {
                                "operation": "EXCLUDE_GRAPH_VERSION_FROM_CURRENT",
                                "graph_version_id": failed["graph_version_id"],
                            }
                        ]
                    ),
                    Jsonb(
                        [
                            o["legacy_object_id"]
                            for o in objects
                            if o["object_kind"] == "NODE"
                        ]
                    ),
                    Jsonb(
                        [
                            o["legacy_object_id"]
                            for o in objects
                            if o["object_kind"] == "EDGE"
                        ]
                    ),
                    Jsonb(provenance),
                    Jsonb(["AUTHORITATIVE_CURRENT"]),
                    Jsonb({"current_graph_version_id": failed["graph_version_id"]}),
                    digest(identity),
                    authority.service_identity,
                    authority.correlation_id,
                ),
            )
            manifest = dict(cur.fetchone())
            if state != "ROLLBACK_REQUIRED":
                self._transition(
                    cur,
                    publication_id,
                    "ROLLBACK_REQUIRED",
                    authority,
                    {
                        "reason_code": reason.reason_code,
                        "rollback_id": manifest["rollback_id"],
                    },
                )
            self._audit(
                cur,
                "ROLLBACK_MANIFEST_CREATED",
                publication_id,
                authority,
                {"rollback_id": manifest["rollback_id"]},
            )
            return manifest

    def execute_rollback(self, rollback_id, authority):
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended('controlled-graph-publication',88))"
            )
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.rollback_transactions WHERE rollback_id=%s",
                (rollback_id,),
            )
            if existing := cur.fetchone():
                return {**dict(existing), "duplicate": True}
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.rollback_manifests WHERE rollback_id=%s",
                (rollback_id,),
            )
            manifest = cur.fetchone()
            if not manifest:
                raise ValueError("ROLLBACK_MANIFEST_NOT_FOUND")
            if self._state(cur, manifest["publication_id"]) != "ROLLBACK_REQUIRED":
                raise ValueError("ROLLBACK_REQUIRED_STATE_MISSING")
            cur.execute(
                "SELECT graph_version_id FROM oc_knowledge_publication.current_graph_version WHERE singleton=TRUE FOR UPDATE"
            )
            current = cur.fetchone()["graph_version_id"]
            if current != manifest["failed_graph_version_id"]:
                raise ValueError("ROLLBACK_GRAPH_VERSION_CONFLICT")
            cur.execute(
                "UPDATE oc_knowledge_publication.current_graph_version SET graph_version_id=%s,sequence=COALESCE((SELECT sequence FROM oc_knowledge_publication.graph_versions WHERE graph_version_id=%s),0),updated_at=NOW() WHERE singleton=TRUE",
                (
                    manifest["coherent_graph_version_id"],
                    manifest["coherent_graph_version_id"],
                ),
            )
            identity = {
                "rollback": rollback_id,
                "restored": manifest["coherent_graph_version_id"],
            }
            cur.execute(
                "INSERT INTO oc_knowledge_publication.rollback_transactions(rollback_id,original_graph_transaction_id,restored_graph_version_id,outcome,fingerprint,service_identity,correlation_id) VALUES(%s,%s,%s,'ROLLED_BACK',%s,%s,%s) RETURNING *",
                (
                    rollback_id,
                    manifest["original_graph_transaction_id"],
                    manifest["coherent_graph_version_id"],
                    digest(identity),
                    authority.service_identity,
                    authority.correlation_id,
                ),
            )
            transaction = dict(cur.fetchone())
            self._transition(
                cur,
                manifest["publication_id"],
                "ROLLED_BACK",
                authority,
                {
                    "reason_code": "TECHNICAL_ROLLBACK_COMMITTED",
                    "rollback_id": rollback_id,
                },
            )
            self._projection(
                cur,
                manifest["publication_id"],
                manifest["failed_graph_version_id"],
                "ROLLED_BACK",
                False,
                "ROLLBACK",
                transaction["rollback_transaction_id"],
                authority,
            )
            self._impacts(
                cur,
                "ROLLBACK",
                transaction["rollback_transaction_id"],
                manifest["publication_id"],
                self._object_keys(cur, manifest["publication_id"]),
                authority,
            )
            self._audit(
                cur,
                "ROLLBACK_COMPLETED",
                manifest["publication_id"],
                authority,
                {"rollback_id": rollback_id},
            )
            return transaction

    def _status_action(
        self,
        publication_id,
        action_type,
        state,
        authority,
        reason,
        invalidation,
        propagate=False,
    ):
        with self._connect() as con, con.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (publication_id,))
            publication = self._publication(cur, publication_id)
            current = self._state(cur, publication_id)
            if current == state:
                cur.execute(
                    "SELECT * FROM oc_knowledge_publication.publication_lifecycle_actions WHERE publication_id=%s AND action_type=%s ORDER BY action_id DESC LIMIT 1",
                    (publication_id, action_type),
                )
                return {**dict(cur.fetchone()), "duplicate": True}
            if current not in {"PUBLISHED", "REEVALUATION_REQUIRED"}:
                raise ValueError("PUBLICATION_NOT_ELIGIBLE_FOR_LIFECYCLE_ACTION")
            identity = {
                "publication": publication_id,
                "action": action_type,
                "reason": reason.reason_code,
                "invalidation": invalidation,
            }
            action = self._action(
                cur,
                publication_id,
                action_type,
                authority,
                reason,
                invalidation,
                publication,
                digest(identity),
            )
            self._transition(
                cur,
                publication_id,
                state,
                authority,
                {"reason_code": reason.reason_code, "action_id": action["action_id"]},
            )
            projection = "WITHDRAWN" if state == "WITHDRAWN" else "RETRACTED"
            self._projection(
                cur,
                publication_id,
                publication.get("graph_version_id"),
                projection,
                False,
                action_type,
                action["action_id"],
                authority,
            )
            self._impacts(
                cur,
                action_type,
                action["action_id"],
                publication_id,
                self._object_keys(cur, publication_id),
                authority,
            )
            self._audit(
                cur,
                f"{action_type}_COMPLETED",
                publication_id,
                authority,
                {"action_id": action["action_id"]},
            )
            if propagate:
                cur.execute(
                    "SELECT dependent_publication_id FROM oc_knowledge_publication.publication_dependencies WHERE source_publication_id=%s ORDER BY dependency_id LIMIT 100",
                    (publication_id,),
                )
                dependents = [row["dependent_publication_id"] for row in cur.fetchall()]
                for dependent in dependents:
                    if self._state(cur, dependent) == "PUBLISHED":
                        self._transition(
                            cur,
                            dependent,
                            "REEVALUATION_REQUIRED",
                            authority,
                            {
                                "reason_code": "DEPENDENCY_RETRACTED",
                                "trigger_publication_id": publication_id,
                            },
                        )
                    reevaluation_identity = {
                        "trigger": publication_id,
                        "affected": dependent,
                        "action_id": action["action_id"],
                        "reason": reason.reason_code,
                    }
                    cur.execute(
                        "INSERT INTO oc_knowledge_publication.reevaluation_records(trigger_publication_id,affected_publication_id,trigger_type,trigger_reference,affected_object_keys,status,fingerprint,correlation_id) "
                        "VALUES(%s,%s,'DEPENDENCY_RETRACTED',%s,%s,'PROPAGATED',%s,%s) ON CONFLICT(fingerprint) DO NOTHING RETURNING reevaluation_id",
                        (
                            publication_id,
                            dependent,
                            Jsonb({"action_id": action["action_id"]}),
                            Jsonb(self._object_keys(cur, dependent)),
                            digest(reevaluation_identity),
                            authority.correlation_id,
                        ),
                    )
                    cur.fetchone()
                checkpoint_identity = {
                    "action_id": action["action_id"],
                    "visited": [publication_id, *dependents],
                }
                cur.execute(
                    "INSERT INTO oc_knowledge_publication.propagation_checkpoints(trigger_action_id,batch_number,visited_publication_ids,next_publication_ids,completed,fingerprint,correlation_id) "
                    "VALUES(%s,1,%s,'[]',TRUE,%s,%s) ON CONFLICT(fingerprint) DO NOTHING",
                    (
                        action["action_id"],
                        Jsonb(checkpoint_identity["visited"]),
                        digest(checkpoint_identity),
                        authority.correlation_id,
                    ),
                )
            return action

    def _publication(self, cur, pid):
        cur.execute(
            "SELECT c.*,g.graph_version_id,g.graph_transaction_id FROM oc_knowledge_publication.publication_candidates c LEFT JOIN LATERAL(SELECT * FROM oc_knowledge_publication.graph_versions WHERE publication_id=c.publication_id ORDER BY sequence DESC LIMIT 1)g ON TRUE WHERE c.publication_id=%s",
            (pid,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("PUBLICATION_NOT_FOUND")
        return dict(row)

    def _published(self, cur, pid):
        value = self._publication(cur, pid)
        if self._state(cur, pid) != "PUBLISHED":
            raise ValueError("SUCCESSOR_OR_PREDECESSOR_NOT_PUBLISHED")
        return value

    def _state(self, cur, pid):
        cur.execute(
            "SELECT state FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=%s ORDER BY transition_id DESC LIMIT 1",
            (pid,),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("PUBLICATION_LIFECYCLE_NOT_FOUND")
        return row["state"]

    @staticmethod
    def _lock(cur, *ids):
        for pid in sorted(ids):
            cur.execute("SELECT pg_advisory_xact_lock(%s)", (pid,))

    def _object_keys(self, cur, pid):
        cur.execute(
            "SELECT object_key FROM oc_knowledge_publication.graph_object_versions WHERE publication_id=%s ORDER BY object_version_id",
            (pid,),
        )
        return [r["object_key"] for r in cur.fetchall()]

    def _action(self, cur, pid, kind, authority, reason, invalidation, publication, fp):
        cur.execute(
            "INSERT INTO oc_knowledge_publication.publication_lifecycle_actions(publication_id,action_type,reason_code,rationale,invalidation_source,authority,graph_transaction_id,graph_version_id,fingerprint,correlation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                pid,
                kind,
                reason.reason_code,
                reason.rationale,
                Jsonb(invalidation),
                authority.authority_reference,
                publication.get("graph_transaction_id"),
                publication.get("graph_version_id"),
                fp,
                authority.correlation_id,
            ),
        )
        return dict(cur.fetchone())

    def _projection(
        self, cur, pid, version, projection, included, kind, source_id, authority
    ):
        identity = {
            "publication": pid,
            "version": version,
            "projection": projection,
            "included": included,
            "kind": kind,
            "source": source_id,
        }
        cur.execute(
            "INSERT INTO oc_knowledge_publication.publication_projection_events(publication_id,graph_version_id,projection,included,source_action_type,source_action_id,fingerprint,correlation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(fingerprint) DO NOTHING",
            (
                pid,
                version,
                projection,
                included,
                kind,
                source_id,
                digest(identity),
                authority.correlation_id,
            ),
        )

    def _impacts(self, cur, kind, source_id, pid, keys, authority):
        for consumer in CONSUMERS:
            identity = {
                "kind": kind,
                "source": source_id,
                "publication": pid,
                "consumer": consumer,
            }
            cur.execute(
                "INSERT INTO oc_knowledge_publication.downstream_impacts(source_action_type,source_action_id,affected_publication_id,affected_object_keys,consumer_category,required_action,fingerprint,correlation_id) VALUES(%s,%s,%s,%s,%s,'REEVALUATE_OR_REFRESH',%s,%s) ON CONFLICT(fingerprint) DO NOTHING",
                (
                    kind,
                    source_id,
                    pid,
                    Jsonb(keys),
                    consumer,
                    digest(identity),
                    authority.correlation_id,
                ),
            )

    @staticmethod
    def _transition(cur, pid, state, authority, details):
        cur.execute(
            "INSERT INTO oc_knowledge_publication.lifecycle_transitions(publication_id,state,actor,details) VALUES(%s,%s,%s,%s)",
            (
                pid,
                state,
                authority.service_identity,
                Jsonb(
                    {
                        **details,
                        "authority_reference": authority.authority_reference,
                        "correlation_id": authority.correlation_id,
                    }
                ),
            ),
        )

    @staticmethod
    def _audit(cur, event, pid, authority, details):
        cur.execute(
            "INSERT INTO oc_knowledge_publication.audit_events(artifact_type,artifact_id,event_type,actor,details) VALUES('PUBLICATION_LIFECYCLE',%s,%s,%s,%s)",
            (
                pid,
                event,
                authority.service_identity,
                Jsonb({**details, "correlation_id": authority.correlation_id}),
            ),
        )
