"""Science-first mission registry, integration coordinator, and safe audit payloads.

BUILD-047 created the science department scaffold.
BUILD-048 adds a non-destructive integration coordinator: dataset registry,
coverage-gap reporting, harvester health summaries, dossier queues, and
provenance-safe work-item generation.

This module records audit intent and data-readiness gaps only. It never promotes
unsupported biological claims as facts and does not mutate external systems.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEPARTMENTS: list[tuple[str, str, int, str, list[str]]] = [
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

DATASET_REGISTRY: list[dict[str, Any]] = [
    {
        "dataset_id": "world_plants_orchids",
        "display_name": "World Plants orchid taxonomy",
        "department_id": "taxonomy",
        "source_type": "external_dataset",
        "integration_state": "configured_or_expected",
        "freshness_cadence": "monthly_or_on_release",
        "primary_entities": ["accepted orchid names", "synonyms", "distribution text", "conservation status text"],
        "provenance_required": True,
        "next_safe_action": "audit_taxonomy_source_mapping",
    },
    {
        "dataset_id": "gbif_occurrences",
        "display_name": "GBIF occurrence records",
        "department_id": "geography_atlas",
        "source_type": "external_dataset_or_harvester",
        "integration_state": "configured_or_expected",
        "freshness_cadence": "after_occurrence_imports",
        "primary_entities": ["occurrences", "coordinates", "event dates", "basis of record"],
        "provenance_required": True,
        "next_safe_action": "audit_occurrence_elevation_coverage",
    },
    {
        "dataset_id": "inat_observations",
        "display_name": "iNaturalist observations and living images",
        "department_id": "images",
        "source_type": "harvester",
        "integration_state": "configured_or_expected",
        "freshness_cadence": "daily",
        "primary_entities": ["living images", "observations", "phenology signals"],
        "provenance_required": True,
        "next_safe_action": "audit_species_image_coverage",
    },
    {
        "dataset_id": "eol_traitbank",
        "display_name": "EOL TraitBank",
        "department_id": "traits",
        "source_type": "external_dataset",
        "integration_state": "needs_runtime_audit",
        "freshness_cadence": "weekly_or_on_dataset_update",
        "primary_entities": ["traits", "glossary terms", "trait sources"],
        "provenance_required": True,
        "next_safe_action": "audit_traitbank_coverage",
    },
    {
        "dataset_id": "zenodo_pollination",
        "display_name": "Zenodo orchid pollination dataset",
        "department_id": "pollination",
        "source_type": "external_dataset",
        "integration_state": "needs_runtime_audit",
        "freshness_cadence": "monthly_or_on_release",
        "primary_entities": ["orchid-pollinator interactions", "pollinator guilds", "rewards", "references"],
        "provenance_required": True,
        "next_safe_action": "audit_pollinator_coverage",
    },
    {
        "dataset_id": "globi_interactions",
        "display_name": "GloBI interaction graph",
        "department_id": "pollination",
        "source_type": "external_dataset",
        "integration_state": "needs_runtime_audit",
        "freshness_cadence": "monthly_or_on_release",
        "primary_entities": ["species interactions", "interaction evidence", "interaction source citations"],
        "provenance_required": True,
        "next_safe_action": "audit_pollinator_sources",
    },
    {
        "dataset_id": "literature_claims",
        "display_name": "Orchid literature extraction tables",
        "department_id": "literature",
        "source_type": "internal_tables",
        "integration_state": "needs_runtime_audit",
        "freshness_cadence": "every_few_hours_or_on_new_documents",
        "primary_entities": ["claims", "citations", "evidence summaries", "review state"],
        "provenance_required": True,
        "next_safe_action": "audit_literature_extraction_coverage",
    },
    {
        "dataset_id": "mycorrhiza_relationships",
        "display_name": "Orchid mycorrhizal relationship data",
        "department_id": "mycorrhiza",
        "source_type": "internal_or_external_dataset",
        "integration_state": "needs_runtime_audit",
        "freshness_cadence": "daily_or_on_new_literature",
        "primary_entities": ["orchid-fungus relationships", "fungal taxa", "germination evidence", "citations"],
        "provenance_required": True,
        "next_safe_action": "audit_mycorrhiza_coverage",
    },
    {
        "dataset_id": "climate_elevation_layers",
        "display_name": "Climate and elevation layers",
        "department_id": "climate",
        "source_type": "derived_or_external_layers",
        "integration_state": "needs_runtime_audit",
        "freshness_cadence": "monthly_or_after_new_occurrences",
        "primary_entities": ["elevation", "temperature normals", "precipitation", "seasonality"],
        "provenance_required": True,
        "next_safe_action": "audit_climate_layer_coverage",
    },
]


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


def datasets() -> dict[str, Any]:
    rows = sorted(DATASET_REGISTRY, key=lambda item: department_by_id(item["department_id"])["priority"], reverse=True)
    return {
        "status": "ok",
        "dataset_count": len(rows),
        "datasets": rows,
        "safety": {
            "external_fetches_performed": False,
            "database_mutations_performed": False,
            "purpose": "registry_and_readiness_tracking_only",
        },
    }


def _mission_for_department(department_id: str) -> str:
    return (MISSION_TYPES.get(department_id) or [f"audit_{department_id}"])[0]


def coverage_gaps() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for department in departments():
        if department["department_id"] in {"judging", "awards"}:
            continue
        rows.append({
            "gap_id": f"gap_{department['department_id']}",
            "department_id": department["department_id"],
            "priority": department["priority"],
            "gap_type": "data_readiness_unknown",
            "summary": f"{department['display_name']} needs live schema/table coverage verification before enrichment.",
            "recommended_mission": _mission_for_department(department["department_id"]),
            "risk_level": "safe_audit_only",
            "claim_type": "coverage_gap_audit",
            "confidence": "audit_only",
            "review_status": "needs_review",
            "source": "BUILD-048 scientific integration coordinator",
            "promoted_claims": False,
        })
    return {
        "status": "ok",
        "gap_count": len(rows),
        "gaps": rows,
        "blocked_actions": ["promote_unreviewed_claim", "external_mutation", "destructive_mutation"],
    }


def integration_status() -> dict[str, Any]:
    deps = departments()
    gap_report = coverage_gaps()
    dataset_report = datasets()
    return {
        "status": "ok",
        "mode": "BUILD-048 scientific integration coordinator",
        "science_departments_enabled": len([d for d in deps if d["department_id"] not in {"judging", "awards"}]),
        "dataset_count": dataset_report["dataset_count"],
        "known_gap_count": gap_report["gap_count"],
        "highest_priority_work": gap_report["gaps"][:5],
        "next_recommended_actions": [
            "Run safe pollinator and mycorrhiza audits.",
            "Inspect live database schemas for relationship/evidence tables.",
            "Wire read-only coverage queries after schema verification.",
            "Keep judging and awards low priority unless explicitly requested.",
        ],
        "safety": {
            "destructive_actions": False,
            "external_mutations": False,
            "unsupported_claims_promoted": False,
            "provenance_required_for_scientific_claims": True,
        },
    }


def harvester_status() -> dict[str, Any]:
    known_harvesters = [
        {
            "harvester_id": "inat_observations",
            "department_id": "images",
            "expected_output": "living orchid observations and images",
            "status": "needs_live_runtime_audit",
            "recommended_action": "verify last cursor, inserted record count, failure count, and image quality yield",
        },
        {
            "harvester_id": "gbif_occurrences",
            "department_id": "geography_atlas",
            "expected_output": "occurrence records for Atlas and elevation/climate enrichment",
            "status": "needs_live_runtime_audit",
            "recommended_action": "verify last import date, new records, duplicate rate, and missing elevation rate",
        },
        {
            "harvester_id": "literature_ingestion",
            "department_id": "literature",
            "expected_output": "papers, citations, extracted claims, and review queues",
            "status": "needs_live_runtime_audit",
            "recommended_action": "verify pending documents, extraction failures, and uncited claims",
        },
    ]
    return {
        "status": "ok",
        "harvester_count": len(known_harvesters),
        "harvesters": known_harvesters,
        "recommendations": [
            "Do not run every harvester continuously without yield checks.",
            "Prefer cadences based on data-change frequency and recent useful inserts.",
            "Queue schedule changes as needs_review until live metrics are available.",
        ],
        "destructive_actions": False,
    }


def dossier_queue() -> dict[str, Any]:
    candidates = [
        {
            "entity_type": "orchid_species",
            "queue_name": "species_dossiers",
            "priority_reason": "front-end species pages need evidence-backed dossiers",
            "required_sections": ["taxonomy", "images", "occurrences", "habitat", "pollinators", "mycorrhiza", "literature", "conservation"],
            "status": "candidate_queue_ready",
        },
        {
            "entity_type": "pollinator",
            "queue_name": "pollinator_dossiers",
            "priority_reason": "pollinator cards and ecological stories require provenance-first evidence",
            "required_sections": ["taxonomy", "associated orchids", "life history", "evidence", "conservation relevance", "citations"],
            "status": "candidate_queue_ready",
        },
        {
            "entity_type": "fungus",
            "queue_name": "fungal_dossiers",
            "priority_reason": "mycorrhizal relationships need fungal partner context and review status",
            "required_sections": ["taxonomy", "associated orchids", "germination evidence", "habitat", "sequence/literature evidence", "citations"],
            "status": "candidate_queue_ready",
        },
    ]
    return {"status": "ok", "candidate_queue_count": len(candidates), "candidates": candidates, "promoted_claims": False}


def audit_result(department_id: str, mission_type: str | None = None) -> dict[str, Any]:
    department = department_by_id(department_id)
    mission_type = mission_type or _mission_for_department(department_id)
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
            "source": "BUILD-048 scientific integration coordinator",
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
    work_items = [
        {
            "work_item_id": f"work_{mission['mission_type']}",
            "mission_type": mission["mission_type"],
            "department_id": mission["department_id"],
            "priority": mission["priority"],
            "status": "recommended",
            "risk_level": "safe_audit_only",
            "requires_schema_review_before_mutation": True,
        }
        for mission in missions
    ]
    return {
        "status": "seed_plan_ready",
        "destructive_actions": False,
        "external_mutations": False,
        "created": [],
        "skipped_duplicates": [],
        "recommended_missions": missions,
        "recommended_work_items": work_items,
        "message": "BUILD-048 prepares scientific work items; persistent queue insertion should be wired after schema review.",
    }


def summary() -> dict[str, Any]:
    deps = departments()
    missions = mission_definitions()
    return {
        "status": "ok",
        "mode": "BUILD-048 scientific integration coordinator",
        "department_count": len(deps),
        "mission_type_count": len(missions),
        "dataset_count": len(DATASET_REGISTRY),
        "top_priorities": deps[:8],
        "low_priority_support": [d for d in deps if d["department_id"] in {"judging", "awards"}],
        "highest_priority_gaps": coverage_gaps()["gaps"][:5],
        "safety": {
            "destructive_actions": False,
            "external_mutations": False,
            "unsupported_claims_promoted": False,
            "provenance_required_for_scientific_claims": True,
        },
    }
