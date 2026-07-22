from __future__ import annotations

import pytest

from app.design_intelligence.knowledge import (
    SemanticDesignDomain,
    SemanticUnit,
    SemanticUnitType,
    SourceLocation,
)
from app.design_intelligence.reasoning import (
    DesignReasoningService,
    MemoryDesignKnowledgeRepository,
)
from app.design_planning.models import CoverageOutcome, LifecycleState
from app.design_planning.my_conservatory import (
    CONFLICTS,
    GOALS,
    REASONING_AREAS,
    SCREEN_NAMES,
    MyConservatoryPlanningDemonstration,
)
from app.design_planning.repository import MemoryDesignPlanningRepository
from app.design_planning.service import Build089EvidenceAdapter, DesignPlanningService


def build_089_adapter():
    repository = MemoryDesignKnowledgeRepository()
    specifications = (
        (
            "accessible dashboard navigation keyboard visible focus",
            SemanticDesignDomain.ACCESSIBILITY,
            "ACCESSIBILITY_REQUIREMENT",
        ),
        (
            "collection search progressive disclosure and validation",
            SemanticDesignDomain.UX,
            "GUIDELINE",
        ),
        (
            "reduced motion feedback animation recommendation",
            SemanticDesignDomain.MOTION_DESIGN,
            "DESIGN_PRINCIPLE",
        ),
        (
            "component library patterns support consistent state feedback",
            SemanticDesignDomain.COMPONENT_LIBRARIES,
            "GUIDELINE",
        ),
        (
            "screen reader names and semantic headings support accessible navigation",
            SemanticDesignDomain.ACCESSIBILITY,
            "ACCESSIBILITY_REQUIREMENT",
        ),
    )
    for index, (text, domain, kind) in enumerate(specifications, 1):
        repository.append_units(
            (
                SemanticUnit(
                    unit_id=f"build-089c-unit-{index}",
                    document_id=index,
                    document_version=1,
                    ordinal=1,
                    unit_type=SemanticUnitType.RECOMMENDATION,
                    text=text,
                    source_location=SourceLocation(
                        format="DOCX",
                        start=index,
                        end=index,
                        locator={
                            "archive": "BUILD-089C",
                            "document": index,
                            "paragraph": index,
                        },
                        content_hash=f"{index:064x}",
                    ),
                    domains=(domain,),
                    knowledge_types=(kind,),
                    classification_confidence=0.95,
                    embedding=tuple([0.1] * 32),
                ),
            )
        )
    return Build089EvidenceAdapter(DesignReasoningService(repository))


@pytest.fixture
def demonstration():
    repository = MemoryDesignPlanningRepository()
    service = DesignPlanningService(repository, build_089_adapter())
    return MyConservatoryPlanningDemonstration(service), service


def test_complete_demonstration_persists_every_artifact_and_is_idempotent(
    demonstration,
):
    demo, service = demonstration
    first = demo.execute()
    second = demo.execute()
    assert first == second
    assert service.repository.get("product_request", first.product_request_id)
    assert service.repository.get("context", first.context_snapshot_id)
    assert service.repository.get("evidence", first.evidence_package_id)
    assert all(
        service.repository.get("reasoning", item) for item in first.reasoning_record_ids
    )
    assert all(
        service.repository.get("conflict", item) for item in first.conflict_record_ids
    )
    assert service.repository.get("plan", first.draft_plan_id)
    assert service.repository.get("plan", first.review_plan_id)
    assert first.audit_event_count == len(service.repository.audits())


def test_product_request_v1_contains_all_confirmed_goals_and_provenance(demonstration):
    demo, service = demonstration
    result = demo.execute()
    request = service.repository.get("product_request", result.product_request_id)
    assert request.version == 1 and len(request.requirements) == len(GOALS) == 18
    assert all(
        item.status.value == "CONFIRMED" and item.provenance
        for item in request.requirements
    )
    assert "frontend implementation" in request.excluded_scope
    assert request.lifecycle_state is LifecycleState.REQUEST_DRAFT


def test_context_captures_authority_rights_and_hard_constraints(demonstration):
    demo, service = demonstration
    result = demo.execute()
    context = service.repository.get("context", result.context_snapshot_id)
    assert len(context.items) == 9
    assert {item.item_type for item in context.items} >= {
        "BUILD_089_CORPUS",
        "BUILD_090_ARCHITECTURE",
        "SCIENTIFIC_REQUIREMENTS",
        "ACCESSIBILITY_REQUIREMENTS",
        "PRIVACY_REQUIREMENTS",
        "PROVENANCE_RULES",
    }
    assert all(item.provenance and item.rights_classification for item in context.items)
    assert sum(item.hard_constraint for item in context.items) == 4


