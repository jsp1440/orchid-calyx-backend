"""Execute the Cognitive Integration path, deterministically and with no provider.

One traversal from a scientific question to an inspectable answer, assembled by
the capabilities the swarm router classifies as deterministic:

    taxonomy-resolution -> literature-evidence-lookup -> interaction-kg-lookup
    -> geospatial-context -> reasoning-map-assembly -> contradiction-detection
    -> evidence-gap-detection -> locality-redaction

The traversal itself is the existing ``ReasoningMapEngine`` over the existing
knowledge-graph repository protocol. This module does not re-implement either;
it selects capabilities, runs them in order, and assembles the result into the
contract the Brain validates.

``natural-language-explanation`` is the one capability here that genuinely needs
a model. It is optional: its absence changes ``explanation_available`` and
nothing else, so the reasoning still reaches Calyx as structured fields.
"""

from __future__ import annotations

import re
from typing import Any

from app.brain.reasoning_map import (
    ReasoningDirection,
    ReasoningMapEngine,
    ReasoningProfile,
)
from runtime.knowledge_graph.repository import GraphRepository

from .fixture import EXPECTED_BUT_ABSENT, SUBJECT_KEY, build_pollination_repository

CONTRACT_VERSION = "1.0.0"

#: The capabilities this executor uses, in the order it uses them. Each one is
#: classified deterministic by app/provider_reservoir/capabilities.py, so this
#: path never reaches a provider lane.
DETERMINISTIC_CAPABILITIES = (
    "taxonomy-resolution",
    "literature-evidence-lookup",
    "interaction-kg-lookup",
    "geospatial-context",
    "reasoning-map-assembly",
    "contradiction-detection",
    "evidence-gap-detection",
    "locality-redaction",
)

#: Needed only to render the assembled result as prose. Optional by construction.
OPTIONAL_CAPABILITY = "natural-language-explanation"

_ALLOWED_EVIDENCE_STATES = frozenset(
    {"SUPPORTED", "CONTESTED", "REPORTED_UNVERIFIED", "REFUTED"}
)

#: Edge types that assert something about reproduction. Two of these pointing at
#: incompatible processes is what contradiction detection looks for.
_REPRODUCTIVE_PREDICATES = ("reported_pollinated_by", "reported_reproductive_strategy")

#: What gets removed.
#:
#: Widened twice, each time after a checker demonstrated a shape that walked
#: through. The first round added space-separated pairs, one- and two-decimal
#: pairs, bare ``lat``/``lon`` without a separator, and the typographic
#: apostrophe. The second added the shapes that carry a position without ever
#: writing a digits-and-dot pair: coordinates spelled out in words, UTM and
#: MGRS grid references, Open Location Codes, and European comma decimals.
#:
#: The lesson each round taught is the same one: this pattern is a list of
#: shapes someone thought of. It is not a proof, which is why the assertion at
#: the end of :func:`execute` deliberately uses a wider net than this.
_DEGREE_WORD = r"(?:\u00b0|deg\.?|degrees?)"
_MINUTE_WORD = r"(?:['\u2018\u2019\u2032]|min\.?|minutes?)"
_HEMISPHERE = r"(?:[NSEW]\b|north|south|east|west)"

