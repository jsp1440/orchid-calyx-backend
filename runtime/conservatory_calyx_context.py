"""The envelope Calyx receives about one plant, with every claim kept apart.

WHAT THIS IS FOR

Before Calyx can usefully answer "is this plant in the right place?", it has to
be handed what is known about the plant without being handed a false
impression of how well any of it is known. This module builds that envelope. It
answers nothing. It deliberately contains no reasoning, no recommendation and
no scoring, because the trust boundary has to exist before anything crosses it.

THE CLASSES OF CLAIM, AND WHY THEY MAY NEVER MERGE

    identity            which plant this is, in this collection
    collection_fact     what the grower recorded about their own plant
    measured_evidence   what an instrument reported
    manual_observation  what a person entered or judged
    inferred_context    what this system derived from something else
    absent              what nobody has recorded

A location reading is not literature. A grower's note is not a measurement. An
inference is not an observation. Each of those collapses is a way of turning
something weak into something authoritative, and once merged there is no way
back — the envelope is the last place the distinction still exists.

WHAT IS DELIBERATELY NOT HERE

Scientific literature evidence and taxon requirements. Those live behind the
knowledge graph's own provenance process, and pulling them in here would let
collection data sit beside published findings in one undifferentiated list.
The envelope names them as absent so a consumer can see the gap rather than
mistake this for the whole picture.

Nothing here may be promoted into scientific evidence. The envelope says so
about itself, in a field, so a downstream consumer cannot claim it did not
know.
"""

from __future__ import annotations

from typing import Any

from runtime.conservatory_taxon_requirements import resolve_taxon_requirements

__all__ = [
    "CLAIM_CLASSES",
    "build_cultivation_context",
]

CLAIM_CLASSES: tuple[str, ...] = (
    "identity",
    "collection_fact",
    "measured_evidence",
    # A published or extracted claim about the taxon, not about this plant.
    "literature_derived",
    "manual_observation",
    "inferred_context",
    "absent",
)

#: Origins recorded against an environmental reading, mapped to the claim class
#: they belong to. The mapping is explicit rather than computed so that adding
#: an origin cannot silently inherit a stronger class than it deserves.
_ORIGIN_TO_CLASS = {
    "measured": "measured_evidence",
    "manual": "manual_observation",
    "inferred": "inferred_context",
    "unknown": "absent",
}


def _requirements_claim(resolved: dict[str, Any]) -> dict[str, Any]:
    """Wrap resolved requirements in the envelope's claim shape.

    Requirements are literature-derived, which is a stronger class than
    anything the grower recorded and still not a verified finding. Collapsing
    them into `measured_evidence` would let a published range sit beside a
    thermometer reading as the same kind of thing.
    """
    if not resolved.get("known"):
        return _claim(
            None,
            "absent",
            reason=resolved.get("reason", "NOT_RESOLVED"),
            # Carried, not inferred from the reason string: a consumer must be
            # able to tell "the literature is silent" from "we never asked"
            # without pattern-matching on prose.
            source_consulted=bool(resolved.get("source_consulted", True)),
        )
    return _claim(
        resolved["requirements"],
        "literature_derived",
        taxon=resolved.get("taxon"),
        note=resolved.get("note"),
    )


def _claim(value: Any, claim_class: str, **extra: Any) -> dict[str, Any]:
    if claim_class not in CLAIM_CLASSES:
        raise ValueError("UNRECOGNISED_CLAIM_CLASS")
    return {"value": value, "claim_class": claim_class, **extra}


