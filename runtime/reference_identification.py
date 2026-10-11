"""Evidence-linked orchid identification from a photograph (IMAGE-INTEL-001).

Workflow for one unknown photograph:

1. take Vision AI character observations (``runtime.image_characters``);
2. take taxonomic / ecological candidates supplied by the caller (e.g. from
   geography and flowering time);
3. retrieve visually similar *verified* reference images (embedding cosine);
4. compare observed characters with formal descriptions and keys through
   the canonical Matrix engine (``runtime.matrix_identification``);
5. rank genus and species hypotheses, listing agreements and contradictions
   with citations and reference-image links;
6. request additional photographs when the evidence cannot separate the
   leading candidates;
7. report confidence (calibrated only when a calibration table from a real
   held-out evaluation is supplied) and abstain when appropriate.

Visual similarity is supporting evidence only. Without comparable
characters, a hypothesis is capped and labelled ``visual_similarity_only``.
Every output is provisional: it is never authoritative, never a training
label, and always requires expert review.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from runtime.image_characters import ImageCharacterObservation, compare_observation
from runtime.image_inventory import AcceptedTaxon
from runtime.matrix_identification import Candidate, Observation, rank_candidates
from runtime.reference_images import (
    DIAGNOSTIC_FLORAL_ORGANS,
    DIAGNOSTIC_FLORAL_VIEWPOINTS,
    ReferenceImageRecord,
)

IDENTIFICATION_SCHEMA_VERSION = "oc-image-identification/v1"

# Reference images allowed for retrieval and the weight of their support.
REFERENCE_WEIGHTS = {"expert_verified": 1.0, "community_consensus": 0.5}


@dataclass(frozen=True)
class IdentificationOptions:
    max_references: int = 25
    max_candidates: int = 25
    character_weight: float = 0.7
    visual_weight: float = 0.3
    visual_only_cap: float = 0.35
    temperature: float = 0.1
    # Score given to the pseudo-candidate "a taxon not represented in the
    # reference data"; it absorbs probability when nothing fits well.
    unrepresented_score: float = 0.45
    species_min_probability: float = 0.5
    species_min_margin: float = 0.15
    genus_min_probability: float = 0.6
    ood_visual_threshold: float = 0.5
    ood_character_threshold: float = 0.5
    include_unverified_references: bool = False


@dataclass(frozen=True)
class QueryImage:
    image_id: str
    observations: Sequence[ImageCharacterObservation] = ()
    embedding: Sequence[float] | None = None
    organ: str = "unknown"
    viewpoint: str = "unknown"
    has_scale: bool = False


@dataclass(frozen=True)
class CalibrationTable:
    """Reliability bins from a held-out evaluation: (upper_bound, accuracy)."""

    bins: tuple[tuple[float, float], ...]
    evaluation_id: str
    level: str = "species"

    def calibrate(self, probability: float) -> float:
        for upper, accuracy in self.bins:
            if probability <= upper:
                return accuracy
        return self.bins[-1][1] if self.bins else probability


@dataclass
class _TaxonEvidence:
    taxon_id: str
    visual: float = 0.0
    references: list[dict[str, Any]] = field(default_factory=list)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b) or not a:
        raise ValueError("embedding_dimension_mismatch")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def retrieve_references(
    query_embedding: Sequence[float],
    references: Iterable[ReferenceImageRecord],
    embeddings: Mapping[str, Sequence[float]],
    *,
    limit: int = 25,
    include_unverified: bool = False,
) -> list[dict[str, Any]]:
    """Nearest reference images, at most one per specimen group."""
    best_per_group: dict[str, dict[str, Any]] = {}
    for ref in references:
        weight = REFERENCE_WEIGHTS.get(ref.verification_status)
        if weight is None:
            if not include_unverified or ref.verification_status in {
                "expert_rejected",
                "disputed",
            }:
                continue
            weight = 0.25
        vector = embeddings.get(ref.image_id)
        if vector is None or not ref.accepted_taxon_id:
            continue
        similarity = max(0.0, cosine(query_embedding, vector))
        hit = {
            "image_id": ref.image_id,
            "accepted_taxon_id": ref.accepted_taxon_id,
            "similarity": round(similarity, 6),
            "weighted_similarity": round(similarity * weight, 6),
            "verification_status": ref.verification_status,
            "specimen_group_key": ref.specimen_group_key,
            "organ": ref.organ,
            "viewpoint": ref.viewpoint,
            "license": ref.license,
            "source": ref.source,
            "source_record_id": ref.source_record_id,
        }
        current = best_per_group.get(ref.specimen_group_key)
        if (
            current is None
            or hit["weighted_similarity"] > current["weighted_similarity"]
        ):
            best_per_group[ref.specimen_group_key] = hit
    hits = sorted(
        best_per_group.values(),
        key=lambda h: (-h["weighted_similarity"], h["image_id"]),
    )
    return hits[:limit]


_CERTAINTY_BY_CONFIDENCE = ((0.85, "certain"), (0.6, "probable"), (0.3, "uncertain"))


def _certainty(confidence: float) -> str:
    for threshold, label in _CERTAINTY_BY_CONFIDENCE:
        if confidence >= threshold:
            return label
    return "unknown"


def _photo_request(character_id: str) -> str:
    c = character_id.casefold()
    if "labell" in c or "lip" in c or "callus" in c:
        return "Face-on and lateral close-ups of the labellum, including the callus."
    if "column" in c or "anther" in c or "pollin" in c or "stigma" in c:
        return "Lateral close-up of the column (remove or fold back the labellum if possible)."
    if "inflorescence" in c or "raceme" in c or "bract" in c:
        return "The whole inflorescence, showing flower arrangement and floral bracts."
    if any(
        k in c for k in ("leaf", "pseudobulb", "stem", "root", "vegetative", "habit")
    ):
        return "Whole-plant habit showing leaves, pseudobulbs/stems and roots."
    if any(k in c for k in ("length", "width", "_mm", "size")):
        return "Re-photograph with a ruler or scale bar in the focal plane."
    if "sepal" in c or "petal" in c:
        return "Face-on view of the whole flower with sepals and petals fully visible."
    return f"A clear close-up of the structure bearing '{character_id}'."


def identify(
    query: QueryImage,
    *,
    taxa: Mapping[str, AcceptedTaxon],
    descriptions: Mapping[str, Mapping[str, Mapping[str, Any]]],
    references: Sequence[ReferenceImageRecord] = (),
    reference_embeddings: Mapping[str, Sequence[float]] | None = None,
    candidate_taxon_ids: Iterable[str] = (),
    calibration: CalibrationTable | None = None,
    options: IdentificationOptions | None = None,
) -> dict[str, Any]:
    """Rank evidence-linked identification hypotheses for one photograph.

    ``descriptions`` is the output of
    :func:`runtime.image_characters.consolidate_description_states`.
    """
    opts = options or IdentificationOptions()
    embeddings = reference_embeddings or {}

    # 1. Visual retrieval over verified references.
    hits: list[dict[str, Any]] = []
    if query.embedding is not None and references:
        hits = retrieve_references(
            query.embedding,
            references,
            embeddings,
            limit=opts.max_references,
            include_unverified=opts.include_unverified_references,
        )
    evidence: dict[str, _TaxonEvidence] = {}
    for hit in hits:
        ev = evidence.setdefault(
            hit["accepted_taxon_id"], _TaxonEvidence(hit["accepted_taxon_id"])
        )
        ev.visual = max(ev.visual, hit["weighted_similarity"])
        ev.references.append(hit)

    # 2. Candidate set: caller-supplied candidates plus visual neighbours.
    candidate_ids = list(dict.fromkeys([*candidate_taxon_ids, *evidence.keys()]))
    if not candidate_ids:
        candidate_ids = sorted(descriptions)
    candidate_ids = [c for c in candidate_ids if c in taxa][: opts.max_candidates]
    unknown_candidates = sorted(set(candidate_taxon_ids) - set(taxa))

    comparable = [o for o in query.observations if o.comparable]
    # 3. Character comparison through the canonical Matrix engine.
    matrix_observations = [
        Observation(
            character=o.character_id,
            value=o.state,
            certainty=_certainty(o.confidence)
            if o.evidence_mode == "observed"
            else ("uncertain" if o.confidence >= 0.3 else "unknown"),
        )
        for o in comparable
    ]
    matrix_candidates = []
    for taxon_id in candidate_ids:
        states: dict[str, Any] = {}
        for character_id, entry in descriptions.get(taxon_id, {}).items():
            if entry.get("numeric_range"):
                lo, hi = entry["numeric_range"]
                states[character_id] = {"min": lo, "max": hi}
            elif entry.get("states"):
                states[character_id] = list(entry["states"])
        matrix_candidates.append(
            Candidate(
                taxon_id=taxon_id,
                scientific_name=taxa[taxon_id].scientific_name,
                states=states,
            )
        )
    matrix_report = (
        rank_candidates(
            matrix_observations,
            matrix_candidates,
            limit=min(200, max(1, len(matrix_candidates))),
        )
        if matrix_observations and matrix_candidates
        else {"candidates": []}
    )
    matrix_by_taxon = {c["taxon_id"]: c for c in matrix_report.get("candidates", [])}

    # 4. Fuse character and visual evidence.
    scored: list[dict[str, Any]] = []
    for taxon_id in candidate_ids:
        taxon = taxa[taxon_id]
        comparisons = [
            compare_observation(o, descriptions.get(taxon_id, {}).get(o.character_id))
            for o in query.observations
        ]
        agreements = [c for c in comparisons if c["outcome"] == "agree"]
        contradictions = [c for c in comparisons if c["outcome"] == "contradict"]
        matrix = matrix_by_taxon.get(taxon_id)
        char_score = (
            matrix["score"] if matrix and matrix["compared_weight"] > 0 else None
        )
        coverage = matrix["coverage"] if matrix else 0.0
        visual = evidence.get(taxon_id, _TaxonEvidence(taxon_id)).visual
        if char_score is not None:
            # Down-weight character agreement that rests on few characters.
            char_component = char_score * (0.5 + 0.5 * coverage)
            score = opts.character_weight * char_component + opts.visual_weight * visual
            basis = "characters_and_visual" if visual > 0 else "characters_only"
        else:
            # Visual similarity alone can never outscore character evidence.
            score = visual * opts.visual_only_cap
            basis = "visual_similarity_only" if visual > 0 else "no_evidence"
        scored.append(
            {
                "taxon_id": taxon_id,
                "scientific_name": taxon.scientific_name,
                "genus": taxon.genus,
                "evidence_score": round(score, 6),
                "evidence_basis": basis,
                "character_score": char_score,
                "character_coverage": coverage,
                "visual_similarity": round(visual, 6),
                "agreements": agreements,
                "contradictions": contradictions,
                "description_silent_characters": sorted(
                    c["character_id"]
                    for c in comparisons
                    if c.get("reason") == "description_silent"
                ),
                "reference_images": evidence.get(
                    taxon_id, _TaxonEvidence(taxon_id)
                ).references[:5],
                "description_available": bool(descriptions.get(taxon_id)),
            }
        )

    # 5. Probabilities with an explicit "unrepresented taxon" alternative.
    t = max(opts.temperature, 1e-6)
    logits = [s["evidence_score"] / t for s in scored] + [opts.unrepresented_score / t]
    peak = max(logits) if logits else 0.0
    exps = [math.exp(x - peak) for x in logits]
    total = sum(exps) or 1.0
    unrepresented_p = exps[-1] / total
    for s, e in zip(scored, exps[:-1], strict=True):
        s["probability_uncalibrated"] = round(e / total, 6)
        s["probability"] = (
            round(calibration.calibrate(e / total), 6)
            if calibration and calibration.level == "species"
            else None
        )
    scored.sort(key=lambda s: (-s["probability_uncalibrated"], s["scientific_name"]))

    genus_p: dict[str, float] = defaultdict(float)
    for s in scored:
        genus_p[s["genus"]] += s["probability_uncalibrated"]
    genera = sorted(
        (
            {"genus": g, "probability_uncalibrated": round(p, 6)}
            for g, p in genus_p.items()
        ),
        key=lambda g: -g["probability_uncalibrated"],
    )

    # 6. Decide, abstain, or flag a possibly unrepresented taxon.
    top = scored[0] if scored else None
    second_p = scored[1]["probability_uncalibrated"] if len(scored) > 1 else 0.0
    best_visual = max((s["visual_similarity"] for s in scored), default=0.0)
    best_char = max((s["character_score"] or 0.0 for s in scored), default=0.0)
    out_of_distribution = (
        bool(scored)
        and best_visual < opts.ood_visual_threshold
        and best_char < opts.ood_character_threshold
    ) or (top is not None and unrepresented_p > top["probability_uncalibrated"])
    if not scored:
        decision, level = "abstain", None
        reason = "no_candidates_with_evidence"
    elif out_of_distribution:
        decision, level = "possible_unrepresented_taxon", None
        reason = "no_reference_or_description_fits_well"
    elif top["evidence_basis"] in {"visual_similarity_only", "no_evidence"}:
        decision, level = "abstain", None
        reason = "visual_similarity_is_not_identification"
    elif (
        top["probability_uncalibrated"] >= opts.species_min_probability
        and top["probability_uncalibrated"] - second_p >= opts.species_min_margin
        and not any(
            c["description_certainty"] == "certain" for c in top["contradictions"]
        )
    ):
        decision, level = "species_hypothesis", "species"
        reason = "leading_species_supported"
    elif genera and genera[0]["probability_uncalibrated"] >= opts.genus_min_probability:
        decision, level = "genus_hypothesis", "genus"
        reason = "species_unresolved_genus_supported"
    else:
        decision, level = "abstain", None
        reason = "evidence_does_not_separate_candidates"

    # 7. Requests for additional evidence.
    requests: list[dict[str, str]] = []
    observed_chars = {o.character_id for o in comparable}
    leaders = scored[:3]
    discriminating: set[str] = set()
    for i, a in enumerate(leaders):
        for b in leaders[i + 1 :]:
            da = descriptions.get(a["taxon_id"], {})
            db = descriptions.get(b["taxon_id"], {})
            for character_id in set(da) & set(db):
                if character_id in observed_chars:
                    continue
                sa, sb = (
                    set(da[character_id].get("states") or []),
                    set(db[character_id].get("states") or []),
                )
                ra, rb = (
                    da[character_id].get("numeric_range"),
                    db[character_id].get("numeric_range"),
                )
                if (sa and sb and not (sa & sb)) or (
                    ra and rb and (ra[1] < rb[0] or rb[1] < ra[0])
                ):
                    discriminating.add(character_id)
    if decision != "species_hypothesis":
        for character_id in sorted(discriminating):
            requests.append(
                {
                    "character_id": character_id,
                    "request": _photo_request(character_id),
                    "reason": "separates_leading_candidates",
                }
            )
        not_visible = sorted(
            {
                o.character_id
                for o in query.observations
                if o.evidence_mode in {"not_visible", "cannot_determine"}
            }
        )
        for character_id in not_visible:
            if character_id in discriminating:
                continue
            requests.append(
                {
                    "character_id": character_id,
                    "request": _photo_request(character_id),
                    "reason": "character_not_determinable_in_photo",
                }
            )
        if not (
            query.organ in DIAGNOSTIC_FLORAL_ORGANS
            and query.viewpoint in DIAGNOSTIC_FLORAL_VIEWPOINTS
        ):
            requests.append(
                {
                    "character_id": "flower",
                    "request": "A face-on view of an open flower.",
                    "reason": "no_diagnostic_floral_view",
                }
            )
        if not query.has_scale and any(
            "UNCALIBRATED" in " ".join(o.limitations) for o in query.observations
        ):
            requests.append(
                {
                    "character_id": "scale",
                    "request": "Include a ruler or scale bar in the focal plane.",
                    "reason": "measurements_withheld_without_scale",
                }
            )

    confidence = {
        "calibrated": calibration is not None,
        "calibration_evaluation_id": calibration.evaluation_id if calibration else None,
        "top_species_probability": (top["probability"] if calibration else None)
        if top
        else None,
        "top_species_probability_uncalibrated": top["probability_uncalibrated"]
        if top
        else None,
        "top_genus_probability_uncalibrated": genera[0]["probability_uncalibrated"]
        if genera
        else None,
        "unrepresented_taxon_probability_uncalibrated": round(unrepresented_p, 6),
        "note": None
        if calibration
        else "Probabilities are uncalibrated relative scores, not accuracy estimates.",
    }

    return {
        "schema_version": IDENTIFICATION_SCHEMA_VERSION,
        "query_image_id": query.image_id,
        "decision": decision,
        "decision_level": level,
        "decision_reason": reason,
        "hypotheses": scored,
        "genus_hypotheses": genera,
        "confidence": confidence,
        "additional_evidence_requests": requests,
        "observations_used": len(comparable),
        "observations_not_comparable": len(query.observations) - len(comparable),
        "reference_hits": len(hits),
        "unknown_candidate_taxon_ids": unknown_candidates,
        "governance": {
            "provisional": True,
            "authoritative": False,
            "training_label_eligible": False,
            "requires_expert_review": True,
            "canonical_taxonomy_mutation": False,
            "knowledge_graph_mutation": False,
        },
    }