_COORDINATE = re.compile(
    # A decimal pair separated by a comma, semicolon or whitespace. One decimal
    # place is ~11 km and still worth withholding for a protected taxon.
    r"[-+]?\d{1,3}\.\d+\s*(?:[,;]\s*|\s+)[-+]?\d{1,3}\.\d+"
    # A named coordinate, with or without a separator character.
    r"|\b(?:lat|latitude|lng|lon|long|longitude)\b\s*[=:]?\s*[-+]?\d+(?:\.\d+)?"
    # Degrees and minutes, symbol or word, straight or typographic apostrophe.
    rf"|\d{{1,3}}\s*{_DEGREE_WORD}\s*\d{{1,2}}\s*{_MINUTE_WORD}"
    # Degrees with a hemisphere, symbol or spelled out. This is the arm that
    # catches "51.7520 degrees north", which carried ~10 m of precision past
    # both the redactor and the fail-closed check.
    rf"|\d{{1,3}}(?:\.\d+)?\s*{_DEGREE_WORD}\s*{_HEMISPHERE}"
    # European comma decimals, as a pair. Three digits after the comma is a
    # thousands separator ("1,234 records") and is deliberately not matched.
    r"|\d{1,3},(?:\d{1,2}|\d{4,})\s*(?:[; ]\s*)[-+]?\d{1,3},(?:\d{1,2}|\d{4,})"
    # UTM and MGRS grid references, which locate a site with no degrees at all.
    r"|\b\d{1,2}\s*[C-HJ-NP-X]\s*[A-Z]{2}\s*\d{4,10}\b"
    r"|\bUTM\b[^\n]{0,24}?\d{5,7}\s+\d{5,8}"
    r"|\b\d{1,2}[C-HJ-NP-X]\s+\d{5,7}\s+\d{5,8}\b"
    # Open Location Code (plus code): eight of the code alphabet, then "+".
    r"|\b[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,7}\b",
    re.IGNORECASE,
)

#: A deliberately broader net for the final check.
#:
#: If the redactor and the assertion share one pattern, the assertion can only
#: confirm what the redactor already did — it cannot catch what the redactor
#: missed. So this one *contains* the redactor's pattern and adds to it, which
#: makes "strictly broader" a structural property rather than a claim: there is
#: no string the redactor matches that this does not.
#:
#: It over-triggers on purpose. A false positive costs one raise; a false
#: negative publishes a wild orchid's position.
_COORDINATE_SUSPICION = re.compile(
    _COORDINATE.pattern
    # Any two decimal numbers in plausible degree range, however separated.
    + r"|[-+]?(?:1[0-7]\d|\d{1,2})\.\d+\D{0,24}[-+]?(?:1[0-7]\d|\d{1,2})\.\d+"
    # Vocabulary that accompanies a position even when the digits are elsewhere.
    + r"|\b(?:lat|lon|lng|latitude|longitude|coordinate|coordinates|gps|utm|mgrs"
    + r"|grid\s*ref(?:erence)?|plus\s*code|what3words|easting|northing|geohash)\b"
    + r"|\u00b0"
    + r"|\b\d{1,3}\s*(?:deg\.?|degrees?)\b"
    # Two long digit runs side by side: the shape of a projected coordinate.
    + r"|\b\d{6,8}\s+\d{6,8}\b",
    re.IGNORECASE,
)


class CognitiveIntegrationError(RuntimeError):
    """The path could not be executed. Raised rather than returning a partial map."""


def _decompose(question: str) -> list[str]:
    """Stored decomposition for the fixture question.

    Deliberately not generated. Parsing an arbitrary free-text question into a
    structured intent is ``free-text-intent-parsing``, which needs a model; the
    known question forms are covered deterministically so the slice runs without
    one.
    """
    return [
        "Resolve the subject to an accepted taxon.",
        "Retrieve reported reproductive relationships for that taxon.",
        "Retrieve the geographic scope each report applies to.",
        "Compare reports that disagree rather than choosing between them.",
        "State what the retrieved evidence does not cover.",
    ]


def _resolve_taxonomy(repository: GraphRepository) -> dict[str, Any]:
    node = repository.get_node_by_key(SUBJECT_KEY)
    if node is None:
        raise CognitiveIntegrationError(f"subject {SUBJECT_KEY!r} is not in the graph")
    payload = node.payload or {}
    return {
        "accepted_name": node.display_label,
        "authorship": payload.get("authorship"),
        "rank": payload.get("rank", "unknown"),
        "taxonomic_status": payload.get("taxonomic_status", "unknown"),
        "resolved_against": "knowledge graph taxon node",
        "kg_node_id": node.kg_node_id,
    }