def build_cultivation_context(
    *,
    plant: dict[str, Any],
    placement_current: dict[str, Any] | None,
    placement_history: list[dict[str, Any]],
    location: dict[str, Any] | None,
    environment: dict[str, Any] | None,
    events: dict[str, Any] | None,
    trait_candidates: list[dict[str, Any]] | None = None,
    trait_source_unavailable: str | None = None,
) -> dict[str, Any]:
    """Assemble what is known about one plant, each claim labelled by class.

    Every argument may be absent, and absence is represented rather than
    dropped. A consumer that cannot see the difference between "no humidity
    sensor" and "humidity not included in this envelope" will reason as though
    the gap were not there.
    """
    identity = {
        "plant_id": _claim(plant.get("id"), "identity"),
        "accession_number": _claim(plant.get("accession_number"), "identity"),
        "display_name": _claim(plant.get("display_name"), "identity"),
        # The grower typed this. It is what they believe the plant is, which is
        # not the same as a determination anybody has verified, so it is a
        # collection fact and never an identity claim.
        "grower_stated_name": _claim(
            plant.get("accepted_scientific_name"),
            "collection_fact" if plant.get("accepted_scientific_name") else "absent",
            note="Entered by the grower. Not a verified taxonomic determination.",
        ),
    }

    if placement_current and location:
        where = _claim(
            {
                "location_id": location.get("id"),
                "name": location.get("name"),
                "kind": location.get("kind"),
                "described_conditions": location.get("described_conditions"),
            },
            "collection_fact",
            # The grower's description of the place is their assessment of it,
            # and must not be read alongside instrument data as an equal.
            described_conditions_class="manual_observation"
            if location.get("described_conditions")
            else "absent",
        )
    else:
        where = _claim(None, "absent", reason="NO_CURRENT_PLACEMENT")

    moves = _claim(
        [
            {
                "location_id": event.get("location_id"),
                "reason": event.get("reason"),
                "recorded_at": event.get("recorded_at"),
            }
            for event in placement_history
        ],
        "collection_fact" if placement_history else "absent",
        note="A correction means the record was wrong, not that the plant moved.",
    )

    conditions: dict[str, Any] = {}
    for variable, reading in ((environment or {}).get("variables") or {}).items():
        if not reading.get("known"):
            conditions[variable] = _claim(
                None,
                "absent",
                unit=reading.get("unit"),
                reason=reading.get("reason", "NOT_RECORDED"),
            )
            continue
        origin = reading.get("origin", "unknown")
        conditions[variable] = _claim(
            reading.get("value"),
            # An unmapped origin is not assumed to be trustworthy.
            _ORIGIN_TO_CLASS.get(origin, "inferred_context"),
            unit=reading.get("unit"),
            origin=origin,
            instrument=reading.get("instrument"),
            observed_at=reading.get("observed_at"),
            # A summary's currency is when its window ended, not when it began.
            # A weekly mean ending yesterday describes this week; read from
            # observed_at alone it would look a week stale.
            window_end=reading.get("window_end"),
            is_summary=reading.get("is_summary", False),
            summary_kind=reading.get("summary_kind"),
        )

    timeline = events or {}
    observations = _claim(
        [
            {
                "kind": event.get("kind"),
                "occurred_at": event.get("occurred_at"),
                "recorded_at": event.get("recorded_at"),
                "recorder_kind": event.get("recorder_kind"),
                "note": event.get("note"),
            }
            for event in timeline.get("standing", [])
        ],
        "manual_observation" if timeline.get("standing") else "absent",
        note="What the grower reported about their own plant.",
    )

    return {
        "plant": identity,
        "current_location": where,
        "placement_history": moves,
        "conditions": conditions,
        "observations": observations,
        # Named as absent rather than omitted: a consumer must be able to see
        # that no published evidence and no taxon requirement is present, or it
        # will reason as though the collection data were the whole picture.
        "literature_evidence": _claim(
            None, "absent", reason="NOT_INCLUDED_IN_COLLECTION_CONTEXT"
        ),
        # Derived from trait evidence the Continuum holds, and absent when it
        # holds none — which is the normal case. A default range here would be
        # acted on by a grower, and acting on a fabricated minimum is worse
        # than being told nothing.
        "taxon_requirements": _requirements_claim(
            resolve_taxon_requirements(
                plant.get("accepted_scientific_name"),
                trait_candidates,
                source_unavailable=trait_source_unavailable,
            )
        ),
        "claim_classes": list(CLAIM_CLASSES),
        # Stated about itself so no consumer can claim it did not know.
        "is_scientific_evidence": False,
        "may_be_promoted_to_evidence": False,
        "envelope_note": (
            "Collection context only. Nothing here is a verified scientific "
            "finding, and no value may be promoted into evidence without the "
            "knowledge graph's own provenance process."
        ),
    }
