from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path
import os
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.scientific_interpretation.models import (
    AssertionRequest,
    CompletenessState,
    CONTEXT_DIMENSIONS,
    ContextForm,
    InterpretationRequest,
    PromotionPath,
    RoutingPolicy,
    SourceAnchorReference,
    SourceEvidenceReference,
)
from app.scientific_interpretation.repository import MemoryInterpretationRepository
from app.scientific_interpretation.service import ScientificInterpretationService


def source(source_id: int = 1, *, policy: str = "FULL_TEXT_ALLOWED") -> SourceEvidenceReference:
    return SourceEvidenceReference(
        source_object_type="DOCUMENT_REVISION",
        source_object_id=source_id,
        source_revision_id=source_id * 10,
        publication_metadata={"doi": f"10.1000/{source_id}", "title": "Orchid study"},
        copyright_policy=policy,
        provenance={"ingestion_run_id": 82, "extraction_run_id": 85, "sha256": f"source-{source_id}"},
        anchors=(
            SourceAnchorReference(
                anchor_id=source_id * 100,
                order=0,
                anchor_type="PARAGRAPH",
                locator={"page": 4, "section": "Results"},
                content_hash=f"anchor-{source_id}",
            ),
        ),
    )


def dimensions(**overrides: CompletenessState) -> dict[str, CompletenessState]:
    values = {name: CompletenessState.PRESENT for name in CONTEXT_DIMENSIONS}
    values.update(overrides)
    return values


def setup():
    repository = MemoryInterpretationRepository()
    return repository, ScientificInterpretationService(repository)


def packet(service: ScientificInterpretationService, *, key: str = "packet-1", form: ContextForm = ContextForm.PARAGRAPH, sources=None, context=None, relationships=()):
    return service.construct_packet(
        packet_key=key,
        context_form=form,
        sources=tuple(sources or (source(),)),
        context_dimensions=context or dimensions(),
        material_dimensions=("taxon", "trait_or_relationship", "geographic_locality", "qualifiers", "negation", "biological_context"),
        structural_relationships=tuple(relationships),
        construction_policy_version="packet-policy-1",
        boundary_analyzer_version="boundary-1",
        construction_rationale="Complete biological context and referents retained",
    )


def interpretation(service: ScientificInterpretationService, packet_id: int, *, confidence: float = 0.96, alternatives=()):
    return service.interpret(
        InterpretationRequest(
            packet_ids=(packet_id,),
            interpretation_key="taxon:masdevallia:habitat",
            statement={"taxon": "Masdevallia", "trait": "habitat", "value": "cloud forest", "negated": False},
            reasoning={"rule": "explicit subject-predicate-object", "qualifier_resolution": "within packet"},
            confidence_factors={"source": confidence, "anchor": confidence, "entity": confidence, "relation": confidence},
            alternatives=tuple(alternatives),
            model_version="deterministic-1",
            ruleset_version="build-087b-1",
            vocabulary_versions={"traits": "1"},
            configuration={"language": "en"},
        )
    )


def routing(service: ScientificInterpretationService, interpretation_id: int, **overrides):
    values = {
        "interpretation_id": interpretation_id,
        "policy": RoutingPolicy("scientific-default", "1", allowed_model_versions=("deterministic-1",), calibration_cohort="build-087b-fixture"),
        "independent_source_count": 2,
        "taxon_unambiguous": True,
        "measurement_compatible": True,
        "unresolved_contradiction": False,
        "impact_class": "ROUTINE_TRAIT",
        "copyright_eligible": True,
        "provenance_complete": True,
    }
    values.update(overrides)
    return service.evaluate_routing(**values)


def test_migration_is_additive_isolated_append_only_and_never_publishes():
    sql = Path("migrations/087b_context_preserving_interpretation.sql").read_text()
    upper = sql.upper()
    assert "CREATE SCHEMA IF NOT EXISTS OC_SCIENTIFIC_INTERPRETATION" in upper
    assert all(name in upper for name in ("EVIDENCE_PACKETS", "MACHINE_INTERPRETATIONS", "CANONICAL_ASSERTIONS", "CORRECTION_RECORDS", "AUDIT_EVENTS"))
    assert "PUBLISHED\": FALSE" in upper
    assert "SCIENTIFIC_ARTIFACTS_ARE_APPEND_ONLY" in upper
    assert all(token not in upper for token in ("DROP TABLE", "TRUNCATE TABLE", "OC_GRAPH.", "OC_TAXONOMY."))


