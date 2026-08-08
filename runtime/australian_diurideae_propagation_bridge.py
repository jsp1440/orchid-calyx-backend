"""Proximal Australian Diurideae propagation evidence for CALYX-639E.

This module records the Collins & Dixon (1992) Diuris longifolia work as a
phylogenetically closer comparator to Thelymitra variegata than the broader
terrestrial-orchid comparator set. It remains comparator evidence: it never
converts Diuris methods into a Thelymitra protocol or success prediction.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

SCHEMA_VERSION = "calyx-australian-diurideae-propagation-bridge/v1"
DIURIS_DOI = "10.1071/EA9920131"


@dataclass(frozen=True)
class ProximalSource:
    source_id: str
    title: str
    taxon: str
    authors: tuple[str, ...]
    year: int
    doi: str
    institution: str
    source_evidence_level: str
    tribe: str
    subtribe: str
    growth_form: str
    distribution_context: str

    def digest(self) -> str:
        return _sha(asdict(self))


@dataclass(frozen=True)
class ProximalObservation:
    observation_id: str
    source_id: str
    taxon: str
    explant: str
    explant_origin: str
    response: str
    treatment: tuple[tuple[str, str], ...]
    response_time_days: float | None = None
    destructive_parent_sampling_required: bool | None = None
    direct_thelymitra_evidence: bool = False
    publication_authority: bool = False

    def digest(self) -> str:
        return _sha(asdict(self))


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    material = value if isinstance(value, str) else _stable(value)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def diuris_source() -> ProximalSource:
    return ProximalSource(
        source_id="collins-dixon-1992-diuris-longifolia",
        title="Micropropagation of an Australian terrestrial orchid Diuris longifolia R. Br.",
        taxon="Diuris longifolia",
        authors=("Margaret T. Collins", "Kingsley W. Dixon"),
        year=1992,
        doi=DIURIS_DOI,
        institution="Kings Park and Botanic Garden, Western Australia",
        source_evidence_level="author_uploaded_article_text_with_publisher_preview",
        tribe="Diurideae",
        subtribe="Diuridinae",
        growth_form="tuberous terrestrial geophyte",
        distribution_context="south-western Western Australia",
    )


def diuris_observations() -> tuple[ProximalObservation, ...]:
    source_id = diuris_source().source_id
    return (
        ProximalObservation(
            observation_id="dl-flower-bud-base-plb-001",
            source_id=source_id,
            taxon="Diuris longifolia",
            explant="basal section of unopened flower bud",
            explant_origin="inflorescence collected from an intact field plant",
            response="protocorm-like bodies formed",
            treatment=(
                ("basal_medium", "modified Burgeff N3f / Pa5 context"),
                ("benzyladenine", "10 µM in reported initiation/proliferation treatment"),
            ),
            response_time_days=49.0,
            destructive_parent_sampling_required=False,
        ),
        ProximalObservation(
            observation_id="dl-inflorescence-node-plb-002",
            source_id=source_id,
            taxon="Diuris longifolia",
            explant="axillary node from inflorescence",
            explant_origin="inflorescence collected from an intact field plant",
            response="protocorm-like bodies formed",
            treatment=(
                ("basal_medium", "modified Burgeff N3f / Pa5 context"),
                ("benzyladenine", "10 µM in reported initiation/proliferation treatment"),
            ),
            response_time_days=49.0,
            destructive_parent_sampling_required=False,
        ),
        ProximalObservation(
            observation_id="dl-shoot-rooting-003",
            source_id=source_id,
            taxon="Diuris longifolia",
            explant="10-20 mm in-vitro shoot",
            explant_origin="PLB-derived micropropagated shoot",
            response="root formation after transfer",
            treatment=(
                ("medium", "reported coconut-water-containing medium"),
                ("cytokinin", "none in rooting treatment"),
            ),
            response_time_days=70.0,
            destructive_parent_sampling_required=False,
        ),
    )


def phylogenetic_bridge() -> dict[str, Any]:
    """Return a bounded proximity statement grounded in Diurideae phylogeny."""
    return {
        "schema_version": SCHEMA_VERSION,
        "focal_taxon": "Thelymitra variegata",
        "focal_subtribe": "Thelymitrinae",
        "comparator_taxon": "Diuris longifolia",
        "comparator_subtribe": "Diuridinae",
        "shared_tribe": "Diurideae",
        "relationship_state": (
            "Diuridinae is a proximal core-Diurideae lineage outside the clade containing "
            "Thelymitrinae; it is closer than the broad comparator taxa but is not the same subtribe."
        ),
        "same_subtribe": False,
        "direct_thelymitra_evidence": False,
        "method_transfer_validated": False,
        "success_probability_generated": False,
        "scientific_review_required": True,
        "publication_authority": False,
        "knowledge_graph_mutation_authorized": False,
    }


def non_destructive_bridge_assessment() -> dict[str, Any]:
    observations = diuris_observations()
    non_destructive_plb = [
        item
        for item in observations
        if item.response == "protocorm-like bodies formed"
        and item.destructive_parent_sampling_required is False
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "question": (
            "Is non-destructive somatic PLB initiation documented in a phylogenetically "
            "proximal Australian tuberous Diurideae orchid?"
        ),
        "answer_state": "documented_in_diuris_longifolia",
        "supporting_observation_ids": [item.observation_id for item in non_destructive_plb],
        "supported_explants": [item.explant for item in non_destructive_plb],
        "key_relevance": (
            "A tuberous Western Australian terrestrial orchid was clonally propagated to PLBs "
            "from inflorescence-derived tissue without sacrificing the parent plant."
        ),
        "direct_thelymitra_evidence": False,
        "recommended_thelymitra_explant": None,
        "success_probability_generated": False,
        "scientific_review_required": True,
        "publication_authority": False,
        "knowledge_graph_mutation_authorized": False,
    }


def bridge_matrix() -> list[dict[str, Any]]:
    source = diuris_source()
    return [
        {
            **asdict(item),
            "treatment": dict(item.treatment),
            "source": {
                **asdict(source),
                "source_sha256": source.digest(),
            },
            "observation_sha256": item.digest(),
        }
        for item in diuris_observations()
    ]
