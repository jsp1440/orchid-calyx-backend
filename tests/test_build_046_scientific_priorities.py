from app.main import JOB_PRIORITIES, MODULE_REGISTRY, SCIENTIFIC_MODULES
from runtime.science_registry import audit_result


def test_scientific_modules_rank_above_judging_and_awards():
    modules = {module["module_name"]: module for module in MODULE_REGISTRY}

    assert modules["pollinator_relationships"]["priority"] == 100
    assert modules["mycorrhiza_relationships"]["priority"] == 98
    assert modules["literature_extraction"]["priority"] == 96
    assert modules["ecological_relationship_graph"]["priority"] == 95
    assert modules["traitbank_traits"]["priority"] == 94
    assert modules["conservation_habitat"]["priority"] == 93
    assert modules["image_species_evidence"]["priority"] == 90
    assert modules["frontend_knowledge_graph_integration"]["priority"] == 88
    assert modules["calyx_core_health"]["priority"] == 80
    assert modules["judging"]["priority"] == 25
    assert modules["awards"]["priority"] == 20

    lowest_science_priority = min(module["priority"] for module in SCIENTIFIC_MODULES)
    assert lowest_science_priority > modules["judging"]["priority"]
    assert lowest_science_priority > modules["awards"]["priority"]


def test_job_priority_map_prefers_science_over_society_modules():
    assert JOB_PRIORITIES["audit_missing_pollinator_data"] > JOB_PRIORITIES["optimize_judging"]
    assert JOB_PRIORITIES["audit_missing_mycorrhizal_data"] > JOB_PRIORITIES["optimize_awards"]


def test_scientific_audit_results_are_provenance_first():
    result = audit_result("pollination", mission_type="audit_missing_pollinator_data")

    assert result["department_id"] == "pollination"
    assert result["mission_type"] == "audit_missing_pollinator_data"
    assert result["provenance_status"] == "required_before_claim_promotion"
    assert result["confidence"] == "audit_only"
    assert result["review_status"] == "unreviewed"
    assert result["promoted_claims"] is False
    assert result["findings"]
    finding = result["findings"][0]
    assert finding["claim_type"] == "coverage_gap_audit"
    assert finding["source"]
    assert finding["confidence"] == "audit_only"
    assert finding["review_status"] == "unreviewed"