def test_source_evidence_is_immutable_and_packet_preserves_every_context_dimension():
    repository, service = setup()
    immutable_source = source()
    with pytest.raises(FrozenInstanceError):
        immutable_source.source_revision_id = 99  # type: ignore[misc]
    created = packet(service)
    assert created["sources"][0]["source_revision_id"] == 10
    assert created["sources"][0]["anchors"][0]["locator"] == {"page": 4, "section": "Results"}
    assert set(created["context_dimensions"]) == set(CONTEXT_DIMENSIONS)
    assert created["state"] == "PACKET_COMPLETE"
    assert repository.events[-1]["event_type"] == "EVIDENCE_PACKET_CREATED"


@pytest.mark.parametrize(
    ("form", "relationships"),
    [
        (ContextForm.PARAGRAPH, ()),
        (ContextForm.LINKED_SENTENCES, ({"relationship": "ANTECEDENT"},)),
        (ContextForm.TABLE_WITH_HEADERS, ({"relationship": "ROW_HEADER"}, {"relationship": "COLUMN_HEADER"})),
        (ContextForm.FIGURE_WITH_CAPTION, ({"relationship": "CAPTION"},)),
        (ContextForm.METHODS_RESULTS, ({"relationship": "METHOD_FOR_RESULT"},)),
        (ContextForm.TAXONOMIC_TREATMENT, ()),
        (ContextForm.SEMANTIC_CONTEXT, ()),
    ],
)
def test_all_approved_packet_forms_are_supported_with_required_structure(form, relationships):
    _, service = setup()
    created = packet(service, form=form, relationships=relationships)
    assert created["context_form"] == form.value


def test_packet_identity_is_idempotent_and_boundary_change_creates_retained_version():
    repository, service = setup()
    first = packet(service)
    same = packet(service)
    changed = service.construct_packet(
        packet_key="packet-1",
        context_form=ContextForm.PARAGRAPH,
        sources=(source(),),
        context_dimensions=dimensions(),
        material_dimensions=("taxon",),
        structural_relationships=(),
        construction_policy_version="packet-policy-2",
        boundary_analyzer_version="boundary-1",
        construction_rationale="Policy now includes expanded context",
    )
    assert first["packet_id"] == same["packet_id"]
    assert changed["version"] == 2 and len(repository.packets) == 2


def test_incomplete_material_context_is_preserved_and_blocks_interpretation():
    _, service = setup()
    created = packet(service, context=dimensions(taxon=CompletenessState.AMBIGUOUS))
    assert created["state"] == "PACKET_INCOMPLETE"
    with pytest.raises(ValueError, match="INCOMPLETE_PACKET"):
        interpretation(service, created["packet_id"])


def test_interpretation_is_reproducible_versioned_and_retains_alternatives():
    repository, service = setup()
    created_packet = packet(service)
    first = interpretation(service, created_packet["packet_id"], alternatives=({"value": "montane forest", "reason": "scope ambiguity"},))
    same = interpretation(service, created_packet["packet_id"], alternatives=({"value": "montane forest", "reason": "scope ambiguity"},))
    changed = service.interpret(
        InterpretationRequest(
            packet_ids=(created_packet["packet_id"],),
            interpretation_key=first["interpretation_key"],
            statement={**first["statement"], "value": "upper montane cloud forest"},
            reasoning={"rule": "reviewed scope"},
            confidence_factors={"source": 0.95, "anchor": 0.95},
            model_version="deterministic-1",
            ruleset_version="build-087b-2",
        ),
        supersedes_interpretation_id=first["interpretation_id"],
    )
    assert first["interpretation_id"] == same["interpretation_id"]
    assert changed["version"] == 2 and changed["supersedes_interpretation_id"] == first["interpretation_id"]
    assert first["alternatives"] and len(repository.interpretations) == 2
    assert first["reproducibility_manifest"]["packet_fingerprints"] == [created_packet["fingerprint"]]


def test_objective_routing_covers_automatic_provisional_and_exception_paths():
    _, service = setup()
    complete = packet(service)
    high = interpretation(service, complete["packet_id"])
    automatic = routing(service, high["interpretation_id"])
    provisional = routing(service, high["interpretation_id"], independent_source_count=1)
    exception = routing(service, high["interpretation_id"], unresolved_contradiction=True)
    assert automatic["path"] == PromotionPath.AUTOMATIC_PROMOTION
    assert provisional["path"] == PromotionPath.PROVISIONAL_SCIENTIFIC_ASSERTION
    assert exception["path"] == PromotionPath.EXCEPTION_REVIEW
    assert exception["gates"]["no_unresolved_contradiction"] is False
    assert "no_unresolved_contradiction" in exception["explanation"]


