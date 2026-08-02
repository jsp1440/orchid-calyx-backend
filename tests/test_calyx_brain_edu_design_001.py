from __future__ import annotations

from app.brain.education_design_routes import EducationDesignSearch, readiness, search
from app.calyx_agent.service import CalyxAgentService
from app.calyx_agent.tools import default_tool_registry
from app.calyx_orchestrator.service import OVERNIGHT_PROFILE, READ_ONLY_JOB_TYPES


def test_registry_exposes_education_and_design_tools():
    registry = default_tool_registry()
    tool_ids = {item["tool_id"] for item in registry.describe()}
    assert {
        "design_intelligence.readiness",
        "design_intelligence.search",
        "education.readiness",
    }.issubset(tool_ids)
    education = registry.execute("education.readiness")
    assert education.status == "partial"
    assert education.data["recommendation_preparation"] is True
    assert education.data["automatic_course_publication"] is False


def test_brain_readiness_reports_governed_boundaries():
    payload = readiness()
    assert payload["design_intelligence"]["semantic_reasoning"] is True
    assert payload["education"]["virtual_lab_runtime"] is False
    assert payload["governance"]["website_changes_require_owner_approval"] is True
    assert payload["governance"]["scientific_publication_requires_scientific_approval"] is True


def test_brain_design_search_is_read_only():
    payload = search(EducationDesignSearch(query="accessible scientific dashboard", limit=5))
    assert payload["brain_boundary"] is True
    assert payload["read_only"] is True
    assert payload["implementation_requires_approval"] is True


def test_agent_routes_website_request_through_design_intelligence():
    response = CalyxAgentService().handle(
        actor="owner",
        request_text="audit the website accessibility and navigation",
        use_provider=False,
    )
    tool_ids = [result.tool_id for result in response.tool_results]
    assert tool_ids[:2] == [
        "design_intelligence.readiness",
        "design_intelligence.search",
    ]
    assert response.steps[-1].action_class.value == "prepare_only"
    assert response.steps[-1].status == "planned"
    assert response.approval_required is False


def test_agent_routes_university_request_through_education_readiness():
    response = CalyxAgentService().handle(
        actor="owner",
        request_text="audit the Orchid Continuum University curriculum and virtual labs",
        use_provider=False,
    )
    tool_ids = [result.tool_id for result in response.tool_results]
    assert "education.readiness" in tool_ids
    assert "design_intelligence.readiness" in tool_ids
    assert response.steps[-1].action_class.value == "prepare_only"
    assert response.approval_required is False


def test_overnight_profile_includes_governed_design_and_education_audits():
    job_types = {item[1] for item in OVERNIGHT_PROFILE}
    assert "website_design_audit" in job_types
    assert "education_readiness" in job_types
    assert job_types.issubset(READ_ONLY_JOB_TYPES)
