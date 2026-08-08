"""Controlled scientific vocabulary for causal reasoning across biological scales.

The canonical Knowledge Graph originally modeled biodiversity relationships that
mostly radiate from a taxon. Causal biological explanations require a different
shape: mechanisms connect genes, molecules, cells, tissues, physiology,
development, environment, phenotype, and cultivation outcomes to one another.

This module is deliberately data-only. It centralizes the node types and
relationship semantics shared by graph validation and the Brain reasoning map.
It does not publish claims or mutate graph state.
"""

from __future__ import annotations

from typing import Final, TypedDict


class CausalRelationSemantics(TypedDict):
    role: str
    polarity: int
    causal: bool


CAUSAL_NODE_TYPE_DOMAIN: Final[dict[str, str]] = {
    "gene": "molecular",
    "genetic_variant": "molecular",
    "protein": "molecular",
    "enzyme": "molecular",
    "hormone": "physiology",
    "signal": "physiology",
    "cell": "anatomy",
    "tissue": "anatomy",
    "organ": "anatomy",
    "physiology": "physiology",
    "process": "physiology",
    "developmental_process": "development",
    "phenotype": "phenotype",
    "environment": "environment",
    "cultivation": "cultivation",
    "symptom": "phenotype",
    "treatment": "cultivation",
    "nutrient": "cultivation",
    "pathogen": "biotic_interactions",
    "pest": "biotic_interactions",
}

# These existing Knowledge Graph node types are also legitimate endpoints in
# causal explanations even though their primary domain predates this module.
CAUSAL_CONTEXT_NODE_TYPES: Final[frozenset[str]] = frozenset(
    {
        "taxon",
        "species",
        "genus",
        "trait",
        "climate",
        "habitat",
        "elevation",
        "pollinator",
        "fungus",
        "molecular_record",
        "assertion",
        "evidence",
        "hypothesis",
        "research_question",
    }
)

CAUSAL_REASONING_NODE_TYPES: Final[frozenset[str]] = frozenset(
    set(CAUSAL_NODE_TYPE_DOMAIN) | set(CAUSAL_CONTEXT_NODE_TYPES)
)

CAUSAL_RELATION_SEMANTICS: Final[dict[str, CausalRelationSemantics]] = {
    "causes": {"role": "causal", "polarity": 1, "causal": True},
    "promotes": {"role": "causal", "polarity": 1, "causal": True},
    "activates": {"role": "causal", "polarity": 1, "causal": True},
    "induces": {"role": "causal", "polarity": 1, "causal": True},
    "enables": {"role": "causal", "polarity": 1, "causal": True},
    "results_in": {"role": "causal", "polarity": 1, "causal": True},
    "expressed_as": {"role": "causal", "polarity": 1, "causal": True},
    "increases": {"role": "causal", "polarity": 1, "causal": True},
    "stimulates": {"role": "causal", "polarity": 1, "causal": True},
    "facilitates": {"role": "causal", "polarity": 1, "causal": True},
    "inhibits": {"role": "causal", "polarity": -1, "causal": True},
    "suppresses": {"role": "causal", "polarity": -1, "causal": True},
    "reduces": {"role": "causal", "polarity": -1, "causal": True},
    "blocks": {"role": "causal", "polarity": -1, "causal": True},
    "represses": {"role": "causal", "polarity": -1, "causal": True},
    "regulates": {"role": "regulatory", "polarity": 0, "causal": True},
    "modulates": {"role": "regulatory", "polarity": 0, "causal": True},
    "responds_to": {"role": "regulatory", "polarity": 0, "causal": True},
    "depends_on": {"role": "regulatory", "polarity": 0, "causal": True},
    "requires": {"role": "regulatory", "polarity": 0, "causal": True},
    "precedes": {"role": "regulatory", "polarity": 0, "causal": True},
    "influences": {"role": "regulatory", "polarity": 0, "causal": True},
    "supports": {"role": "evidence", "polarity": 1, "causal": False},
    "contradicts": {"role": "evidence", "polarity": -1, "causal": False},
    "observed_as": {"role": "evidence", "polarity": 0, "causal": False},
    "derived_from": {"role": "evidence", "polarity": 0, "causal": False},
    "has_evidence": {"role": "evidence", "polarity": 0, "causal": False},
}

CANONICAL_CAUSAL_EDGE_TYPES: Final[frozenset[str]] = frozenset(
    name
    for name, semantics in CAUSAL_RELATION_SEMANTICS.items()
    if semantics["causal"]
)

CAUSAL_EVIDENCE_EDGE_TYPES: Final[frozenset[str]] = frozenset(
    name
    for name, semantics in CAUSAL_RELATION_SEMANTICS.items()
    if semantics["role"] == "evidence"
)


def causal_relation_semantics(edge_type: str) -> CausalRelationSemantics | None:
    """Return controlled causal/evidence semantics for a relation when known."""
    return CAUSAL_RELATION_SEMANTICS.get(edge_type.strip().lower())


def is_causal_reasoning_edge(edge_type: str) -> bool:
    return causal_relation_semantics(edge_type) is not None
