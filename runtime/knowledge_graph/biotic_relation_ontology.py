"""GloBI-compatible normalization of literature-derived biotic interactions.

Global Biotic Interactions (GloBI) indexes verbatim association terms by mapping
those terms to a controlled subset of the OBO Relations Ontology (RO).  Orchid
Continuum uses the same interoperability pattern for reviewed literature claims:
retain the verbatim predicate, normalize only recognized terms, and publish the
canonical GloBI/RO relation label plus its RO URI.

This module is intentionally conservative.  Unknown predicates remain unknown;
there is no embedding/fuzzy inference and no relationship is authored merely
because two taxa co-occur in a paper.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True, slots=True)
class BioticRelation:
    label: str
    ro_uri: str


# Current GloBI-supported RO interaction labels used for indexing.  Keeping the
# canonical GloBI labels gives Orchid Continuum direct semantic interoperability
# with EOL/GloBI while the URI preserves ontology identity independently of text.
GLOBI_RO_RELATIONS: dict[str, str] = {
    "preysOn": "http://purl.obolibrary.org/obo/RO_0002439",
    "parasiteOf": "http://purl.obolibrary.org/obo/RO_0002444",
    "hasHost": "http://purl.obolibrary.org/obo/RO_0002454",
    "hasReservoirHost": "http://purl.obolibrary.org/obo/RO_0002803",
    "interactsWith": "http://purl.obolibrary.org/obo/RO_0002437",
    "trophicallyInteractsWith": "http://purl.obolibrary.org/obo/RO_0002438",
    "hostOf": "http://purl.obolibrary.org/obo/RO_0002453",
    "reservoirHostOf": "http://purl.obolibrary.org/obo/RO_0002802",
    "pollinates": "http://purl.obolibrary.org/obo/RO_0002455",
    "eats": "http://purl.obolibrary.org/obo/RO_0002470",
    "symbiontOf": "http://purl.obolibrary.org/obo/RO_0002440",
    "preyedUponBy": "http://purl.obolibrary.org/obo/RO_0002458",
    "pollinatedBy": "http://purl.obolibrary.org/obo/RO_0002456",
    "eatenBy": "http://purl.obolibrary.org/obo/RO_0002471",
    "hasParasite": "http://purl.obolibrary.org/obo/RO_0002445",
    "hasPathogen": "http://purl.obolibrary.org/obo/RO_0002557",
    "pathogenOf": "http://purl.obolibrary.org/obo/RO_0002556",
    "hasVector": "http://purl.obolibrary.org/obo/RO_0002460",
    "vectorOf": "http://purl.obolibrary.org/obo/RO_0002459",
    "visitedBy": "http://purl.obolibrary.org/obo/RO_0002619",
    "visits": "http://purl.obolibrary.org/obo/RO_0002618",
    "flowersVisitedBy": "http://purl.obolibrary.org/obo/RO_0002623",
    "visitsFlowersOf": "http://purl.obolibrary.org/obo/RO_0002622",
    "adjacentTo": "http://purl.obolibrary.org/obo/RO_0002220",
    "createsHabitatFor": "http://purl.obolibrary.org/obo/RO_0008505",
    "hasHabitat": "http://purl.obolibrary.org/obo/RO_0002303",
    "endoparasiteOf": "http://purl.obolibrary.org/obo/RO_0002634",
    "hasEndoparasite": "http://purl.obolibrary.org/obo/RO_0002635",
    "hyperparasiteOf": "http://purl.obolibrary.org/obo/RO_0002553",
    "hasHyperparasite": "http://purl.obolibrary.org/obo/RO_0002554",
    "ectoparasiteOf": "http://purl.obolibrary.org/obo/RO_0002632",
    "hasEctoparasite": "http://purl.obolibrary.org/obo/RO_0002633",
    "kleptoparasiteOf": "http://purl.obolibrary.org/obo/RO_0008503",
    "hasKleptoparasite": "http://purl.obolibrary.org/obo/RO_0008504",
    "parasitoidOf": "http://purl.obolibrary.org/obo/RO_0002208",
    "hasParasitoid": "http://purl.obolibrary.org/obo/RO_0002209",
    "killedBy": "http://purl.obolibrary.org/obo/RO_0002627",
    "kills": "http://purl.obolibrary.org/obo/RO_0002626",
    "epiphyteOf": "http://purl.obolibrary.org/obo/RO_0008501",
    "hasEpiphyte": "http://purl.obolibrary.org/obo/RO_0008502",
    "laysEggsOn": "http://purl.obolibrary.org/obo/RO_0008507",
    "hasEggsLayedOnBy": "http://purl.obolibrary.org/obo/RO_0008508",
    "laysEggsIn": "http://purl.obolibrary.org/obo/RO_0002624",
    "hasEggsLayedInBy": "http://purl.obolibrary.org/obo/RO_0002625",
    "coOccursWith": "http://purl.obolibrary.org/obo/RO_0008506",
    "commensalistOf": "http://purl.obolibrary.org/obo/RO_0002441",
    "mutualistOf": "http://purl.obolibrary.org/obo/RO_0002442",
    "ecologicallyRelatedTo": "http://purl.obolibrary.org/obo/RO_0002321",
    "coRoostsWith": "http://purl.obolibrary.org/obo/RO_0002801",
    "hasRoost": "http://purl.obolibrary.org/obo/RO_0008509",
    "acquiresNutrientsFrom": "http://purl.obolibrary.org/obo/RO_0002457",
    "providesNutrientsFor": "http://purl.obolibrary.org/obo/RO_0002469",
    "hemiparasiteOf": "http://purl.obolibrary.org/obo/RO_0002237",
    "rootparasiteOf": "http://purl.obolibrary.org/obo/RO_0002236",
    "allelopathOf": "http://purl.obolibrary.org/obo/RO_0002555",
    "hasAllelopath": "http://purl.obolibrary.org/obo/RO_0020301",
    "ectomycorrhizalHostOf": "http://purl.obolibrary.org/obo/RO_0002804",
    "hasEctomycorrhizalHost": "http://purl.obolibrary.org/obo/RO_0002805",
    "arbuscularMycorrhizalHostOf": "http://purl.obolibrary.org/obo/RO_0002806",
    "hasArbuscularMycorrhizalHost": "http://purl.obolibrary.org/obo/RO_0002807",
}


def _key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


# A deliberately small GloBI-style translation layer for common scientific prose.
# More verbatim forms can be added from reviewed extraction telemetry without
# changing the canonical graph vocabulary.
_VERBATIM_TO_LABEL: dict[str, str] = {
    _key("pollinates"): "pollinates",
    _key("pollinated by"): "pollinatedBy",
    _key("visits"): "visits",
    _key("visits flowers of"): "visitsFlowersOf",
    _key("flower visitor of"): "visitsFlowersOf",
    _key("preys on"): "preysOn",
    _key("predates"): "preysOn",
    _key("eats"): "eats",
    _key("feeds on"): "eats",
    _key("parasite of"): "parasiteOf",
    _key("parasitizes"): "parasiteOf",
    _key("parasitoid of"): "parasitoidOf",
    _key("pathogen of"): "pathogenOf",
    _key("infects"): "pathogenOf",
    _key("host of"): "hostOf",
    _key("host for"): "hostOf",
    _key("vector of"): "vectorOf",
    _key("symbiont of"): "symbiontOf",
    _key("mutualist of"): "mutualistOf",
    _key("commensalist of"): "commensalistOf",
    _key("epiphyte of"): "epiphyteOf",
    _key("grows epiphytically on"): "epiphyteOf",
    _key("co-occurs with"): "coOccursWith",
    _key("interacts with"): "interactsWith",
    _key("ecologically related to"): "ecologicallyRelatedTo",
    _key("acquires nutrients from"): "acquiresNutrientsFrom",
    _key("obtains nutrients from"): "acquiresNutrientsFrom",
    _key("provides nutrients for"): "providesNutrientsFor",
    _key("lays eggs on"): "laysEggsOn",
    _key("lays eggs in"): "laysEggsIn",
    _key("kills"): "kills",
}
for _label in GLOBI_RO_RELATIONS:
    _VERBATIM_TO_LABEL.setdefault(_key(_label), _label)


def normalize_biotic_relation(predicate: str | None) -> BioticRelation | None:
    """Return a canonical GloBI/RO relationship for a recognized predicate.

    Unknown or empty predicates fail closed.  This function normalizes language;
    it does not establish that a biological relationship is true.  Publication
    eligibility and source evidence are enforced by the caller.
    """
    if not predicate or not str(predicate).strip():
        return None
    label = _VERBATIM_TO_LABEL.get(_key(str(predicate)))
    if not label:
        return None
    return BioticRelation(label=label, ro_uri=GLOBI_RO_RELATIONS[label])


BIOTIC_RELATION_EDGE_TYPE_DOMAIN: dict[str, str] = {
    label: "biotic_interactions" for label in GLOBI_RO_RELATIONS
}
