"""Bind image evidence to the knowledge graph as governed relationship links.

Produces canonical :class:`runtime.relationship_integration.RelationshipLink`
candidates - the same link type the taxonomy-image population and the
relationship-integration audit use - so image evidence enters the existing
graph pipeline rather than a parallel store. Nothing is written here.

Validation status rules:

* ``image -depicts-> taxon`` is ``verified`` only for expert-verified
  identifications; source and community identifications stay
  ``provisional``; expert-rejected identifications become ``rejected``.
* ``image -shows_character-> character`` from Vision AI is always
  ``provisional`` until a reviewer accepts the observation.
* ``image -identification_hypothesis-> taxon`` from the identification
  workflow is always ``provisional`` and flagged non-authoritative; it can
  never be used as a training label.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from runtime.image_characters import ImageCharacterObservation
from runtime.reference_images import ReferenceImageRecord
from runtime.relationship_integration import RelationshipLink

_DEPICTS_STATUS = {
    "expert_verified": "verified",
    "expert_rejected": "rejected",
    "needs_reverification": "superseded",
}


def depicts_links(records: Iterable[ReferenceImageRecord]) -> list[RelationshipLink]:
    links = []
    for rec in records:
        if not rec.accepted_taxon_id:
            continue
        links.append(
            RelationshipLink(
                source_domain="images",
                source_record_id=rec.image_id,
                target_domain="taxonomy",
                target_record_id=rec.accepted_taxon_id,
                relationship_type="depicts",
                taxon_id=rec.accepted_taxon_id,
                match_method="expert_verification"
                if rec.expert_confirmed
                else "source_identification",
                confidence=rec.identification_confidence
                if rec.identification_confidence is not None
                else (1.0 if rec.expert_confirmed else 0.5),
                provenance={
                    "source": rec.source,
                    "source_record_id": rec.source_record_id,
                    "verbatim_name": rec.verbatim_name,
                    "verification_status": rec.verification_status,
                    "verifier": rec.verifier,
                    "taxonomic_authority": rec.taxonomic_authority,
                    "taxonomy_version": rec.taxonomy_version,
                    "license": rec.license,
                },
                validation_status=_DEPICTS_STATUS.get(
                    rec.verification_status, "provisional"
                ),
            ).validated()
        )
    return links


def character_links(
    observations: Iterable[ImageCharacterObservation],
) -> list[RelationshipLink]:
    links = []
    for obs in observations:
        if not obs.comparable:
            # Not visible / undetermined is evidence of nothing; no edge.
            continue
        links.append(
            RelationshipLink(
                source_domain="images",
                source_record_id=obs.image_id,
                target_domain="morphology",
                target_record_id=obs.character_id,
                relationship_type="shows_character",
                taxon_id=None,
                match_method=obs.method,
                confidence=obs.confidence,
                provenance={
                    "observation_id": obs.observation_id,
                    "state": obs.state,
                    "unit": obs.unit,
                    "evidence_mode": obs.evidence_mode,
                    "measurement_basis": obs.measurement_basis,
                    "model_version": obs.model_version,
                    "limitations": list(obs.limitations),
                    "review_state": obs.review_state,
                },
                validation_status="verified"
                if obs.review_state == "reviewer_accepted"
                else "provisional",
            ).validated()
        )
    return links


def hypothesis_links(
    identification: Mapping[str, Any], *, max_hypotheses: int = 5
) -> list[RelationshipLink]:
    links = []
    for hyp in identification.get("hypotheses", [])[:max_hypotheses]:
        links.append(
            RelationshipLink(
                source_domain="images",
                source_record_id=str(identification["query_image_id"]),
                target_domain="taxonomy",
                target_record_id=hyp["taxon_id"],
                relationship_type="identification_hypothesis",
                taxon_id=hyp["taxon_id"],
                match_method=f"image_identification:{hyp['evidence_basis']}",
                confidence=max(0.0, min(1.0, hyp["probability_uncalibrated"])),
                provenance={
                    "schema_version": identification.get("schema_version"),
                    "decision": identification.get("decision"),
                    "agreements": [
                        a["character_id"] for a in hyp.get("agreements", [])
                    ],
                    "contradictions": [
                        c["character_id"] for c in hyp.get("contradictions", [])
                    ],
                    "reference_images": [
                        r["image_id"] for r in hyp.get("reference_images", [])
                    ],
                    "authoritative": False,
                    "training_label_eligible": False,
                },
                validation_status="provisional",
            ).validated()
        )
    return links
