"""What is known about a taxon's cultivation requirements, and how well.

WHY THIS IS NOT A LOOKUP TABLE

It would be easy, and wrong, to ship a dictionary saying Cattleya wants 18-28C.
Numbers like that are real claims about the world, and a claim with no source
is indistinguishable from an invention once it is in the record. A grower
deciding whether to move a plant deserves to know whether the range they are
acting on came from a reviewed study, one unverified extraction, or nobody.

So a requirement here is always derived from evidence the Continuum already
holds — trait candidates with exact source anchors — and it always arrives
carrying the provenance of that evidence.

WHY IT FAILS CLOSED

Most taxa in most collections have no cultivation evidence at all. That is the
normal case, not an error, and it must surface as "nobody has recorded this"
rather than as a default range. A default would be acted on: a grower moving a
plant because of a fabricated minimum has been actively misled, which is worse
than being told nothing.

WHAT IT DELIBERATELY DOES NOT DO

It does not decide whether a plant is in the right place. That comparison needs
this contract and the Conservatory's environmental context together, and
belongs beyond this boundary. This module answers only "what does the Continuum
know about this taxon, and how well does it know it".
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "REQUIREMENT_PREDICATES",
    "EvidenceStrength",
    "resolve_taxon_requirements",
]

#: Trait predicates that describe a cultivation requirement, mapped to the
#: environmental variable the Conservatory records against a location. Only
#: pairs that measure the same thing in the same unit appear here: comparing a
#: humidity claim against a temperature reading is not a weaker comparison, it
#: is a meaningless one.
REQUIREMENT_PREDICATES: dict[str, dict[str, str]] = {
    "minimum_temperature": {
        "variable": "temperature_c",
        "unit": "degrees Celsius",
        "bound": "minimum",
    },
    "maximum_temperature": {
        "variable": "temperature_c",
        "unit": "degrees Celsius",
        "bound": "maximum",
    },
    "night_minimum_temperature": {
        "variable": "temperature_c",
        "unit": "degrees Celsius",
        "bound": "minimum",
    },
    "minimum_relative_humidity": {
        "variable": "relative_humidity_pct",
        "unit": "percent",
        "bound": "minimum",
    },
    "maximum_relative_humidity": {
        "variable": "relative_humidity_pct",
        "unit": "percent",
        "bound": "maximum",
    },
    "minimum_light_ppfd": {
        "variable": "light_ppfd_umol_m2_s",
        "unit": "micromole per square metre per second",
        "bound": "minimum",
    },
    "maximum_light_ppfd": {
        "variable": "light_ppfd_umol_m2_s",
        "unit": "micromole per square metre per second",
        "bound": "maximum",
    },
}


class EvidenceStrength:
    """How far a claim has got through the Continuum's own review process.

    Deliberately ordinal and deliberately coarse. A finer scale would invite
    arithmetic on it, and averaging "reviewed" with "unverified" produces a
    number that describes no actual state of knowledge.
    """

    VERIFIED = "verified"
    REVIEWED = "reviewed"
    UNVERIFIED = "unverified"
    #: Present in the store but withdrawn, superseded or rejected. Never used.
    NOT_USABLE = "not_usable"


def _strength(candidate: dict[str, Any]) -> str:
    status = str(candidate.get("status", "")).upper()
    if status in {"WITHDRAWN", "SUPERSEDED", "REJECTED"}:
        return EvidenceStrength.NOT_USABLE
    if str(candidate.get("verification_state", "")).upper() == "VERIFIED":
        return EvidenceStrength.VERIFIED
    if str(candidate.get("review_state", "")).upper() in {
        "CLEAR",
        "ACCEPTED",
        "COMPLETE",
    }:
        return EvidenceStrength.REVIEWED
    return EvidenceStrength.UNVERIFIED


def _usable(candidate: dict[str, Any]) -> bool:
    """Whether a candidate may contribute a requirement at all."""
    if _strength(candidate) == EvidenceStrength.NOT_USABLE:
        return False
    if candidate.get("predicate") not in REQUIREMENT_PREDICATES:
        return False
    # A requirement needs a number. A trait recorded only as free text says
    # something real but cannot be compared against a thermometer, and
    # coercing it would invent precision the source never had.
    if candidate.get("numeric_value") is None:
        return False
    # Exact source anchors are what makes a claim checkable. Without them the
    # number cannot be traced back to anything, which is the same position as
    # having invented it.
    return bool(candidate.get("source_anchor_ids"))


def resolve_taxon_requirements(
    taxon: str | None,
    candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """Assemble what the Continuum knows about a taxon's requirements.

    `candidates` are trait candidates already held by the evidence system. This
    function reads them; it never fetches, and it never writes.
    """
    if not taxon or not str(taxon).strip():
        return {
            "taxon": None,
            "known": False,
            "reason": "NO_TAXON_SUPPLIED",
            "requirements": {},
            "claim_class": "absent",
            "is_scientific_evidence": False,
        }

    usable = [row for row in (candidates or []) if _usable(row)]
    requirements: dict[str, dict[str, Any]] = {}

    for candidate in usable:
        predicate = str(candidate["predicate"])
        mapping = REQUIREMENT_PREDICATES[predicate]
        # A unit mismatch is not a weaker claim, it is a different measurement.
        # Silently accepting one would compare Fahrenheit against Celsius.
        stated_unit = candidate.get("unit")
        if stated_unit is not None and str(stated_unit) != mapping["unit"]:
            continue
        entry = requirements.setdefault(
            mapping["variable"],
            {"unit": mapping["unit"], "bounds": {}},
        )
        bound = mapping["bound"]
        claim = {
            "value": candidate["numeric_value"],
            "predicate": predicate,
            # Carried, never collapsed: a grower acting on a range is entitled
            # to know whether anybody checked it.
            "evidence_strength": _strength(candidate),
            "source_anchor_ids": list(candidate.get("source_anchor_ids") or []),
            "source_revision_id": candidate.get("source_revision_id"),
            "directness": candidate.get("directness", "INDIRECT"),
            "confidence": candidate.get("confidence"),
        }
        existing = entry["bounds"].get(bound)
        if existing is None:
            entry["bounds"][bound] = [claim]
        else:
            # Competing claims are kept side by side rather than averaged. Two
            # sources disagreeing about a minimum is information; their mean is
            # a number no source stated.
            existing.append(claim)

    if not requirements:
        return {
            "taxon": taxon,
            "known": False,
            "reason": "NO_CULTIVATION_EVIDENCE_FOR_THIS_TAXON",
            "requirements": {},
            "claim_class": "absent",
            "is_scientific_evidence": False,
        }

    return {
        "taxon": taxon,
        "known": True,
        "requirements": requirements,
        # These derive from evidence the Continuum holds, but the derivation
        # itself is not a published finding, and nothing downstream may treat
        # the assembled shape as one.
        "claim_class": "literature_derived_claim",
        "is_scientific_evidence": False,
        "note": (
            "Assembled from trait evidence the Continuum holds. Each bound "
            "carries the strength of the evidence behind it; competing claims "
            "are listed rather than averaged."
        ),
    }