def _relationships(repository: GraphRepository, subject_id: int) -> list[dict[str, Any]]:
    """Literature and interaction evidence, each carrying its own provenance."""
    nodes = {n.kg_node_id: n for n in repository.all_nodes()}
    rows: list[dict[str, Any]] = []
    for edge in sorted(repository.all_edges(), key=lambda e: e.kg_edge_id):
        if edge.from_node_id != subject_id:
            continue
        state = edge.evidence_class
        if state not in _ALLOWED_EVIDENCE_STATES:
            raise CognitiveIntegrationError(
                f"edge {edge.kg_edge_id} carries evidence state {state!r}, which is not "
                "one of the states a reasoning map may present"
            )
        payload = edge.payload or {}
        rows.append(
            {
                "subject": nodes[edge.from_node_id].display_label,
                "predicate": edge.edge_type,
                "object": nodes[edge.to_node_id].display_label,
                "evidence_state": state,
                "geographic_scope": payload.get("geographic_scope"),
                # Structured scope, used to decide whether a disagreement is
                # resolved by the claims applying to different places. Stripped
                # before serving: it is routing input, not a published claim.
                "scope_region": payload.get("scope_region"),
                # How far the cited source actually reaches. A genus-wide study
                # cited for a species-level claim is real support, but not for
                # the claim as stated. Routing input, stripped before serving.
                "support_scope": payload.get("support_scope"),
                "provenance": [
                    {
                        "source_type": payload.get("source_type") or "occurrence_dataset",
                        "citation": payload.get("citation") or "",
                        "identifier": payload.get("identifier"),
                    }
                ],
            }
        )
    if not rows:
        raise CognitiveIntegrationError("no relationship evidence retrieved for the subject")
    return rows


def _geographic_context(
    relationships: list[dict[str, Any]], disjoint: set[frozenset[str]]
) -> dict[str, Any]:
    regions = sorted({r["object"] for r in relationships if r["predicate"] == "reported_from"})
    habitats = sorted({r["object"] for r in relationships if r["predicate"] == "co_occurs_with"})
    notes = [f"Most records associate the taxon with {h.lower()}." for h in habitats]
    # Only claim a regional division when the graph establishes one. Two
    # different scope strings are not a division: "predominant throughout the
    # range" and "chiefly in the Mediterranean" describe overlapping ground, and
    # asserting a split for them is the overstatement the scopes were reworded
    # to remove.
    scoped = {
        r["scope_region"]
        for r in relationships
        if r["predicate"] in _REPRODUCTIVE_PREDICATES and r.get("scope_region")
    }
    if any(pair <= scoped for pair in disjoint):
        notes.append(
            "The reported reproductive strategy differs between parts of the range, "
            "so scope is part of the claim rather than context for it."
        )
    elif len({r.get("geographic_scope") for r in relationships if r.get("geographic_scope")}) > 1:
        notes.append(
            "The reports carry different scopes, but nothing retrieved establishes that "
            "those scopes are separate places, so the difference does not divide the range."
        )
    return {
        "scope": "; ".join(regions) if regions else "unspecified",
        "environmental_notes": notes,
        "coordinates_present": False,
    }


