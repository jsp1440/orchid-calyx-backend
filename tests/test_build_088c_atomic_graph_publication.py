import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.knowledge_publication.graph_mapping import AssertionGraphMapper, stable_id
from app.knowledge_publication.graph_models import PublicationExecutionRequest


def assertion(**overrides):
    statement = {
        "assertion_type": "TRAIT",
        "subject": "Masdevallia veitchiana",
        "predicate": "HAS_TRAIT",
        "object": "orange sepals",
        "units": "categorical",
        "life_stage": "flowering",
        "geography": "Peru",
        "negation": False,
        "uncertainty": {"confidence": 0.96},
    }
    statement.update(overrides.pop("statement", {}))
    scope = {
        "scientific_domain": "BOTANY",
        "taxonomy_unambiguous": True,
        "taxonomy_concept_id": "taxon:mv",
        "taxonomy_version": "2026.1",
        "impact_class": "STANDARD",
    }
    scope.update(overrides.pop("scope", {}))
    return {
        "assertion_id": 3,
        "version": 2,
        "normalized_statement": statement,
        "scientific_scope": scope,
        "supporting_interpretation_ids": [7],
        "conflicting_interpretation_ids": [8],
        **overrides,
    }


def publication():
    return {
        "publication_id": 11,
        "publication_version": 1,
        "assertion_id": 3,
        "assertion_version": 2,
    }


def test_mapping_is_deterministic_qualified_and_context_preserving():
    mapper = AssertionGraphMapper()
    first = mapper.map(assertion(), publication())
    assert first == mapper.map(assertion(), publication())
    assert [item.order for item in first] == list(range(len(first)))
    qualified = next(
        item for item in first if item.payload.get("node_type") == "qualified_assertion"
    )
    assert qualified.payload["context"]["life_stage"] == "flowering"
    assert qualified.payload["context"]["geography"] == "Peru"
    assert (
        "uncertainty" in qualified.payload["context"]
        and qualified.payload["negation"] is False
    )
    assert {item.operation_type.value for item in first} >= {
        "CREATE_NODE",
        "CREATE_EDGE",
        "ADD_ASSERTION_SUPPORT",
        "ADD_CONFLICTING_EVIDENCE",
    }


def test_mapping_preserves_material_distinctions_in_identifiers():
    mapper = AssertionGraphMapper()
    positive = mapper.map(assertion(), publication())
    negative = mapper.map(assertion(statement={"negation": True}), publication())
    positive_assertion = next(
        item.object_key
        for item in positive
        if item.payload.get("node_type") == "qualified_assertion"
    )
    negative_assertion = next(
        item.object_key
        for item in negative
        if item.payload.get("node_type") == "qualified_assertion"
    )
    assert positive_assertion != negative_assertion
    assert stable_id("x", {"a": 1, "b": 2}) == stable_id("x", {"b": 2, "a": 1})


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"statement": {"predicate": "UNSUPPORTED"}}, "UNSUPPORTED_PREDICATE"),
        ({"scope": {"taxonomy_concept_id": None}}, "TAXONOMY_RESOLUTION_REQUIRED"),
        ({"statement": {"measurement": 2, "units": None}}, "UNSAFE_UNIT_NORMALIZATION"),
    ],
)
def test_mapping_fails_closed(change, reason):
    with pytest.raises(ValueError, match=reason):
        AssertionGraphMapper().map(assertion(**change), publication())