def test_canonical_assertions_are_versioned_derived_and_never_published():
    repository, service = setup()
    created_packet = packet(service)
    interpreted = interpretation(service, created_packet["packet_id"])
    decision = routing(service, interpreted["interpretation_id"])
    request = AssertionRequest(
        assertion_key="taxon:masdevallia:habitat",
        normalized_statement={"subject": "Masdevallia", "predicate": "has_habitat", "object": "cloud forest"},
        scientific_scope={"geography": "source locality", "life_stage": "NOT_APPLICABLE", "qualifiers": []},
        supporting_interpretation_ids=(interpreted["interpretation_id"],),
    )
    first = service.create_assertion(request, decision["routing_decision_id"])
    same = service.create_assertion(request, decision["routing_decision_id"])
    assert first["assertion_id"] == same["assertion_id"]
    assert first["publication_eligible"] is True and first["published"] is False
    assert repository.events[-1]["details"]["published"] is False


def test_correction_creates_new_interpretation_version_and_complete_audit_history():
    repository, service = setup()
    created_packet = packet(service)
    original = interpretation(service, created_packet["packet_id"])
    result = service.correct_interpretation(
        interpretation_id=original["interpretation_id"],
        correction_key="correction:masdevallia:habitat",
        error_category="SCOPE_TOO_BROAD",
        affected_field="value",
        corrected_value="upper montane cloud forest",
        rationale="The locality and qualifier restrict the habitat statement",
        reviewer="reviewer-1",
        reviewer_specialty="orchid ecology",
        applicability={"taxon": "Masdevallia", "source_revision_id": 10},
        permitted_use="EVALUATION_ONLY",
    )
    corrected = result["corrected_interpretation"]
    assert original["statement"]["value"] == "cloud forest"
    assert corrected["statement"]["value"] == "upper montane cloud forest"
    assert corrected["version"] == 2 and corrected["supersedes_interpretation_id"] == original["interpretation_id"]
    assert result["correction"]["feedback_state"] == "CAPTURED"
    assert any(event["event_type"] == "CORRECTION_RECORDED" for event in repository.events)


def test_foundation_processes_large_fixture_without_context_copy_or_publication_surface():
    repository, service = setup()
    started = time.perf_counter()
    for index in range(1, 1001):
        packet(service, key=f"packet-{index}", sources=(source(index),))
    elapsed = time.perf_counter() - started
    assert len(repository.packets) == 1000 and elapsed < 5
    code = "\n".join(path.read_text() for path in Path("app/scientific_interpretation").glob("*.py"))
    assert all(token not in code for token in ("publish_graph", "publish_node", "publish_edge", "drive.files.update"))


def test_api_requires_authentication_and_exposes_no_publication_endpoint(monkeypatch):
    from app.scientific_interpretation.routes import router

    monkeypatch.setenv("CALYX_API_KEY", "build-087b-test-key")
    application = FastAPI()
    application.include_router(router)
    client = TestClient(application)
    assert client.get("/api/scientific-interpretation/health").status_code == 401
    health = client.get("/api/scientific-interpretation/health", headers={"X-API-Key": "build-087b-test-key"})
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "three_layers_separate": True, "publishes_graph": False, "immutable_evidence": True}
    assert all("publish" not in route.path for route in router.routes)


@pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="TEST_DATABASE_URL not configured")
def test_postgres_repository_round_trip_is_append_only_and_audited():
    import psycopg

    from app.scientific_interpretation.postgres_repository import PostgresInterpretationRepository

    database_url = os.environ["TEST_DATABASE_URL"]
    migration = Path("migrations/087b_context_preserving_interpretation.sql").read_text()
    with psycopg.connect(database_url) as connection:
        connection.execute(migration)
    repository = PostgresInterpretationRepository(database_url)
    service = ScientificInterpretationService(repository)
    created_packet = packet(service, key="postgres-packet")
    interpreted = interpretation(service, created_packet["packet_id"])
    decision = routing(service, interpreted["interpretation_id"])
    assertion = service.create_assertion(
        AssertionRequest(
            assertion_key="postgres:masdevallia:habitat",
            normalized_statement={"subject": "Masdevallia", "predicate": "has_habitat", "object": "cloud forest"},
            scientific_scope={"geography": "source locality"},
            supporting_interpretation_ids=(interpreted["interpretation_id"],),
        ),
        decision["routing_decision_id"],
    )
    reconstructed = PostgresInterpretationRepository(database_url)
    assert reconstructed.packet_by_fingerprint(created_packet["fingerprint"])["packet_id"] == created_packet["packet_id"]
    assert reconstructed.interpretation(interpreted["interpretation_id"])["fingerprint"] == interpreted["fingerprint"]
    assert assertion["published"] is False
    assert reconstructed.history("CANONICAL_ASSERTION", assertion["assertion_id"])
    with pytest.raises(psycopg.errors.RaiseException, match="SCIENTIFIC_ARTIFACTS_ARE_APPEND_ONLY"):
        with psycopg.connect(database_url) as connection:
            connection.execute(
                "UPDATE oc_scientific_interpretation.machine_interpretations SET payload='{}' WHERE interpretation_id=%s",
                (interpreted["interpretation_id"],),
            )
