"""Where in a collection a candidate taxon's requirements could be met.

THE QUESTION THIS ANSWERS

A grower is looking at a plant they do not own. The useful question is not
"should I buy it" — nobody here knows their budget, their shelf space or their
patience. It is: given what my benches actually measure, is there anywhere the
published requirements for this taxon are met?

That is the placement comparison already used on a plant's dossier, run against
every location instead of one, with no plant involved.

WHY IT MUST NOT BECOME A RECOMMENDATION

The pull towards "yes, buy it, put it on bench 3" is strong and every part of
it is unsupported. Whether a bench has room, whether its readings are current,
whether the grower can keep them there through a season — none of that is in
this data. So the result is a comparison per location and nothing else: no
ranking, no best match, no verdict about the purchase.

`unassessable` is the common answer and it is the honest one. The Continuum
holds cultivation trait evidence for very few taxa, and a location that cannot
be compared must not read as a location that will do.

WHAT A RETIRED BENCH IS DOING HERE

Nothing: retired locations are excluded. A place the grower has dismantled
cannot house a plant they have not bought yet, and listing it would answer a
question about the past.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from runtime.conservatory_suitability import assess_placement_suitability

__all__ = ["MAX_TAXON_LENGTH", "build_taxon_placement_search"]

#: Bounded because it arrives from a query string. Longer than any accepted
#: name and short enough that nothing downstream is asked to hold a document.
MAX_TAXON_LENGTH = 180


def _conditions_from(environment: dict[str, Any] | None) -> dict[str, Any]:
    """A location's readings in the shape the comparison reads.

    The same shape the cultivation-context envelope produces, built here
    because there is no plant to build an envelope for. Origins travel
    unchanged: a bench whose humidity is somebody's estimate must not compare
    as though it were instrumented.
    """
    conditions: dict[str, Any] = {}
    for variable, reading in ((environment or {}).get("variables") or {}).items():
        if not reading.get("known"):
            conditions[variable] = {
                "value": None,
                "claim_class": "absent",
                "unit": reading.get("unit"),
                "reason": reading.get("reason", "NOT_RECORDED"),
            }
            continue
        origin = reading.get("origin", "unknown")
        conditions[variable] = {
            "value": reading.get("value"),
            "claim_class": (
                "measured_evidence" if origin == "measured" else "manual_observation"
            ),
            "unit": reading.get("unit"),
            "origin": origin,
            "instrument": reading.get("instrument"),
            "observed_at": reading.get("observed_at"),
            "window_end": reading.get("window_end"),
            "is_summary": reading.get("is_summary", False),
            "summary_kind": reading.get("summary_kind"),
        }
    return conditions


def build_taxon_placement_search(
    *,
    taxon: str | None,
    requirements_claim: dict[str, Any],
    locations: list[dict[str, Any]],
    environment_for: Any,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Compare every active location against one taxon's requirements.

    `requirements_claim` is the envelope-shaped claim the resolver produces, so
    an unreadable evidence store stays distinguishable from a taxon nobody has
    published on — all the way into each location's per-variable reason.
    """
    normalised = (taxon or "").strip()
    if not normalised:
        return {
            "taxon": None,
            "locations": [],
            "requirements": requirements_claim,
            "anything_assessed": False,
            "is_recommendation": False,
            "reason": "NO_TAXON_SUPPLIED",
        }

    results = []
    for location in locations:
        # A place the grower has dismantled cannot house a plant they have not
        # bought yet.
        if location.get("retired_at"):
            continue
        assessment = assess_placement_suitability(
            {
                "conditions": _conditions_from(environment_for(location["id"])),
                "taxon_requirements": requirements_claim,
            },
            as_of=as_of,
        )
        results.append(
            {
                "location_id": location["id"],
                "name": location.get("name"),
                "kind": location.get("kind"),
                "assessments": assessment["assessments"],
                "counts": assessment["counts"],
                # Repeated per location rather than only in the summary: a
                # reader scanning one row must not have to trust that a
                # heading somewhere above still applies to it.
                "anything_assessed": assessment["anything_assessed"],
                "oldest_verdict_condition_age_days": assessment.get(
                    "oldest_verdict_condition_age_days"
                ),
            }
        )

    return {
        "taxon": normalised,
        "locations": results,
        # Carried whole so the caller can see the evidence strength behind each
        # bound, and whether the store was consulted at all.
        "requirements": requirements_claim,
        # Stated rather than inferred from an absence of complaints. A search
        # where nothing could be compared anywhere must not read as a search
        # that found no problems.
        "anything_assessed": any(row["anything_assessed"] for row in results),
        # No ranking, no best match, no answer about the purchase. Whether a
        # bench has room, and whether the grower can hold it there through a
        # season, are not in this data.
        "is_recommendation": False,
        "is_scientific_evidence": False,
        "note": (
            "A comparison of each location's recorded conditions against "
            "published requirements for this taxon. It is not advice about "
            "whether to buy the plant, and locations are not ranked."
        ),
    }
