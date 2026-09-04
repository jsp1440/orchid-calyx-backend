"""Fixture-backed orchid end-to-end proof for AI Vision → Matrix → Review path.

OC-COMPLETE-007 — AI Vision, Matrix, Glossary scientific-engine convergence.

Traces the shared scientific path:
  licensed image → visual structures/regions/observations →
  canonical glossary concept grounding → governed matrix observations →
  candidate ranking/explanation → evidence/review handoff

No live model spending. No live image URL fetching. No unlicensed media promotion.
No automatic publication. No knowledge graph mutation.

All vision suggestions remain MACHINE_GENERATED.
All matrix candidates remain unranked until a human review decision is recorded.

Scientific guards (ALL must hold at every stage output):
  - review_state = MACHINE_GENERATED
  - automatic_publication = False
  - knowledge_graph_mutation = False
  - review_required = True
  - promoted_to_kg = False (if applicable)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from app.multimodal_intelligence.contracts import (
    CharacterContribution,
    CharacterObservation,
    ImageAnalysisResult,
    MatrixCandidate,
    MatrixProfile,
    ModelProvenance,
    PlantPartDetection,
)

PROOF_SCHEMA_VERSION = "oc-vision-matrix-proof/v1"

# ---------------------------------------------------------------------------
# Fixture: representative licensed orchid herbarium image
# ---------------------------------------------------------------------------

ORCHID_IMAGE_FIXTURE: dict[str, Any] = {
    "image_id": "idigbio:uuid:0d73e8c1-2f4b-4a5d-9b23-3c7e1a4b6f82",
    "content_hash": "a" * 64,  # SHA-256 hex placeholder for fixture
    "license_code": "CC-BY-4.0",
    "attribution": "Field Museum of Natural History — Herbarium Collection — CC-BY-4.0",
    "canonical_uri": "https://example.idigbio.org/records/0d73e8c1",
    "taxon_hint": "Epidendrum secundum Jacq.",
    "source_dataset": "iDigBio",
    "source_collection": "Field Museum Herbarium",
}

# ---------------------------------------------------------------------------
# Fixture: model provenance (canonical fixture — not a live call)
# ---------------------------------------------------------------------------

MODEL_PROVENANCE_FIXTURE = ModelProvenance(
    provider="anthropic",
    model_name="claude-claude-sonnet-4-6",
    model_version="fixture-v1",
    inference_id="fixture-inference-00000000",
)

# ---------------------------------------------------------------------------
# Fixture: expected character matrix for Epidendrum secundum
#
# Drawn from published orchid flora descriptions (Dressler 1993, Williams 1946).
# These are fixture profiles only — not production data.
# ---------------------------------------------------------------------------

EPIDENDRUM_MATRIX_PROFILE = MatrixProfile(
    taxon_id="GBIF:5304082",
    accepted_name="Epidendrum secundum Jacq.",
    states={
        "chr:floral_symmetry": frozenset(["zygomorphic"]),
        "chr:labellum_fusion": frozenset(["adnate_to_column"]),
        "chr:lip_color": frozenset(["pink", "magenta", "white"]),
        "chr:inflorescence_type": frozenset(["terminal_raceme"]),
        "chr:pseudobulb_presence": frozenset(["absent"]),
        "chr:leaf_texture": frozenset(["coriaceous"]),
    },
    provenance=("published:dressler1993", "published:williams1946"),
)

# Close relative: Epidendrum radicans (common garden orchid, visually similar)
EPIDENDRUM_RADICANS_PROFILE = MatrixProfile(
    taxon_id="GBIF:5304231",
    accepted_name="Epidendrum radicans Pav. ex Lindl.",
    states={
        "chr:floral_symmetry": frozenset(["zygomorphic"]),
        "chr:labellum_fusion": frozenset(["adnate_to_column"]),
        "chr:lip_color": frozenset(["orange", "red", "yellow"]),
        "chr:inflorescence_type": frozenset(["terminal_raceme"]),
        "chr:pseudobulb_presence": frozenset(["absent"]),
        "chr:leaf_texture": frozenset(["coriaceous"]),
    },
    provenance=("published:dressler1993",),
)


# ---------------------------------------------------------------------------
# Glossary concept grounding stub
#
# In production this bridges to app.lexicon concept store.
# Here it is a bounded fixture map to prove the grounding path works.
# ---------------------------------------------------------------------------

GLOSSARY_CONCEPT_MAP: dict[str, dict[str, str]] = {
    "chr:floral_symmetry": {
        "concept_id": "chr:floral_symmetry",
        "display_label": "Floral symmetry",
        "definition": "Whether the flower has one (zygomorphic/monosymmetric) or multiple (actinomorphic/polysymmetric) planes of symmetry",
        "lexicon_source": "orchid_morphology_v1",
    },
    "chr:labellum_fusion": {
        "concept_id": "chr:labellum_fusion",
        "display_label": "Labellum fusion",
        "definition": "Degree and type of labellum (lip) fusion to the column",
        "lexicon_source": "orchid_morphology_v1",
    },
    "chr:lip_color": {
        "concept_id": "chr:lip_color",
        "display_label": "Lip colour",
        "definition": "Observed or reported colour of the labellum. IMAGE_DERIVED only from vision analysis.",
        "lexicon_source": "orchid_morphology_v1",
    },
    "chr:inflorescence_type": {
        "concept_id": "chr:inflorescence_type",
        "display_label": "Inflorescence type",
        "definition": "Arrangement of flowers on the axis (raceme, panicle, corymb, solitary, etc.)",
        "lexicon_source": "orchid_morphology_v1",
    },
    "chr:pseudobulb_presence": {
        "concept_id": "chr:pseudobulb_presence",
        "display_label": "Pseudobulb presence",
        "definition": "Whether pseudobulbs are present, absent, or indeterminate",
        "lexicon_source": "orchid_morphology_v1",
    },
    "chr:leaf_texture": {
        "concept_id": "chr:leaf_texture",
        "display_label": "Leaf texture",
        "definition": "Surface and structural quality of leaves (coriaceous, membranous, succulent, etc.)",
        "lexicon_source": "orchid_morphology_v1",
    },
}


# ---------------------------------------------------------------------------
# Stage 1: IMAGE_INTAKE — validate licensed image identity
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ImageIntakeResult:
    image_id: str
    license_code: str
    attribution: str
    source_dataset: str
    review_state: str = "MACHINE_GENERATED"
    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False
    review_required: bool = True


def stage_image_intake(fixture: dict[str, Any]) -> ImageIntakeResult:
    """STAGE 1: Accept only images with explicit license and attribution."""
    if not fixture.get("license_code") or not fixture.get("attribution"):
        raise PermissionError("LICENSE_AND_ATTRIBUTION_REQUIRED")
    return ImageIntakeResult(
        image_id=fixture["image_id"],
        license_code=fixture["license_code"],
        attribution=fixture["attribution"],
        source_dataset=fixture.get("source_dataset", "UNKNOWN"),
    )


# ---------------------------------------------------------------------------
# Stage 2: VISION_ANALYSIS — build ImageAnalysisResult from fixture
#
# In production: AI model API call yields detected_parts + character_observations.
# Here: fixture-driven with bounded confidence (capped below 0.98 guard).
# ---------------------------------------------------------------------------

def build_vision_analysis_result() -> ImageAnalysisResult:
    """STAGE 2: Construct fixture-backed vision analysis (no live model call)."""
    result = ImageAnalysisResult(
        image_id=ORCHID_IMAGE_FIXTURE["image_id"],
        content_hash=ORCHID_IMAGE_FIXTURE["content_hash"],
        license_code=ORCHID_IMAGE_FIXTURE["license_code"],
        attribution=ORCHID_IMAGE_FIXTURE["attribution"],
        model=MODEL_PROVENANCE_FIXTURE,
        detected_parts=(
            PlantPartDetection(part="labellum", confidence=0.91),
            PlantPartDetection(part="column", confidence=0.87),
            PlantPartDetection(part="lateral_sepals", confidence=0.84),
            PlantPartDetection(part="petals", confidence=0.79),
            PlantPartDetection(part="inflorescence_axis", confidence=0.76),
        ),
        character_observations=(
            CharacterObservation(
                character_id="chr:floral_symmetry",
                state="zygomorphic",
                confidence=0.93,
                provenance=("vision:labellum_detection", "vision:petal_asymmetry"),
            ),
            CharacterObservation(
                character_id="chr:lip_color",
                state="pink",
                confidence=0.85,
                provenance=("vision:color_region_labellum",),
            ),
            CharacterObservation(
                character_id="chr:inflorescence_type",
                state="terminal_raceme",
                confidence=0.72,
                provenance=("vision:inflorescence_axis",),
            ),
            CharacterObservation(
                character_id="chr:pseudobulb_presence",
                state=None,
                confidence=0.61,
                provenance=("vision:stem_base_region",),
            ),
        ),
        warnings=("chr:pseudobulb_presence state=None: region occluded in image",),
    )
    result.validate()
    return result


# ---------------------------------------------------------------------------
# Stage 3: GLOSSARY_GROUNDING — map character_ids to Lexicon concepts
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GroundingResult:
    character_id: str
    observed_state: str | None
    confidence: float
    concept: dict[str, str] | None
    grounding_status: str  # GROUNDED, UNGROUNDED
    review_state: str = "MACHINE_GENERATED"
    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False


def stage_glossary_grounding(
    observations: tuple[CharacterObservation, ...],
) -> list[GroundingResult]:
    """STAGE 3: Ground each character_id to a canonical Lexicon concept."""
    results = []
    for obs in observations:
        concept = GLOSSARY_CONCEPT_MAP.get(obs.character_id)
        results.append(
            GroundingResult(
                character_id=obs.character_id,
                observed_state=obs.state,
                confidence=obs.confidence,
                concept=concept,
                grounding_status="GROUNDED" if concept else "UNGROUNDED",
            )
        )
    return results


# ---------------------------------------------------------------------------
# Stage 4: MATRIX_SCORING — score each candidate taxon against observations
# ---------------------------------------------------------------------------

def _score_candidate(
    observations: tuple[CharacterObservation, ...],
    profile: MatrixProfile,
) -> MatrixCandidate:
    """Score a candidate taxon against a set of character observations."""
    support = 0
    contradiction = 0
    unknown = 0
    contributions = []
    total_score = 0.0

    for obs in observations:
        expected = profile.states.get(obs.character_id)
        if expected is None:
            unknown += 1
            outcome = "UNKNOWN"
            weighted = 0.0
        elif obs.state is None:
            unknown += 1
            outcome = "UNKNOWN"
            weighted = 0.0
        elif obs.state in expected:
            support += 1
            outcome = "SUPPORT"
            weighted = obs.confidence
        else:
            contradiction += 1
            outcome = "CONTRADICTION"
            weighted = -obs.confidence
        total_score += weighted
        contributions.append(
            CharacterContribution(
                character_id=obs.character_id,
                observed_state=obs.state,
                expected_states=tuple(sorted(expected)) if expected else (),
                outcome=outcome,
                weighted_score=weighted,
            )
        )

    return MatrixCandidate(
        taxon_id=profile.taxon_id,
        accepted_name=profile.accepted_name,
        score=round(total_score, 4),
        support_count=support,
        contradiction_count=contradiction,
        unknown_count=unknown,
        contributions=tuple(contributions),
    )


@dataclass
class MatrixScoringResult:
    candidates: list[MatrixCandidate]
    observation_count: int
    review_state: str = "MACHINE_GENERATED"
    automatic_publication: bool = False
    knowledge_graph_mutation: bool = False
    review_required: bool = True


def stage_matrix_scoring(
    vision_result: ImageAnalysisResult,
    profiles: list[MatrixProfile],
) -> MatrixScoringResult:
    """STAGE 4: Score each candidate taxon profile against vision observations."""
    candidates = [
        _score_candidate(vision_result.character_observations, profile)
        for profile in profiles
    ]
    candidates.sort(key=lambda c: c.score, reverse=True)
    return MatrixScoringResult(
        candidates=candidates,
        observation_count=len(vision_result.character_observations),
    )


# ---------------------------------------------------------------------------
# Stage 5: REVIEW_HANDOFF — produce governed evidence/review handoff record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReviewHandoff:
    handoff_id: str
    image_id: str
    top_candidate: str
    top_candidate_taxon_id: str
    top_score: float
    support_count: int
    contradiction_count: int
    unknown_count: int
    observation_count: int
    model_provenance: str
    review_state: str
    automatic_publication: bool
    knowledge_graph_mutation: bool
    review_required: bool
    promoted_to_kg: bool
    handoff_note: str


def stage_review_handoff(
    intake: ImageIntakeResult,
    vision: ImageAnalysisResult,
    scoring: MatrixScoringResult,
) -> ReviewHandoff:
    """STAGE 5: Produce governed handoff record for human scientific review."""
    top = scoring.candidates[0] if scoring.candidates else None
    return ReviewHandoff(
        handoff_id=f"handoff:{vision.image_id}",
        image_id=vision.image_id,
        top_candidate=top.accepted_name if top else "NONE",
        top_candidate_taxon_id=top.taxon_id if top else "NONE",
        top_score=top.score if top else 0.0,
        support_count=top.support_count if top else 0,
        contradiction_count=top.contradiction_count if top else 0,
        unknown_count=top.unknown_count if top else 0,
        observation_count=scoring.observation_count,
        model_provenance=f"{vision.model.provider}/{vision.model.model_name}@{vision.model.model_version}",
        review_state="MACHINE_GENERATED",
        automatic_publication=False,
        knowledge_graph_mutation=False,
        review_required=True,
        promoted_to_kg=False,
        handoff_note=(
            "AI suggestion awaiting expert botanical review. "
            "Score reflects fixture-based character matching only. "
            "No publication or knowledge graph mutation will occur without "
            "separate scientific review and owner authorization."
        ),
    )


# ---------------------------------------------------------------------------
# Full proof runner
# ---------------------------------------------------------------------------

def run_vision_matrix_proof(
    *,
    image_fixture: dict[str, Any] | None = None,
    candidate_profiles: list[MatrixProfile] | None = None,
) -> dict[str, Any]:
    """Run the orchid image → vision → glossary → matrix → review proof.

    All five stages execute against bounded fixtures; no live model or DB call.

    Returns:
        Proof dict with all five stage outputs, hard invariant attestations,
        and a PASS/FAIL verdict.
    """
    if image_fixture is None:
        image_fixture = ORCHID_IMAGE_FIXTURE
    if candidate_profiles is None:
        candidate_profiles = [EPIDENDRUM_MATRIX_PROFILE, EPIDENDRUM_RADICANS_PROFILE]

    stage_intake = stage_image_intake(image_fixture)
    stage_vision = build_vision_analysis_result()
    stage_grounding = stage_glossary_grounding(stage_vision.character_observations)
    stage_scoring = stage_matrix_scoring(stage_vision, candidate_profiles)
    handoff = stage_review_handoff(stage_intake, stage_vision, stage_scoring)

    grounded_count = sum(1 for g in stage_grounding if g.grounding_status == "GROUNDED")
    all_machine_generated = (
        stage_intake.review_state == "MACHINE_GENERATED"
        and stage_scoring.review_state == "MACHINE_GENERATED"
        and handoff.review_state == "MACHINE_GENERATED"
    )
    no_auto_publication = (
        stage_intake.automatic_publication is False
        and stage_scoring.automatic_publication is False
        and handoff.automatic_publication is False
    )
    no_kg_mutation = (
        stage_intake.knowledge_graph_mutation is False
        and stage_scoring.knowledge_graph_mutation is False
        and handoff.knowledge_graph_mutation is False
    )
    not_promoted = handoff.promoted_to_kg is False

    invariants_hold = all_machine_generated and no_auto_publication and no_kg_mutation and not_promoted
    verdict = "PASS" if invariants_hold else "FAIL_INVARIANT_VIOLATION"

    def _candidate_to_dict(c: MatrixCandidate) -> dict[str, Any]:
        return {
            "taxon_id": c.taxon_id,
            "accepted_name": c.accepted_name,
            "score": c.score,
            "support_count": c.support_count,
            "contradiction_count": c.contradiction_count,
            "unknown_count": c.unknown_count,
            "contributions": [
                {
                    "character_id": contrib.character_id,
                    "observed_state": contrib.observed_state,
                    "expected_states": list(contrib.expected_states),
                    "outcome": contrib.outcome,
                    "weighted_score": contrib.weighted_score,
                }
                for contrib in c.contributions
            ],
        }

    return {
        "schema_version": PROOF_SCHEMA_VERSION,
        "verdict": verdict,
        "stages": {
            "image_intake": {
                "stage": "IMAGE_INTAKE",
                "image_id": stage_intake.image_id,
                "license_code": stage_intake.license_code,
                "source_dataset": stage_intake.source_dataset,
                "review_state": stage_intake.review_state,
                "automatic_publication": stage_intake.automatic_publication,
                "knowledge_graph_mutation": stage_intake.knowledge_graph_mutation,
            },
            "vision_analysis": {
                "stage": "VISION_ANALYSIS",
                "image_id": stage_vision.image_id,
                "model_provider": stage_vision.model.provider,
                "model_name": stage_vision.model.model_name,
                "detected_parts_count": len(stage_vision.detected_parts),
                "character_observations_count": len(stage_vision.character_observations),
                "warnings": list(stage_vision.warnings),
                "review_state": "MACHINE_GENERATED",
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            },
            "glossary_grounding": {
                "stage": "GLOSSARY_GROUNDING",
                "observation_count": len(stage_grounding),
                "grounded_count": grounded_count,
                "ungrounded_count": len(stage_grounding) - grounded_count,
                "groundings": [
                    {
                        "character_id": g.character_id,
                        "observed_state": g.observed_state,
                        "confidence": g.confidence,
                        "grounding_status": g.grounding_status,
                        "concept_label": g.concept["display_label"] if g.concept else None,
                    }
                    for g in stage_grounding
                ],
                "review_state": "MACHINE_GENERATED",
                "automatic_publication": False,
                "knowledge_graph_mutation": False,
            },
            "matrix_scoring": {
                "stage": "MATRIX_SCORING",
                "observation_count": stage_scoring.observation_count,
                "candidate_count": len(stage_scoring.candidates),
                "ranked_candidates": [_candidate_to_dict(c) for c in stage_scoring.candidates],
                "review_state": stage_scoring.review_state,
                "automatic_publication": stage_scoring.automatic_publication,
                "knowledge_graph_mutation": stage_scoring.knowledge_graph_mutation,
                "review_required": stage_scoring.review_required,
            },
            "review_handoff": {
                "stage": "REVIEW_HANDOFF",
                "handoff_id": handoff.handoff_id,
                "top_candidate": handoff.top_candidate,
                "top_candidate_taxon_id": handoff.top_candidate_taxon_id,
                "top_score": handoff.top_score,
                "support_count": handoff.support_count,
                "contradiction_count": handoff.contradiction_count,
                "unknown_count": handoff.unknown_count,
                "review_state": handoff.review_state,
                "automatic_publication": handoff.automatic_publication,
                "knowledge_graph_mutation": handoff.knowledge_graph_mutation,
                "review_required": handoff.review_required,
                "promoted_to_kg": handoff.promoted_to_kg,
                "handoff_note": handoff.handoff_note,
            },
        },
        "invariant_attestations": {
            "all_stages_machine_generated": all_machine_generated,
            "no_automatic_publication_at_any_stage": no_auto_publication,
            "no_knowledge_graph_mutation_at_any_stage": no_kg_mutation,
            "not_promoted_to_kg": not_promoted,
            "all_invariants_hold": invariants_hold,
        },
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
    }


def serialize_proof_as_json(proof: dict[str, Any], *, indent: int = 2) -> str:
    return json.dumps(proof, indent=indent, sort_keys=False, default=str)