def test_build_089_retrieval_preserves_citations_ranking_coverage_gaps_and_rights(
    demonstration,
):
    demo, service = demonstration
    result = demo.execute()
    evidence = service.repository.get("evidence", result.evidence_package_id)
    assert evidence.ranked_results
    assert all(
        item.semantic_unit_id.startswith("build-089c-unit-")
        for item in evidence.ranked_results
    )
    assert all(
        item.citation and item.provenance and item.source_location
        for item in evidence.ranked_results
    )
    assert evidence.coverage["ACCESSIBILITY"] is CoverageOutcome.COVERED
    assert (
        evidence.coverage["SCIENTIFIC_VISUALIZATION"]
        is CoverageOutcome.NOT_PRESENT_IN_SOURCE_CORPUS
    )
    assert "USER_SUPPLIED_INTERNAL_RESEARCH_ONLY" in evidence.rights_restrictions
    assert list(evidence.ranked_results) == sorted(
        evidence.ranked_results,
        key=lambda item: (-item.score, item.document_id, item.semantic_unit_id),
    )


def test_reasoning_records_cover_all_required_areas_and_remain_auditable(demonstration):
    demo, service = demonstration
    result = demo.execute()
    records = [
        service.repository.get("reasoning", item)
        for item in result.reasoning_record_ids
    ]
    assert len(records) == len(REASONING_AREAS) == 10
    assert {item.affected_product_area for item in records} == {
        item[0] for item in REASONING_AREAS
    }
    assert all(
        item.considered_alternatives and item.concise_decision_rationale
        for item in records
    )
    assert all(item.supporting_evidence_references and item.risks for item in records)


def test_material_conflicts_are_versioned_open_and_not_silently_resolved(demonstration):
    demo, service = demonstration
    result = demo.execute()
    records = [
        service.repository.get("conflict", item) for item in result.conflict_record_ids
    ]
    assert len(records) == len(CONFLICTS) == 5
    assert all(
        item.version == 1 and item.review_status == "DECISION_REQUIRED"
        for item in records
    )
    assert all(
        item.disposition is None and item.required_decision_owner_role
        for item in records
    )
    assert sum(item.hard_constraint for item in records) >= 2


def test_interface_plan_has_complete_screen_contract_and_review_lifecycle(
    demonstration,
):
    demo, service = demonstration
    result = demo.execute()
    draft = service.repository.get("plan", result.draft_plan_id)
    review = service.repository.get("plan", result.review_plan_id)
    screens = draft.sections["view_inventory"]
    assert {item["name"] for item in screens} == set(SCREEN_NAMES)
    required = {
        "purpose",
        "users",
        "workflows",
        "required_data",
        "interactions",
        "accessibility",
        "scientific_presentation",
        "error_handling",
        "loading_states",
        "empty_states",
        "acceptance_criteria",
        "evidence_references",
    }
    assert all(required <= item.keys() for item in screens)
    assert draft.lifecycle_state is LifecycleState.PLAN_DRAFTED
    assert review.lifecycle_state is LifecycleState.REVIEW_REQUIRED
    assert review.supersedes_plan_id == draft.interface_plan_id and review.version == 2
    assert len(review.required_review_roles) == 6


def test_no_interface_code_or_implementation_authority_is_produced(demonstration):
    demo, service = demonstration
    result = demo.execute()
    plan = service.repository.get("plan", result.review_plan_id)
    serialized = repr(plan).casefold()
    assert "<html" not in serialized and "import react" not in serialized
    assert plan.lifecycle_state is LifecycleState.REVIEW_REQUIRED
    assert service.health()["implementation_authorization"] is False


def test_audit_history_links_every_persisted_artifact(demonstration):
    demo, service = demonstration
    result = demo.execute()
    events = service.repository.audits()
    identities = {item.artifact_id for item in events}
    assert {
        result.product_request_id,
        result.context_snapshot_id,
        result.evidence_package_id,
        result.review_plan_id,
    } <= identities
    assert all(
        item.actor and item.integrity_hash and item.correlation_id for item in events
    )
