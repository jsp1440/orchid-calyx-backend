"""BUILD-077 PostgreSQL staging validation.

This script is intended to run inside GitHub Actions with DATABASE_URL supplied
from repository secrets. It never prints the secret value. It performs additive
migration validation and writes only clearly marked BUILD-077 validation rows in
the intake, semantic, and ontology schemas.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import psycopg
from fastapi.testclient import TestClient
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = [
    ("076a", ROOT / "migrations" / "076a_universal_intake.sql"),
    ("076b", ROOT / "migrations" / "076b_semantic_extraction.sql"),
    ("077", ROOT / "migrations" / "077_ontology_evidence_registry.sql"),
]
EXPECTED_077_TABLES = {
    "ontology_registries",
    "ontology_terms",
    "ontology_synonyms",
    "candidate_resolutions",
    "evidence_registry",
    "publication_readiness",
    "ontology_audit_events",
}
EXPECTED_077_TRIGGERS = {
    "ontology_registry_identity_immutable",
    "ontology_term_links_valid",
    "ontology_entity_resolution_only",
    "ontology_evidence_hash_immutable",
}
EXPECTED_077_INDEXES = {
    "ontology_one_accepted_resolution_idx",
    "ontology_current_readiness_idx",
    "ontology_terms_lookup_idx",
    "ontology_synonyms_lookup_idx",
    "ontology_resolution_candidate_idx",
    "ontology_audit_target_idx",
}


class ValidationError(RuntimeError):
    pass


def require_database_url() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise ValidationError("DATABASE_URL is not available to the validation job.")
    print("DATABASE_URL available: yes")
    print("::add-mask::" + dsn)
    return dsn


def redacted_target(dsn: str) -> dict[str, str | None]:
    parsed = urlparse(dsn)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": str(parsed.port) if parsed.port else None,
        "database": parsed.path.lstrip("/") or None,
        "username_present": "yes" if parsed.username else "no",
    }


def fetch_one(cur, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any]:
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        raise ValidationError(f"Expected one row from query: {sql}")
    return dict(row)


def table_exists(cur, schema: str, table: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
          SELECT 1 FROM information_schema.tables
          WHERE table_schema = %s AND table_name = %s
        ) AS exists
        """,
        (schema, table),
    )
    return bool(cur.fetchone()["exists"])


def schema_exists(cur, schema: str) -> bool:
    cur.execute("SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name=%s) AS exists", (schema,))
    return bool(cur.fetchone()["exists"])