def test_execution_request_prevents_mass_assignment_surface():
    request = PublicationExecutionRequest(
        1, 1, "controlled-publication-service", "corr"
    )
    assert not hasattr(request, "authorization") and not hasattr(
        request, "graph_version"
    )
    with pytest.raises((AttributeError, TypeError)):
        request.publication_id = 2


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_atomic_idempotent_concurrent_publication_and_rollback():
    import json
    import uuid
    import psycopg
    from app.knowledge_publication.graph_postgres_repository import (
        PostgresControlledGraphRepository,
    )

    dsn = os.environ["TEST_DATABASE_URL"]
    suffix = uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as con:
        for migration in (
            "087b_context_preserving_interpretation.sql",
            "088b_publication_registry_policy_foundation.sql",
            "088c_atomic_graph_transaction_publication_engine.sql",
        ):
            con.execute(Path("migrations", migration).read_text())
        con.execute("CREATE SCHEMA IF NOT EXISTS oc_graph")
        con.execute(
            """CREATE TABLE IF NOT EXISTS oc_graph.kg_nodes(kg_node_id BIGSERIAL PRIMARY KEY,node_type TEXT NOT NULL,canonical_key TEXT NOT NULL,display_label TEXT,source_table TEXT,source_pk TEXT,evidence_class TEXT,confidence_score NUMERIC,confidence_label TEXT,payload_json JSONB NOT NULL DEFAULT '{}',is_active BOOLEAN NOT NULL DEFAULT TRUE,updated_at TIMESTAMPTZ DEFAULT NOW(),UNIQUE(node_type,canonical_key))"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS oc_graph.kg_edges(kg_edge_id BIGSERIAL PRIMARY KEY,edge_type TEXT NOT NULL,from_node_id BIGINT NOT NULL REFERENCES oc_graph.kg_nodes,to_node_id BIGINT NOT NULL REFERENCES oc_graph.kg_nodes,source_table TEXT,source_pk TEXT,evidence_class TEXT,confidence_score NUMERIC,confidence_label TEXT,rule_name TEXT,payload_json JSONB NOT NULL DEFAULT '{}',is_active BOOLEAN NOT NULL DEFAULT TRUE,updated_at TIMESTAMPTZ DEFAULT NOW())"""
        )
        packet = con.execute(
            "INSERT INTO oc_scientific_interpretation.evidence_packets(packet_key,version,fingerprint,payload) VALUES(%s,1,%s,%s::jsonb) RETURNING packet_id",
            (
                f"p-{suffix}",
                f"p-{suffix}",
                json.dumps(
                    {
                        "sources": [
                            {
                                "source_object_id": 1,
                                "source_revision_id": 101,
                                "copyright_policy": "DERIVED_FACTS_ALLOWED",
                                "anchors": [{"anchor_id": 1, "content_hash": "abc"}],
                            }
                        ]
                    }
                ),
            ),
        ).fetchone()[0]
        interpretation = con.execute(
            "INSERT INTO oc_scientific_interpretation.machine_interpretations(interpretation_key,version,fingerprint,payload) VALUES(%s,1,%s,%s::jsonb) RETURNING interpretation_id",
            (f"i-{suffix}", f"i-{suffix}", json.dumps({"packet_ids": [packet]})),
        ).fetchone()[0]
        routing = con.execute(
            "INSERT INTO oc_scientific_interpretation.routing_decisions(interpretation_id,policy_name,policy_version,path,fingerprint,payload) VALUES(%s,'p','1','AUTOMATIC_PROMOTION',%s,%s::jsonb) RETURNING routing_decision_id",
            (
                interpretation,
                f"r-{suffix}",
                json.dumps({"path": "AUTOMATIC_PROMOTION", "hard_failures": []}),
            ),
        ).fetchone()[0]
        assertion_payload = assertion(
            assertion_id=None,
            version=None,
            supporting_interpretation_ids=[interpretation],
            conflicting_interpretation_ids=[],
            routing_decision_id=routing,
            publication_eligible=True,
            published=False,
        )
        assertion_id = con.execute(
            "INSERT INTO oc_scientific_interpretation.canonical_assertions(assertion_key,version,fingerprint,payload) VALUES(%s,1,%s,%s::jsonb) RETURNING assertion_id",
            (f"a-{suffix}", f"a-{suffix}", json.dumps(assertion_payload)),
        ).fetchone()[0]
        assertion_payload.update({"assertion_id": assertion_id, "version": 1})
        policy_pk = con.execute(
            "INSERT INTO oc_knowledge_publication.policy_versions(policy_id,version,name,rules,provenance,fingerprint) VALUES(%s,1,'test','{}','{}',%s) RETURNING policy_version_id",
            (f"policy-{suffix}", f"policy-{suffix}"),
        ).fetchone()[0]
        con.execute(
            "INSERT INTO oc_knowledge_publication.policy_lifecycle_events(policy_version_id,state,actor) VALUES(%s,'DRAFT','test'),(%s,'ACTIVE','test')",
            (policy_pk, policy_pk),
        )
        trusted = {
            "assertion": assertion_payload,
            "eligibility_decision": {
                "routing_decision_id": routing,
                "path": "AUTOMATIC_PROMOTION",
                "hard_failures": [],
            },
            "provenance_roots": [
                {
                    "source_object_id": 1,
                    "source_revision_id": 101,
                    "copyright_policy": "DERIVED_FACTS_ALLOWED",
                }
            ],
        }
        publication_id = con.execute(
            """INSERT INTO oc_knowledge_publication.publication_candidates(assertion_id,assertion_version,eligibility_decision_id,eligibility_decision_version,policy_version_id,requested_pathway,idempotency_key,fingerprint,correlation_id,created_by,assertion_type,scientific_domain,taxonomy_concept_id,taxonomy_version,scientific_scope,qualifiers,supporting_evidence_refs,conflicting_evidence_refs,provenance_root_refs,immutable_metadata,trusted_snapshot) VALUES(%s,1,%s,1,%s,'AUTOMATIC_GOVERNED_PUBLICATION',%s,%s,%s,'test','TRAIT','BOTANY','taxon:mv','2026.1',%s::jsonb,'{}','[]','[]',%s::jsonb,'{}',%s::jsonb) RETURNING publication_id""",
            (
                assertion_id,
                routing,
                policy_pk,
                f"key-{suffix}",
                f"fp-{suffix}",
                f"corr-{suffix}",
                json.dumps(assertion_payload["scientific_scope"]),
                json.dumps(trusted["provenance_roots"]),
                json.dumps(trusted),
            ),
        ).fetchone()[0]
        con.execute(
            "INSERT INTO oc_knowledge_publication.lifecycle_transitions(publication_id,state,actor) VALUES(%s,'PUBLICATION_CANDIDATE','test'),(%s,'VALIDATING','test'),(%s,'AUTHORIZED','test')",
            (publication_id, publication_id, publication_id),
        )
        con.execute(
            "INSERT INTO oc_knowledge_publication.authorization_decisions(publication_id,publication_version,assertion_id,assertion_version,eligibility_decision_id,eligibility_decision_version,policy_version_id,requested_pathway,resolved_pathway,outcome,decision,fingerprint,actor,correlation_id) VALUES(%s,1,%s,1,%s,1,%s,'AUTOMATIC_GOVERNED_PUBLICATION','AUTOMATIC_GOVERNED_PUBLICATION','AUTHORIZED','{}',%s,'authority',%s)",
            (
                publication_id,
                assertion_id,
                routing,
                policy_pk,
                f"decision-{suffix}",
                f"corr-{suffix}",
            ),
        )
    request = PublicationExecutionRequest(
        publication_id, 1, "controlled-publication-service", f"corr-{suffix}"
    )
    repo = PostgresControlledGraphRepository(dsn)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repo.publish(request), range(2)))
    assert {result["outcome"] for result in results} == {"PUBLISHED", "NO_OP_DUPLICATE"}
    with psycopg.connect(dsn) as con:
        assert (
            con.execute(
                "SELECT count(*) FROM oc_knowledge_publication.graph_versions WHERE publication_id=%s",
                (publication_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            con.execute(
                "SELECT state FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=%s ORDER BY transition_id DESC LIMIT 1",
                (publication_id,),
            ).fetchone()[0]
            == "PUBLISHED"
        )
        assert (
            con.execute(
                "SELECT count(*) FROM oc_knowledge_publication.graph_provenance_links WHERE publication_id=%s",
                (publication_id,),
            ).fetchone()[0]
            > 0
        )
