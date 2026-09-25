"""Reading trait evidence out of the candidate store the Continuum actually keeps.

WHY THIS EXISTS SEPARATELY FROM THE ADAPTER

`conservatory_requirement_source.collect_trait_candidates` translates candidate
rows into the resolver's shape. It assumes it was handed rows. This module is
the step before that: going to the store, surviving the store being absent, and
saying which of those two happened.

THE DISTINCTION THIS MODULE EXISTS TO PRESERVE

    "nobody has published a minimum temperature for this taxon"
    "we could not reach the store that would know"

Both leave a grower without a bound, and collapsing them would let a routine
outage read as settled scientific silence. The first is a finding about the
literature. The second is a fact about our own plumbing, and a grower deciding
whether to move a plant off a cold bench is entitled to know which one they are
looking at.

So a failure here never returns an empty candidate list on its own. It returns
an empty list *and* a reason, and the resolver refuses to characterise the
literature at all while that reason is set.

WHY A PARTIAL READ IS DISCARDED

If the store errors part-way through, whatever was already read is not a
smaller truth — it is an unknown fraction of one. Passing it forward would let
a plant assess `within` a maximum whose matching minimum simply had not loaded
yet. Fail closed: on any failure the candidates go, and only the reason
remains.

WHAT IT DOES NOT DO

It does not filter by review state, promote anything, or judge quality. The
candidate store holds unreviewed extractions by design, and every row it
returns arrives at the resolver labelled with exactly the strength the store
recorded. Screening here would hide that labelling from the layer built to
carry it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from runtime.conservatory_requirement_source import collect_trait_candidates

__all__ = ["TRAIT_SOURCE_UNAVAILABLE", "TraitSupply", "supply_from_repository"]

#: Reason code for "the store could not be read", as distinct from "the store
#: was read and holds nothing for this taxon".
TRAIT_SOURCE_UNAVAILABLE = "TRAIT_SOURCE_UNAVAILABLE"


@dataclass(frozen=True)
class TraitSupply:
    """Trait candidates for one taxon, plus why there are none if there are none."""

    candidates: list[dict[str, Any]] = field(default_factory=list)
    #: Set only when the store could not be read. `None` means the read
    #: succeeded, and an empty `candidates` then genuinely means the store
    #: holds no usable trait evidence for this taxon.
    unavailable_reason: str | None = None

    @property
    def available(self) -> bool:
        return self.unavailable_reason is None


def supply_from_repository(taxon: str | None, repository: Any) -> TraitSupply:
    """Read trait candidates for `taxon` from a candidate repository.

    The repository is passed in rather than located here so that this stays
    testable against a stub and stays free of any particular deployment's
    wiring. Anything that raises — no repository, a refresh that cannot reach
    the database, a shape that is not what we expect — becomes unavailability
    rather than silence.
    """
    if repository is None:
        return TraitSupply(unavailable_reason=TRAIT_SOURCE_UNAVAILABLE)

    try:
        # Postgres-backed repositories cache state in memory and reload on
        # demand. Skipping the reload would serve whatever this process last
        # saw, which for a long-lived worker can be hours stale.
        refresh = getattr(repository, "refresh", None)
        if callable(refresh):
            refresh()
        candidates = list(repository.candidates)
        evidence_links = list(repository.evidence_links)
    except Exception:  # noqa: BLE001 - any failure is the same failure here
        return TraitSupply(unavailable_reason=TRAIT_SOURCE_UNAVAILABLE)

    try:
        collected = collect_trait_candidates(
            taxon, candidates=candidates, evidence_links=evidence_links
        )
    except Exception:  # noqa: BLE001
        return TraitSupply(unavailable_reason=TRAIT_SOURCE_UNAVAILABLE)

    return TraitSupply(candidates=collected)
