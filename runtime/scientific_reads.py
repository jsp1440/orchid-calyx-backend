"""Canonical scientific read-through for the recovery vertical slice.

Gate 4 of CALYX-RECOVERY-001. Calyx must be able to answer from the best
source the Continuum actually has, and every datum it returns must say where
it came from.

Two failures this exists to prevent, which are opposite and equally wrong:

* treating "not in the Knowledge Graph" as "not in the Continuum" — the
  canonical tables hold data the graph has not materialised, and reporting it
  as absent understates what is known;
* treating "in the Knowledge Graph" as "complete" — a materialised edge is not
  a survey, and reporting it as coverage overstates what is known.

So a reading is never a bare value. It carries its origin, and a domain that
was not consulted reports ``UNAVAILABLE`` rather than an empty list, because
"nobody looked" and "we looked and found nothing" are different scientific
statements and only one of them is about the orchid.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------- provenance

CANONICAL_DATABASE = "CANONICAL_DATABASE"
PERSISTED_KNOWLEDGE_GRAPH = "PERSISTED_KNOWLEDGE_GRAPH"
REVIEWED_EXTERNAL_DISCOVERY = "REVIEWED_EXTERNAL_DISCOVERY"
CANDIDATE_KNOWLEDGE = "CANDIDATE_KNOWLEDGE"
DERIVED_INFERENCE = "DERIVED_INFERENCE"

ORIGINS = frozenset(
    {
        CANONICAL_DATABASE,
        PERSISTED_KNOWLEDGE_GRAPH,
        REVIEWED_EXTERNAL_DISCOVERY,
        CANDIDATE_KNOWLEDGE,
        DERIVED_INFERENCE,
    }
)

#: Origins that may be presented as established. CANDIDATE_KNOWLEDGE has not
#: been reviewed and DERIVED_INFERENCE was computed rather than observed;
#: presenting either as evidence is how a hypothesis becomes a finding.
EVIDENTIARY_ORIGINS = frozenset(
    {CANONICAL_DATABASE, PERSISTED_KNOWLEDGE_GRAPH, REVIEWED_EXTERNAL_DISCOVERY}
)

# -------------------------------------------------------------------- states

AVAILABLE = "AVAILABLE"
EMPTY = "EMPTY"
UNAVAILABLE = "UNAVAILABLE"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

#: The domains the recovery slice reads.
DOMAINS = (
    "taxonomy",
    "occurrences",
    "geography",
    "elevation",
    "traits",
    "literature",
    "pollinators",
    "mycorrhiza",
    "habitat",
    "climate",
    "media",
)


@dataclass(frozen=True)
class ScientificReading:
    """One domain's answer for one taxon, with where it came from."""

    domain: str
    state: str
    origin: str | None = None
    records: tuple[Mapping[str, Any], ...] = ()
    provenance: Mapping[str, Any] = field(default_factory=dict)
    detail: str | None = None

    def __post_init__(self) -> None:
        if self.state == AVAILABLE:
            if self.origin not in ORIGINS:
                raise ValueError(f"a reading with data must name a known origin: {self.origin}")
            if not self.records:
                # Otherwise AVAILABLE-with-nothing is indistinguishable from
                # EMPTY, and the difference is the whole point of the states.
                raise ValueError("an AVAILABLE reading must carry at least one record")

    @property
    def is_evidentiary(self) -> bool:
        return self.state == AVAILABLE and self.origin in EVIDENTIARY_ORIGINS

    def as_record(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "state": self.state,
            "origin": self.origin,
            "record_count": len(self.records),
            "records": [dict(item) for item in self.records],
            "provenance": dict(self.provenance),
            "detail": self.detail,
        }


def unavailable(domain: str, detail: str) -> ScientificReading:
    """No source was consulted, or the source could not answer.

    Never an empty result. A reader must be able to tell a silent source from
    a source that answered "none".
    """
    return ScientificReading(domain=domain, state=UNAVAILABLE, detail=detail)


def empty(domain: str, origin: str, detail: str | None = None) -> ScientificReading:
    """A source was consulted and holds nothing for this taxon."""
    return ScientificReading(domain=domain, state=EMPTY, origin=origin, detail=detail)


def available(
    domain: str,
    origin: str,
    records: Sequence[Mapping[str, Any]],
    provenance: Mapping[str, Any] | None = None,
) -> ScientificReading:
    return ScientificReading(
        domain=domain,
        state=AVAILABLE,
        origin=origin,
        records=tuple(dict(item) for item in records),
        provenance=dict(provenance or {}),
    )


DomainReader = Callable[[str], ScientificReading]


class ScientificReadThrough:
    """Reads a taxon across every recovery-slice domain.

    Readers are injected. A domain with no reader registered reports
    ``UNAVAILABLE`` with the reason, which is the honest state for this
    container: no database is reachable from it, so most domains genuinely
    cannot be consulted and must not be reported as empty.
    """

    def __init__(self, readers: Mapping[str, DomainReader] | None = None) -> None:
        self._readers = dict(readers or {})

    def register(self, domain: str, reader: DomainReader) -> None:
        if domain not in DOMAINS:
            raise ValueError(f"unknown domain: {domain}")
        self._readers[domain] = reader

    def read(self, taxon: str) -> dict[str, ScientificReading]:
        results: dict[str, ScientificReading] = {}
        for domain in DOMAINS:
            reader = self._readers.get(domain)
            if reader is None:
                results[domain] = unavailable(
                    domain, "no canonical reader is bound in this deployment"
                )
                continue
            try:
                results[domain] = reader(taxon)
            except Exception as exc:  # noqa: BLE001
                # A reader that raises has not proved the domain is empty.
                results[domain] = unavailable(domain, f"{type(exc).__name__}: {exc}")
        return results

    def summarize(self, readings: Mapping[str, ScientificReading]) -> dict[str, Any]:
        """A coverage summary that never converts unavailable into zero."""
        by_state: dict[str, list[str]] = {}
        for domain, reading in readings.items():
            by_state.setdefault(reading.state, []).append(domain)
        evidentiary = [d for d, r in readings.items() if r.is_evidentiary]
        return {
            "domains_total": len(readings),
            "by_state": {state: sorted(names) for state, names in sorted(by_state.items())},
            "evidentiary_domains": sorted(evidentiary),
            # Deliberately not a percentage of "complete": the denominator
            # would have to include domains nobody consulted.
            "domains_with_evidence": len(evidentiary),
            "domains_not_consulted": sorted(
                d for d, r in readings.items() if r.state == UNAVAILABLE
            ),
        }