def schema_tables(cur, schemas: list[str]) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_schema = ANY(%s) AND table_type='BASE TABLE'
        ORDER BY table_schema, table_name
        """,
        (schemas,),
    )
    return [dict(row) for row in cur.fetchall()]


def count_rows(cur, schema: str, table: str) -> int | None:
    try:
        cur.execute(f'SELECT COUNT(*) AS count FROM "{schema}"."{table}"')
        return int(cur.fetchone()["count"])
    except Exception:
        return None


def relation_counts(cur, schemas: list[str]) -> dict[str, int | None]:
    counts: dict[str, int | None] = {}
    for row in schema_tables(cur, schemas):
        key = f"{row['table_schema']}.{row['table_name']}"
        counts[key] = count_rows(cur, row["table_schema"], row["table_name"])
    return counts


def object_fingerprint(cur, schemas: list[str]) -> str:
    cur.execute(
        """
        SELECT 'column' AS kind, table_schema AS schema, table_name AS object_name,
               column_name || ':' || data_type || ':' || is_nullable || ':' || COALESCE(column_default,'') AS definition
        FROM information_schema.columns
        WHERE table_schema = ANY(%s)
        UNION ALL
        SELECT 'constraint', tc.table_schema, tc.table_name,
               tc.constraint_name || ':' || tc.constraint_type
        FROM information_schema.table_constraints tc
        WHERE tc.table_schema = ANY(%s)
        UNION ALL
        SELECT 'index', schemaname, tablename, indexname || ':' || indexdef
        FROM pg_indexes
        WHERE schemaname = ANY(%s)
        UNION ALL
        SELECT 'trigger', event_object_schema, event_object_table, trigger_name || ':' || action_timing || ':' || event_manipulation
        FROM information_schema.triggers
        WHERE event_object_schema = ANY(%s)
        ORDER BY 1,2,3,4
        """,
        (schemas, schemas, schemas, schemas),
    )
    payload = json.dumps([dict(row) for row in cur.fetchall()], sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def graph_taxonomy_schemas(cur) -> list[str]:
    cur.execute(
        """
        SELECT schema_name
        FROM information_schema.schemata
        WHERE schema_name = 'oc_graph'
           OR schema_name ILIKE '%%taxonomy%%'
           OR schema_name ILIKE '%%canonical%%'
        ORDER BY schema_name
        """
    )
    return [row["schema_name"] for row in cur.fetchall()]


def apply_migration(cur, label: str, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    forbidden = ["DROP TABLE", "DROP SCHEMA", "TRUNCATE", "DELETE FROM", "ALTER TABLE DROP"]
    upper = sql.upper()
    hits = [item for item in forbidden if item in upper]
    if hits:
        raise ValidationError(f"Refusing migration {label}; forbidden destructive SQL found: {hits}")
    print(f"Applying migration {label}: {path.name}")
    cur.execute(sql)


def ensure_migrations(conn) -> list[str]:
    applied: list[str] = []
    with conn.cursor() as cur:
        if not schema_exists(cur, "oc_intake"):
            raise ValidationError("oc_intake schema is absent; target is not a verified Orchid Continuum database.")
        required = {
            "076a": [("oc_intake", "ingestion_batches"), ("oc_intake", "documents"), ("oc_intake", "document_events")],
            "076b": [("oc_semantic", "extraction_sessions"), ("oc_semantic", "evidence_objects"), ("oc_semantic", "candidates")],
            "077": [("oc_ontology", table) for table in sorted(EXPECTED_077_TABLES)],
        }
        for label, path in MIGRATIONS:
            missing = [(schema, table) for schema, table in required[label] if not table_exists(cur, schema, table)]
            if missing:
                apply_migration(cur, label, path)
                applied.append(label)
            else:
                print(f"Migration {label}: already installed, verified required tables exist")
    conn.commit()
    return applied


def validate_objects(conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='oc_ontology' AND table_type='BASE TABLE'
            """
        )
        tables = {row["table_name"] for row in cur.fetchall()}
        missing_tables = sorted(EXPECTED_077_TABLES - tables)
        if missing_tables:
            raise ValidationError(f"Missing oc_ontology tables: {missing_tables}")

        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname='oc_ontology'")
        indexes = {row["indexname"] for row in cur.fetchall()}
        missing_indexes = sorted(EXPECTED_077_INDEXES - indexes)
        if missing_indexes:
            raise ValidationError(f"Missing oc_ontology indexes: {missing_indexes}")

        cur.execute("SELECT trigger_name FROM information_schema.triggers WHERE event_object_schema='oc_ontology'")
        triggers = {row["trigger_name"] for row in cur.fetchall()}
        missing_triggers = sorted(EXPECTED_077_TRIGGERS - triggers)
        if missing_triggers:
            raise ValidationError(f"Missing oc_ontology triggers: {missing_triggers}")

        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema='oc_ontology'
            ORDER BY table_name, ordinal_position
            """
        )
        columns = [dict(row) for row in cur.fetchall()]
        cur.execute(
            """
            SELECT tc.table_name, tc.constraint_name, tc.constraint_type
            FROM information_schema.table_constraints tc
            WHERE tc.table_schema='oc_ontology'
            ORDER BY tc.table_name, tc.constraint_name
            """
        )
        constraints = [dict(row) for row in cur.fetchall()]
        return {
            "tables": sorted(tables),
            "indexes": sorted(indexes),
            "triggers": sorted(triggers),
            "column_count": len(columns),
            "constraint_count": len(constraints),
        }


def permissions_report(conn) -> dict[str, Any]:
    with conn.cursor() as cur:
        row = fetch_one(
            cur,
            """
            SELECT
              current_user AS active_role,
              has_schema_privilege(current_user, 'oc_ontology', 'USAGE') AS schema_usage,
              has_schema_privilege(current_user, 'oc_ontology', 'CREATE') AS schema_create
            """,
        )
        cur.execute(
            """
            SELECT table_name,
              has_table_privilege(current_user, format('oc_ontology.%I', table_name), 'SELECT') AS can_select,
              has_table_privilege(current_user, format('oc_ontology.%I', table_name), 'INSERT') AS can_insert,
              has_table_privilege(current_user, format('oc_ontology.%I', table_name), 'UPDATE') AS can_update,
              has_table_privilege(current_user, format('oc_ontology.%I', table_name), 'DELETE') AS can_delete
            FROM information_schema.tables
            WHERE table_schema='oc_ontology' AND table_type='BASE TABLE'
            ORDER BY table_name
            """
        )
        table_privileges = [dict(row) for row in cur.fetchall()]
    if not row["schema_usage"]:
        raise ValidationError("Active role does not have USAGE on oc_ontology.")
    if not all(item["can_select"] and item["can_insert"] and item["can_update"] for item in table_privileges):
        raise ValidationError("Active role lacks required select/insert/update privileges on oc_ontology.")
    return {**row, "table_privileges": table_privileges}


def seed_semantic_context(conn, marker: str) -> dict[str, int]:
    sha = hashlib.sha256(marker.encode("utf-8")).hexdigest()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oc_intake.ingestion_batches(display_name,uploader,source_label,status,file_count,accepted_count,notes)
            VALUES (%s,'build-077-validation','github-actions','COMPLETED',1,1,%s) RETURNING id
            """,
            (f"BUILD-077 validation {marker}", marker),
        )
        batch_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO oc_intake.documents(
              batch_id, original_filename, display_title, media_type, extension, byte_size, sha256, storage_key,
              uploader, processing_status, text_extraction_status, extracted_text,
              preliminary_document_type, classification_confidence, relevance, relevance_confidence,
              relevance_explanation, review_status, provenance
            )
            VALUES (%s,%s,%s,'text/plain','txt',64,%s,%s,'build-077-validation','COMPLETED','COMPLETED',
                    %s,'SCIENTIFIC_TEXT',0.99,'RELEVANT',0.99,'BUILD-077 validation fixture','ACCEPTED',%s)
            RETURNING id
            """,
            (
                batch_id,
                f"{marker}.txt",
                f"BUILD-077 validation document {marker}",
                sha,
                f"build-077-validation/{marker}.txt",
                f"{marker} Species alpha is pollinated by {marker} Pollinator beta.",
                Jsonb({"build": "077", "marker": marker}),
            ),
        )
        document_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO oc_semantic.extraction_sessions(
              document_id, stage, created_by, provenance, completed_at
            ) VALUES (%s,'READY_FOR_REVIEW','build-077-validation',%s,NOW()) RETURNING id
            """,
            (document_id, Jsonb({"build": "077", "marker": marker})),
        )
        session_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO oc_semantic.evidence_objects(
              session_id, evidence_type, exact_text, start_offset, end_offset, source_sha256, provenance
            ) VALUES (%s,'TEXT_SPAN',%s,0,32,%s,%s) RETURNING id
            """,
            (session_id, f"{marker} Species alpha evidence", sha, Jsonb({"build": "077", "marker": marker})),
        )
        evidence_id = cur.fetchone()["id"]

        def entity(name: str, start: int, end: int) -> int:
            cur.execute(
                """
                INSERT INTO oc_semantic.candidates(session_id, kind, confidence, review_status)
                VALUES (%s,'ENTITY',0.99,'ACCEPTED') RETURNING id
                """,
                (session_id,),
            )
            candidate_id = cur.fetchone()["id"]
            cur.execute(
                """
                INSERT INTO oc_semantic.candidate_entities(
                  candidate_id, entity_type, name, normalized_name, start_offset, end_offset, attributes
                ) VALUES (%s,'SPECIES',%s,%s,%s,%s,%s)
                """,
                (candidate_id, name, name.casefold(), start, end, Jsonb({"build": "077", "marker": marker})),
            )
            return candidate_id

        entity_one = entity(f"{marker} Species alpha", 0, 12)
        entity_two = entity(f"{marker} Pollinator beta", 20, 32)
        fuzzy_entity = entity(f"{marker} Species alp", 34, 48)
        unresolved_entity = entity(f"{marker} unmatched concept", 50, 70)
        cur.execute(
            """
            INSERT INTO oc_semantic.candidates(session_id, kind, confidence, review_status)
            VALUES (%s,'RELATIONSHIP',0.97,'ACCEPTED') RETURNING id
            """,
            (session_id,),
        )
        relationship = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO oc_semantic.candidate_relationships(
              candidate_id, subject_candidate_id, predicate, object_candidate_id, evidence_id
            ) VALUES (%s,%s,'POLLINATED_BY',%s,%s)
            """,
            (relationship, entity_one, entity_two, evidence_id),
        )
        cur.execute(
            """
            INSERT INTO oc_semantic.reviews(session_id, decision, actor, notes, candidate_ids, canonical_graph_mutated)
            VALUES (%s,'ACCEPT','build-077-validation',%s,%s,FALSE)
            """,
            (session_id, marker, [entity_one, entity_two, fuzzy_entity, unresolved_entity, relationship]),
        )
    conn.commit()
    return {
        "batch_id": batch_id,
        "document_id": document_id,
        "session_id": session_id,
        "evidence_id": evidence_id,
        "entity_one": entity_one,
        "entity_two": entity_two,
        "fuzzy_entity": fuzzy_entity,
        "unresolved_entity": unresolved_entity,
        "relationship": relationship,
    }


