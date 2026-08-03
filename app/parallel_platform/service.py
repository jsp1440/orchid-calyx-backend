from __future__ import annotations

from typing import Any

from app.parallel_platform.contracts import CONTRACT_VERSION, MATRIX_DIMENSIONS, IdentificationRequest, MatrixRequest


def capabilities() -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION,
        "homepage": {"available": True, "source": "canonical_backend_contract"},
        "relationship_matrix": {"available": True, "dimensions": list(MATRIX_DIMENSIONS)},
        "identification": {"available": True, "verified_identity_authority": False},
        "education": {"available": True, "state": "contract_ready"},
        "design": {"available": True, "state": "contract_ready"},
        "brain_handoff": {"available": True, "automatic_implementation": False},
    }


def homepage_document() -> dict[str, Any]:
    section_names = (
        "mission",
        "featured_genus",
        "featured_species",
        "evolution",
        "relationships",
        "species",
        "conservation",
        "education",
        "current_activity",
    )
    return {
        "contract_version": CONTRACT_VERSION,
        "title": "Orchid Continuum",
        "mission": "Connect orchid biodiversity knowledge across species, places, evidence, and people.",
        "sections": [
            {
                "id": name,
                "availability": "degraded",
                "data": None,
                "evidence": [],
                "message": "Canonical source integration is pending for this section.",
            }
            for name in section_names
        ],
        "governance": {
            "real_approved_imagery_only": True,
            "provenance_required": True,
            "uncertainty_required": True,
            "client_scoring_allowed": False,
        },
    }


def score_matrix(request: MatrixRequest) -> dict[str, Any]:
    dimensions: list[dict[str, Any]] = []
    weighted_total = 0.0
    total_weight = 0.0
    for name in MATRIX_DIMENSIONS:
        item = request.dimensions.get(name)
        if item is None or not item.available or item.score is None:
            dimensions.append(
                {
                    "name": name,
                    "availability": "unavailable",
                    "score": None,
                    "weight": item.weight if item else 1.0,
                    "confidence": None,
                    "evidence": item.evidence if item else [],
                }
            )
            continue
        availability = "available" if item.evidence else "degraded"
        confidence = item.confidence if item.confidence is not None else (0.6 if item.evidence else 0.25)
        dimensions.append(
            {
                "name": name,
                "availability": availability,
                "score": item.score,
                "weight": item.weight,
                "confidence": confidence,
                "evidence": item.evidence,
            }
        )
        if item.weight > 0:
            weighted_total += item.score * item.weight
            total_weight += item.weight
    score = round(weighted_total / total_weight, 6) if total_weight else None
    coverage = round(sum(item["score"] is not None for item in dimensions) / len(dimensions), 6)
    return {
        "contract_version": CONTRACT_VERSION,
        "subject_taxon_id": request.subject_taxon_id,
        "object_taxon_id": request.object_taxon_id,
        "score": score,
        "coverage": coverage,
        "dimensions": dimensions,
        "interpretation": "candidate_relationship" if score is not None else "insufficient_evidence",
        "publication_authority": False,
    }


def rank_candidates(request: IdentificationRequest) -> dict[str, Any]:
    observed = request.features
    ranked: list[dict[str, Any]] = []
    for candidate in request.candidates:
        keys = sorted(set(observed) | set(candidate.features))
        support: list[str] = []
        conflicts: list[str] = []
        missing: list[str] = []
        for key in keys:
            if key not in observed or key not in candidate.features or observed[key] is None or candidate.features[key] is None:
                missing.append(key)
            elif observed[key] == candidate.features[key]:
                support.append(key)
            else:
                conflicts.append(key)
        assessed = len(support) + len(conflicts)
        fit = len(support) / assessed if assessed else 0.0
        completeness = assessed / len(keys) if keys else 0.0
        score = round(fit * (0.5 + 0.5 * completeness), 6)
        ranked.append(
            {
                "taxon_id": candidate.taxon_id,
                "scientific_name": candidate.scientific_name,
                "score": score,
                "support": support,
                "conflicts": conflicts,
                "missing": missing,
                "evidence": candidate.evidence,
                "state": "candidate_suggestion",
            }
        )
    ranked.sort(key=lambda item: (-item["score"], item["taxon_id"]))
    unresolved = sorted({feature for item in ranked for feature in item["missing"]})
    state = "observation_incomplete"
    if ranked:
        top = ranked[0]
        state = "requires_expert_review" if top["score"] >= 0.85 and not top["conflicts"] else "ambiguous"
    return {
        "contract_version": CONTRACT_VERSION,
        "observation_id": request.observation_id,
        "state": state,
        "candidates": ranked,
        "next_best_observation": unresolved[0] if unresolved else None,
        "verified_identity": None,
        "publication_authority": False,
    }
