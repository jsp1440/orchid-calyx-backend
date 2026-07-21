import json
import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from app.knowledge_publication import (
    LifecycleAuthority,
    LifecycleReason,
    OperationalReadinessReport,
    PostgresPublicationReadinessRepository,
    PublicationExecutionRequest,
    ReadinessFinding,
    ReadinessSeverity,
    ReadinessValidationError,
    RetractionReason,
)


def test_readiness_contract_is_structured_immutable_and_fail_closed():
    finding = ReadinessFinding(
        "provenance", "MISSING", ReadinessSeverity.CRITICAL, "quarantine", 1
    )
    report = OperationalReadinessReport(
        False, {}, 0.0, {}, {}, {}, (finding,)
    )
    with pytest.raises(FrozenInstanceError):
        finding.count = 0
    assert not report.healthy and report.findings[0].recommended_action == "quarantine"
    with pytest.raises(ValueError, match="DATABASE_URL_REQUIRED"):
        PostgresPublicationReadinessRepository("")
    with pytest.raises(ReadinessValidationError, match="READINESS_VALIDATION_UNAVAILABLE"):
        PostgresPublicationReadinessRepository(
            "postgresql://invalid:invalid@127.0.0.1:1/invalid"
        ).validate()


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_complete_pipeline_lifecycle_reconstruction_and_readiness():
    import psycopg

    from app.knowledge_publication.graph_postgres_repository import (
        PostgresControlledGraphRepository,
    )
    from app.knowledge_publication.lifecycle_postgres_repository import (
        PostgresPublicationLifecycleRepository,
    )

    dsn = os.environ["TEST_DATABASE_URL"]
    suffix = uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as con:
        for migration in (
            "087b_context_preserving_interpretation.sql",
            "088b_publication_registry_policy_foundation.sql",
            "088c_atomic_graph_transaction_publication_engine.sql",
            "088d_publication_lifecycle_corrections_rollback.sql",
        ):
            con.execute(Path("migrations", migration).read_text())
        con.execute("CREATE SCHEMA IF NOT EXISTS oc_graph")
        con.execute(
            """CREATE TABLE IF NOT EXISTS oc_graph.kg_nodes(
            kg_node_id BIGSERIAL PRIMARY KEY,node_type TEXT NOT NULL,canonical_key TEXT NOT NULL,
            display_label TEXT,source_table TEXT,source_pk TEXT,evidence_class TEXT,
            confidence_score NUMERIC,confidence_label TEXT,payload_json JSONB NOT NULL DEFAULT '{}',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(node_type,canonical_key))"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS oc_graph.kg_edges(
            kg_edge_id BIGSERIAL PRIMARY KEY,edge_type TEXT NOT NULL,
            from_node_id BIGINT NOT NULL REFERENCES oc_graph.kg_nodes,
            to_node_id BIGINT NOT NULL REFERENCES oc_graph.kg_nodes,source_table TEXT,
            source_pk TEXT,evidence_class TEXT,confidence_score NUMERIC,confidence_label TEXT,
            rule_name TEXT,payload_json JSONB NOT NULL DEFAULT '{}',is_active BOOLEAN NOT NULL DEFAULT TRUE,
            updated_at TIMESTAMPTZ DEFAULT NOW())"""
        )
        policy = con.execute(
            "INSERT INTO oc_knowledge_publication.policy_versions(policy_id,version,name,rules,provenance,fingerprint) VALUES(%s,1,'BUILD-088E test','{}','{}',%s) RETURNING policy_version_id",
            (f"policy-{suffix}", f"policy-{suffix}"),
        ).fetchone()[0]
        con.execute(
            "INSERT INTO oc_knowledge_publication.policy_lifecycle_events(policy_version_id,state,actor) VALUES(%s,'DRAFT','test'),(%s,'ACTIVE','test')",
            (policy, policy),
        )

        def seed(label: str, assertion_key: str, version: int) -> int:
            packet = con.execute(
                "INSERT INTO oc_scientific_interpretation.evidence_packets(packet_key,version,fingerprint,payload) VALUES(%s,1,%s,%s::jsonb) RETURNING packet_id",
                (
                    f"packet-{suffix}-{label}",
                    f"packet-{suffix}-{label}",
                    json.dumps(
                        {
                            "context_form": "LINKED_SENTENCES",
                            "sources": [
                                {
                                    "source_object_id": f"source-{label}",
                                    "source_revision_id": version + 1000,
                                    "anchors": [{"anchor_id": label, "content_hash": label}],
                                    "copyright_policy": "DERIVED_FACTS_ALLOWED",
                                }
                            ],
                        }
                    ),
                ),
            ).fetchone()[0]
            interpretation = con.execute(
                "INSERT INTO oc_scientific_interpretation.machine_interpretations(interpretation_key,version,fingerprint,payload) VALUES(%s,1,%s,%s::jsonb) RETURNING interpretation_id",
                (
                    f"interpretation-{suffix}-{label}",
                    f"interpretation-{suffix}-{label}",
                    json.dumps({"packet_ids": [packet], "model": "deterministic-test"}),
                ),
            ).fetchone()[0]
            routing = con.execute(
                "INSERT INTO oc_scientific_interpretation.routing_decisions(interpretation_id,policy_name,policy_version,path,fingerprint,payload) VALUES(%s,'build-087','1','AUTOMATIC_PROMOTION',%s,%s::jsonb) RETURNING routing_decision_id",
                (
                    interpretation,
                    f"routing-{suffix}-{label}",
                    json.dumps({"path": "AUTOMATIC_PROMOTION", "hard_failures": []}),
                ),
            ).fetchone()[0]
            assertion = {
                "published": False,
                "publication_eligible": True,
                "routing_decision_id": routing,
                "supporting_interpretation_ids": [interpretation],
                "conflicting_interpretation_ids": [],
                "normalized_statement": {
                    "assertion_type": "TRAIT",
                    "subject": f"Masdevallia {label}",
                    "predicate": "HAS_TRAIT",
                    "object": f"trait {label}",
                    "units": "categorical",
                    "negation": False,
                },
                "scientific_scope": {
                    "scientific_domain": "BOTANY",
                    "taxonomy_concept_id": f"taxon:{label}",
                    "taxonomy_version": "2026.1",
                    "taxonomy_unambiguous": True,
                    "impact_class": "STANDARD",
                },
            }
            assertion_id = con.execute(
                "INSERT INTO oc_scientific_interpretation.canonical_assertions(assertion_key,version,fingerprint,payload) VALUES(%s,%s,%s,%s::jsonb) RETURNING assertion_id",
                (assertion_key, version, f"assertion-{suffix}-{label}", json.dumps(assertion)),
            ).fetchone()[0]
            assertion.update({"assertion_id": assertion_id, "version": version})
            provenance = [
                {
                    "source_object_id": f"source-{label}",
                    "source_revision_id": version + 1000,
                    "interpretation_id": interpretation,
                    "evidence_packet_id": packet,
                    "anchor_ids": [label],
                    "copyright_policy": "DERIVED_FACTS_ALLOWED",
                }
            ]
            trusted = {
                "assertion": assertion,
                "eligibility_decision": {"routing_decision_id": routing},
                "provenance_roots": provenance,
            }
            publication_id = con.execute(
                """INSERT INTO oc_knowledge_publication.publication_candidates(
                assertion_id,assertion_version,eligibility_decision_id,eligibility_decision_version,
                policy_version_id,requested_pathway,idempotency_key,fingerprint,correlation_id,created_by,
                assertion_type,scientific_domain,taxonomy_concept_id,taxonomy_version,scientific_scope,
                qualifiers,supporting_evidence_refs,conflicting_evidence_refs,provenance_root_refs,
                immutable_metadata,trusted_snapshot) VALUES(
                %s,%s,%s,1,%s,'AUTOMATIC_GOVERNED_PUBLICATION',%s,%s,%s,'test','TRAIT','BOTANY',
                %s,'2026.1',%s::jsonb,'{}',%s::jsonb,'[]',%s::jsonb,'{}',%s::jsonb) RETURNING publication_id""",
                (
                    assertion_id,
                    version,
                    routing,
                    policy,
                    f"key-{suffix}-{label}",
                    f"publication-{suffix}-{label}",
                    f"corr-{suffix}-{label}",
                    f"taxon:{label}",
                    json.dumps(assertion["scientific_scope"]),
                    json.dumps([interpretation]),
                    json.dumps(provenance),
                    json.dumps(trusted),
                ),
            ).fetchone()[0]
            con.execute(
                "INSERT INTO oc_knowledge_publication.lifecycle_transitions(publication_id,state,actor) VALUES(%s,'PUBLICATION_CANDIDATE','test'),(%s,'VALIDATING','test'),(%s,'AUTHORIZED','authority')",
                (publication_id, publication_id, publication_id),
            )
            con.execute(
                """INSERT INTO oc_knowledge_publication.authorization_decisions(
                publication_id,publication_version,assertion_id,assertion_version,eligibility_decision_id,
                eligibility_decision_version,policy_version_id,requested_pathway,resolved_pathway,outcome,
                decision,fingerprint,actor,correlation_id) VALUES(
                %s,1,%s,%s,%s,1,%s,'AUTOMATIC_GOVERNED_PUBLICATION',
                'AUTOMATIC_GOVERNED_PUBLICATION','AUTHORIZED','{}',%s,'authority',%s)""",
                (
                    publication_id,
                    assertion_id,
                    version,
                    routing,
                    policy,
                    f"decision-{suffix}-{label}",
                    f"corr-{suffix}-{label}",
                ),
            )
            return publication_id

        publications = {
            "new": seed("new", f"assertion-{suffix}-new", 1),
            "prior": seed("prior", f"assertion-{suffix}-correction", 1),
            "successor": seed("successor", f"assertion-{suffix}-correction", 2),
            "withdraw": seed("withdraw", f"assertion-{suffix}-withdraw", 1),
            "retract": seed("retract", f"assertion-{suffix}-retract", 1),
            "dependent": seed("dependent", f"assertion-{suffix}-dependent", 1),
            "rollback": seed("rollback", f"assertion-{suffix}-rollback", 1),
        }
        con.execute(
            "INSERT INTO oc_knowledge_publication.publication_dependencies(source_publication_id,dependent_publication_id,dependency_type,fingerprint) VALUES(%s,%s,'SUPPORTS',%s)",
            (publications["retract"], publications["dependent"], f"dependency-{suffix}"),
        )

    graph = PostgresControlledGraphRepository(dsn)
    for label, publication_id in publications.items():
        request = PublicationExecutionRequest(
            publication_id, 1, "controlled-publication-service", f"corr-{suffix}-{label}"
        )
        if label == "new":
            with ThreadPoolExecutor(max_workers=3) as pool:
                outcomes = [
                    item["outcome"] for item in pool.map(lambda _: graph.publish(request), range(3))
                ]
            assert outcomes.count("PUBLISHED") == 1
            assert outcomes.count("NO_OP_DUPLICATE") == 2
        else:
            assert graph.publish(request)["outcome"] == "PUBLISHED"

    lifecycle = PostgresPublicationLifecycleRepository(dsn)
    authority = LifecycleAuthority("lifecycle-service", "authority:088e", f"corr-{suffix}")
    lifecycle.supersede(
        publications["prior"],
        publications["successor"],
        authority,
        LifecycleReason("CORRECTED_ASSERTION", "Corrected assertion version"),
    )
    lifecycle.withdraw(
        publications["withdraw"], authority, LifecycleReason("WITHDRAWN", "Withdrawn")
    )
    lifecycle.restore(
        publications["withdraw"], authority, LifecycleReason("RESTORED", "Restored")
    )
    lifecycle.retract(
        publications["retract"],
        authority,
        LifecycleReason(
            RetractionReason.SOURCE_FORMALLY_RETRACTED.value, "Source retracted"
        ),
        {"source_revision_id": 1001},
    )
    rollback = lifecycle.prepare_rollback(
        publications["rollback"],
        authority,
        LifecycleReason("IMMEDIATE_TECHNICAL_INVALIDITY", "Invalid projection"),
        "build-088e-validator",
    )
    assert lifecycle.execute_rollback(rollback["rollback_id"], authority)["outcome"] == "ROLLED_BACK"

    report = PostgresPublicationReadinessRepository(dsn).require_healthy()
    assert report.provenance_coverage == 1.0
    assert report.counts["graph_versions"] == 7
    assert report.counts["rollback_events"] == 1
    assert report.counts["reevaluation_events"] >= 1
    assert report.duplicate_suppression_counts["publication_idempotency"] == 2
    assert all(value >= 0 for value in report.latency_ms.values())

    with psycopg.connect(dsn) as con:
        versions = con.execute(
            "SELECT sequence,parent_graph_version_id FROM oc_knowledge_publication.graph_versions ORDER BY sequence"
        ).fetchall()
        assert len(versions) == 7 and versions[0][1] is None
        chain = con.execute(
            "SELECT count(*) FROM oc_knowledge_publication.graph_provenance_links p "
            "JOIN oc_knowledge_publication.publication_candidates c USING(publication_id) "
            "JOIN oc_scientific_interpretation.canonical_assertions a ON a.assertion_id=p.assertion_id"
        ).fetchone()[0]
        assert chain > 0