def exercise_services(dsn: str, marker: str, ids: dict[str, int]) -> dict[str, Any]:
    from app.ontology.repositories import PostgresOntologyRepository
    from app.ontology.services import (
        CandidateResolutionService,
        EvidenceRegistryService,
        OntologyRegistryService,
        OntologyTermService,
        PublicationReadinessService,
    )

    repo = PostgresOntologyRepository(dsn)
    registry_service = OntologyRegistryService(repo)
    term_service = OntologyTermService(repo)
    resolution_service = CandidateResolutionService(repo)
    evidence_service = EvidenceRegistryService(repo)
    readiness_service = PublicationReadinessService(repo)

    checksum = hashlib.sha256(f"registry:{marker}".encode("utf-8")).hexdigest()
    registry = registry_service.create_registry(
        {
            "namespace": f"build-077-validation-{marker}",
            "name": f"BUILD-077 validation {marker}",
            "authority": "GitHub Actions validation",
            "source_uri": None,
            "version": marker,
            "ontology_type": "TAXONOMY",
            "checksum": checksum,
            "provenance": {"build": "077", "marker": marker},
            "created_by": "build-077-validation",
        }
    )
    term_one = term_service.create_term(
        {
            "registry_id": registry["id"],
            "canonical_key": f"{marker}_species_alpha",
            "preferred_label": f"{marker} Species alpha",
            "term_type": "TAXON",
            "actor": "build-077-validation",
        }
    )
    term_two = term_service.create_term(
        {
            "registry_id": registry["id"],
            "canonical_key": f"{marker}_pollinator_beta",
            "preferred_label": f"{marker} Pollinator beta",
            "term_type": "TAXON",
            "actor": "build-077-validation",
        }
    )
    synonym = term_service.add_synonym(
        term_one["id"],
        {
            "synonym": f"{marker} Species a.",
            "synonym_type": "COMMON_NAME",
            "provenance": {"build": "077", "marker": marker},
            "actor": "build-077-validation",
        },
    )
    registry_service.activate_registry(registry["id"], "build-077-validation", "validated")

    exact = resolution_service.resolve_one(ids["entity_one"], "build-077-validation")
    accepted_one = resolution_service.decide(exact[0]["id"], "ACCEPTED", "build-077-validation", "exact accepted")
    exact_two = resolution_service.resolve_one(ids["entity_two"], "build-077-validation")
    accepted_two = resolution_service.decide(exact_two[0]["id"], "ACCEPTED", "build-077-validation", "exact accepted")
    fuzzy = resolution_service.resolve_one(ids["fuzzy_entity"], "build-077-validation", fuzzy_threshold=0.75)
    unresolved = resolution_service.resolve_one(ids["unresolved_entity"], "build-077-validation")
    manual = resolution_service.manual_assign(ids["unresolved_entity"], term_one["id"], "build-077-validation", "manual validation")
    rejected_manual = resolution_service.decide(manual["id"], "REJECTED", "build-077-validation", "leave unresolved")

    evidence = evidence_service.register(ids["evidence_id"], "build-077-validation")
    evidence_valid = evidence_service.validate(ids["evidence_id"], "build-077-validation")
    readiness_one = readiness_service.evaluate_candidate(ids["entity_one"], "build-077-validation")
    readiness_two = readiness_service.evaluate_candidate(ids["entity_two"], "build-077-validation")
    readiness_relationship = readiness_service.evaluate_candidate(ids["relationship"], "build-077-validation")
    session_readiness = readiness_service.evaluate_session(ids["session_id"], "build-077-validation")

    return {
        "registry_id": registry["id"],
        "term_ids": [term_one["id"], term_two["id"]],
        "synonym_id": synonym["id"],
        "accepted_resolution_ids": [accepted_one["id"], accepted_two["id"]],
        "fuzzy_status": fuzzy[0]["status"],
        "fuzzy_method": fuzzy[0]["resolution_method"],
        "unresolved_method": unresolved[0]["resolution_method"],
        "manual_rejected_status": rejected_manual["status"],
        "evidence_registry_id": evidence["id"],
        "evidence_validation_status": evidence_valid["validation_status"],
        "readiness": {
            "entity_one": readiness_one["ready_for_publication"],
            "entity_two": readiness_two["ready_for_publication"],
            "relationship": readiness_relationship["ready_for_publication"],
            "session": session_readiness["ready_for_publication"],
            "canonical_graph_mutated": session_readiness["canonical_graph_mutated"],
        },
    }


