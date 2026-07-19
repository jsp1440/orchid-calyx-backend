from __future__ import annotations

import os
import uuid
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.publication.repositories import PostgresPublicationRepository
from app.publication.services import PublicationService


ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    "076a_universal_intake.sql",
    "076b_semantic_extraction.sql",
    "077_ontology_evidence_registry.sql",
    "078_controlled_publication_gate.sql",
]


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def execute_sql_file(cur, name: str) -> None:
    cur.execute((ROOT / "migrations" / name).read_text(encoding="utf-8"))


def ensure_graph_backbone(cur) -> None:
    cur.execute("CREATE SCHEMA IF NOT EXISTS oc_intake")
    cur.execute("CREATE SCHEMA IF NOT EXISTS oc_graph")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oc_graph.kg_nodes (
          kg_node_id BIGSERIAL PRIMARY KEY,
          node_type TEXT NOT NULL,
          canonical_key TEXT NOT NULL,
          display_label TEXT,
          source_table TEXT,
          source_pk TEXT,
          evidence_class TEXT,
          confidence_score DOUBLE PRECISION,
          confidence_label TEXT,
          payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          build_run_id BIGINT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          CONSTRAINT kg_nodes_unique UNIQUE (node_type, canonical_key)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS oc_graph.kg_edges (
          kg_edge_id BIGSERIAL PRIMARY KEY,
          edge_type TEXT NOT NULL,
          from_node_id BIGINT NOT NULL REFERENCES oc_graph.kg_nodes(kg_node_id),
          to_node_id BIGINT NOT NULL REFERENCES oc_graph.kg_nodes(kg_node_id),
          source_table TEXT,
          source_pk TEXT,
          evidence_class TEXT NOT NULL DEFAULT 'normalized',
          confidence_score DOUBLE PRECISION,
          confidence_label TEXT,
          rule_name TEXT,
          payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
          is_active BOOLEAN NOT NULL DEFAULT TRUE,
          build_run_id BIGINT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )


def table_count(cur, table: str) -> int:
    cur.execute(f"SELECT count(*) AS count FROM {table}")
    return int(cur.fetchone()["count"])


def seed_release_fixture(cur, marker: str) -> tuple[int, list[int]]:
    sha = "b" * 64
    cur.execute(
        """INSERT INTO oc_intake.ingestion_batches(display_name,uploader,source_label,status)
        VALUES (%s,'build-078','ci','VALIDATION') RETURNING id""",
        (f"BUILD-078 validation {marker}",),
    )
    batch_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO oc_intake.documents
        (batch_id,original_filename,display_title,media_type,extension,byte_size,sha256,storage_key,
         uploader,processing_status,text_extraction_status,extracted_text,preliminary_document_type,
         relevance,review_status,provenance)
        VALUES (%s,%s,%s,'text/plain','.txt',64,%s,%s,'build-078','COMPLETE','COMPLETE',
         'Dracula lafleurii is associated with Euglossa imperialis.','scientific_note','RELEVANT','ACCEPTED',%s)
        RETURNING id""",
        (batch_id, f"{marker}.txt", f"BUILD-078 fixture {marker}", sha, f"build-078/{marker}.txt", Jsonb({"build": "078", "marker": marker})),
    )
    document_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO oc_semantic.extraction_sessions(document_id,stage,created_by,provenance)
        VALUES (%s,'READY_FOR_REVIEW','build-078',%s) RETURNING id""",
        (document_id, Jsonb({"build": "078", "marker": marker})),
    )
    session_id = cur.fetchone()["id"]
    entity_ids = []
    for entity_type, name in (("TAXON", "Dracula lafleurii"), ("POLLINATOR", "Euglossa imperialis")):
        cur.execute("INSERT INTO oc_semantic.candidates(session_id,kind,confidence,review_status) VALUES (%s,'ENTITY',0.99,'ACCEPTED') RETURNING id", (session_id,))
        candidate_id = cur.fetchone()["id"]
        entity_ids.append(candidate_id)
        cur.execute(
            """INSERT INTO oc_semantic.candidate_entities(candidate_id,entity_type,name,normalized_name,start_offset,end_offset,attributes)
            VALUES (%s,%s,%s,lower(%s),0,10,%s)""",
            (candidate_id, entity_type, name, name, Jsonb({"build": "078"})),
        )
    cur.execute(
        """INSERT INTO oc_semantic.evidence_objects(session_id,evidence_type,exact_text,start_offset,end_offset,source_sha256,provenance)
        VALUES (%s,'TEXT_SPAN','Dracula lafleurii is associated with Euglossa imperialis',0,58,%s,%s) RETURNING id""",
        (session_id, sha, Jsonb({"build": "078", "document_id": document_id})),
    )
    evidence_id = cur.fetchone()["id"]
    cur.execute("INSERT INTO oc_semantic.candidates(session_id,kind,confidence,review_status) VALUES (%s,'RELATIONSHIP',0.93,'ACCEPTED') RETURNING id", (session_id,))
    relationship_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO oc_semantic.candidate_relationships(candidate_id,subject_candidate_id,predicate,object_candidate_id,evidence_id)
        VALUES (%s,%s,'associated_with_pollinator',%s,%s)""",
        (relationship_id, entity_ids[0], entity_ids[1], evidence_id),
    )
    cur.execute(
        """INSERT INTO oc_ontology.ontology_registries(namespace,name,authority,version,ontology_type,status,checksum,provenance,created_by)
        VALUES (%s,'Build 078 taxonomy','staging','2026.078','TAXONOMY','ACTIVE',%s,%s,'build-078') RETURNING id""",
        (f"build-078-taxonomy-{marker}", "c" * 64, Jsonb({"build": "078"})),
    )
    tax_registry_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO oc_ontology.ontology_registries(namespace,name,authority,version,ontology_type,status,checksum,provenance,created_by)
        VALUES (%s,'Build 078 pollinators','staging','2026.078','POLLINATOR','ACTIVE',%s,%s,'build-078') RETURNING id""",
        (f"build-078-pollinator-{marker}", "d" * 64, Jsonb({"build": "078"})),
    )
    pollinator_registry_id = cur.fetchone()["id"]
    terms = [(tax_registry_id, entity_ids[0], "dracula_lafleurii", "Dracula lafleurii", "TAXON", {"canonical_taxon_id": f"wp:{marker}"}), (pollinator_registry_id, entity_ids[1], "euglossa_imperialis", "Euglossa imperialis", "POLLINATOR", {})]
    for registry_id, candidate_id, key, label, term_type, external_ids in terms:
        cur.execute(
            """INSERT INTO oc_ontology.ontology_terms(registry_id,canonical_key,preferred_label,normalized_label,term_type,external_ids,status)
            VALUES (%s,%s,%s,lower(%s),%s,%s,'ACTIVE') RETURNING id""",
            (registry_id, key, label, label, term_type, Jsonb(external_ids)),
        )
        term_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO oc_ontology.candidate_resolutions
            (candidate_id,ontology_term_id,resolution_method,confidence,status,normalized_input,matched_label,ontology_namespace,ontology_version,explanation,provenance,resolved_by,resolved_at)
            VALUES (%s,%s,'EXACT',1,'ACCEPTED',lower(%s),%s,'build-078','2026.078',%s,%s,'build-078',NOW())""",
            (candidate_id, term_id, label, label, Jsonb({"build": "078"}), Jsonb({"build": "078"})),
        )
    cur.execute(
        """INSERT INTO oc_ontology.evidence_registry
        (evidence_object_id,evidence_hash,source_document_id,source_sha256,validation_status,validation_details,validator_version,registered_by,last_validated_at)
        VALUES (%s,%s,%s,%s,'VALID',%s,'build-078-validation','build-078',NOW())""",
        (evidence_id, sha, document_id, sha, Jsonb({"build": "078"})),
    )
    for candidate_id in [*entity_ids, relationship_id]:
        cur.execute(
            """INSERT INTO oc_ontology.publication_readiness
            (candidate_id,evidence_complete,ontology_resolved,review_complete,provenance_complete,ready_for_publication,blockers,evaluated_by,evaluation_version,is_current)
            VALUES (%s,TRUE,TRUE,TRUE,TRUE,TRUE,'[]'::jsonb,'build-078','build-078-validation',TRUE)""",
            (candidate_id,),
        )
    return session_id, [*entity_ids, relationship_id]


def main() -> None:
    dsn = database_url()
    marker = uuid.uuid4().hex[:12]
    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        ensure_graph_backbone(cur)
        before_graph = {"nodes": table_count(cur, "oc_graph.kg_nodes"), "edges": table_count(cur, "oc_graph.kg_edges")}
        taxonomy_tables = [row["table_name"] for row in cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='oc_taxonomy'").fetchall()]
        before_taxonomy = {name: table_count(cur, f"oc_taxonomy.{name}") for name in taxonomy_tables}
        for migration in MIGRATIONS:
            execute_sql_file(cur, migration)
        session_id, candidate_ids = seed_release_fixture(cur, marker)
        conn.commit()

    service = PublicationService(PostgresPublicationRepository(dsn))
    payload = {
        "actor": "build-078-ci",
        "reason": "BUILD-078 PostgreSQL staging validation",
        "scope": {"session_id": session_id},
        "approval_reference": f"ci-{marker}",
        "publication_authority": "github-actions-staging",
    }
    dry_run = service.dry_run(payload)
    if dry_run["canonical_graph_mutated"] or dry_run["status"] != "DRY_RUN_COMPLETE":
        raise AssertionError(f"dry run failed safety contract: {dry_run['status']}")
    published = service.publish({**payload, "dry_run_run_id": dry_run["run_id"]})
    if published["status"] != "PUBLISHED" or not published["canonical_graph_mutated"]:
        raise AssertionError(f"publish failed: {published['status']}")
    rerun = service.publish({**payload, "dry_run_run_id": dry_run["run_id"]})
    if rerun["run_id"] != published["run_id"]:
        raise AssertionError("publication idempotency returned a new run")

    with psycopg.connect(dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
        after_graph = {"nodes": table_count(cur, "oc_graph.kg_nodes"), "edges": table_count(cur, "oc_graph.kg_edges")}
        after_taxonomy = {name: table_count(cur, f"oc_taxonomy.{name}") for name in taxonomy_tables}
        cur.execute("SELECT count(*) AS count FROM oc_publication.publication_audit_events WHERE run_id=%s", (published["run_id"],))
        audit_count = int(cur.fetchone()["count"])
    if audit_count < 1:
        raise AssertionError("publication audit events were not recorded")
    if after_taxonomy != before_taxonomy:
        raise AssertionError("taxonomy tables were modified")
    if after_graph["nodes"] < before_graph["nodes"] + 2 or after_graph["edges"] < before_graph["edges"] + 1:
        raise AssertionError("expected controlled graph inserts were not observed")

    print("BUILD-078 PostgreSQL validation succeeded")
    print(f"session_id={session_id} candidates={candidate_ids} dry_run_id={dry_run['run_id']} publish_id={published['run_id']}")
    print(f"graph_before={before_graph} graph_after={after_graph}")
    print("taxonomy_preserved=yes")


if __name__ == "__main__":
    main()
