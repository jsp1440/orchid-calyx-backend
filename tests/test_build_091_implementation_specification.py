from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.design_planning.my_conservatory import MyConservatoryPlanningDemonstration
from app.design_planning.repository import MemoryDesignPlanningRepository
from app.design_planning.service import DesignPlanningService
from app.implementation_planning.models import ReadinessStatus, SpecificationLifecycle
from app.implementation_planning.repository import MemoryImplementationPlanningRepository
from app.implementation_planning.routes import router
from app.implementation_planning.service import (
    ImplementationPlanningError,
    ImplementationSpecificationService,
    SourcePlanningBundle,
)
from app.security import verify_owner_or_api_key
from tests.test_build_090c_my_conservatory_planning import build_089_adapter


def source_bundle():
    repository = MemoryDesignPlanningRepository()
    planning = DesignPlanningService(repository, build_089_adapter())
    result = MyConservatoryPlanningDemonstration(planning).execute()
    plan = repository.get("plan", result.review_plan_id)
    return SourcePlanningBundle(
        repository.get("product_request", result.product_request_id),
        repository.get("context", result.context_snapshot_id),
        repository.get("evidence", result.evidence_package_id),
        tuple(repository.get("reasoning", x) for x in result.reasoning_record_ids),
        tuple(repository.get("conflict", x) for x in result.conflict_record_ids),
        plan,
    )


@pytest.fixture
def generated():
    service = ImplementationSpecificationService(MemoryImplementationPlanningRepository())
    artifact = service.generate_my_conservatory(source_bundle(), "build-091")
    return service, artifact


def test_generation_reuses_complete_source_chain_and_is_idempotent(generated):
    service, first = generated
    second = service.generate_my_conservatory(source_bundle(), "build-091")
    assert first is second and first.version == 1
    assert first.source_plan_lifecycle == "REVIEW_REQUIRED"
    assert len(first.source_artifacts) == 19
    assert len(first.reasoning_record_ids) == 10 and len(first.conflict_record_ids) == 5
    assert first.evidence_package_ids and first.provenance and first.rights_restrictions
    assert len(service.repository.audits()) == 1


def test_all_twelve_page_specifications_are_complete(generated):
    _, artifact = generated
    assert len(artifact.pages) == 12
    required = {
        "route", "purpose", "permitted_roles", "requirement_ids", "source_planning_references",
        "layout_regions", "primary_sections", "required_components", "required_data",
        "backend_capabilities", "api_contract_ids", "request_models", "response_models",
        "behaviors", "telemetry_events", "acceptance_criteria", "unresolved_dependencies",
    }
    for page in artifact.pages:
        assert all(getattr(page, name) for name in required)
        assert page.readiness_status is ReadinessStatus.BLOCKED
        assert set(page.behaviors) >= {"authorization", "loading", "empty", "error", "retry", "offline", "responsive", "keyboard", "screen_reader", "focus", "reduced_motion", "scientific", "provenance", "privacy", "state_transitions"}


def test_component_catalog_has_every_required_contract(generated):
    _, artifact = generated
    assert len(artifact.components) == 39
    for component in artifact.components:
        assert component.inputs and component.outputs and component.properties
        assert component.emitted_events and component.internal_state
        assert set(component.behaviors) >= {"loading", "error", "accessibility", "keyboard", "focus", "responsive", "scientific", "provenance", "privacy"}
        assert component.dependencies and component.acceptance_criteria


def test_navigation_graph_and_state_domains_are_complete(generated):
    _, artifact = generated
    assert len(artifact.navigation.route_registry) == 12
    assert set(artifact.navigation.rules) >= {"deep_links", "qr", "search", "breadcrumbs", "back", "mobile", "tablet", "desktop", "invalid", "unauthorized", "missing_plant"}
    assert len(artifact.states) == 17
    assert all(x.transitions and x.rollback_behavior and x.conflict_behavior and x.offline_behavior and x.privacy_restrictions for x in artifact.states)