def expect_raises(conn, sql: str, params: tuple[Any, ...], expected_sqlstate_prefix: str | None = None) -> str:
    try:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(sql, params)
    except Exception as exc:
        sqlstate = getattr(exc, "sqlstate", "")
        if expected_sqlstate_prefix and not str(sqlstate).startswith(expected_sqlstate_prefix):
            raise ValidationError(f"Expected SQLSTATE {expected_sqlstate_prefix}, got {sqlstate}: {exc}") from exc
        return f"{exc.__class__.__name__}:{sqlstate}"
    raise ValidationError("Expected PostgreSQL to reject invalid mutation, but it succeeded.")


def negative_constraint_tests(conn, ids: dict[str, int], service_result: dict[str, Any]) -> dict[str, str]:
    registry_id = service_result["registry_id"]
    term_one, term_two = service_result["term_ids"]
    evidence_registry_id = service_result["evidence_registry_id"]
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO oc_ontology.ontology_registries(
              namespace,name,authority,version,ontology_type,status,checksum,provenance,created_by
            ) VALUES (%s,'link validation','GitHub Actions',%s,'TAXONOMY','DRAFT',%s,%s,'build-077-validation')
            RETURNING id
            """,
            (f"build-077-link-{int(time.time())}", f"link-{int(time.time())}", "b" * 64, Jsonb({"build": "077"})),
        )
        other_registry_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO oc_ontology.ontology_terms(
              registry_id, canonical_key, preferred_label, normalized_label, term_type
            ) VALUES (%s,'other','Other','other','TAXON') RETURNING id
            """,
            (other_registry_id,),
        )
        other_term_id = cur.fetchone()["id"]
    conn.commit()
    return {
        "evidence_hash_immutable": expect_raises(
            conn,
            "UPDATE oc_ontology.evidence_registry SET evidence_hash=%s WHERE id=%s",
            ("0" * 64, evidence_registry_id),
            "P",
        ),
        "same_registry_term_link": expect_raises(
            conn,
            "UPDATE oc_ontology.ontology_terms SET parent_term_id=%s WHERE id=%s",
            (other_term_id, term_one),
            "P",
        ),
        "entity_only_resolution": expect_raises(
            conn,
            """
            INSERT INTO oc_ontology.candidate_resolutions(
              candidate_id, ontology_term_id, resolution_method, confidence, status,
              normalized_input, matched_label, ontology_namespace, ontology_version, explanation, provenance
            ) VALUES (%s,%s,'MANUAL',1.0,'PROPOSED','relationship','relationship','validation','1',%s,%s)
            """,
            (ids["relationship"], term_two, Jsonb({"negative": "relationship"}), Jsonb({"build": "077"})),
            "P",
        ),
        "accepted_requires_term": expect_raises(
            conn,
            """
            INSERT INTO oc_ontology.candidate_resolutions(
              candidate_id, ontology_term_id, resolution_method, confidence, status,
              normalized_input, matched_label, ontology_namespace, ontology_version, explanation, provenance
            ) VALUES (%s,NULL,'UNRESOLVED',0.0,'ACCEPTED','missing','missing',NULL,NULL,%s,%s)
            """,
            (ids["entity_one"], Jsonb({"negative": "accepted-without-term"}), Jsonb({"build": "077"})),
            "23",
        ),
        "readiness_invariant": expect_raises(
            conn,
            """
            INSERT INTO oc_ontology.publication_readiness(
              candidate_id,evidence_complete,ontology_resolved,review_complete,provenance_complete,
              ready_for_publication,blockers,evaluated_by,evaluation_version,is_current
            ) VALUES (%s,FALSE,FALSE,FALSE,FALSE,TRUE,%s,'build-077-validation','negative',FALSE)
            """,
            (ids["entity_one"], Jsonb(["BLOCKED"])),
            "23",
        ),
    }


