"""Comparing where a plant is against what its taxon is known to need.

WHAT THIS ANSWERS, AND WHAT IT REFUSES TO

It answers: for each variable, does the condition recorded at this plant's
location fall inside a bound the Continuum has evidence for, and how good is
the evidence on both sides.

It refuses to answer "should I move this plant". That question depends on
things absent from every contract here — what else is on the bench, what the
grower can actually do, what time of year it is, and how much they trust their
own thermometer. A verdict of "move it" from this data would be a
recommendation dressed as a deduction.

THE FOUR OUTCOMES, AND WHY THREE OF THEM ARE NOT "FINE"

    within         a value and a bound both exist, and the value is inside it
    outside        both exist, and the value is outside it
    unassessable   one side or the other is missing
    conflicting    the evidence disagrees with itself about the bound

`unassessable` is the common one and the most important. A bench with no
thermometer and a taxon nobody has studied produces no assessment at all, and
saying "within" there — the natural default for a comparison that finds nothing
to complain about — would tell a grower their plant is fine on the strength of
two absences.

`conflicting` exists because the requirement contract preserves disagreement
rather than averaging it. Two sources giving different minima cannot yield one
verdict, and picking the stricter would silently invent a precautionary policy
nobody agreed to.

CONFIDENCE IS NOT COMPUTED

There is no score. Both sides carry their own provenance — how the condition
was obtained, how far the requirement got through review — and those travel
into the result unchanged. Multiplying an instrument reading by an unverified
literature claim produces a number that describes nothing.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ASSESSMENT_OUTCOMES", "assess_placement_suitability"]

ASSESSMENT_OUTCOMES: tuple[str, ...] = (
    "within",
    "outside",
    "unassessable",
    "conflicting",
)


def _bound_values(claims: list[dict[str, Any]] | None) -> list[float]:
    return [
        float(claim["value"])
        for claim in (claims or [])
        if isinstance(claim.get("value"), (int, float))
    ]


def _assess_variable(
    variable: str,
    condition: dict[str, Any] | None,
    requirement: dict[str, Any] | None,
    *,
    requirement_source_consulted: bool = True,
) -> dict[str, Any]:
    """One variable, compared only when both sides genuinely exist."""
    # The envelope wraps every condition as a claim: {value, claim_class, ...}
    # with "absent" standing for "nobody recorded this". There is no `known`
    # flag at this layer — reading one would silently treat every condition as
    # missing, which is how a comparison quietly stops comparing.
    have_condition = bool(
        condition
        and condition.get("claim_class") != "absent"
        and condition.get("value") is not None
    )
    have_requirement = bool(requirement and requirement.get("bounds"))

    if not have_condition and not have_requirement:
        return {
            "variable": variable,
            "outcome": "unassessable",
            "reason": (
                "NO_CONDITION_AND_NO_REQUIREMENT"
                if requirement_source_consulted
                else "NO_CONDITION_AND_REQUIREMENT_SOURCE_UNAVAILABLE"
            ),
        }
    if not have_condition:
        return {
            "variable": variable,
            "outcome": "unassessable",
            "reason": "NO_CONDITION_RECORDED",
        }
    if not have_requirement:
        return {
            "variable": variable,
            "outcome": "unassessable",
            # "No evidence exists" and "we could not read the store that holds
            # it" are different answers. Reporting the first for the second
            # would turn an outage into a statement about the literature.
            "reason": (
                "NO_REQUIREMENT_EVIDENCE"
                if requirement_source_consulted
                else "REQUIREMENT_SOURCE_UNAVAILABLE"
            ),
        }

    value = condition.get("value")
    if not isinstance(value, (int, float)):
        return {
            "variable": variable,
            "outcome": "unassessable",
            "reason": "CONDITION_NOT_NUMERIC",
        }

    bounds = requirement["bounds"]
    minima = _bound_values(bounds.get("minimum"))
    maxima = _bound_values(bounds.get("maximum"))

    # Disagreement is not resolved here. Picking the stricter bound would
    # invent a precautionary policy nobody agreed to; picking the mean would
    # state a number no source gave.
    if len({round(m, 6) for m in minima}) > 1 or len({round(m, 6) for m in maxima}) > 1:
        return {
            "variable": variable,
            "outcome": "conflicting",
            "reason": "SOURCES_DISAGREE_ABOUT_THE_BOUND",
            "condition": condition,
            "bounds": bounds,
        }

    breached = []
    if minima and value < minima[0]:
        breached.append({"bound": "minimum", "limit": minima[0]})
    if maxima and value > maxima[0]:
        breached.append({"bound": "maximum", "limit": maxima[0]})

    return {
        "variable": variable,
        "outcome": "outside" if breached else "within",
        "breached": breached,
        # Both provenances travel unchanged. A reader weighing this needs to
        # know it compared a hand-entered number against an unverified claim,
        # if that is what happened.
        "condition": condition,
        "bounds": bounds,
    }


def assess_placement_suitability(context: dict[str, Any]) -> dict[str, Any]:
    """Compare a cultivation-context envelope against its taxon requirements.

    Takes the envelope built by `conservatory_calyx_context` so that both sides
    arrive already carrying their claim classes, and nothing has to be fetched
    or trusted twice.
    """
    conditions = context.get("conditions") or {}
    requirements_claim = context.get("taxon_requirements") or {}
    requirements = requirements_claim.get("value") or {}
    # Absent means the envelope carried no flag, which is the pre-existing
    # shape and means the store was read. Only an explicit False says we never
    # got to look.
    source_consulted = requirements_claim.get("source_consulted", True) is not False

    variables = sorted(set(conditions) | set(requirements))
    assessments = [
        _assess_variable(
            variable,
            conditions.get(variable),
            requirements.get(variable),
            requirement_source_consulted=source_consulted,
        )
        for variable in variables
    ]

    counts = {outcome: 0 for outcome in ASSESSMENT_OUTCOMES}
    for assessment in assessments:
        counts[assessment["outcome"]] += 1

    return {
        "plant": context.get("plant", {}).get("plant_id", {}).get("value"),
        "assessments": assessments,
        "counts": counts,
        # Stated rather than left to be inferred from counts: a reader who sees
        # zero "outside" must not conclude the plant is well placed when
        # nothing could be assessed at all.
        "anything_assessed": counts["within"] + counts["outside"] > 0,
        # A run where nothing could be assessed reads identically whether the
        # literature is silent or the store was unreachable. This is how a
        # caller tells them apart without reading per-variable reasons.
        "requirement_source_consulted": source_consulted,
        "is_scientific_evidence": False,
        "is_recommendation": False,
        "note": (
            "A comparison of recorded conditions against evidence-backed "
            "bounds. It is not advice about whether to move the plant: that "
            "depends on what else is on the bench, what the grower can do, and "
            "the season, none of which are in this data."
        ),
    }
