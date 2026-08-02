import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.knowledge_publication.lifecycle_models import (
    LifecycleAuthority,
    LifecycleReason,
    RetractionReason,
)


def test_authority_and_reason_are_immutable_and_complete():
    authority = LifecycleAuthority("lifecycle-service", "decision:42", "corr")
    reason = LifecycleReason(
        "PUBLISHER_WITHDRAWAL", "Publisher no longer endorses this publication"
    )
    with pytest.raises((AttributeError, TypeError)):
        authority.service_identity = "caller"
    assert reason.reason_code == "PUBLISHER_WITHDRAWAL"
    with pytest.raises(ValueError, match="TRUSTED_LIFECYCLE_AUTHORITY_REQUIRED"):
        LifecycleAuthority("", "x", "c")


def test_retraction_reasons_are_explicit_and_distinct():
    assert (
        RetractionReason.SOURCE_FORMALLY_RETRACTED
        != RetractionReason.PUBLICATION_POLICY_VIOLATION
    )
    assert len(RetractionReason) == 9


def test_migration_is_additive_and_has_projection_and_immutability_controls():
    sql = Path(
        "migrations/088d_publication_lifecycle_corrections_rollback.sql"
    ).read_text()
    assert "TRUNCATE" not in sql and "DROP TABLE" not in sql
    assert "current_publication_projection" in sql and "rollback_manifests" in sql
    assert "protect_088d_" in sql and "REEVALUATION_REQUIRED" in sql


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_lifecycle_concurrency_projections_propagation_and_rollback():
    import json
    import uuid

    import psycopg

    from app.knowledge_publication.lifecycle_postgres_repository import (
        PostgresPublicationLifecycleRepository,
    )

    dsn = os.environ["TEST_DATABASE_URL"]
    suffix = uuid.uuid4().hex
    with psycopg.connect(dsn, autocommit=True) as con:
        for name in (
            "087b_context_preserving_interpretation.sql",
            "088b_publication_registry_policy_foundation.sql",
            "088c_atomic_graph_transaction_publication_engine.sql",
            "088d_publication_lifecycle_corrections_rollback.sql",
        ):
            con.execute(Path("migrations", name).read_text())
        policy = con.execute(
            "INSERT INTO oc_knowledge_publication.policy_versions(policy_id,version,name,rules,provenance,fingerprint) VALUES(%s,1,'test','{}','{}',%s) RETURNING policy_version_id",
            (f"policy-{suffix}", f"policy-{suffix}"),
        ).fetchone()[0]
        con.execute(
            "INSERT INTO oc_knowledge_publication.policy_lifecycle_events(policy_version_id,state,actor) VALUES(%s,'DRAFT','test'),(%s,'ACTIVE','test')",
            (policy, policy),
        )

        def seed(version, sequence):
            interp = con.execute(
                "INSERT INTO oc_scientific_interpretation.machine_interpretations(interpretation_key,version,fingerprint,payload) VALUES(%s,1,%s,'{\"packet_ids\":[]}') RETURNING interpretation_id",
                (f"i-{suffix}-{version}", f"i-{suffix}-{version}"),
            ).fetchone()[0]
            route = con.execute(
                "INSERT INTO oc_scientific_interpretation.routing_decisions(interpretation_id,policy_name,policy_version,path,fingerprint,payload) VALUES(%s,'p','1','AUTOMATIC_PROMOTION',%s,'{\"hard_failures\":[],\"path\":\"AUTOMATIC_PROMOTION\"}') RETURNING routing_decision_id",
                (interp, f"r-{suffix}-{version}"),
            ).fetchone()[0]
            payload = {
                "published": False,
                "publication_eligible": True,
                "routing_decision_id": route,
                "supporting_interpretation_ids": [interp],
                "conflicting_interpretation_ids": [],
                "normalized_statement": {"assertion_type": "TRAIT"},
                "scientific_scope": {
                    "scientific_domain": "BOTANY",
                    "taxonomy_concept_id": "taxon:x",
                    "taxonomy_version": "1",
                    "taxonomy_unambiguous": True,
                },
            }
            aid = con.execute(
                "INSERT INTO oc_scientific_interpretation.canonical_assertions(assertion_key,version,fingerprint,payload) VALUES(%s,%s,%s,%s::jsonb) RETURNING assertion_id",
                (f"a-{suffix}", version, f"a-{suffix}-{version}", json.dumps(payload)),
            ).fetchone()[0]
            payload.update({"assertion_id": aid, "version": version})
            trusted = {
                "assertion": payload,
                "provenance_roots": [{"source_revision_id": version}],
            }
            pid = con.execute(
                """INSERT INTO oc_knowledge_publication.publication_candidates(assertion_id,assertion_version,eligibility_decision_id,eligibility_decision_version,policy_version_id,requested_pathway,idempotency_key,fingerprint,correlation_id,created_by,assertion_type,scientific_domain,taxonomy_concept_id,taxonomy_version,scientific_scope,qualifiers,supporting_evidence_refs,conflicting_evidence_refs,provenance_root_refs,immutable_metadata,trusted_snapshot) VALUES(%s,%s,%s,1,%s,'AUTOMATIC_GOVERNED_PUBLICATION',%s,%s,%s,'test','TRAIT','BOTANY','taxon:x','1','{}','{}','[]','[]','[]','{}',%s::jsonb) RETURNING publication_id""",
                (
                    aid,
                    version,
                    route,
                    policy,
                    f"key-{suffix}-{version}",
                    f"fp-{suffix}-{version}",
                    f"corr-{suffix}-{version}",
                    json.dumps(trusted),
                ),
            ).fetchone()[0]
            con.execute(
                "INSERT INTO oc_knowledge_publication.lifecycle_transitions(publication_id,state,actor) VALUES(%s,'PUBLICATION_CANDIDATE','test'),(%s,'VALIDATING','test'),(%s,'AUTHORIZED','test')",
                (pid, pid, pid),
            )
            decision = con.execute(
                "INSERT INTO oc_knowledge_publication.authorization_decisions(publication_id,publication_version,assertion_id,assertion_version,eligibility_decision_id,eligibility_decision_version,policy_version_id,requested_pathway,resolved_pathway,outcome,decision,fingerprint,actor,correlation_id) VALUES(%s,1,%s,%s,%s,1,%s,'AUTOMATIC_GOVERNED_PUBLICATION','AUTOMATIC_GOVERNED_PUBLICATION','AUTHORIZED','{}',%s,'authority','corr') RETURNING decision_id",
                (pid, aid, version, route, policy, f"d-{suffix}-{version}"),
            ).fetchone()[0]
            change = con.execute(
                "INSERT INTO oc_knowledge_publication.graph_change_sets(publication_id,publication_version,authorization_decision_id,assertion_id,assertion_version,policy_version_id,operations,trusted_snapshot,validation_status,fingerprint,created_by,correlation_id) VALUES(%s,1,%s,%s,%s,%s,'[]','{}','VALIDATED',%s,'test','corr') RETURNING change_set_id",
                (pid, decision, aid, version, policy, f"cs-{suffix}-{version}"),
            ).fetchone()[0]
            tx = con.execute(
                "INSERT INTO oc_knowledge_publication.graph_transaction_manifests(change_set_id,publication_id,publication_version,intended_target_sequence,ordered_operations,validation_checks,status,fingerprint,service_identity,correlation_id) VALUES(%s,%s,1,%s,'[]','{}','PREPARED',%s,'test','corr') RETURNING graph_transaction_id",
                (change, pid, sequence, f"tx-{suffix}-{version}"),
            ).fetchone()[0]
            parent = con.execute(
                "SELECT graph_version_id FROM oc_knowledge_publication.current_graph_version WHERE singleton"
            ).fetchone()[0]
            gv = con.execute(
                "INSERT INTO oc_knowledge_publication.graph_versions(sequence,parent_graph_version_id,graph_transaction_id,publication_id,publication_version,status,node_change_count,edge_change_count,provenance_complete,fingerprint,correlation_id) VALUES(%s,%s,%s,%s,1,'COMMITTED',1,0,TRUE,%s,'corr') RETURNING graph_version_id",
                (sequence, parent, tx, pid, f"gv-{suffix}-{version}"),
            ).fetchone()[0]
            con.execute(
                "INSERT INTO oc_knowledge_publication.graph_object_versions(graph_version_id,graph_transaction_id,publication_id,object_kind,object_key,legacy_object_id,operation_type,payload,fingerprint) VALUES(%s,%s,%s,'NODE',%s,%s,'CREATE_NODE','{}',%s)",
                (
                    gv,
                    tx,
                    pid,
                    f"obj-{suffix}-{version}",
                    version,
                    f"objfp-{suffix}-{version}",
                ),
            )
            con.execute(
                "UPDATE oc_knowledge_publication.current_graph_version SET graph_version_id=%s,sequence=%s WHERE singleton",
                (gv, sequence),
            )
            con.execute(
                "INSERT INTO oc_knowledge_publication.lifecycle_transitions(publication_id,state,actor) VALUES(%s,'TRANSACTION_PREPARED','test'),(%s,'PUBLISHING','test'),(%s,'PUBLISHED','test')",
                (pid, pid, pid),
            )
            return pid, gv

        # Migration 088C creates the immutable genesis graph at sequence 1.
        # Test publications must therefore begin at the next available sequence.
        prior, _ = seed(1, 2)
        successor, _ = seed(2, 3)
        withdrawable, _ = seed(3, 4)
        dependent, _ = seed(4, 5)
        racing, _ = seed(5, 6)
        rollback_pub, rollback_gv = seed(6, 7)
        con.execute(
            "INSERT INTO oc_knowledge_publication.publication_dependencies(source_publication_id,dependent_publication_id,dependency_type,fingerprint) VALUES(%s,%s,'SUPPORTS',%s)",
            (withdrawable, dependent, f"dep-{suffix}"),
        )
    repo = PostgresPublicationLifecycleRepository(dsn)
    authority = LifecycleAuthority("lifecycle-service", "authority:1", f"corr-{suffix}")
    lineage = repo.supersede(
        prior,
        successor,
        authority,
        LifecycleReason("CORRECTED_ASSERTION", "New assertion version"),
    )
    assert lineage["successor_publication_id"] == successor
    repo.withdraw(
        withdrawable,
        authority,
        LifecycleReason("PUBLISHER_WITHDRAWAL", "No longer endorsed"),
    )
    assert repo.withdraw(
        withdrawable,
        authority,
        LifecycleReason("PUBLISHER_WITHDRAWAL", "No longer endorsed"),
    )["duplicate"]
    repo.restore(
        withdrawable,
        authority,
        LifecycleReason("ENDORSEMENT_RESTORED", "Validation restored endorsement"),
    )
    repo.retract(
        withdrawable,
        authority,
        LifecycleReason(
            RetractionReason.SOURCE_FORMALLY_RETRACTED.value,
            "Source formally retracted",
        ),
        {"source_revision_id": 3},
    )
    with pytest.raises(ValueError, match="REQUIRES_REPUBLICATION"):
        repo.restore(withdrawable, authority, LifecycleReason("RESTORE", "invalid"))
    rollback = repo.prepare_rollback(
        rollback_pub,
        authority,
        LifecycleReason("IMMEDIATE_TECHNICAL_INVALIDITY", "Technical integrity defect"),
        "integrity-monitor",
    )
    result = repo.execute_rollback(rollback["rollback_id"], authority)
    assert (
        result["outcome"] == "ROLLED_BACK"
        and repo.execute_rollback(rollback["rollback_id"], authority)["duplicate"]
    )

    def race(action):
        try:
            if action == "withdraw":
                repo.withdraw(
                    racing,
                    authority,
                    LifecycleReason("PUBLISHER_WITHDRAWAL", "Concurrent withdrawal"),
                )
            else:
                repo.retract(
                    racing,
                    authority,
                    LifecycleReason(
                        RetractionReason.ASSERTION_INVALIDATED.value,
                        "Concurrent retraction",
                    ),
                    {"assertion": "invalid"},
                )
            return "committed"
        except ValueError:
            return "rejected"

    with ThreadPoolExecutor(max_workers=2) as pool:
        race_results = list(pool.map(race, ("withdraw", "retract")))
    assert sorted(race_results) == ["committed", "rejected"]
    with psycopg.connect(dsn) as con:
        assert (
            con.execute(
                "SELECT state FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=%s ORDER BY transition_id DESC LIMIT 1",
                (prior,),
            ).fetchone()[0]
            == "SUPERSEDED"
        )
        assert (
            con.execute(
                "SELECT state FROM oc_knowledge_publication.lifecycle_transitions WHERE publication_id=%s ORDER BY transition_id DESC LIMIT 1",
                (dependent,),
            ).fetchone()[0]
            == "REEVALUATION_REQUIRED"
        )
        assert (
            con.execute(
                "SELECT graph_version_id FROM oc_knowledge_publication.current_graph_version WHERE singleton"
            ).fetchone()[0]
            != rollback_gv
        )
        assert con.execute(
            "SELECT count(*) FROM oc_knowledge_publication.downstream_impacts"
        ).fetchone()[0] >= len(tuple(range(15)))
