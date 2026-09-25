"""Capability/readiness inventory for AI Vision, Matrix, and Glossary engines.

OC-COMPLETE-007 — convergence audit of #416, #418, #831, and Matrix issues.

KEEP       — implemented, tested, correct; no change needed
CONVERGE   — implemented in multiple places; needs single authoritative path
SUPERSEDE  — old implementation; new authoritative version exists
GAP        — capability described but not yet implemented

No live-model spending. No taxonomy activation. No scientific publication.
No production KG mutation.
"""

from __future__ import annotations

import json
from typing import Any

SCHEMA_VERSION = "oc-vision-matrix-glossary-inventory/v1"


CAPABILITY_INVENTORY: list[dict[str, Any]] = [

    # -------------------------------------------------------------------------
    # VISION ENGINE
    # -------------------------------------------------------------------------
    {
        "capability_id": "vision_image_identity",
        "capability": "Image identity: license, attribution, content hash, canonical URI",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.multimodal_intelligence.contracts.ImageAnalysisResult",
        "guard": "validate() raises PermissionError if license_code or attribution is absent",
        "evidence": "license_code + attribution enforced at construction; content_hash length guard",
        "notes": "ImageAnalysisResult.validate() enforces this at the contract level; no bypass possible",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "vision_model_provenance",
        "capability": "Model provenance: provider, model_name, model_version, inference_id",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.multimodal_intelligence.contracts.ModelProvenance",
        "guard": "validate() requires all four fields non-empty",
        "evidence": "ModelProvenance.validate() in contracts.py:126",
        "notes": "AI model identity is always surfaced in the provenance chain",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "vision_plant_part_detection",
        "capability": "Bounded plant-part/structure observations with confidence",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.multimodal_intelligence.contracts.PlantPartDetection",
        "guard": "confidence capped — any observation.confidence > 0.98 fails validate()",
        "evidence": "ImageAnalysisResult.validate() line 164: UNSUPPORTED_VISION_CONFIDENCE guard",
        "notes": "Confidence cap prevents over-certain AI assertions from entering the system",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "vision_calibration_guard",
        "capability": "Absolute measurements only with proven calibration",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.vision_lexicon.contracts.MorphometricObservation",
        "guard": "ABSOLUTE_LENGTH/AREA/VOLUME require CalibrationState != UNCALIBRATED",
        "evidence": "MorphometricObservation.validate(); CharacterObservation.validate() guards absolute units",
        "notes": "Two independent guards: CharacterObservation (unit-based) and MorphometricObservation (metric_type-based)",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "vision_color_phenotype",
        "capability": "Color phenotype class with pigment evidence requirements",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.vision_lexicon.contracts.ColorPhenotypeObservation",
        "guard": "INFERRED_PIGMENT_CLASS and CHEMICALLY_VERIFIED require pigment_evidence_source",
        "evidence": "ColorPhenotypeObservation.validate(); Vision may only assert IMAGE_DERIVED without external evidence",
        "notes": "Prevents AI from promoting image color into chemically verified pigment identity",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "vision_review_state",
        "capability": "MACHINE_GENERATED entry state; no auto-promotion without human review",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.vision_lexicon.contracts.VisionReviewState",
        "guard": "auto_promotion_blocked=True required for COMMUNITY tier reviews",
        "evidence": "VisionReviewRecord.validate() enforces COMMUNITY_AUTO_PROMOTION_BLOCKED",
        "notes": "Community agreement cannot become canonical scientific truth; APPROVED requires EXPERT or SCIENTIFIC_AUTHORITY tier",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "vision_provider_registry",
        "capability": "Vision provider registry (Anthropic, extensible to others)",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.multimodal_intelligence.vision_provider_registry",
        "guard": "Provider selection is registry-driven; no hard-coded model identifiers in pipeline",
        "evidence": "app/multimodal_intelligence/vision_provider_registry.py + anthropic_vision_provider.py",
        "notes": None,
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "vision_herbarium_ocr",
        "capability": "Herbarium label OCR and verbatim-vs-normalized text separation",
        "domain": "vision",
        "status": "GAP",
        "authoritative_module": None,
        "guard": None,
        "evidence": "No file matching herbarium, ocr, or image_analysis exists under app/, runtime/, or scripts/",
        "notes": "The pipeline can classify plant parts and derive character observations but has no label-extraction path. Herbarium specimen images from iDigBio/Kew would need OCR extraction.",
        "gap_description": "Build herbarium label OCR extractor: verbatim label text → normalized fields (collector, date, locality, taxon). Verbatim text must be stored separately from normalized fields. Locality stripping applies to extracted GPS.",
        "child_task": "OC-COMPLETE-007-herbarium-ocr: Herbarium label OCR verbatim/normalized extractor",
    },
    {
        "capability_id": "vision_segmentation_contract",
        "capability": "Segmentation/landmark/measurement contracts",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.vision_lexicon.contracts.VisionRegion",
        "guard": "bounding_box and landmarks are optional; confidence required if present",
        "evidence": "VisionRegion.validate(); segmentation_ref field carries external segmentation reference",
        "notes": "Contract exists and is well-defined; actual segmentation model integration (SAM, etc.) is not yet wired but the contract is ready to receive it",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "vision_cannot_determine",
        "capability": "CANNOT_DETERMINE as first-class outcome preserved across pipeline",
        "domain": "vision",
        "status": "KEEP",
        "authoritative_module": "app.vision_lexicon.contracts.CharacterConformanceResult",
        "guard": "CANNOT_DETERMINE must not be collapsed into PASS or FAIL by consumers",
        "evidence": "CharacterConformanceResult enum; docstring prohibition on collapsing; AnalysisStatus.CANNOT_DETERMINE",
        "notes": "Preserved at CharacterConformanceCheck, AnalysisStatus, and MeasurementBasis.CANNOT_DETERMINE levels",
        "gap_description": None,
        "child_task": None,
    },

    # -------------------------------------------------------------------------
    # GLOSSARY / LEXICON
    # -------------------------------------------------------------------------
    {
        "capability_id": "glossary_lexicon_ingestion",
        "capability": "Botanical glossary/lexicon concept ingestion and storage",
        "domain": "glossary",
        "status": "KEEP",
        "authoritative_module": "app.lexicon",
        "guard": "Intake controlled via intake.py and intake_seed.py; route-level gates",
        "evidence": "app/lexicon/intake.py, intake_routes.py, intake_seed.py, routes.py",
        "notes": "Lexicon is the canonical concept store; vision observations link to lexicon concept_ids",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "glossary_vision_lexicon_bridge",
        "capability": "Vision-to-Lexicon character/concept ID grounding",
        "domain": "glossary",
        "status": "KEEP",
        "authoritative_module": "app.vision_lexicon",
        "guard": "CharacterObservation.concept_id links to Lexicon UUID; vision assertions carry evidence_id",
        "evidence": "app/vision_lexicon/contracts.py: concept_id fields on VisionRegion, CharacterObservation, VisionAssertion",
        "notes": "The bridge exists at the contract level; service-level wiring in app/vision_lexicon/service.py",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "glossary_literature_extraction",
        "capability": "Botanical glossary concept extraction from literature text",
        "domain": "glossary",
        "status": "CONVERGE",
        "authoritative_module": "app.literature_extraction.extractors.glossary",
        "guard": "Extraction is text-only; no auto-promotion to canonical concept",
        "evidence": "app/literature_extraction/extractors/glossary.py",
        "notes": "Glossary extractor exists as a literature sub-extractor. Needs explicit integration with the Lexicon intake path so extracted concepts flow into the governed concept store rather than remaining as unstructured text.",
        "gap_description": "Wire literature glossary extractor output to app.lexicon.intake for review-bound concept staging",
        "child_task": "OC-COMPLETE-007-glossary-intake-wire: Connect literature glossary extractor to Lexicon intake staging",
    },
    {
        "capability_id": "glossary_botanical_latin",
        "capability": "Botanical Latin/etymology consumer for morphology/anatomy concepts",
        "domain": "glossary",
        "status": "GAP",
        "authoritative_module": None,
        "guard": None,
        "evidence": "No botanical Latin / etymology extractor or concept field found in app/ or runtime/",
        "notes": "The Lexicon stores concepts but has no etymological enrichment. For expert/educational audiences, Botanical Latin roots would add significant depth.",
        "gap_description": "Add botanical Latin etymology annotations to Lexicon concept records (e.g. 'resupinate' → Latin roots, usage in orchidology)",
        "child_task": "OC-COMPLETE-007-botanical-latin: Botanical Latin etymology annotations for Lexicon concepts",
    },

    # -------------------------------------------------------------------------
    # MATRIX ENGINE
    # -------------------------------------------------------------------------
    {
        "capability_id": "matrix_support_contradiction_unknown",
        "capability": "Matrix support/contradiction/unknown/missing accounting per character",
        "domain": "matrix",
        "status": "KEEP",
        "authoritative_module": "app.multimodal_intelligence.contracts.MatrixCandidate",
        "guard": "support_count, contradiction_count, unknown_count are explicit fields",
        "evidence": "MatrixCandidate: score + support_count + contradiction_count + unknown_count + contributions",
        "notes": "Each contribution carries outcome (SUPPORT/CONTRADICTION/UNKNOWN) and weighted_score. Cannot-determine is preserved via unknown_count.",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "matrix_candidate_ranking",
        "capability": "Candidate ranking and explanation",
        "domain": "matrix",
        "status": "KEEP",
        "authoritative_module": "runtime.matrix_identification",
        "guard": "AI suggestions remain MACHINE_GENERATED; no auto-promotion to canonical ID",
        "evidence": "runtime/matrix_identification.py; app/routers/matrix_identification.py; matrix_identification_explanation.py",
        "notes": None,
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "matrix_next_best_observation",
        "capability": "Next-best observation guidance",
        "domain": "matrix",
        "status": "KEEP",
        "authoritative_module": "app.routers.matrix_identification_explanation",
        "guard": "Recommendations are suggestions only; cannot trigger automatic re-identification",
        "evidence": "app/routers/matrix_identification_explanation.py; runtime/matrix_identification_explanation.py",
        "notes": None,
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "matrix_registry_persistence",
        "capability": "Matrix registry persistence and durability",
        "domain": "matrix",
        "status": "KEEP",
        "authoritative_module": "runtime.matrix_identification_registry",
        "guard": "Persistence preflight in runtime/matrix_identification_persistence_preflight.py",
        "evidence": "runtime/matrix_identification_registry.py, _store.py, _preflight.py; scripts/calyx_matrix_durability_run.py",
        "notes": "Durability-check scripts exist; bounded deploy scripts present",
        "gap_description": None,
        "child_task": None,
    },
    {
        "capability_id": "matrix_vision_integration",
        "capability": "Matrix session ↔ Vision analysis integration",
        "domain": "matrix",
        "status": "CONVERGE",
        "authoritative_module": "runtime.matrix_identification_vision",
        "guard": "Vision outputs remain MACHINE_GENERATED in matrix context",
        "evidence": "runtime/matrix_identification_vision.py; app/routers/matrix_identification_vision.py; app/routers/vision_activation_preflight.py",
        "notes": "Two parallel modules (runtime + routers) for matrix-vision integration. Vision activation preflight exists but integration path needs a single documented canonical entry point.",
        "gap_description": "Document and test the single authoritative path: VisionAnalysis → CharacterObservations → MatrixSession.add_observations(). Preflight should gate all entry points.",
        "child_task": "OC-COMPLETE-007-matrix-vision-canonical-path: Single documented Vision→Matrix canonical integration path",
    },

    # -------------------------------------------------------------------------
    # END-TO-END PATH
    # -------------------------------------------------------------------------
    {
        "capability_id": "e2e_licensed_image_to_review",
        "capability": "End-to-end: licensed image → visual observations → glossary → matrix → review handoff",
        "domain": "end_to_end",
        "status": "CONVERGE",
        "authoritative_module": "app.scientific_adapter_lab.vision_matrix_proof",
        "guard": "All steps preserve MACHINE_GENERATED state; review_required at every output",
        "evidence": "Proof module with fixture-backed orchid test: see vision_matrix_proof.py in this lab",
        "notes": "Contracts are mature at each stage; the fixture-backed proof makes the path executable and testable",
        "gap_description": "Wire the single authoritative Vision→Glossary→Matrix→Review path end-to-end with production service integration",
        "child_task": "OC-COMPLETE-007-e2e-service-wire: Wire production Vision→Glossary→Matrix→Review service integration",
    },
]


def get_inventory() -> dict[str, Any]:
    status_summary: dict[str, int] = {}
    for item in CAPABILITY_INVENTORY:
        status = item["status"]
        status_summary[status] = status_summary.get(status, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION,
        "capability_count": len(CAPABILITY_INVENTORY),
        "status_summary": status_summary,
        "capabilities": CAPABILITY_INVENTORY,
        "graph_mutation": False,
        "automatic_publication": False,
    }


def get_capabilities_by_status(status: str) -> list[dict[str, Any]]:
    return [c for c in CAPABILITY_INVENTORY if c["status"] == status]


def get_child_tasks() -> list[dict[str, Any]]:
    return [
        {
            "capability_id": c["capability_id"],
            "title": c["child_task"],
            "status": c["status"],
            "domain": c["domain"],
            "gap_description": c["gap_description"],
        }
        for c in CAPABILITY_INVENTORY
        if c.get("child_task")
    ]


def serialize_inventory_as_json(*, indent: int = 2) -> str:
    return json.dumps(get_inventory(), indent=indent, sort_keys=False)