def _mechanisms(repository: GraphRepository, relationships: list[dict[str, Any]]) -> list[dict]:
    nodes = {n.kg_node_id: n for n in repository.all_nodes()}
    mechanism_edges = [e for e in repository.all_edges() if e.edge_type == "mechanism_of"]
    out: list[dict[str, Any]] = []
    for edge in sorted(mechanism_edges, key=lambda e: e.kg_edge_id):
        out.append(
            {
                "name": (nodes[edge.to_node_id].display_label or "").lower(),
                "kind": "proposed_mechanism",
                "statement": (
                    f"{nodes[edge.from_node_id].display_label} is reported to pollinate the "
                    f"subject by {(nodes[edge.to_node_id].display_label or '').lower()}."
                ),
                "evidence_state": edge.evidence_class,
            }
        )
    for relationship in relationships:
        if relationship["predicate"] == "reported_reproductive_strategy":
            # Describe what the edge says, not what this fixture's edge happens
            # to say. The previous wording asserted "reproduces without any
            # insect" for every reported strategy, so relabelling the node to an
            # insect-mediated one would have emitted a false statement while the
            # detection stayed correct.
            scope = relationship.get("geographic_scope") or "the reported range"
            out.append(
                {
                    "name": (relationship["object"] or "").lower(),
                    "kind": "competing_mechanism",
                    "statement": (
                        f"{relationship['object']} is reported as the reproductive strategy "
                        f"({scope}), which is a separate account of how seed set occurs."
                    ),
                    "evidence_state": relationship["evidence_state"],
                }
            )
    # The null explanation is not derived from an edge, because its whole point
    # is that no edge supports it. An observed visit is not evidence of
    # pollination, and a map that omitted this would overstate the others.
    out.append(
        {
            "name": "no pollinator relationship in this population",
            "kind": "null_explanation",
            "statement": (
                "An observed insect visit does not establish pollination. Where another "
                "retrieved strategy already accounts for seed set, a visiting insect may "
                "be incidental."
            ),
            "evidence_state": "REPORTED_UNVERIFIED",
        }
    )
    return out


def _disjoint_regions(repository: GraphRepository) -> set[frozenset[str]]:
    """Region pairs the graph declares non-overlapping.

    Read from ``disjoint_from`` edges rather than assumed. Two place names being
    different strings says nothing about whether the places overlap: "throughout
    the range" and "chiefly in the Mediterranean" are different strings
    describing ground that includes the same ground.
    """
    keys = {node.kg_node_id: node.canonical_key for node in repository.all_nodes()}
    pairs: set[frozenset[str]] = set()
    for edge in repository.all_edges():
        if edge.edge_type != "disjoint_from":
            continue
        first, second = keys.get(edge.from_node_id), keys.get(edge.to_node_id)
        if first and second and first != second:
            pairs.add(frozenset({first, second}))
    return pairs


def _scope_resolution(
    first: dict[str, Any], second: dict[str, Any], disjoint: set[frozenset[str]]
) -> str:
    """Whether a disagreement is resolved by the two claims applying elsewhere.

    Resolution requires *established* disjointness: both claims naming a region,
    and the graph declaring those two regions non-overlapping. Anything short of
    that leaves the contradiction standing, which is the fail-closed direction —
    a contradiction wrongly left open costs a reader some care, and one wrongly
    closed deletes a real scientific disagreement.

    Three things this deliberately does not treat as resolution:

    * **Equal scopes.** Two incompatible claims about the *same* place is the
      definition of a live conflict. The predicate this replaced returned
      ``resolved_by_scope`` for exactly that case, and because absent scopes
      compare equal, it did so for every claim that named no place at all —
      then dropped the contradiction from ``unresolved`` and *raised* the
      confidence for it.
    * **Absent scopes.** Unknown is not the same as equal, and it is not the
      same as disjoint.
    * **Different free-text scopes.** Different wording is not disjointness.
    """
    first_region = first.get("scope_region")
    second_region = second.get("scope_region")
    if not first_region or not second_region:
        return "unresolved_presented_as_contested"
    if first_region == second_region:
        return "unresolved_presented_as_contested"
    if frozenset({first_region, second_region}) not in disjoint:
        return "unresolved_presented_as_contested"
    return "resolved_by_scope"


def _describe_conflict(first: dict[str, Any], second: dict[str, Any]) -> str:
    """Say what the two claims are, rather than what they were expected to be.

    The sentence this replaced asserted that one report was insect-mediated and
    the other needed no insect. That is true of the shipped fixture and false of
    any graph where both reports are insect-mediated, where it would have gone
    on describing a difference that was not there.
    """
    return (
        f"One report gives {first['object']}; the other gives {second['object']}. "
        "Both are carried. They are not reconciled by preferring the "
        "better-supported one."
    )


