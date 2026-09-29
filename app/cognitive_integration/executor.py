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
import unicodedata
from dataclasses import dataclass
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
    # The digit run is a pair: an easting and a northing of equal length. A
    # single run leaves the second number sitting in the output next to the
    # marker, which is most of a position and reads as though it were redacted.
    r"|\b\d{1,2}\s*[C-HJ-NP-X]\s*[A-Z]{2}\s*\d{4,10}(?:\s+\d{4,10})?\b"
    r"|\bUTM\b[^\n]{0,24}?\d{5,7}\s+\d{5,8}"
    r"|\b\d{1,2}[C-HJ-NP-X]\s+\d{5,7}\s+\d{5,8}\b"
    # Open Location Code (plus code): eight of the code alphabet, then "+".
    r"|\b[23456789CFGHJMPQRVWX]{4,8}\+[23456789CFGHJMPQRVWX]{2,7}\b"
    # Ordnance Survey national grid, spaced or not. This is the grid a British
    # recorder actually writes, and it was missing while UTM and MGRS — the
    # international and military grids — were covered. The worked example
    # throughout this module is Oxford.
    r"|\b[HNOST][A-Z]\s?\d{2,5}\s?\d{2,5}\b"
    # Geohash: base-32 without a, i, l or o, carrying at least one digit. The
    # excluded letters are what keep this off ordinary words. The word
    # "geohash" was already in the suspicion vocabulary while the code itself
    # was not.
    r"|\b(?=[0-9bcdefghjkmnpqrstuvwxyz]*\d)[0-9bcdefghjkmnpqrstuvwxyz]{7,12}\b"
    # A pair in scientific notation.
    r"|[-+]?\d(?:\.\d+)?[eE][-+]?\d+\s*[,;]\s*[-+]?\d(?:\.\d+)?[eE][-+]?\d+"
    # Degrees, minutes and seconds with no unit words at all.
    r"|\b\d{1,3}\s+\d{1,2}\s+\d{1,2}\s*[NSEW]\b"
    # A bare what3words address. Bounded so it cannot take a bite out of a
    # longer dotted chain: `app.brain.reasoning_map` is a module path, not a
    # position, and it escaped only because an underscore happened to follow.
    r"|(?<![\w.])[a-z]{3,12}\.[a-z]{3,12}\.[a-z]{3,12}(?!\w|\.\w)"
    # Digits spaced out to defeat a pattern that assumes they are adjacent.
    r"|\d(?:\s+\d)+\s*\.\s*\d(?:\s+\d)+",
    re.IGNORECASE,
)

def _fold_digits(text: str) -> str:
    r"""Fold every Unicode decimal digit to ASCII before matching.

    Full-width, Arabic-Indic and Devanagari digits are digits to a reader and
    invisible to ``\d``. ``51.7520`` written in any of them is the same
    position.
    """
    # NFKC first, which folds full-width digits *and* the full-width period and
    # minus that go with them: "５１．７５２０" is not a number until its
    # decimal point is one too.
    folded = unicodedata.normalize("NFKC", text)
    return "".join(
        "."
        if ch == "\u066b"  # Arabic decimal separator
        else ","
        if ch == "\u066c"  # Arabic thousands separator
        else str(unicodedata.digit(ch))
        if ch.isdigit() and not ch.isascii()
        else ch
        for ch in folded
    )


#: A bare number that is a position. Two decimal places is ~1 km, which still
#: locates a population; one is ~11 km and is indistinguishable from an ordinary
#: measurement, so it is left alone rather than making every quantity a leak.
_NUMERIC_COORDINATE = re.compile(r"^-?(?:1[0-7]\d|\d{1,2})\.\d{2,}$")

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
    # Two decimal places, not one. "Seed set fell by 12.5 percent over 3.5
    # seasons" raised and took the whole map down — and `quantified_seed_set`
    # is one of this module's own EXPECTED_BUT_ABSENT predicates, so the
    # evidence it most wants was the shape that broke it. Every real coordinate
    # form carries two or more.
    + r"|[-+]?(?:1[0-7]\d|\d{1,2})\.\d{2,}\D{0,24}[-+]?(?:1[0-7]\d|\d{1,2})\.\d{2,}"
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
        # Filled in by execute() from what redaction actually did. A literal
        # here certified every shape the pattern missed as safe, which is worse
        # than missing it: a consumer has been told the field is clean.
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


