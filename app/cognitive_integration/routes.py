"""Serve the Cognitive Integration reasoning map to Calyx.

Public read. The map carries no locality, no submitter identity and no
credential — every field is assembled from evidence that is already citable, and
the executor fails closed rather than serving a map that leaked.

The optional prose explanation is *not* generated here. This route returns the
structured reasoning, which is what lets a client show evidence, contradiction,
uncertainty and unknowns as distinct things rather than as one paragraph.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from .executor import CognitiveIntegrationError, execute

router = APIRouter(prefix="/api/cognitive-integration", tags=["cognitive-integration"])

#: The question forms the deterministic decomposition covers. Anything else needs
#: `free-text-intent-parsing`, which requires a provider, so it is refused here
#: rather than answered from a decomposition that does not fit it.
SUPPORTED_QUESTIONS = (
    "What pollinates the bee orchid, and is the answer the same everywhere it grows?",
)


@router.get("/reasoning-map")
def reasoning_map(
    question: str = Query(default=SUPPORTED_QUESTIONS[0], max_length=500),
) -> dict[str, Any]:
    """Return the inspectable reasoning map for a supported question.

    A question outside the stored set is refused with what it would take to
    answer it, rather than being answered from a decomposition written for a
    different question.
    """
    if question not in SUPPORTED_QUESTIONS:
        raise HTTPException(
            status_code=422,
            detail={
                "reason": "question_not_in_deterministic_set",
                "message": (
                    "This question is not one the stored decomposition covers. "
                    "Interpreting an arbitrary question requires the "
                    "free-text-intent-parsing capability, which needs a provider."
                ),
                "supported_questions": list(SUPPORTED_QUESTIONS),
                "required_capability": "free-text-intent-parsing",
            },
        )
    try:
        return execute(question)
    except CognitiveIntegrationError as exc:
        raise HTTPException(status_code=503, detail={"reason": str(exc)}) from exc


@router.get("/capabilities")
def capabilities() -> dict[str, Any]:
    """What this path uses, and which part of it would need a provider."""
    from .executor import DETERMINISTIC_CAPABILITIES, OPTIONAL_CAPABILITY

    return {
        "deterministic": list(DETERMINISTIC_CAPABILITIES),
        "optional_provider": [OPTIONAL_CAPABILITY],
        "provider_required_for_reasoning": False,
        "note": (
            "The reasoning is assembled deterministically. A provider is needed only to "
            "render it as prose, and its absence changes nothing else."
        ),
    }