def _contradictions(
    relationships: list[dict[str, Any]], disjoint: set[frozenset[str]]
) -> list[dict[str, Any]]:
    """Find claims that disagree, and keep both rather than choosing."""
    reproductive = [r for r in relationships if r["predicate"] in _REPRODUCTIVE_PREDICATES]
    found: list[dict[str, Any]] = []
    for index, first in enumerate(reproductive):
        for second in reproductive[index + 1 :]:
            if first["predicate"] == second["predicate"]:
                continue
            found.append(
                {
                    "between": [
                        f"{first['predicate']} {first['object']}",
                        f"{second['predicate']} {second['object']}",
                    ],
                    "description": _describe_conflict(first, second),
                    "resolution": _scope_resolution(first, second, disjoint),
                    "scopes": [first.get("geographic_scope"), second.get("geographic_scope")],
                }
            )
    return found


def _evidence_gaps(repository: GraphRepository, relationships: list[dict[str, Any]]) -> list[str]:
    """What the retrieved evidence does not cover, derived from the graph."""
    present = {r["predicate"] for r in relationships}
    gaps = [
        reason for predicate, reason in EXPECTED_BUT_ABSENT if predicate not in present
    ]
    nodes = {n.kg_node_id: n for n in repository.all_nodes()}
    for node in nodes.values():
        if (node.payload or {}).get("identified_to") == "genus":
            gaps.append(
                f"{node.display_label} is identified to genus, not species, in the "
                "retrieved evidence."
            )
    if not any(r["provenance"][0]["source_type"] == "human_observation" for r in relationships):
        gaps.append(
            "No local observation supports any retrieved claim; the evidence is literature "
            "and aggregated records only."
        )
    # A source establishing something across a genus is weak support for a claim
    # about one species in it, and it is weakest precisely where the species is
    # the genus's exception — which is this taxon's whole scientific interest.
    # The citation field cannot say this (the reasoning-map contract fixes the
    # provenance keys), so the limitation is stated here rather than left for a
    # reader to notice. Substituting a species-level citation nobody retrieved
    # would be the fabrication this whole path exists to avoid.
    for relationship in relationships:
        if relationship.get("support_scope") != "genus":
            continue
        gaps.append(
            f"The source for {relationship['subject']} {relationship['predicate']} "
            f"{relationship['object']} establishes this at genus level; nothing "
            "retrieved reports it for this species specifically."
        )
    return gaps


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _COORDINATE.sub("[locality withheld]", value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


def _confidence(unresolved: list[dict[str, Any]], gaps: list[str]) -> dict[str, Any]:
    """Confidence and the reasons for it, derived together so they cannot disagree."""
    reasons = ["The taxonomic identity is resolved."]
    if unresolved:
        reasons.append("Reports conflict and nothing retrieved settles the disagreement.")
        level = "low" if len(gaps) >= 4 else "moderate"
    else:
        reasons.append("No retrieved report contradicts another.")
        level = "moderate" if gaps else "high"
    if gaps:
        reasons.append(f"{len(gaps)} gap(s) remain in the retrieved evidence.")
    return {
        "qualitative": level,
        "basis": " ".join(reasons),
        # A number here would be fabricated: nothing retrieved supports one.
        "numeric_precision_claimed": False,
    }


def execute(
    question: str = "What pollinates the bee orchid, and is the answer the same everywhere it grows?",
    *,
    repository: GraphRepository | None = None,
    explanation: str | None = None,
) -> dict[str, Any]:
    """Run the path and return an inspectable reasoning map.

    ``explanation`` is the optional provider-produced prose. Passing ``None``
    is the provider-free path and is fully supported: every field below is
    assembled without it.
    """
    repo = repository or build_pollination_repository()

    identity = _resolve_taxonomy(repo)
    relationships = _relationships(repo, identity["kg_node_id"])
    geography = _geographic_context(relationships, _disjoint_regions(repo))
    mechanisms = _mechanisms(repo, relationships)
    contradictions = _contradictions(relationships, _disjoint_regions(repo))
    gaps = _evidence_gaps(repo, relationships)

    traversal = ReasoningMapEngine(repo).build(
        identity["kg_node_id"],
        direction=ReasoningDirection.BOTH,
        profile=ReasoningProfile.ALL_RELATIONSHIPS,
        max_depth=3,
        limit=100,
    )

    unresolved = [c for c in contradictions if c["resolution"] != "resolved_by_scope"]
    # Internal routing input; never part of the published relationship.
    served_relationships = [
        {k: v for k, v in relationship.items() if k not in ("scope_region", "support_scope")}
        for relationship in relationships
    ]
    result = {
        "schema_version": CONTRACT_VERSION,
        "question": question,
        "intent": {"decomposition": _decompose(question), "deterministic": True},
        "capabilities_selected": list(DETERMINISTIC_CAPABILITIES),
        "taxonomic_identity": {k: v for k, v in identity.items() if k != "kg_node_id"},
        "relationships": served_relationships,
        "geographic_context": geography,
        "mechanisms": mechanisms,
        "contradictions": contradictions,
        "evidence_gaps": gaps,
        "known_unknowns": [
            (
                "Whether the two reproductive strategies co-occur in one population or "
                "partition by geography."
            ),
            "Whether the insect-mediated mechanism is currently active throughout the range.",
            "What conditions, if any, shift a population between strategies.",
        ],
        # Derived together with its reasons, so the two cannot disagree. A fixed
        # basis string contradicted itself the moment the contradiction resolved:
        # it went on saying "held below high because the reports conflict" while
        # reporting high.
        "confidence": _confidence(unresolved, gaps),
        "locality_policy": {
            "protected_taxon_present": True,
            "disclosure": "WITHHELD_PENDING_REVIEW",
            "redaction_applied": True,
        },
        "recommended_next_evidence": [
            "Pollinator observation records with the insect identified to species.",
            "Exclusion experiments separating self-pollinated from insect-mediated seed set.",
            (
                "Any source reporting both strategies in one population, which would resolve "
                "the contradiction by scope rather than leaving it contested."
            ),
        ],
        "handoffs": {
            "research_station": {"available": True, "carries_evidence_states": True},
            "education": {"available": True, "audience_adaptation_may_change_meaning": False},
        },
        "governance": {
            "scientific_review_required": True,
            "automatic_publication": False,
            "automatic_candidate_knowledge": False,
            "automatic_knowledge_promotion": False,
            "production_runtime_enabled": False,
        },
        # How this was executed, kept separate from what was reasoned. The
        # scientific contract is the same object the Brain validates; execution
        # metadata is additive and optional, so the two never drift into
        # disagreeing about the science because one side reports a path count.
        "execution": {
            "traversal": {
                "path_count": len(traversal.get("paths") or []),
                "node_count": len(traversal.get("nodes") or []),
                "edge_count": len(traversal.get("edges") or []),
                "engine": "app.brain.reasoning_map.ReasoningMapEngine",
            },
            "explanation": explanation,
            "explanation_available": explanation is not None,
            "explanation_capability": OPTIONAL_CAPABILITY,
            "provider_calls": 1 if explanation is not None else 0,
        },
    }

    redacted = _redact(result)
    # Fail closed rather than serving a map that leaked. The suspicion pattern is
    # broader than the redactor on purpose.
    leaked = _COORDINATE_SUSPICION.search(str(redacted))
    if leaked:
        raise CognitiveIntegrationError(
            f"coordinate-shaped content survived redaction: {leaked.group(0)!r}"
        )
    return redacted