def _disjointness_provenance(repository: GraphRepository) -> dict[frozenset[str], str]:
    """What cited each declared disjointness, so a reader can check it.

    ``resolved_by_scope`` is the only inference in this module that removes a
    disagreement, and it was the only one a reader could not audit: the served
    contradiction reported the resolution with no indication that a
    ``disjoint_from`` edge existed or what stood behind it.
    """
    keys = {node.kg_node_id: node.canonical_key for node in repository.all_nodes()}
    out: dict[frozenset[str], str] = {}
    for edge in repository.all_edges():
        if edge.edge_type != "disjoint_from":
            continue
        first, second = keys.get(edge.from_node_id), keys.get(edge.to_node_id)
        if not first or not second or first == second:
            continue
        payload = edge.payload or {}
        out[frozenset({first, second})] = str(payload.get("citation") or "no citation recorded")
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
    relationships: list[dict[str, Any]],
    disjoint: set[frozenset[str]],
    provenance: dict[frozenset[str], str] | None = None,
) -> list[dict[str, Any]]:
    """Find claims that disagree, and keep both rather than choosing."""
    reproductive = [r for r in relationships if r["predicate"] in _REPRODUCTIVE_PREDICATES]
    found: list[dict[str, Any]] = []
    for index, first in enumerate(reproductive):
        for second in reproductive[index + 1 :]:
            if first["predicate"] == second["predicate"]:
                continue
            resolution = _scope_resolution(first, second, disjoint)
            found.append(
                {
                    "between": [
                        f"{first['predicate']} {first['object']}",
                        f"{second['predicate']} {second['object']}",
                    ],
                    "description": _describe_conflict(first, second),
                    "resolution": resolution,
                    "scopes": [first.get("geographic_scope"), second.get("geographic_scope")],
                    # When scope removes a disagreement, say what declared the
                    # two places separate. Without it the reader is asked to
                    # accept the one inference here that deletes a conflict.
                    "resolved_by": (
                        (provenance or {}).get(
                            frozenset(
                                {first.get("scope_region") or "", second.get("scope_region") or ""}
                            ),
                            "no citation recorded",
                        )
                        if resolution == "resolved_by_scope"
                        else None
                    ),
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


@dataclass
class RedactionOutcome:
    """What redaction actually did, so the map can report it instead of asserting it."""

    fields_redacted: int = 0

    @property
    def applied(self) -> bool:
        return self.fields_redacted > 0


def _redact(value: Any, outcome: RedactionOutcome | None = None) -> Any:
    """Withhold coordinate-shaped content, whatever type it arrives as.

    The earlier version returned every non-string unexamined, so a position
    carried as JSON numbers went straight to the client: two edges with
    ``identifier`` set to ``51.7520`` and ``-1.2577`` were served intact under
    ``redaction_applied: True``. That is the shape a real occurrence record is
    most likely to arrive in, and checking only strings is a bug class rather
    than a missing pattern.
    """
    record = outcome if outcome is not None else RedactionOutcome()
    if isinstance(value, str):
        # Folded first, so a position written in non-ASCII digits is seen. The
        # folded text is what gets served when it matches, which is the safe
        # direction: the alternative is serving the original because the
        # pattern could not read it.
        folded = _fold_digits(value)
        cleaned = _COORDINATE.sub("[locality withheld]", folded)
        if cleaned != folded:
            record.fields_redacted += 1
            return cleaned
        return value
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        # A bare number is only a position in company, so it is judged against
        # the fail-closed net rather than the redactor: a plausible degree value
        # carried to locating precision.
        if _NUMERIC_COORDINATE.match(f"{value}"):
            record.fields_redacted += 1
            return "[locality withheld]"
        return value
    if isinstance(value, list):
        return [_redact(item, record) for item in value]
    if isinstance(value, dict):
        # Keys are checked too. A key is rendered wherever the payload is.
        return {
            _redact(key, record) if isinstance(key, str) else key: _redact(item, record)
            for key, item in value.items()
        }
    return value


def _strategy_objects(relationships: list[dict[str, Any]]) -> list[str]:
    """The reproductive accounts actually retrieved, in the graph's own words."""
    return sorted(
        {r["object"] for r in relationships if r["predicate"] in _REPRODUCTIVE_PREDICATES}
    )


def _known_unknowns(
    relationships: list[dict[str, Any]], mechanisms: list[dict[str, Any]]
) -> list[str]:
    """Open questions, counted and named from the graph.

    These were fixed sentences asserting "the two reproductive strategies" and
    "the insect-mediated mechanism". With four reports in the graph the first
    still said two, and the second survived unchanged when every ``mechanism_of``
    edge was deleted. Same defect as the recited mechanism prose, in the region
    that fix did not reach.
    """
    strategies = _strategy_objects(relationships)
    out: list[str] = []
    if len(strategies) > 1:
        out.append(
            f"Whether the {len(strategies)} retrieved accounts "
            f"({', '.join(strategies)}) co-occur in one population or partition "
            "by geography."
        )
    proposed = [m["name"] for m in mechanisms if m["kind"] != "null_explanation"]
    for name in proposed:
        out.append(f"Whether {name} is currently active throughout the range.")
    if strategies:
        out.append("What conditions, if any, shift a population between the retrieved accounts.")
    return out


def _next_evidence(
    relationships: list[dict[str, Any]],
    mechanisms: list[dict[str, Any]],
    unresolved: list[dict[str, Any]],
) -> list[str]:
    """What would move this forward, derived rather than promised.

    The third entry used to say that a source reporting both strategies in one
    population "would resolve the contradiction by scope rather than leaving it
    contested". Under the rule this module now implements, two incompatible
    claims about one population is the *definition* of a live conflict — the
    sentence was the inverted rule written in prose, recommending evidence and
    stating the opposite of what the code does with it.
    """
    out: list[str] = []
    genus_level = [
        r for r in relationships if r.get("support_scope") == "genus"
    ]
    if genus_level or any(m["kind"] == "proposed_mechanism" for m in mechanisms):
        out.append("Pollinator observation records with the insect identified to species.")
    strategies = _strategy_objects(relationships)
    if len(strategies) > 1:
        out.append(
            "Exclusion experiments separating the contribution of "
            f"{' and '.join(strategies)} to seed set."
        )
    if unresolved:
        out.append(
            "A source reporting the competing accounts in one population, which would let "
            "the disagreement be assessed within a single place rather than across "
            "reports that may not describe the same ground."
        )
        out.append(
            "Evidence that the scopes of the competing reports are separate places, which "
            "is what it would take to resolve this by scope."
        )
    return out


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
    contradictions = _contradictions(
        relationships, _disjoint_regions(repo), _disjointness_provenance(repo)
    )
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
        "known_unknowns": _known_unknowns(relationships, mechanisms),
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
        "recommended_next_evidence": _next_evidence(relationships, mechanisms, unresolved),
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

    outcome = RedactionOutcome()
    redacted = _redact(result, outcome)

    # The safety fields say what redaction did, not what it hoped. They were
    # literals — `coordinates_present: False` and `redaction_applied: True`
    # regardless — so every shape the pattern missed was served with a positive
    # assertion that the map was clean. That is worse than the miss: a consumer
    # cannot defend itself against a field that lies, and the module's own
    # docstring is candid that the pattern "is a list of shapes someone thought
    # of, not a proof". The served map now carries that candour.
    # `coordinates_present` now means what its name says: coordinate-shaped
    # content was found in this reasoning. It was a literal `False`, so every
    # shape the pattern missed was served with a positive assertion that the
    # map was clean — worse than the miss, because a consumer cannot defend
    # itself against a field that lies.
    #
    # Deriving it also makes the two layers compose. A rendering surface that
    # finds a position in a map declaring `False` has caught a real upstream
    # miss, rather than contradicting a constant that was never a claim.
    redacted["geographic_context"]["coordinates_present"] = outcome.applied

    # `redaction_applied` stays true, and that is not an oversight. The Brain's
    # scientific contract reads it as "the redaction policy is in force for a
    # protected taxon" (validator line 203), not "a substitution occurred" —
    # and for a protected taxon whose sources happen to carry no coordinates,
    # the policy did run and found nothing. Deriving it from the substitution
    # count would break that contract and would say something false.
    #
    # What neither field can express is the thing most worth saying: absence
    # was never *verified*, only unmatched. `locality_policy` is
    # `additionalProperties: false` in the Brain schema, so carrying that
    # honesty to a client needs a field there rather than an extra key here.

    # Fail closed rather than serving a map that leaked. The suspicion pattern is
    # broader than the redactor on purpose.
    leaked = _COORDINATE_SUSPICION.search(_fold_digits(str(redacted)))
    if leaked:
        raise CognitiveIntegrationError(
            f"coordinate-shaped content survived redaction: {leaked.group(0)!r}"
        )
    return redacted
