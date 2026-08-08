"""Same-subtribe propagation evidence-gap registry for CALYX-639G.

This module records the result of a targeted Thelymitrinae evidence search without
converting search non-retrieval into evidence of absence. It identifies authoritative
acquisition leads and keeps direct vegetative-culture support unresolved until source
text is acquired and reviewed.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

SCHEMA_VERSION = "calyx-thelymitrinae-propagation-evidence-gap/v1"


@dataclass(frozen=True)
class AcquisitionLead:
    lead_id: str
    title: str
    authors: tuple[str, ...]
    source_type: str
    focal_taxa: tuple[str, ...]
    retrievable_fact: str
    unresolved_question: str
    acquisition_priority: str
    direct_vegetative_evidence_verified: bool = False
    publication_authority: bool = False

    def digest(self) -> str:
        return _sha(asdict(self))


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    material = value if isinstance(value, str) else _stable(value)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def acquisition_leads() -> tuple[AcquisitionLead, ...]:
    return (
        AcquisitionLead(
            lead_id="yam-arditti-micropropagation-thelymitra",
            title="Micropropagation of Orchids, Third Edition",
            authors=("Tim Wing Yam", "Joseph Arditti"),
            source_type="specialist_reference_book",
            focal_taxa=("Thelymitra",),
            retrievable_fact=(
                "Publisher table of contents confirms a dedicated Thelymitra section in the "
                "micropropagation reference work."
            ),
            unresolved_question=(
                "Does the Thelymitra section document vegetative explants, meristem/shoot-tip "
                "culture, inflorescence-derived culture, PLB induction, or only seed/protocorm methods?"
            ),
            acquisition_priority="critical",
        ),
        AcquisitionLead(
            lead_id="dbca-kings-park-queen-of-sheba-conservation",
            title="Saving orchids one species at a time",
            authors=("Department of Biodiversity, Conservation and Attractions",),
            source_type="institutional_conservation_summary",
            focal_taxa=("Thelymitra variegata",),
            retrievable_fact=(
                "Kings Park reports work improving tissue-culture output and vigour from limited "
                "Queen of Sheba seed sources and expects broader conservation value."
            ),
            unresolved_question=(
                "The summary does not establish a mature vegetative explant entry route; obtain "
                "underlying protocols and technical reports before inferring one."
            ),
            acquisition_priority="high",
        ),
    )


def targeted_search_state() -> dict[str, Any]:
    leads = acquisition_leads()
    return {
        "schema_version": SCHEMA_VERSION,
        "focal_subtribe": "Thelymitrinae",
        "searched_genera": ["Thelymitra", "Calochilus", "Epiblema"],
        "question": (
            "Is direct vegetative-to-PLB or meristematic micropropagation verified within "
            "Thelymitrinae independently of the Davis et al. seed/protocorm pathway?"
        ),
        "answer_state": "unresolved_source_acquisition_required",
        "direct_same_subtribe_vegetative_evidence_verified": False,
        "evidence_of_absence_claimed": False,
        "search_nonretrieval_means_absence": False,
        "lead_count": len(leads),
        "lead_ids": [lead.lead_id for lead in leads],
        "highest_priority_next_source": "yam-arditti-micropropagation-thelymitra",
        "scientific_review_required": True,
        "publication_authority": False,
        "knowledge_graph_mutation_authorized": False,
    }


def evidence_ladder() -> dict[str, Any]:
    """Return the current bounded evidence hierarchy for vegetative entry."""
    return {
        "schema_version": SCHEMA_VERSION,
        "focal_taxon": "Thelymitra variegata",
        "levels": [
            {
                "rank": 1,
                "scope": "same species",
                "state": "seed/protocorm_PLB_pathway_verified; vegetative_entry_unverified",
            },
            {
                "rank": 2,
                "scope": "same subtribe Thelymitrinae",
                "state": "unresolved_source_acquisition_required",
            },
            {
                "rank": 3,
                "scope": "proximal core Diurideae",
                "state": "Diuris_longifolia_non_destructive_inflorescence_to_PLB_documented",
            },
            {
                "rank": 4,
                "scope": "other terrestrial orchids",
                "state": "vegetative_and_meristem_to_PLB_documented_multiple_taxa",
            },
        ],
        "automatic_protocol_selection_allowed": False,
        "destructive_tuber_sampling_priority": "defer_until_lower_risk_routes_reviewed",
        "scientific_review_required": True,
        "publication_authority": False,
        "knowledge_graph_mutation_authorized": False,
    }


def acquisition_matrix() -> list[dict[str, Any]]:
    return [
        {**asdict(lead), "lead_sha256": lead.digest()}
        for lead in sorted(acquisition_leads(), key=lambda item: item.lead_id)
    ]
