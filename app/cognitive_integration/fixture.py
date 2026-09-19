"""The pollination scenario, seeded into the real knowledge graph fabric.

This is a *fixture*, not a second graph. It builds ordinary
:class:`runtime.knowledge_graph.Node` and :class:`Edge` records and loads them
into ``InMemoryGraphRepository`` — the same repository protocol the Postgres
store implements — so the executor traverses them with the real
``ReasoningMapEngine``. Nothing here is a parallel structure, and nothing here
is written to the canonical graph.

The scenario is *Ophrys apifera*, chosen because the published record genuinely
disagrees with itself: the same taxon is reported as pollinated by sexual
deception and as habitually self-pollinating. A fixture that resolved that
disagreement would be teaching the system to fabricate. This one carries it.

Every citation here supports the claim it is attached to, and only that claim.
That is not a detail in a fixture whose purpose is to demonstrate provenance
integrity — a fabricated attribution here would discredit everything the path
asserts about its own sources.
"""

from __future__ import annotations

from runtime.knowledge_graph import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository

#: Evidence classes used here. They mirror the vocabulary the reasoning map
#: contract allows; none of them asserts canonical fact.
SUPPORTED = "SUPPORTED"
CONTESTED = "CONTESTED"
REPORTED_UNVERIFIED = "REPORTED_UNVERIFIED"

#: Darwin observed *O. apifera* habitually self-fertilising and remarked on never
#: having seen an insect visit it. That is what this citation supports, and the
#: only claim it is attached to.
DARWIN_1862 = (
    "Darwin, C. (1862). On the Various Contrivances by which British and Foreign "
    "Orchids are Fertilised by Insects. John Murray, London."
)

#: Pseudocopulation in *Ophrys* was proposed by Pouyanne and Correvon in
#: 1916-1923 and established systematically by Kullenberg. Attributing it to
#: Darwin would credit him with a mechanism described more than fifty years
#: after his book, and would invert what he actually wrote about this species.
KULLENBERG_1961 = (
    "Kullenberg, B. (1961). Studies in Ophrys pollination. "
    "Zoologiska Bidrag fran Uppsala 34: 1-340."
)

#: Provenance types. A 19th-century single-author monograph is not a
#: peer-reviewed journal article, and a system that distinguishes evidence
#: classes should not record it as one.
MONOGRAPH = "scholarly_monograph"
PEER_REVIEWED = "peer_reviewed_literature"
OCCURRENCE = "occurrence_dataset"

SUBJECT_KEY = "taxon:ophrys-apifera"


def _node(node_id: int, node_type: str, key: str, label: str, **payload) -> Node:
    return Node(
        kg_node_id=node_id,
        node_type=node_type,
        canonical_key=key,
        display_label=label,
        evidence_class=payload.pop("evidence_class", None),
        payload=payload,
    )


def _edge(
    edge_id: int,
    edge_type: str,
    src: int,
    dst: int,
    *,
    evidence_class: str,
    citation: str | None = None,
    source_type: str | None = None,
    **payload,
) -> Edge:
    return Edge(
        kg_edge_id=edge_id,
        edge_type=edge_type,
        from_node_id=src,
        to_node_id=dst,
        evidence_class=evidence_class,
        payload={"citation": citation, "source_type": source_type, **payload},
    )


def build_pollination_repository() -> InMemoryGraphRepository:
    """Seed the scenario. Deterministic: identical on every call."""
    nodes = [
        _node(1, "taxon", SUBJECT_KEY, "Ophrys apifera",
              authorship="Huds.", rank="species",
              taxonomic_status="recorded_in_orchid_taxonomy_table"),
        _node(2, "organism", "pollinator:eucera", "Eucera (solitary bees)",
              identified_to="genus"),
        _node(3, "process", "process:sexual-deception", "Sexual deception"),
        _node(4, "process", "process:autogamy", "Habitual self-pollination"),
        _node(5, "environment", "habitat:calcareous-grassland",
              "Calcareous grassland"),
        _node(6, "region", "region:mediterranean", "Mediterranean range"),
        _node(7, "region", "region:north-western-europe", "North-western range"),
    ]

    edges = [
        # The two reports that disagree. Both are carried; neither is preferred.
        #
        # The scopes are deliberately asymmetric, because the record is. Autogamy
        # is the predominant mode throughout the range, including the
        # Mediterranean; insect pollination is a sporadic local exception rather
        # than a regional alternative. Framing it as "Mediterranean versus
        # north-west" would be tidier and would overstate what is reported.
        # Kullenberg established pseudocopulation across *Ophrys*, which is the
        # right source for the mechanism. It is weaker support for *this*
        # species being insect-pollinated, because *O. apifera* is precisely the
        # autogamous exception within the genus. The apifera-specific *Eucera*
        # reports are scattered Mediterranean observations that are not
        # Kullenberg's subject and that this fixture does not hold. Saying so is
        # the honest move; inventing a species-level citation is not.
        _edge(1, "reported_pollinated_by", 1, 2,
              evidence_class=CONTESTED, citation=KULLENBERG_1961,
              source_type=PEER_REVIEWED, support_scope="genus",
              geographic_scope="sporadically reported, chiefly in the Mediterranean"),
        _edge(2, "reported_reproductive_strategy", 1, 4,
              evidence_class=SUPPORTED, citation=DARWIN_1862,
              source_type=MONOGRAPH,
              geographic_scope="predominant throughout the range"),
        # Mechanism attachment. Cited to the work that established it, not to
        # Darwin, who had no concept of sexual deception.
        _edge(3, "mechanism_of", 2, 3,
              evidence_class=SUPPORTED, citation=KULLENBERG_1961,
              source_type=PEER_REVIEWED),
        # Habitat and range, from occurrence records only.
        _edge(4, "co_occurs_with", 1, 5,
              evidence_class=REPORTED_UNVERIFIED,
              citation="Aggregated occurrence records held in the Continuum, habitat field only.",
              source_type=OCCURRENCE),
        _edge(5, "reported_from", 1, 6,
              evidence_class=REPORTED_UNVERIFIED,
              citation="Aggregated occurrence records, country resolution only.",
              source_type=OCCURRENCE),
        _edge(6, "reported_from", 1, 7,
              evidence_class=REPORTED_UNVERIFIED,
              citation="Aggregated occurrence records, country resolution only.",
              source_type=OCCURRENCE),
        # Regions that do not overlap, declared rather than inferred from their
        # names. Scope can only resolve a disagreement when the two claims are
        # established to apply to separate ground, and no amount of string
        # comparison over free-text scope labels establishes that.
        #
        # Note which edges do NOT carry a scope_region: the two reproductive
        # reports. Their scopes are frequency statements over overlapping
        # ground — autogamy is predominant throughout the range, the Mediterranean
        # included — so the disagreement genuinely stands, and pinning either to
        # a region here would resolve it by fiat.
        _edge(7, "disjoint_from", 6, 7,
              evidence_class=REPORTED_UNVERIFIED,
              citation="Range descriptions in the aggregated occurrence records.",
              source_type=OCCURRENCE),
    ]
    return InMemoryGraphRepository(nodes=nodes, edges=edges)


#: Relationships the scenario deliberately does NOT contain, so that gap
#: detection has something real to find rather than a contrived absence.
EXPECTED_BUT_ABSENT = (
    ("observed_pollination_event", "no population-level pollination observation is held"),
    ("quantified_seed_set", "no source quantifies the contribution of either strategy"),
)
