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

_COORDINATE = re.compile(
    r"[-+]?\d{1,3}\.\d{3,}\s*[,;]\s*[-+]?\d{1,3}\.\d{3,}"
    r"|\b(?:lat|latitude|lng|lon|longitude)\s*[=:]\s*[-+]?\d+(?:\.\d+)?"
    r"|\d{1,3}\s*°\s*\d{1,2}\s*['′]",
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


def _geographic_context(relationships: list[dict[str, Any]]) -> dict[str, Any]:
    regions = sorted({r["object"] for r in relationships if r["predicate"] == "reported_from"})
    habitats = sorted({r["object"] for r in relationships if r["predicate"] == "co_occurs_with"})
    notes = [f"Most records associate the taxon with {h.lower()}." for h in habitats]
    if len({r.get("geographic_scope") for r in relationships if r.get("geographic_scope")}) > 1:
        notes.append(
            "The reported reproductive strategy differs between parts of the range, "
            "so scope is part of the claim rather than context for it."
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
            out.append(
                {
                    "name": (relationship["object"] or "").lower(),
                    "kind": "competing_mechanism",
                    "statement": (
                        f"In the {relationship.get('geographic_scope') or 'reported'} the subject "
                        "reproduces without any insect, so the pollination relationship is not "
                        "required to explain seed set there."
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
                "An observed insect visit does not establish pollination. Where a "
                "non-insect strategy already accounts for seed set, a visiting insect may "
                "be incidental."
            ),
            "evidence_state": "REPORTED_UNVERIFIED",
        }
    )
    return out


def _contradictions(relationships: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Find claims that disagree, and keep both rather than choosing."""
    reproductive = [r for r in relationships if r["predicate"] in _REPRODUCTIVE_PREDICATES]
    found: list[dict[str, Any]] = []
    for index, first in enumerate(reproductive):
        for second in reproductive[index + 1 :]:
            if first["predicate"] == second["predicate"]:
                continue
            same_scope = first.get("geographic_scope") == second.get("geographic_scope")
            found.append(
                {
                    "between": [
                        f"{first['predicate']} {first['object']}",
                        f"{second['predicate']} {second['object']}",
                    ],
                    "description": (
                        "One report describes an insect-mediated system; the other describes "
                        "reproduction that needs no insect. They are not reconciled by "
                        "preferring the better-supported one."
                    ),
                    "resolution": "resolved_by_scope" if same_scope
                    else "unresolved_presented_as_contested",
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
    return gaps


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _COORDINATE.sub("[locality withheld]", value)
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    return value


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
    geography = _geographic_context(relationships)
    mechanisms = _mechanisms(repo, relationships)
    contradictions = _contradictions(relationships)
    gaps = _evidence_gaps(repo, relationships)

    traversal = ReasoningMapEngine(repo).build(
        identity["kg_node_id"],
        direction=ReasoningDirection.BOTH,
        profile=ReasoningProfile.ALL_RELATIONSHIPS,
        max_depth=3,
        limit=100,
    )

    unresolved = [c for c in contradictions if c["resolution"] != "resolved_by_scope"]
    result = {
        "schema_version": CONTRACT_VERSION,
        "question": question,
        "intent": {"decomposition": _decompose(question), "deterministic": True},
        "capabilities_selected": list(DETERMINISTIC_CAPABILITIES),
        "taxonomic_identity": {k: v for k, v in identity.items() if k != "kg_node_id"},
        "relationships": relationships,
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
        "confidence": {
            # Qualitative, with its basis written out. A number here would be
            # fabricated: nothing retrieved supports one.
            "qualitative": "moderate" if unresolved else "high",
            "basis": (
                "The identity is resolved and both strategies are reported in the primary "
                "literature. Held below high because the reports conflict, no local "
                "observation supports either, and no source quantifies their contribution."
            ),
            "numeric_precision_claimed": False,
        },
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
    # Fail closed rather than serving a map that leaked. Redaction already ran;
    # anything still matching means a shape redaction does not cover.
    if _COORDINATE.search(str(redacted)):
        raise CognitiveIntegrationError("coordinate-shaped content survived redaction")
    return redacted
