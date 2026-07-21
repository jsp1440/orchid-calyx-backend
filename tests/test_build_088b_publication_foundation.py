import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.knowledge_publication.models import (
    CandidateRequest,
    PublicationPathway,
    PublicationPolicy,
)
from app.knowledge_publication.policy import PublicationAuthority


def policy():
    item = PublicationPolicy(
        policy_id="botany",
        version=1,
        name="Botany publication",
        supported_assertion_types=("TRAIT",),
        supported_domains=("BOTANY",),
        automatic_assertion_types=("TRAIT",),
        automatic_domains=("BOTANY",),
        permitted_copyright_policies=("DERIVED_FACTS_ALLOWED",),
        provenance={"architecture": "BUILD-088A"},
    )
    return {"policy_id": item.policy_id, "version": item.version, "rules": item.rules()}


def candidate():
    return {
        "assertion_version": 2,
        "eligibility_decision_id": 7,
        "requested_pathway": PublicationPathway.AUTOMATIC.value,
        "assertion": {
            "version": 2,
            "published": False,
            "publication_eligible": True,
            "routing_decision_id": 7,
            "normalized_statement": {"assertion_type": "TRAIT"},
            "scientific_scope": {
                "scientific_domain": "BOTANY",
                "taxonomy_unambiguous": True,
                "impact_class": "STANDARD",
            },
            "conflicting_interpretation_ids": [],
        },
        "eligibility_decision": {"path": "AUTOMATIC_PROMOTION", "hard_failures": []},
        "provenance_roots": [
            {"source_revision_id": 11, "copyright_policy": "DERIVED_FACTS_ALLOWED"},
            {"source_revision_id": 12, "copyright_policy": "DERIVED_FACTS_ALLOWED"},
        ],
    }


def test_automatic_authorization_is_deterministic_and_explainable():
    authority = PublicationAuthority()
    first = authority.evaluate(candidate(), policy())
    assert first == authority.evaluate(candidate(), policy())
    assert first["state"] == "AUTHORIZED"
    assert all(first["checks"].values())


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("published", True, "assertion_unpublished"),
        ("publication_eligible", False, "assertion_publication_eligible"),
    ],
)
def test_authority_fails_closed(field, value, reason):
    item = candidate()
    item["assertion"][field] = value
    result = PublicationAuthority().evaluate(item, policy())
    assert result["state"] == "REJECTED" and reason in result["failure_reasons"]


def test_conflicts_and_incomplete_provenance_reject():
    item = candidate()
    item["assertion"]["conflicting_interpretation_ids"] = [9]
    item["provenance_roots"] = []
    result = PublicationAuthority().evaluate(item, policy())
    assert {
        "conflicts_resolved",
        "provenance_complete",
        "copyright_permitted",
    }.issubset(result["failure_reasons"])


def test_human_and_provisional_paths_never_auto_authorize():
    for pathway in (PublicationPathway.HUMAN, PublicationPathway.PROVISIONAL):
        item = candidate()
        item["requested_pathway"] = pathway.value
        assert PublicationAuthority().evaluate(item, policy())["state"] == "REJECTED"


def test_typed_requests_reject_unversioned_or_incomplete_identity():
    with pytest.raises(ValueError, match="INVALID_VERSIONED_REFERENCE"):
        CandidateRequest(
            1, 0, "p", 1, PublicationPathway.AUTOMATIC, "key", "actor", "corr"
        )


def test_policy_versions_are_distinct_immutable_values():
    original = PublicationPolicy(
        "p", 1, "one", ("TRAIT",), ("BOTANY",), provenance={"source": "approved"}
    )
    newer = replace(original, version=2, minimum_independent_sources=3)
    assert (
        original.version == 1
        and newer.version == 2
        and original.rules() != newer.rules()
    )


def test_migration_declares_additive_immutable_postgres_invariants():
    sql = Path("migrations/088b_publication_registry_policy_foundation.sql").read_text()
    assert "CREATE SCHEMA IF NOT EXISTS" in sql
    assert "KNOWLEDGE_PUBLICATION_RECORDS_ARE_APPEND_ONLY" in sql
    assert "INVALID_PUBLICATION_LIFECYCLE_TRANSITION" in sql
    assert "ACTIVE_POLICY_VERSION_ALREADY_EXISTS" in sql
    assert "DROP TABLE" not in sql and "TRUNCATE" not in sql


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_migration_enforces_append_only_registry():
    import psycopg

    dsn = os.environ["TEST_DATABASE_URL"]
    prerequisite = Path(
        "migrations/087b_context_preserving_interpretation.sql"
    ).read_text()
    migration = Path(
        "migrations/088b_publication_registry_policy_foundation.sql"
    ).read_text()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(prerequisite)
        connection.execute(migration)
        row = connection.execute(
            """INSERT INTO oc_knowledge_publication.policy_versions
            (policy_id,version,name,rules,provenance,fingerprint)
            VALUES('build-088b-pg',999999,'test','{}','{}',md5(random()::text)) RETURNING policy_version_id"""
        ).fetchone()
        with pytest.raises(psycopg.Error, match="APPEND_ONLY"):
            connection.execute(
                "DELETE FROM oc_knowledge_publication.policy_versions WHERE policy_version_id=%s",
                (row[0],),
            )


@pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured"
)
def test_postgres_repository_resolves_trusted_inputs_and_suppresses_duplicates():
    import uuid
    from concurrent.futures import ThreadPoolExecutor

    import psycopg

    from app.knowledge_publication.postgres_repository import (
        PostgresPublicationRegistry,
    )

    dsn = os.environ["TEST_DATABASE_URL"]
    suffix = uuid.uuid4().hex
    prerequisite = Path(
        "migrations/087b_context_preserving_interpretation.sql"
    ).read_text()
    migration = Path(
        "migrations/088b_publication_registry_policy_foundation.sql"
    ).read_text()
    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute(prerequisite)
        connection.execute(migration)
        packet = connection.execute(
            """INSERT INTO oc_scientific_interpretation.evidence_packets(packet_key,version,fingerprint,payload)
            VALUES(%s,1,%s,%s::jsonb) RETURNING packet_id""",
            (
                f"packet-{suffix}",
                f"packet-{suffix}",
                '{"sources":[{"source_revision_id":101,"copyright_policy":"DERIVED_FACTS_ALLOWED"},{"source_revision_id":102,"copyright_policy":"DERIVED_FACTS_ALLOWED"}]}',
            ),
        ).fetchone()[0]
        interpretation = connection.execute(
            """INSERT INTO oc_scientific_interpretation.machine_interpretations(interpretation_key,version,fingerprint,payload)
            VALUES(%s,1,%s,%s::jsonb) RETURNING interpretation_id""",
            (
                f"interpretation-{suffix}",
                f"interpretation-{suffix}",
                f'{{"packet_ids":[{packet}]}}',
            ),
        ).fetchone()[0]
        routing = connection.execute(
            """INSERT INTO oc_scientific_interpretation.routing_decisions(interpretation_id,policy_name,policy_version,path,fingerprint,payload)
            VALUES(%s,'build-087','1','AUTOMATIC_PROMOTION',%s,%s::jsonb) RETURNING routing_decision_id""",
            (
                interpretation,
                f"routing-{suffix}",
                f'{{"interpretation_id":{interpretation},"path":"AUTOMATIC_PROMOTION","hard_failures":[],"factors":{{"confidence":0.99}}}}',
            ),
        ).fetchone()[0]
        assertion = connection.execute(
            """INSERT INTO oc_scientific_interpretation.canonical_assertions(assertion_key,version,fingerprint,payload)
            VALUES(%s,1,%s,%s::jsonb) RETURNING assertion_id""",
            (
                f"assertion-{suffix}",
                f"assertion-{suffix}",
                f'{{"published":false,"publication_eligible":true,"routing_decision_id":{routing},"supporting_interpretation_ids":[{interpretation}],"conflicting_interpretation_ids":[],"normalized_statement":{{"assertion_type":"TRAIT"}},"scientific_scope":{{"scientific_domain":"BOTANY","taxonomy_unambiguous":true,"impact_class":"STANDARD"}}}}',
            ),
        ).fetchone()[0]

    registry = PostgresPublicationRegistry(dsn)
    publication_policy = PublicationPolicy(
        f"policy-{suffix}",
        1,
        "Botany",
        ("TRAIT",),
        ("BOTANY",),
        automatic_assertion_types=("TRAIT",),
        automatic_domains=("BOTANY",),
        provenance={"approval": "BUILD-088A"},
    )
    registry.create_policy(publication_policy, "policy-admin")
    registry.activate_policy(publication_policy.policy_id, 1, "policy-admin")
    request = CandidateRequest(
        assertion,
        1,
        publication_policy.policy_id,
        1,
        PublicationPathway.AUTOMATIC,
        f"request-{suffix}",
        "publication-service",
        f"correlation-{suffix}",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        candidates = list(
            pool.map(lambda _: registry.create_candidate(request), range(2))
        )
    assert candidates[0]["publication_id"] == candidates[1]["publication_id"]
    first = registry.authorize(candidates[0]["publication_id"], "publication-authority")
    second = registry.authorize(
        candidates[0]["publication_id"], "publication-authority"
    )
    assert first["decision_id"] == second["decision_id"]
    assert registry.candidate(candidates[0]["publication_id"])["state"] == "AUTHORIZED"
    assert {
        event["event_type"]
        for event in registry.audit_history(
            "PUBLICATION_CANDIDATE", candidates[0]["publication_id"]
        )
    } == {"CANDIDATE_CREATED", "AUTHORITY_EVALUATED"}