def test_api_mapping_does_not_claim_missing_product_endpoints_exist(generated):
    _, artifact = generated
    existing = [x for x in artifact.api_contracts if x.status.startswith("EXISTING")]
    proposed = [x for x in artifact.api_contracts if x.status == "PROPOSED"]
    assert {(x.existing_endpoint, x.capability) for x in existing} == {("/verify", "verify authenticated session"), ("/awards", "generic awards records")}
    assert len(proposed) == 15
    assert len({x.proposed_contract["route"] for x in proposed}) == len(proposed)
    assert all(x.readiness_status is ReadinessStatus.BLOCKED and x.exact_dependency for x in proposed)
    assert all(x.proposed_contract["authentication"] == "required" for x in proposed)


def test_data_accessibility_scientific_and_privacy_contracts(generated):
    _, artifact = generated
    assert len(artifact.data_contracts) == 24
    assert all(x.required_fields and x.validation_rules and x.provenance_requirements and x.versioning for x in artifact.data_contracts)
    contracts = {x.contract_type: x for x in artifact.cross_cutting_contracts}
    assert set(contracts) == {"ACCESSIBILITY", "SCIENTIFIC-PRESENTATION", "PRIVACY-SECURITY"}
    assert all(len(x.page_mappings) == 12 and len(x.component_mappings) == 39 for x in contracts.values())
    privacy_text = " ".join(contracts["PRIVACY-SECURITY"].rules)
    assert "telemetry" in privacy_text and "never location" in privacy_text


def test_conflicts_propagate_without_resolution_and_block_work(generated):
    _, artifact = generated
    assert len(artifact.conflict_impacts) == 5
    assert all(x.status == "DECISION_REQUIRED" and x.blocked_work and x.decision_owner for x in artifact.conflict_impacts)
    assert {x.title for x in artifact.conflict_impacts} == {
        "simplicity versus scientific completeness", "mobile versus desktop workflows",
        "rapid entry versus validation", "privacy versus sharing", "novice versus expert users",
    }


def test_readiness_and_nine_phase_sequence_have_exact_dependencies(generated):
    _, artifact = generated
    assert len(artifact.sequence) == 9
    assert all(x.prerequisites and x.deliverables and x.acceptance_criteria and x.recommended_build for x in artifact.sequence)
    assert all(isinstance(x.status, ReadinessStatus) and (x.status is ReadinessStatus.READY or x.exact_dependency) for x in artifact.readiness)
    assert any(x.status is ReadinessStatus.BLOCKED for x in artifact.readiness)


def test_versioning_supersession_review_and_immutability(generated):
    service, first = generated
    second = service.new_version(first.specification_id, {"unresolved_questions": (*first.unresolved_questions, "owner decision pending")}, "owner")
    assert second.version == 2 and second.supersedes_specification_id == first.specification_id
    with pytest.raises(FrozenInstanceError):
        second.version = 3
    with pytest.raises(ImplementationPlanningError, match="UNAUTHORIZED"):
        service.review(second.specification_id, {"reviewer_role": "UX", "decision": "REQUEST_REVISION", "rationale": "change"}, "outsider", set())
    review = service.review(second.specification_id, {"reviewer_role": "UX", "decision": "REQUEST_REVISION", "rationale": "resolve documented issue"}, "ux-reviewer", {"UX"})
    assert review.specification_hash == second.integrity_hash


def test_source_plan_must_not_be_falsely_approved():
    source = source_bundle()
    from dataclasses import replace
    rejected = replace(source.plan, lifecycle_state=source.plan.lifecycle_state.APPROVED)
    with pytest.raises(ImplementationPlanningError, match="REVIEW_REQUIRED"):
        ImplementationSpecificationService().generate_my_conservatory(replace(source, plan=rejected), "actor")


def test_authenticated_routes_and_prohibited_generation(generated):
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    assert client.get("/api/implementation-planning/health").status_code in {401, 403}
    app.dependency_overrides[verify_owner_or_api_key] = lambda: True
    health = client.get("/api/implementation-planning/health").json()
    assert health == {"ready": True, "version": "091-my-conservatory-1", "specifications_only": True, "frontend_generation": False, "implementation_authorization": False, "knowledge_graph_publication": False}
    _, artifact = generated
    serialized = repr(artifact).casefold()
    assert all(token not in serialized for token in ("import react", "<html", "<style", "jsx.element", "createapp("))
    assert artifact.lifecycle_state is SpecificationLifecycle.REVIEW_REQUIRED