def exercise_api(marker: str) -> dict[str, Any]:
    os.environ["CALYX_API_KEY"] = "build-077-validation-api-key"
    from app.main import app

    client = TestClient(app)
    unauth = client.get("/api/ontology/registries")
    if unauth.status_code != 401:
        raise ValidationError(f"Expected unauthenticated request rejection, got {unauth.status_code}")
    headers = {"X-API-Key": "build-077-validation-api-key"}
    auth = client.get("/api/ontology/registries", headers=headers)
    if auth.status_code != 200:
        raise ValidationError(f"Expected authenticated registry list, got {auth.status_code}: {auth.text}")
    paths = [route.path for route in app.routes]
    publication_routes = [path for path in paths if path.startswith("/api/ontology") and "publish" in path.lower()]
    if publication_routes:
        raise ValidationError(f"Unexpected publication routes: {publication_routes}")
    return {
        "unauthorized_status": unauth.status_code,
        "authenticated_status": auth.status_code,
        "ontology_route_count": len([path for path in paths if path.startswith("/api/ontology")]),
        "publication_routes": publication_routes,
    }


def run_command(args: list[str], *, expose_database_url: bool = False) -> str:
    env = os.environ.copy()
    if not expose_database_url:
        env.pop("DATABASE_URL", None)
        env.pop("TEST_DATABASE_URL", None)
    completed = subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True, env=env)
    return completed.stdout.strip()


