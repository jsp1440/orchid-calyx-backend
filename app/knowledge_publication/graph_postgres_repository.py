from __future__ import annotations

import hashlib
import json
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .graph_mapping import AssertionGraphMapper
from .graph_models import GraphOperationType, PublicationExecutionRequest


def fingerprint(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def json_safe(value: Any) -> Any:
    """Canonicalize trusted database values without admitting caller encoders."""
    return json.loads(json.dumps(value, sort_keys=True, default=str))


class PostgresControlledGraphRepository:
    """Atomic BUILD-088C writer; no caller-supplied scientific or authority state."""

    def __init__(self, database_url: str, graph_schema: str = "oc_graph") -> None:
        if not database_url:
            raise ValueError("DATABASE_URL_REQUIRED")
        if not graph_schema.replace("_", "").isalnum():
            raise ValueError("INVALID_GRAPH_SCHEMA")
        self.database_url, self.graph_schema = database_url, graph_schema

    def _connect(self):
        return psycopg.connect(
            self.database_url, row_factory=dict_row, connect_timeout=10
        )

    def prepare(self, request: PublicationExecutionRequest) -> dict[str, Any]:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,88))",
                (
                    f"publication:{request.publication_id}:{request.publication_version}",
                ),
            )
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.graph_transaction_manifests WHERE publication_id=%s AND publication_version=%s ORDER BY graph_transaction_id DESC LIMIT 1",
                (request.publication_id, request.publication_version),
            )
            if row := cur.fetchone():
                return dict(row)
            publication = self._trusted_publication(cur, request)
            assertion = publication["assertion"]
            operations = AssertionGraphMapper().map(assertion, publication)
            operation_values = [
                {
                    "order": op.order,
                    "operation_type": op.operation_type.value,
                    "object_key": op.object_key,
                    "payload": op.payload,
                }
                for op in operations
            ]
            cur.execute(
                "SELECT graph_version_id,sequence FROM oc_knowledge_publication.current_graph_version WHERE singleton=TRUE FOR SHARE"
            )
            current = cur.fetchone()
            validation = {
                "authorized": True,
                "exact_assertion": assertion["version"]
                == publication["assertion_version"],
                "policy_resolved": True,
                "provenance_complete": bool(publication["provenance_roots"]),
                "taxonomy_resolved": bool(
                    publication.get("taxonomy_concept_id")
                    and publication.get("taxonomy_version")
                ),
                "supported_operations": all(
                    op.operation_type in GraphOperationType for op in operations
                ),
                "source_graph_current": True,
            }
            if not all(validation.values()):
                raise ValueError("PRECOMMIT_VALIDATION_FAILED")
            change_identity = {
                "publication_id": request.publication_id,
                "publication_version": request.publication_version,
                "authorization_decision_id": publication["authorization_decision_id"],
                "assertion_id": publication["assertion_id"],
                "assertion_version": publication["assertion_version"],
                "policy_version_id": publication["policy_version_id"],
                "source_graph_version_id": current["graph_version_id"],
                "operations": operation_values,
                "scientific_scope": publication["scientific_scope"],
                "qualifiers": publication["qualifiers"],
            }
            change_fingerprint = fingerprint(change_identity)
            cur.execute(
                "INSERT INTO oc_knowledge_publication.graph_change_sets(publication_id,publication_version,authorization_decision_id,assertion_id,assertion_version,policy_version_id,source_graph_version_id,operations,trusted_snapshot,validation_status,fingerprint,created_by,correlation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'VALIDATED',%s,%s,%s) RETURNING *",
                (
                    request.publication_id,
                    request.publication_version,
                    publication["authorization_decision_id"],
                    publication["assertion_id"],
                    publication["assertion_version"],
                    publication["policy_version_id"],
                    current["graph_version_id"],
                    Jsonb(operation_values),
                    Jsonb(json_safe(publication)),
                    change_fingerprint,
                    request.service_identity,
                    request.correlation_id,
                ),
            )
            change_set = cur.fetchone()
            manifest_identity = {
                "change_set_fingerprint": change_fingerprint,
                "source_graph_version_id": current["graph_version_id"],
                "intended_target_sequence": current["sequence"] + 1,
                "operations": operation_values,
            }
            cur.execute(
                "INSERT INTO oc_knowledge_publication.graph_transaction_manifests(change_set_id,publication_id,publication_version,source_graph_version_id,intended_target_sequence,ordered_operations,validation_checks,status,fingerprint,service_identity,correlation_id) VALUES(%s,%s,%s,%s,%s,%s,%s,'PREPARED',%s,%s,%s) RETURNING *",
                (
                    change_set["change_set_id"],
                    request.publication_id,
                    request.publication_version,
                    current["graph_version_id"],
                    current["sequence"] + 1,
                    Jsonb(operation_values),
                    Jsonb(validation),
                    fingerprint(manifest_identity),
                    request.service_identity,
                    request.correlation_id,
                ),
            )
            manifest = dict(cur.fetchone())
            self._transition(
                cur,
                request.publication_id,
                "TRANSACTION_PREPARED",
                request,
                {
                    "graph_transaction_id": manifest["graph_transaction_id"],
                    "reason_code": "MANIFEST_VALIDATED",
                },
            )
            self._audit(
                cur,
                "TRANSACTION_PREPARED",
                request,
                manifest["graph_transaction_id"],
                {
                    "change_set_id": change_set["change_set_id"],
                    "policy_version_id": publication["policy_version_id"],
                },
            )
            return manifest

    def publish(self, request: PublicationExecutionRequest) -> dict[str, Any]:
        manifest = self.prepare(request)
        try:
            with self._connect() as con, con.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended('controlled-graph-publication',88))"
                )
                cur.execute(
                    "SELECT g.* FROM oc_knowledge_publication.graph_versions g JOIN oc_knowledge_publication.graph_transaction_manifests m USING(graph_transaction_id) WHERE m.fingerprint=%s",
                    (manifest["fingerprint"],),
                )
                if existing := cur.fetchone():
                    return {**dict(existing), "outcome": "NO_OP_DUPLICATE"}
                cur.execute(
                    "SELECT * FROM oc_knowledge_publication.graph_transaction_manifests WHERE graph_transaction_id=%s",
                    (manifest["graph_transaction_id"],),
                )
                manifest_row = cur.fetchone()
                cur.execute(
                    "SELECT * FROM oc_knowledge_publication.graph_change_sets WHERE change_set_id=%s",
                    (manifest_row["change_set_id"],),
                )
                change_set = cur.fetchone()
                publication = dict(change_set["trusted_snapshot"])
                cur.execute(
                    "SELECT graph_version_id,sequence FROM oc_knowledge_publication.current_graph_version WHERE singleton=TRUE FOR UPDATE"
                )
                current = cur.fetchone()
                if (
                    current["graph_version_id"]
                    != manifest_row["source_graph_version_id"]
                    or current["sequence"] + 1
                    != manifest_row["intended_target_sequence"]
                ):
                    raise ValueError("SOURCE_GRAPH_VERSION_CONFLICT")
                self._transition(
                    cur,
                    request.publication_id,
                    "PUBLISHING",
                    request,
                    {
                        "graph_transaction_id": manifest_row["graph_transaction_id"],
                        "reason_code": "ATOMIC_COMMIT_STARTED",
                    },
                )
                operations = list(manifest_row["ordered_operations"])
                node_count = sum(
                    op["operation_type"] == "CREATE_NODE" for op in operations
                )
                edge_count = sum(
                    op["operation_type"] == "CREATE_EDGE" for op in operations
                )
                version_identity = {
                    "parent": current["graph_version_id"],
                    "transaction": manifest_row["graph_transaction_id"],
                    "sequence": current["sequence"] + 1,
                    "publication": request.publication_id,
                }
                cur.execute(
                    "INSERT INTO oc_knowledge_publication.graph_versions(sequence,parent_graph_version_id,graph_transaction_id,publication_id,publication_version,status,node_change_count,edge_change_count,provenance_complete,fingerprint,correlation_id) VALUES(%s,%s,%s,%s,%s,'COMMITTED',%s,%s,TRUE,%s,%s) RETURNING *",
                    (
                        current["sequence"] + 1,
                        current["graph_version_id"],
                        manifest_row["graph_transaction_id"],
                        request.publication_id,
                        request.publication_version,
                        node_count,
                        edge_count,
                        fingerprint(version_identity),
                        request.correlation_id,
                    ),
                )
                graph_version = dict(cur.fetchone())
                node_ids: dict[str, int] = {}
                object_versions: list[dict[str, Any]] = []
                for operation in operations:
                    if operation["operation_type"] == "CREATE_NODE":
                        node_id = self._create_node(cur, operation, request)
                        node_ids[operation["object_key"]] = node_id
                        object_versions.append(
                            self._object_version(
                                cur, graph_version, operation, node_id, "NODE"
                            )
                        )
                for operation in operations:
                    if operation["operation_type"] == "CREATE_EDGE":
                        edge_id = self._create_edge(cur, operation, node_ids, request)
                        object_versions.append(
                            self._object_version(
                                cur, graph_version, operation, edge_id, "EDGE"
                            )
                        )
                for object_version in object_versions:
                    self._provenance(cur, object_version, graph_version, publication)
                cur.execute(
                    "UPDATE oc_knowledge_publication.current_graph_version SET graph_version_id=%s,sequence=%s,updated_at=NOW() WHERE singleton=TRUE",
                    (graph_version["graph_version_id"], graph_version["sequence"]),
                )
                cur.execute(
                    "INSERT INTO oc_knowledge_publication.graph_transaction_attempts(graph_transaction_id,attempt_number,outcome,reason_code,details,actor,correlation_id) VALUES(%s,1,'COMMITTED','ATOMIC_PUBLICATION_COMMITTED',%s,%s,%s)",
                    (
                        manifest_row["graph_transaction_id"],
                        Jsonb({"graph_version_id": graph_version["graph_version_id"]}),
                        request.service_identity,
                        request.correlation_id,
                    ),
                )
                self._audit(
                    cur,
                    "GRAPH_TRANSACTION_COMMITTED",
                    request,
                    manifest_row["graph_transaction_id"],
                    {
                        "graph_version_id": graph_version["graph_version_id"],
                        "node_count": node_count,
                        "edge_count": edge_count,
                    },
                )
                self._transition(
                    cur,
                    request.publication_id,
                    "PUBLISHED",
                    request,
                    {
                        "graph_transaction_id": manifest_row["graph_transaction_id"],
                        "graph_version_id": graph_version["graph_version_id"],
                        "reason_code": "ATOMIC_PUBLICATION_COMMITTED",
                    },
                )
                return {**graph_version, "outcome": "PUBLISHED"}
        except Exception as exc:
            self._record_failure(
                request, manifest["graph_transaction_id"], type(exc).__name__
            )
            raise

    def _trusted_publication(
        self, cur, request: PublicationExecutionRequest
    ) -> dict[str, Any]:
        cur.execute(
            "SELECT c.*,t.state FROM oc_knowledge_publication.publication_candidates c JOIN LATERAL(SELECT state FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=c.publication_id ORDER BY transition_id DESC LIMIT 1)t ON TRUE WHERE c.publication_id=%s AND c.publication_version=%s",
            (request.publication_id, request.publication_version),
        )
        row = cur.fetchone()
        if not row:
            raise ValueError("EXACT_PUBLICATION_NOT_FOUND")
        if row["state"] != "AUTHORIZED":
            raise ValueError("PUBLICATION_NOT_AUTHORIZED")
        cur.execute(
            "SELECT * FROM oc_knowledge_publication.authorization_decisions WHERE publication_id=%s AND publication_version=%s AND outcome='AUTHORIZED' ORDER BY decision_id DESC LIMIT 1",
            (request.publication_id, request.publication_version),
        )
        decision = cur.fetchone()
        if not decision:
            raise ValueError("AUTHORIZATION_DECISION_MISSING")
        cur.execute(
            "SELECT 1 FROM oc_knowledge_publication.policy_versions WHERE policy_version_id=%s",
            (row["policy_version_id"],),
        )
        if not cur.fetchone():
            raise ValueError("POLICY_VERSION_MISSING")
        trusted = dict(row["trusted_snapshot"])
        assertion = dict(trusted.get("assertion", {}))
        provenance = list(trusted.get("provenance_roots", []))
        if (
            assertion.get("assertion_id") != row["assertion_id"]
            or assertion.get("version") != row["assertion_version"]
        ):
            raise ValueError("ASSERTION_VERSION_MISMATCH")
        if assertion.get("routing_decision_id") != row[
            "eligibility_decision_id"
        ] or not assertion.get("publication_eligible"):
            raise ValueError("ELIGIBILITY_CHANGED")
        if not provenance:
            raise ValueError("PROVENANCE_MISSING")
        return {
            **dict(row),
            "authorization_decision_id": decision["decision_id"],
            "assertion": assertion,
            "provenance_roots": provenance,
        }

    def _create_node(self, cur, operation, request) -> int:
        payload = operation["payload"]
        cur.execute(
            f"INSERT INTO {self.graph_schema}.kg_nodes(node_type,canonical_key,display_label,source_table,source_pk,evidence_class,confidence_label,payload_json,is_active,updated_at) VALUES(%s,%s,%s,'oc_knowledge_publication.publication_candidates',%s,'governed','policy-authorized',%s,TRUE,NOW()) ON CONFLICT(node_type,canonical_key) DO NOTHING RETURNING kg_node_id",
            (
                payload["node_type"],
                operation["object_key"],
                payload["display_label"],
                str(request.publication_id),
                Jsonb(payload),
            ),
        )
        row = cur.fetchone()
        if row:
            return row["kg_node_id"]
        cur.execute(
            f"SELECT kg_node_id FROM {self.graph_schema}.kg_nodes WHERE node_type=%s AND canonical_key=%s AND is_active",
            (payload["node_type"], operation["object_key"]),
        )
        return cur.fetchone()["kg_node_id"]

    def _create_edge(self, cur, operation, node_ids, request) -> int:
        payload = operation["payload"]
        cur.execute(
            f"INSERT INTO {self.graph_schema}.kg_edges(edge_type,from_node_id,to_node_id,source_table,source_pk,evidence_class,confidence_label,rule_name,payload_json,is_active,updated_at) VALUES(%s,%s,%s,'oc_knowledge_publication.publication_candidates',%s,'governed','policy-authorized','BUILD-088C',%s,TRUE,NOW()) RETURNING kg_edge_id",
            (
                payload["edge_type"],
                node_ids[payload["from_key"]],
                node_ids[payload["to_key"]],
                str(request.publication_id),
                Jsonb(payload),
            ),
        )
        return cur.fetchone()["kg_edge_id"]

    def _object_version(self, cur, version, operation, legacy_id, kind):
        identity = {
            "graph_version_id": version["graph_version_id"],
            "object_key": operation["object_key"],
            "payload": operation["payload"],
        }
        cur.execute(
            "INSERT INTO oc_knowledge_publication.graph_object_versions(graph_version_id,graph_transaction_id,publication_id,object_kind,object_key,legacy_object_id,operation_type,payload,fingerprint) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (
                version["graph_version_id"],
                version["graph_transaction_id"],
                version["publication_id"],
                kind,
                operation["object_key"],
                legacy_id,
                operation["operation_type"],
                Jsonb(operation["payload"]),
                fingerprint(identity),
            ),
        )
        return dict(cur.fetchone())

    def _provenance(self, cur, object_version, version, publication):
        for source in publication["provenance_roots"]:
            identity = {
                "object_version_id": object_version["object_version_id"],
                "source_revision_id": source.get("source_revision_id"),
                "source_object_id": source.get("source_object_id"),
            }
            cur.execute(
                "INSERT INTO oc_knowledge_publication.graph_provenance_links(object_version_id,graph_transaction_id,publication_id,authorization_decision_id,assertion_id,assertion_version,source_revision_id,provenance,fingerprint) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (
                    object_version["object_version_id"],
                    version["graph_transaction_id"],
                    version["publication_id"],
                    publication["authorization_decision_id"],
                    publication["assertion_id"],
                    publication["assertion_version"],
                    source.get("source_revision_id"),
                    Jsonb(source),
                    fingerprint(identity),
                ),
            )

    def _record_failure(self, request, transaction_id, reason):
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT state FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=%s ORDER BY transition_id DESC LIMIT 1",
                (request.publication_id,),
            )
            state = cur.fetchone()["state"]
            if state in {"AUTHORIZED", "TRANSACTION_PREPARED", "PUBLISHING"}:
                self._transition(
                    cur,
                    request.publication_id,
                    "PUBLICATION_FAILED",
                    request,
                    {"graph_transaction_id": transaction_id, "reason_code": reason},
                )
                self._audit(
                    cur,
                    "GRAPH_TRANSACTION_FAILED",
                    request,
                    transaction_id,
                    {"reason_code": reason},
                )

    @staticmethod
    def _transition(cur, publication_id, state, request, details):
        cur.execute(
            "INSERT INTO oc_knowledge_publication.lifecycle_transitions(publication_id,state,actor,details) VALUES(%s,%s,%s,%s)",
            (
                publication_id,
                state,
                request.service_identity,
                Jsonb({**details, "correlation_id": request.correlation_id}),
            ),
        )

    @staticmethod
    def _audit(cur, event_type, request, transaction_id, details):
        cur.execute(
            "INSERT INTO oc_knowledge_publication.audit_events(artifact_type,artifact_id,event_type,actor,details) VALUES('GRAPH_TRANSACTION',%s,%s,%s,%s)",
            (
                transaction_id,
                event_type,
                request.service_identity,
                Jsonb({**details, "correlation_id": request.correlation_id}),
            ),
        )

    def transaction(self, transaction_id: int) -> dict[str, Any] | None:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.graph_transaction_manifests WHERE graph_transaction_id=%s",
                (transaction_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def graph_version(self, graph_version_id: int) -> dict[str, Any] | None:
        with self._connect() as con, con.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_knowledge_publication.graph_versions WHERE graph_version_id=%s",
                (graph_version_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
