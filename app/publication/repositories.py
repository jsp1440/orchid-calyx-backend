from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from runtime.knowledge_graph.repository import _publication_lock_key


def publication_database_url() -> str:
    value = os.getenv("DATABASE_URL") or os.getenv("TEST_DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required for publication operations")
    return value


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(v) for v in value]
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def digest_manifest(manifest: Mapping[str, Any]) -> str:
    encoded = json.dumps(json_safe(manifest), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class PostgresPublicationRepository:
    def __init__(self, database_url: str | None = None, graph_schema: str = "oc_graph") -> None:
        self.database_url = database_url or publication_database_url()
        self.graph_schema = graph_schema
        self.lock_id = _publication_lock_key(graph_schema)

    def _connect(self):
        import psycopg

        return psycopg.connect(self.database_url, row_factory=dict_row, connect_timeout=10)

    def candidate_ids_for_scope(self, scope: Mapping[str, Any]) -> list[int]:
        with self._connect() as conn, conn.cursor() as cur:
            if scope.get("session_id") is not None:
                cur.execute(
                    "SELECT id FROM oc_semantic.candidates WHERE session_id=%s ORDER BY CASE kind WHEN 'ENTITY' THEN 0 ELSE 1 END,id",
                    (scope["session_id"],),
                )
            else:
                cur.execute(
                    "SELECT id FROM oc_semantic.candidates WHERE id=ANY(%s) ORDER BY CASE kind WHEN 'ENTITY' THEN 0 ELSE 1 END,id",
                    (list(scope["candidate_ids"]),),
                )
            return [int(row["id"]) for row in cur.fetchall()]

    def load_candidate(self, candidate_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id,c.session_id,c.kind,c.confidence,c.review_status,s.stage AS session_stage,
                  s.provenance AS session_provenance,e.entity_type,e.name,e.normalized_name,e.attributes,
                  rel.subject_candidate_id,rel.predicate,rel.object_candidate_id,rel.evidence_id,
                  pr.ready_for_publication,pr.blockers AS readiness_blockers,
                  cr.id AS resolution_id,cr.status AS resolution_status,cr.ontology_term_id,
                  cr.resolution_method,cr.confidence AS resolution_confidence,cr.provenance AS resolution_provenance,
                  t.canonical_key AS term_canonical_key,t.preferred_label,t.term_type,t.external_ids,t.metadata AS term_metadata,
                  t.status AS term_status,r.namespace,r.version,r.status AS registry_status,r.ontology_type,
                  er.validation_status AS evidence_validation_status,er.evidence_hash,er.source_sha256
                FROM oc_semantic.candidates c
                JOIN oc_semantic.extraction_sessions s ON s.id=c.session_id
                LEFT JOIN oc_semantic.candidate_entities e ON e.candidate_id=c.id
                LEFT JOIN oc_semantic.candidate_relationships rel ON rel.candidate_id=c.id
                LEFT JOIN oc_ontology.publication_readiness pr ON pr.candidate_id=c.id AND pr.is_current
                LEFT JOIN oc_ontology.candidate_resolutions cr ON cr.candidate_id=c.id AND cr.status='ACCEPTED'
                LEFT JOIN oc_ontology.ontology_terms t ON t.id=cr.ontology_term_id
                LEFT JOIN oc_ontology.ontology_registries r ON r.id=t.registry_id
                LEFT JOIN oc_ontology.evidence_registry er ON er.evidence_object_id=rel.evidence_id
                WHERE c.id=%s
                """,
                (candidate_id,),
            )
            return cur.fetchone()

    def graph_counts(self) -> dict[str, int]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(f"SELECT count(*) AS count FROM {self.graph_schema}.kg_nodes WHERE is_active")
            nodes = int(cur.fetchone()["count"])
            cur.execute(f"SELECT count(*) AS count FROM {self.graph_schema}.kg_edges WHERE is_active")
            edges = int(cur.fetchone()["count"])
            return {"nodes": nodes, "edges": edges}

    def get_node_by_key(self, canonical_key: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT * FROM {self.graph_schema}.kg_nodes WHERE canonical_key=%s AND is_active ORDER BY kg_node_id LIMIT 1",
                (canonical_key,),
            )
            return cur.fetchone()

    def find_edge(self, edge_type: str, from_node_id: int, to_node_id: int, source_table: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"""SELECT * FROM {self.graph_schema}.kg_edges
                WHERE edge_type=%s AND from_node_id=%s AND to_node_id=%s
                  AND source_table IS NOT DISTINCT FROM %s AND is_active
                ORDER BY kg_edge_id LIMIT 1""",
                (edge_type, from_node_id, to_node_id, source_table),
            )
            return cur.fetchone()

    def existing_publication(self, mode: str, manifest_digest: str) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_publication.publication_runs WHERE mode=%s AND manifest_digest=%s",
                (mode, manifest_digest),
            )
            return cur.fetchone()

    def read_run_items(self, run_id: int) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_publication.publication_items WHERE run_id=%s ORDER BY id", (run_id,))
            return list(cur.fetchall())

    def record_dry_run(self, run: Mapping[str, Any], items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        return self._record_run("DRY_RUN", run, list(items), mutate_graph=False)

    def publish(self, run: Mapping[str, Any], items: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
        return self._record_run("PUBLISH", run, list(items), mutate_graph=True)

    def rollback_run(self, run_id: int, actor: str, reason: str, strategy: str) -> dict[str, Any]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM oc_publication.publication_runs WHERE id=%s FOR UPDATE", (run_id,))
            previous = cur.fetchone()
            if previous is None:
                raise LookupError("PUBLICATION_RUN_NOT_FOUND")
            if previous["status"] != "PUBLISHED":
                raise ValueError("ONLY_PUBLISHED_RUNS_CAN_BE_ROLLED_BACK")
            target_status = "ROLLED_BACK" if strategy == "MARK_ROLLED_BACK" else "SUPERSEDED"
            cur.execute("UPDATE oc_publication.publication_runs SET status=%s, completed_at=NOW() WHERE id=%s RETURNING *", (target_status, run_id))
            updated = cur.fetchone()
            cur.execute(
                """INSERT INTO oc_publication.publication_rollbacks
                (run_id, rollback_actor, reason, strategy, supersession_state, canonical_graph_mutated)
                VALUES (%s,%s,%s,%s,%s,FALSE) RETURNING *""",
                (run_id, actor, reason, strategy, Jsonb({"previous_status": previous["status"], "resulting_status": target_status})),
            )
            rollback = cur.fetchone()
            self._audit(cur, run_id, None, actor, "ROLLBACK_RECORDED", "PUBLICATION_RUN", str(run_id), previous, updated, reason)
            return {**rollback, "run": updated}

    def _record_run(self, mode: str, run: Mapping[str, Any], items: list[Mapping[str, Any]], mutate_graph: bool) -> dict[str, Any]:
        with self._connect() as conn:
            conn.autocommit = False
            with conn.cursor() as cur:
                lock_held = False
                try:
                    if mutate_graph:
                        cur.execute("SELECT pg_try_advisory_lock(%s)", (self.lock_id,))
                        lock_held = bool(cur.fetchone()["pg_try_advisory_lock"])
                        if not lock_held:
                            raise ValueError("PUBLICATION_ALREADY_IN_PROGRESS")
                    before = self._graph_counts_cur(cur)
                    status = "PUBLISHING" if mutate_graph else "DRY_RUN_COMPLETE"
                    cur.execute(
                        """INSERT INTO oc_publication.publication_runs
                        (mode, source_scope, manifest, manifest_digest, status, requesting_actor,
                         approval_reference, publication_authority, reason, dry_run_run_id,
                         item_count, ready_count, blocked_count, before_graph_counts, started_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (mode, manifest_digest) DO UPDATE SET manifest=EXCLUDED.manifest
                        RETURNING *""",
                        (
                            mode, Jsonb(json_safe(run["source_scope"])), Jsonb(json_safe(run["manifest"])),
                            run["manifest_digest"], status, run["actor"], run.get("approval_reference"),
                            run.get("publication_authority"), run["reason"], run.get("dry_run_run_id"),
                            len(items), sum(1 for item in items if item["state"] == "READY"),
                            sum(1 for item in items if item["state"] == "BLOCKED"), Jsonb(before),
                        ),
                    )
                    stored_run = cur.fetchone()
                    run_id = int(stored_run["id"])
                    inserted_nodes = linked_nodes = inserted_edges = linked_edges = 0
                    stored_items: list[dict[str, Any]] = []
                    for item in items:
                        stored = self._insert_item(cur, run_id, item)
                        if item["state"] == "BLOCKED":
                            self._record_conflicts(cur, run_id, int(stored["id"]), item)
                            stored_items.append(stored)
                            continue
                        if mutate_graph:
                            stored, counters = self._publish_item_cur(cur, stored, item)
                            inserted_nodes += counters["inserted_node_count"]
                            linked_nodes += counters["linked_node_count"]
                            inserted_edges += counters["inserted_edge_count"]
                            linked_edges += counters["linked_edge_count"]
                        elif stored["state"] == "READY":
                            cur.execute(
                                "UPDATE oc_publication.publication_items SET state='DRY_RUN_COMPLETE' WHERE id=%s RETURNING *",
                                (stored["id"],),
                            )
                            stored = cur.fetchone()
                        self._audit(cur, run_id, int(stored["id"]), run["actor"], item["audit_action"], "PUBLICATION_ITEM", str(stored["id"]), None, stored, run["reason"])
                        stored_items.append(stored)
                    after = self._graph_counts_cur(cur)
                    final_status = "PUBLISHED" if mutate_graph and not any(i["state"] == "BLOCKED" for i in items) else status
                    if not mutate_graph and any(i["state"] == "BLOCKED" for i in items):
                        final_status = "BLOCKED"
                    cur.execute(
                        """UPDATE oc_publication.publication_runs
                        SET status=%s, inserted_node_count=%s, linked_node_count=%s,
                            inserted_edge_count=%s, linked_edge_count=%s,
                            canonical_graph_mutated=%s, after_graph_counts=%s, completed_at=NOW()
                        WHERE id=%s RETURNING *""",
                        (
                            final_status, inserted_nodes, linked_nodes, inserted_edges, linked_edges,
                            mutate_graph and (inserted_nodes > 0 or inserted_edges > 0), Jsonb(after), run_id,
                        ),
                    )
                    stored_run = cur.fetchone()
                    self._audit(cur, run_id, None, run["actor"], mode, "PUBLICATION_RUN", str(run_id), None, stored_run, run["reason"])
                    conn.commit()
                    return {"run": stored_run, "items": stored_items}
                except BaseException:
                    conn.rollback()
                    raise
                finally:
                    if lock_held:
                        try:
                            with conn.cursor() as unlock:
                                unlock.execute("SELECT pg_advisory_unlock(%s)", (self.lock_id,))
                        except BaseException:
                            pass

    def _graph_counts_cur(self, cur) -> dict[str, int]:
        cur.execute(f"SELECT count(*) AS count FROM {self.graph_schema}.kg_nodes WHERE is_active")
        nodes = int(cur.fetchone()["count"])
        cur.execute(f"SELECT count(*) AS count FROM {self.graph_schema}.kg_edges WHERE is_active")
        edges = int(cur.fetchone()["count"])
        return {"nodes": nodes, "edges": edges}

    def _insert_item(self, cur, run_id: int, item: Mapping[str, Any]) -> dict[str, Any]:
        cur.execute(
            """INSERT INTO oc_publication.publication_items
            (run_id,candidate_id,item_type,state,action,canonical_key,blockers,conflict_keys,provenance,manifest_digest)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (run_id,candidate_id) DO UPDATE SET state=EXCLUDED.state
            RETURNING *""",
            (
                run_id, item["candidate_id"], item["item_type"], item["state"], item["action"],
                item["canonical_key"], Jsonb(json_safe(item["blockers"])), Jsonb(json_safe(item["conflict_keys"])),
                Jsonb(json_safe(item["provenance"])), item["manifest_digest"],
            ),
        )
        return cur.fetchone()

    def _publish_item_cur(self, cur, stored: Mapping[str, Any], item: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
        counters = {"inserted_node_count": 0, "linked_node_count": 0, "inserted_edge_count": 0, "linked_edge_count": 0}
        cur.execute("UPDATE oc_publication.publication_items SET state='PUBLISHING' WHERE id=%s RETURNING *", (stored["id"],))
        stored = cur.fetchone()
        if item["item_type"] == "ENTITY":
            cur.execute(
                f"""INSERT INTO {self.graph_schema}.kg_nodes
                (node_type,canonical_key,display_label,source_table,source_pk,evidence_class,confidence_score,confidence_label,payload_json,is_active,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,TRUE,NOW())
                ON CONFLICT (node_type, canonical_key) DO UPDATE SET
                  display_label=EXCLUDED.display_label, source_table=EXCLUDED.source_table,
                  source_pk=EXCLUDED.source_pk, evidence_class=EXCLUDED.evidence_class,
                  confidence_score=EXCLUDED.confidence_score, confidence_label=EXCLUDED.confidence_label,
                  payload_json=EXCLUDED.payload_json, is_active=TRUE, updated_at=NOW()
                RETURNING kg_node_id, (xmax = 0) AS inserted""",
                (
                    item["node_type"], item["canonical_key"], item["display_label"],
                    "oc_semantic.candidate_entities", str(item["candidate_id"]), item["evidence_class"],
                    item["confidence_score"], item["confidence_label"], json.dumps(json_safe(item["payload"])),
                ),
            )
            node = cur.fetchone()
            counters["inserted_node_count" if node["inserted"] else "linked_node_count"] += 1
            cur.execute("UPDATE oc_publication.publication_items SET state='PUBLISHED', graph_node_id=%s WHERE id=%s RETURNING *", (node["kg_node_id"], stored["id"]))
            return cur.fetchone(), counters
        cur.execute(
            f"SELECT kg_node_id FROM {self.graph_schema}.kg_nodes WHERE canonical_key=%s AND is_active ORDER BY kg_node_id LIMIT 1",
            (item["from_canonical_key"],),
        )
        from_node = cur.fetchone()
        cur.execute(
            f"SELECT kg_node_id FROM {self.graph_schema}.kg_nodes WHERE canonical_key=%s AND is_active ORDER BY kg_node_id LIMIT 1",
            (item["to_canonical_key"],),
        )
        to_node = cur.fetchone()
        if from_node is None or to_node is None:
            raise ValueError("PUBLICATION_RELATIONSHIP_ENDPOINT_MISSING")
        from_node_id = int(from_node["kg_node_id"])
        to_node_id = int(to_node["kg_node_id"])
        cur.execute(
            f"""SELECT kg_edge_id FROM {self.graph_schema}.kg_edges
            WHERE edge_type=%s AND from_node_id=%s AND to_node_id=%s
              AND source_table IS NOT DISTINCT FROM 'oc_semantic.candidate_relationships' AND is_active
            ORDER BY kg_edge_id LIMIT 1""",
            (item["edge_type"], from_node_id, to_node_id),
        )
        existing = cur.fetchone()
        if existing:
            edge_id = existing["kg_edge_id"]
            counters["linked_edge_count"] += 1
        else:
            cur.execute(
                f"""INSERT INTO {self.graph_schema}.kg_edges
                (edge_type,from_node_id,to_node_id,source_table,source_pk,evidence_class,confidence_score,confidence_label,rule_name,payload_json,is_active,updated_at)
                VALUES (%s,%s,%s,'oc_semantic.candidate_relationships',%s,%s,%s,%s,%s,%s::jsonb,TRUE,NOW())
                RETURNING kg_edge_id""",
                (
                    item["edge_type"], from_node_id, to_node_id, str(item["candidate_id"]),
                    item["evidence_class"], item["confidence_score"], item["confidence_label"],
                    "build-078-controlled-publication", json.dumps(json_safe(item["payload"])),
                ),
            )
            edge_id = cur.fetchone()["kg_edge_id"]
            counters["inserted_edge_count"] += 1
        cur.execute("UPDATE oc_publication.publication_items SET state='PUBLISHED', graph_edge_id=%s WHERE id=%s RETURNING *", (edge_id, stored["id"]))
        return cur.fetchone(), counters

    def _record_conflicts(self, cur, run_id: int, item_id: int, item: Mapping[str, Any]) -> None:
        for blocker in item["blockers"]:
            if str(blocker).endswith("CONFLICT") or "CONFLICT" in str(blocker):
                cur.execute(
                    """INSERT INTO oc_publication.publication_conflicts(run_id,item_id,candidate_id,conflict_type,details)
                    VALUES (%s,%s,%s,%s,%s)""",
                    (run_id, item_id, item["candidate_id"], str(blocker), Jsonb(json_safe({"conflict_keys": item["conflict_keys"]}))),
                )

    def _audit(self, cur, run_id: int | None, item_id: int | None, actor: str, action: str, target_type: str, target_id: str | None, previous: Any, resulting: Any, reason: str) -> None:
        cur.execute(
            """INSERT INTO oc_publication.publication_audit_events
            (run_id,item_id,actor,action,target_type,target_id,previous_state,resulting_state,reason)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, item_id, actor, action, target_type, target_id, Jsonb(json_safe(previous)) if previous is not None else None, Jsonb(json_safe(resulting)) if resulting is not None else None, reason),
        )