def run_regressions() -> dict[str, str]:
    return {
        "build_077_focused": run_command([sys.executable, "-m", "pytest", "tests/test_build_077_ontology_registry.py", "-q"]),
        "build_076b_regression": run_command([sys.executable, "-m", "pytest", "tests/test_build_076b_semantic_extraction.py", "-q"]),
        "postgres_backed": run_command([sys.executable, "-m", "pytest", "tests/test_build_067_pg_writer.py", "-q"], expose_database_url=True),
        "complete_backend": run_command([sys.executable, "-m", "pytest", "-q"]),
        "compile": run_command([sys.executable, "-m", "compileall", "-q", "app", "tests"]),
    }


def main() -> int:
    dsn = require_database_url()
    target = redacted_target(dsn)
    print("Sanitized database target:", json.dumps(target, sort_keys=True))
    marker = f"build077_{int(time.time())}"

    with psycopg.connect(dsn, row_factory=dict_row, connect_timeout=10) as conn:
        with conn.cursor() as cur:
            identity = fetch_one(
                cur,
                """
                SELECT current_database() AS database_name,
                       current_user AS active_role,
                       version() AS postgres_version,
                       inet_server_addr()::text AS server_address,
                       inet_server_port() AS server_port
                """,
            )
            print("Database identity:", json.dumps(identity, sort_keys=True))
            known_schemas = [row["schema_name"] for row in cur.execute(
                """
                SELECT schema_name FROM information_schema.schemata
                WHERE schema_name IN ('oc_intake','oc_semantic','oc_ontology','oc_graph')
                ORDER BY schema_name
                """
            ).fetchall()]
            if "oc_intake" not in known_schemas:
                raise ValidationError(f"Target does not look like Orchid Continuum; schemas found: {known_schemas}")
            graph_taxonomy = graph_taxonomy_schemas(cur)
            watched_schemas = sorted(set(["oc_intake", "oc_semantic", "oc_ontology"] + graph_taxonomy))
            pre_counts = relation_counts(cur, watched_schemas)
            graph_taxonomy_pre_counts = relation_counts(cur, graph_taxonomy) if graph_taxonomy else {}
            graph_taxonomy_pre_fingerprint = object_fingerprint(cur, graph_taxonomy) if graph_taxonomy else None

        applied = ensure_migrations(conn)
        object_report = validate_objects(conn)
        permissions = permissions_report(conn)
        ids = seed_semantic_context(conn, marker)
        service_result = exercise_services(dsn, marker, ids)
        negative_results = negative_constraint_tests(conn, ids, service_result)
        api_result = exercise_api(marker)

        with conn.cursor() as cur:
            post_counts = relation_counts(cur, watched_schemas)
            graph_taxonomy_post_counts = relation_counts(cur, graph_taxonomy) if graph_taxonomy else {}
            graph_taxonomy_post_fingerprint = object_fingerprint(cur, graph_taxonomy) if graph_taxonomy else None
            audit_count = fetch_one(
                cur,
                "SELECT COUNT(*) AS count FROM oc_ontology.ontology_audit_events WHERE actor='build-077-validation'",
            )["count"]

    if graph_taxonomy_pre_counts != graph_taxonomy_post_counts:
        raise ValidationError("Canonical graph/taxonomy row counts changed.")
    if graph_taxonomy_pre_fingerprint != graph_taxonomy_post_fingerprint:
        raise ValidationError("Canonical graph/taxonomy object definitions changed.")
    if not service_result["readiness"]["canonical_graph_mutated"]:
        canonical_graph_mutated = False
    else:
        raise ValidationError("Readiness reported canonical_graph_mutated=true.")

    regressions = run_regressions()
    report = {
        "database_url_available": True,
        "secret_supply": "GitHub Actions repository secret DATABASE_URL, scoped to BUILD-077 validation job env",
        "target": target,
        "migrations_applied": applied,
        "object_report": object_report,
        "permissions": permissions,
        "pre_counts": pre_counts,
        "post_counts": post_counts,
        "graph_taxonomy_schemas": graph_taxonomy,
        "graph_taxonomy_counts_unchanged": graph_taxonomy_pre_counts == graph_taxonomy_post_counts,
        "graph_taxonomy_definitions_unchanged": graph_taxonomy_pre_fingerprint == graph_taxonomy_post_fingerprint,
        "seeded_validation_ids": ids,
        "service_result": service_result,
        "negative_constraint_results": negative_results,
        "api_result": api_result,
        "audit_events_for_validation_actor": audit_count,
        "canonical_graph_mutated": canonical_graph_mutated,
        "regressions": regressions,
    }
    print("BUILD-077 PostgreSQL validation report:")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"BUILD-077 PostgreSQL validation failed: {exc}", file=sys.stderr)
        raise
