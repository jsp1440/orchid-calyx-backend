from __future__ import annotations


def capability_status() -> dict:
    return {
        "capability": "literature_matrix_vision",
        "state": "functional_integration_slice",
        "production_ready": False,
        "priority_10": {
            "completed": [
                "document_text_adapter",
                "ocr_fallback_contract",
                "canonical_taxonomy_resolver",
                "candidate_knowledge_payload_adapter",
                "versioned_matrix_registry",
                "geography_filter",
                "phenology_filter",
                "accepted_name_binding",
                "vision_provider_adapter",
                "label_token_extraction_and_abstention",
            ],
            "count": 10,
        },
        "lanes": {
            "literature": {
                "state": "deterministic_integration_ready",
                "available": [
                    "canonical_source_identity",
                    "content_hash",
                    "evidence_spans",
                    "document_page_adapter",
                    "taxon_identity_resolution",
                    "confidence",
                    "contradictions",
                    "candidate_knowledge_payload",
                    "disabled_ocr_fail_closed",
                ],
                "remaining": [
                    "production_pdf_adapter",
                    "configured_ocr_provider",
                    "hassler_database_adapter",
                    "real_paper_validation_set",
                ],
            },
            "matrix": {
                "state": "versioned_deterministic_engine_ready",
                "available": [
                    "versioned_matrix_registry",
                    "versionable_characters",
                    "taxon_profiles",
                    "weighted_scoring",
                    "missing_data_accounting",
                    "geography_filter",
                    "phenology_filter",
                    "accepted_name_binding",
                    "per_character_explanations",
                    "confidence_abstention",
                ],
                "remaining": [
                    "curated_orchid_matrices",
                    "database_persistence",
                    "field_validation_dataset",
                ],
            },
            "vision": {
                "state": "provider_adapter_and_fixture_pipeline_ready",
                "available": [
                    "image_identity",
                    "license_and_attribution",
                    "model_provenance",
                    "plant_part_detections",
                    "vision_provider_protocol",
                    "fixture_provider",
                    "image_to_matrix_observations",
                    "label_token_extraction",
                    "confidence_abstention",
                ],
                "remaining": [
                    "configured_live_model_provider",
                    "flower_structure_model",
                    "configured_label_ocr",
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
        "next_human_action": "Review the ten deterministic integration components before configuring live providers or production datasets.",
    }
