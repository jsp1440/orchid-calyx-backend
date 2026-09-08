"""Canonical Vision → Matrix integration path documentation and adapter.

OC-COMPLETE-007-matrix-vision-canonical-path: Single documented authoritative
integration path for VisionAnalysis → CharacterObservations → Matrix scoring.

TWO INTEGRATION MODES — one per usage context:

1. INTERACTIVE (session-gated, `runtime.matrix_identification_vision`):
   VisionAnalysis → attach_vision_analysis() → VisionSuggestion(pending_review)
   → review_vision_suggestion(accept/revise/reject) → add_observation()
   → rank_matrix_candidates()

   Used when a human reviewer must explicitly accept or revise each vision
   suggestion before it enters a Matrix Identification session.
   Vision observations remain MACHINE_GENERATED until a reviewer accepts them.

2. BATCH (direct scoring, `app.multimodal_intelligence.engine`):
   VisionAnalysis → matrix_observations_from_vision() → rank_matrix_candidates()

   Used for fixture-backed proofs, benchmarks, and batch candidate ranking where
   review of each individual suggestion is deferred to the ReviewHandoff stage.
   Confidence cap (max 0.95) is enforced by `matrix_observations_from_vision`.

In BOTH modes:
- Vision outputs remain MACHINE_GENERATED (review_state != APPROVED automatically).
- No auto-promotion to canonical morphology/ID.
- `ImageAnalysisResult.validate()` must pass before any scoring (enforces
  license_code, attribution, content_hash, and the confidence cap).
- CANNOT_DETERMINE is preserved, never collapsed.

ENTRY POINT GUARD:
All callers must pass an `ImageAnalysisResult` with a non-empty `license_code`
and `attribution`; the `guard_vision_analysis_entry` function below enforces this.
"""
from __future__ import annotations

from typing import Any

from app.multimodal_intelligence.contracts import (
    CharacterObservation,
    ImageAnalysisResult,
)
from app.multimodal_intelligence.engine import matrix_observations_from_vision


PATH_SCHEMA_VERSION = "oc-matrix-vision-path/v1"

CANONICAL_PATH_DESCRIPTION = {
    "schema_version": PATH_SCHEMA_VERSION,
    "modes": {
        "interactive": {
            "entry": "runtime.matrix_identification_vision.attach_vision_analysis",
            "review_step": "runtime.matrix_identification_vision.review_vision_suggestion",
            "scoring_step": "app.multimodal_intelligence.engine.rank_matrix_candidates",
            "review_gated": True,
            "machine_generated_until_review": True,
            "use_when": "Human must review each vision suggestion before it enters the matrix session",
        },
        "batch": {
            "entry": "app.multimodal_intelligence.engine.matrix_observations_from_vision",
            "scoring_step": "app.multimodal_intelligence.engine.rank_matrix_candidates",
            "review_gated": False,
            "machine_generated_until_review": True,
            "use_when": "Proof/benchmark scoring; review deferred to ReviewHandoff stage",
        },
    },
    "invariants": {
        "review_state": "MACHINE_GENERATED — never auto-approved",
        "auto_promotion": False,
        "cannot_determine_preserved": True,
        "confidence_cap": 0.95,
        "license_required": True,
        "attribution_required": True,
    },
}


def guard_vision_analysis_entry(result: ImageAnalysisResult) -> None:
    """Validate that a VisionAnalysis is safe to enter the canonical Matrix path.

    Raises ValueError or PermissionError on invariant violation (delegates to
    ImageAnalysisResult.validate() first, which raises PermissionError for
    missing license/attribution and ValueError for invalid structure/confidence).
    """
    result.validate()


def batch_path(
    result: ImageAnalysisResult,
) -> tuple[CharacterObservation, ...]:
    """Canonical batch path: ImageAnalysisResult → CharacterObservations.

    Enforces entry guard, then delegates to `matrix_observations_from_vision`.
    Returns observations ready for `rank_matrix_candidates`.

    Args:
        result: Fully validated ImageAnalysisResult from a governed vision provider.

    Returns:
        Tuple of CharacterObservation with confidence capped at 0.95 and
        full model provenance embedded in each observation's provenance chain.
    """
    guard_vision_analysis_entry(result)
    return matrix_observations_from_vision(result)


def describe_canonical_path() -> dict[str, Any]:
    """Return the canonical path description for audit / Mission Control."""
    return CANONICAL_PATH_DESCRIPTION
