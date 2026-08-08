"""Independent terrestrial-orchid comparator evidence for CALYX-639.

These records test whether the proposed vegetative-entry question has precedent in
other terrestrial orchids. They are comparative evidence only: no record is allowed
to prove or predict that Thelymitra variegata will respond similarly.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

COMPARATOR_SCHEMA_VERSION = "calyx-terrestrial-orchid-propagation-comparator/v1"


@dataclass(frozen=True)
class ComparatorSource:
    source_id: str
    title: str
    taxon: str
    year: int
    doi: str | None
    pmid: str | None
    evidence_completeness: str
    terrestrial_orchid: bool
    conservation_context: str

    def digest(self) -> str:
        return _sha(asdict(self))


@dataclass(frozen=True)
class ComparatorObservation:
    observation_id: str
    source_id: str
    taxon: str
    explant: str
    explant_origin: str
    response: str
    treatment: tuple[tuple[str, str], ...]
    quantitative_value: float | None = None
    quantitative_unit: str | None = None
    response_time_days: float | None = None
    direction: str = "positive"
    abstract_reported: bool = True
    directly_about_thelymitra: bool = False
    publication_authority: bool = False

    def digest(self) -> str:
        return _sha(asdict(self))


def _stable(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(value: Any) -> str:
    material = value if isinstance(value, str) else _stable(value)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def comparator_sources() -> tuple[ComparatorSource, ...]:
    return (
        ComparatorSource(
            source_id="teng-1997-spathoglottis-plicata",
            title="Micropropagation of Spathoglottis plicata",
            taxon="Spathoglottis plicata",
            year=1997,
            doi="10.1007/s002990050329",
            pmid="30727588",
            evidence_completeness="pubmed_abstract_verified",
            terrestrial_orchid=True,
            conservation_context="terrestrial orchid micropropagation comparator",
        ),
        ComparatorSource(
            source_id="martin-madassery-2005-ipsea-malabarica",
            title=(
                "Rapid in vitro propagation of the threatened endemic orchid, "
                "Ipsea malabarica through protocorm-like bodies"
            ),
            taxon="Ipsea malabarica",
            year=2005,
            doi=None,
            pmid="16187536",
            evidence_completeness="pubmed_abstract_verified",
            terrestrial_orchid=True,
            conservation_context=(
                "threatened endemic terrestrial orchid; propagation and attempted reintroduction"
            ),
        ),
    )


def comparator_observations() -> tuple[ComparatorObservation, ...]:
    """Encode only quantitative/method facts stated in the verified PubMed abstracts."""
    return (
        ComparatorObservation(
            observation_id="sp-nodal-plb-001",
            source_id="teng-1997-spathoglottis-plicata",
            taxon="Spathoglottis plicata",
            explant="nodal explant",
            explant_origin="8-month-old pot-grown seedling",
            response="PLB regeneration followed by plantlet development",
            treatment=(
                ("basal_medium", "charcoal-amended Murashige and Skoog"),
                ("NAA", "5.37 µM"),
                ("BA", "0.44 µM"),
            ),
            quantitative_value=98.5,
            quantitative_unit="percent nodal explants producing PLBs/plantlets",
        ),
        ComparatorObservation(
            observation_id="sp-leaf-plb-002",
            source_id="teng-1997-spathoglottis-plicata",
            taxon="Spathoglottis plicata",
            explant="leaf explant",
            explant_origin="8-month-old pot-grown seedling",
            response="PLB regeneration followed by plantlet development",
            treatment=(("medium_context", "same 16 NAA/BA combinations investigated"),),
            quantitative_value=6.5,
            quantitative_unit="percent leaf explants producing PLBs/plantlets",
        ),
        ComparatorObservation(
            observation_id="sp-root-plb-003",
            source_id="teng-1997-spathoglottis-plicata",
            taxon="Spathoglottis plicata",
            explant="root segment",
            explant_origin="regenerated in vitro plantlet",
            response="occasional PLB and plantlet production",
            treatment=(("medium_context", "reported in micropropagation experiment"),),
            direction="low_frequency_positive",
        ),
        ComparatorObservation(
            observation_id="im-axillary-plb-001",
            source_id="martin-madassery-2005-ipsea-malabarica",
            taxon="Ipsea malabarica",
            explant="axillary bud",
            explant_origin="in vitro shoot derived from field-grown rhizome",
            response="axillary buds converted to PLBs",
            treatment=(
                ("basal_medium", "Murashige and Skoog"),
                ("BA", "13.3 µM"),
                ("commercial_grade_sugar", "2%"),
            ),
            quantitative_value=33.1,
            quantitative_unit="mean PLBs by 50 days",
            response_time_days=25.0,
        ),
        ComparatorObservation(
            observation_id="im-kin-negative-002",
            source_id="martin-madassery-2005-ipsea-malabarica",
            taxon="Ipsea malabarica",
            explant="axillary bud",
            explant_origin="in vitro shoot derived from field-grown rhizome",
            response="kinetin did not induce PLBs; axillary bud proliferation occurred",
            treatment=(("kinetin", "tested; concentration not retained from abstract summary"),),
            direction="negative_for_plb_induction",
        ),
        ComparatorObservation(
            observation_id="im-plb-multiply-003",
            source_id="martin-madassery-2005-ipsea-malabarica",
            taxon="Ipsea malabarica",
            explant="PLB",
            explant_origin="axillary-bud-derived PLB",
            response="rapid secondary PLB multiplication",
            treatment=(
                ("basal_medium", "Murashige and Skoog"),
                ("BA", "13.3 µM"),
                ("commercial_grade_sugar", "2%"),
            ),
            quantitative_value=47.5,
            quantitative_unit="mean PLBs after transfer",
        ),
        ComparatorObservation(
            observation_id="im-plantlet-004",
            source_id="martin-madassery-2005-ipsea-malabarica",
            taxon="Ipsea malabarica",
            explant="PLB",
            explant_origin="axillary-bud-derived PLB",
            response="PLBs converted to plantlets",
            treatment=(
                ("basal_medium", "half-strength Murashige and Skoog"),
                ("kinetin", "6.97 µM"),
            ),
            quantitative_value=98.0,
            quantitative_unit="percent PLBs converted to plantlets",
        ),
    )


def comparator_matrix() -> list[dict[str, Any]]:
    sources = {source.source_id: source for source in comparator_sources()}
    rows: list[dict[str, Any]] = []
    for observation in sorted(comparator_observations(), key=lambda item: item.observation_id):
        source = sources[observation.source_id]
        rows.append(
            {
                **asdict(observation),
                "treatment": dict(observation.treatment),
                "source": {
                    "title": source.title,
                    "year": source.year,
                    "doi": source.doi,
                    "pmid": source.pmid,
                    "evidence_completeness": source.evidence_completeness,
                    "terrestrial_orchid": source.terrestrial_orchid,
                    "conservation_context": source.conservation_context,
                    "source_sha256": source.digest(),
                },
                "observation_sha256": observation.digest(),
            }
        )
    return rows


def vegetative_plb_bridge_assessment() -> dict[str, Any]:
    observations = comparator_observations()
    vegetative = [
        item
        for item in observations
        if item.explant in {"nodal explant", "leaf explant", "root segment", "axillary bud"}
    ]
    positive = [item for item in vegetative if item.direction != "negative_for_plb_induction"]
    negative = [item for item in vegetative if item.direction == "negative_for_plb_induction"]
    taxa = sorted({item.taxon for item in positive})
    return {
        "schema_version": COMPARATOR_SCHEMA_VERSION,
        "question": (
            "Is vegetative-tissue-to-PLB regeneration documented in terrestrial orchids "
            "independently of Thelymitra variegata?"
        ),
        "answer_state": "documented_in_other_terrestrial_orchids",
        "positive_vegetative_observation_ids": [item.observation_id for item in positive],
        "negative_or_noninductive_observation_ids": [item.observation_id for item in negative],
        "supporting_taxa": taxa,
        "direct_thelymitra_evidence": False,
        "prediction_of_thelymitra_success": False,
        "interpretation": (
            "Vegetative explants can enter PLB pathways in other terrestrial orchids, "
            "so the proposed Thelymitra vegetative-entry experiment has biological "
            "precedent. The evidence does not establish explant choice, medium, response "
            "rate, or feasibility for Thelymitra variegata."
        ),
        "scientific_review_required": True,
        "publication_authority": False,
        "knowledge_graph_mutation_authorized": False,
    }
