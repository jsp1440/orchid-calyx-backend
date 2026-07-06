"""BUILD-047 science-first mission registry and safe audit payloads.

Non-destructive Orchid Continuum scientific operations scaffold. It records audit
intent and gaps only; it never promotes unsupported biological claims as facts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEPARTMENTS: list[dict[str, Any]] = [
    ("taxonomy", "Taxonomy", 100, "weekly_or_on_dataset_update", ["accepted_names", "synonyms", "taxon_resolution_gaps"]),
    ("pollination", "Pollination", 99, "daily_or_on_new_literature", ["pollinator_relationship_gaps", "pollinator_dossier_candidates"]),
    ("mycorrhiza", "Mycorrhiza and fungi", 98, "daily_or_on_new_literature", ["fungal_relationship_gaps", "fungal_dossier_candidates"]),
    ("literature", "Literature extraction", 97, "every_few_hours_or_on_new_documents", ["claim_gaps", "citation_gaps", "papers_needing_extraction"]),
    ("traits", "Traits and TraitBank", 96, "weekly_or_on_dataset_update", ["trait_coverage_gaps", "glossary_normalization_gaps"]),
    ("geography_atlas", "Geography and Atlas", 95, "after_occurrence_imports", ["range_gaps", "thematic_map_readiness", "atlas_cache_gaps"]),
    ("climate", "Climate and elevation", 94, "monthly_or_after_new_occurrences", ["missing_elevation", "missing_climate_context", "phenology_climate_gaps"]),
    ("conservation", "Conservation and habitat", 93, "weekly_or_on_status_update", ["conservation_status_gaps", "habitat_gaps", "threat_context_gaps"]),
    ("images", "Images and species evidence", 92, "daily_or_after_image_harvest", ["image_coverage_gaps", "image_quality_gaps", "source_license_gaps"]),
    ("dossiers", "Species, pollinator, and fungal dossiers", 91, "daily_candidate_queue_review", ["species_dossier_candidates", "pollinator_dossier_candidates", "fungal_dossier_candidates"]),
    ("harvester_operations", "Harvester operations", 90, "daily", ["stale_harvesters", "low_yield_harvesters", "cadence_recommendations"]),
    ("frontend_integration", "Frontend integration", 88, "after_backend_schema_or_endpoint_changes", ["relationship_card_contract", "atlas_contract", "dossier_contract"]),
    ("judging", "Judging", 25, "only_when_requested_or_no_scientific_work_pending", ["judging_readiness"]),
    ("awards", "Awards", 20, "only_when_requested_or_no_scientific_work_pending", ["awards_readiness"]),
]

MISSION_TYPES: dict[str, list[str]] = {
    "pollination": ["audit_pollinator_coverage", "identify_orchids_missing_pollinator_data", "identify_pollinator_taxa_missing_dossiers", "audit_pollinator_sources", "audit_pollinator_relationship_confidence"],
    "mycorrhiza": ["audit_mycorrhiza_coverage", "identify_orchids_missing_fungal_data", "identify_fungal_taxa_missing_dossiers", "audit_mycorrhiza_sources", "audit_fungal_relationship_confidence"],
    "literature": ["audit_literature_extraction_coverage", "identify_species_missing_literature_claims", "identify_unreviewed_literature_claims", "audit_citation_provenance"],
    "traits": ["audit_traitbank_coverage", "identify_species_missing_trait_data", "audit_trait_source_mapping"],
    "geography_atlas": ["audit_occurrence_elevation_coverage", "identify_occurrences_missing_elevation", "audit_geographic_range_coverage", "audit_thematic_map_readiness"],
    "climate": ["audit_climate_layer_coverage", "identify_occurrences_missing_climate_context", "audit_phenology_climate_linkage"],
    "images": ["audit_species_image_coverage", "identify_species_missing_living_images", "audit_image_quality_and_source", "audit_herbarium_vs_living_image_balance"],
    "dossiers": ["audit_species_dossier_readiness", "audit_pollinator_dossier_readiness", "audit_fungus_dossier_readiness"],
    "harvester_operations": ["audit_harvester_health", "identify_stale_harvesters", "identify_low_yield_harvesters", "recommend_harvester_cadence_changes"],
    "frontend_integration": ["audit_frontend_relationship_card_data", "audit_frontend_genus_of_day_data", "audit_frontend_atlas_data", "audit_frontend_dossier_data"],
}

AUDIT_ENDPOINT_TO_DEPARTMENT = {
    "pollinators": "pollination",
    "mycorrhiza": "mycorrhiza",
    "literature": "literature",
    "traits": "traits",
    "elevation": "geography_atlas",
    "climate": "climate",
    "harvesters": "harvester_operations",
    "dossiers": "dossiers",
}


def departments() -> list[dict[str, Any]]:
    rows = []
    for department_id, display_name, priority, cadence_hint, outputs in DEPARTMENTS:
        scientific = department_id not in {"judging", "awards"}
        rows.append({
            "department_id": department_id,
            "display_name": display_name,
            "priority": priority,
            "enabled": True,
            "cadence_hint": cadence_hint,
            "safe_task_types": ["coverage_audit", "source_audit", "readiness_audit"],
            "blocked_task_types": ["destructive_mutation", "external_send", "promote_unreviewed_claim"] if scientific else ["replace_scientific_priorities"],
            "primary_outputs": outputs,
            "provenance_required": scientific,
        })
    return sorted(rows, key=lambda item: item["priority"], reverse=True)


def department_by_id(department_id: str) -> dict[str, Any]:
    for department in departments():
        if department["department_id"] == department_id:
            return department
    raise KeyError(department_id)


def mission_definitions() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for department_id, mission_types in MISSION_TYPES.items():
        department = department_by_id(department_id)
        for mission_type in mission_types:
            rows.append({
                "mission_type": mission_type,
                "department_id": department_id,
                "priority": department["priority"],
                "status": "available",
                "risk_level": "safe_audit_only",
                "provenance_required": department["provenance_required"],
            })
    return sorted(rows, key=lambda item: item["priority"], reverse=True)


def audit_result(department_id: str, mission_type: str | None = None) -> dict[str, Any]:
    department = department_by_id(department_id)
    mission_type = mission_type or (MISSION_TYPES.get(department_id) or [f"audit_{department_id}"])[0]
    now = utc_now()
    return {
        "status": "completed",
        "department_id": department_id,
        "mission_type": mission_type,
        "priority": department["priority"],
        "summary": f"{department['display_name']} safe coverage audit completed.",
        "findings": [{
            "claim_type": "coverage_gap_audit",
            "subject_type": "orchid_continuum_dataset",
            "subject_name": department_id,
            "relationship_type": "needs_evidence_review",
            "evidence_status": "missing_or_unverified",
            "confidence": "audit_only",
            "source": "BUILD-047 internal safe audit scaffold",
            "review_status": "unreviewed",
        }],
        "recommended_next_tasks": [{
            "task_type": "schema_review",
            "status": "needs_review",
            "summary": f"Inspect live tables/endpoints for {department['display_name']} before enrichment or claim promotion.",
        }],
        "source_tables_or_endpoints": [],
        "provenance_status": "required_before_claim_promotion",
        "confidence": "audit_only",
        "review_status": "unreviewed",
        "provenance_required": department["provenance_required"],
        "promoted_claims": False,
        "created_at": now,
        "updated_at": now,
    }


def seed_missions() -> dict[str, Any]:
    missions = mission_definitions()
    return {
        "status": "seed_plan_ready",
        "destructive_actions": False,
        "external_mutations": False,
        "created": [],
        "skipped_duplicates": [],
        "recommended_missions": missions,
        "message": "BUILD-047 exposes the scientific mission plan; persistent queue insertion should be wired after schema review.",
    }


def summary() -> dict[str, Any]:
    deps = departments()
    missions = mission_definitions()
    return {
        "status": "ok",
        "mode": "BUILD-047 scientific integration scaffold",
        "department_count": len(deps),
        "mission_type_count": len(missions),
        "top_priorities": deps[:8],
        "low_priority_support": [d for d in deps if d["department_id"] in {"judging", "awards"}],
        "safety": {
            "destructive_actions": False,
            "external_mutations": False,
            "unsupported_claims_promoted": False,
            "provenance_required_for_scientific_claims": True,
        },
    }
