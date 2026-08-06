from __future__ import annotations


def capability_status() -> dict:
    return {
        "capability": "literature_matrix_vision",
        "state": "functional_engine_slice",
        "production_ready": False,
        "lanes": {
            "literature": {
                "state": "contract_and_handoff_ready",
                "available": [
                    "canonical_source_identity",
                    "content_hash",
                    "evidence_spans",
                    "taxon_identity",
                    "confidence",
                    "contradictions",
                    "candidate_knowledge_handoff_shape",
                ],
                "remaining": [
                    "real_document_adapter",
                    "ocr_fallback",
                    "canonical_taxonomy_resolution",
                    "real_paper_validation_set",
                ],
            },
            "matrix": {
                "state": "deterministic_engine_ready",
                "available": [
                    "versionable_characters",
                    "taxon_profiles",
                    "weighted_scoring",
                    "missing_data_accounting",
                    "per_character_explanations",
                ],
                "remaining": [
                    "curated_orchid_matrices",
                    "geography_and_phenology_filters",
                    "accepted_name_binding",
                    "field_validation_dataset",
                ],
            },
            "vision": {
                "state": "provider_neutral_contract_ready",
                "available": [
                    "image_identity",
                    "license_and_attribution",
                    "model_provenance",
                    "plant_part_detections",
                    "image_to_matrix_observations",
                ],
                "remaining": [
                    "live_model_adapter",
                    "flower_structure_detector",
                    "label_ocr_adapter",
                    "verified_image_benchmark",
                ],
            },
        },
        "safety": {
            "live_inference_enabled": False,
            "automatic_species_identification": False,
            "automatic_publication": False,
            "taxonomy_activation": False,
            "production_graph_mutation": False,
            "unlicensed_media_promotion": False,
            "human_review_required": True,
        },
        "next_human_action": "Review the fixture-backed engine slice before enabling provider or production integrations.",
    }
