"""The governed scientific runner behind the research executor.

:mod:`runtime.research_executor` moves a request between states and decides
nothing scientific. This is the other half: it binds one request to a durable
Research Station project, resolves the taxa it names, reads every canonical
domain it can, and records what it found.

The rule it exists to enforce is the one that makes the whole path worth
having: **a source that could not be consulted, or that held nothing, is
reported as such.** No model fills the gap. A request about a taxon the
Continuum holds nothing for completes as ``INSUFFICIENT_EVIDENCE`` with the
domains named, which is a true and useful answer; a fabricated paragraph
would be neither.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from runtime.research_executor import BlockerCode, RunOutcome
from runtime.scientific_reads import (
    AVAILABLE,
    EMPTY,
    UNAVAILABLE,
    ScientificReading,
    ScientificReadThrough,
)


def _taxa_of(request: Mapping[str, Any]) -> list[str]:
    """Taxa the request is about, from the record or from its question."""
    recorded = [
        str(item).strip()
        for item in (request.get("taxa") or ())
        if str(item).strip()
    ]
    if recorded:
        return recorded

    from app.calyx_conversation.external_literature import extract_taxa

    question = " ".join(
        str(request.get(field) or "")
        for field in ("title", "research_question")
    )
    return extract_taxa(question)


class GovernedResearchRunner:
    """Runs one request through canonical reads and a Research Station project.

    Every collaborator is injected. The runner is the place where a wrong
    default would be least visible and most damaging, so it has none: no
    station, no read-through, nothing happens.
    """

    def __init__(
        self,
        *,
        station: Any,
        read_through: ScientificReadThrough,
        owner_id: str = "calyx-research-executor",
        clock: Any | None = None,
    ) -> None:
        self._station = station
        self._reads = read_through
        self._owner_id = owner_id
        self._clock = clock

    def _now(self) -> str:
        if self._clock is not None:
            return self._clock()
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def run(self, request: Mapping[str, Any]) -> RunOutcome:
        request_id = str(request.get("id") or "").strip()
        if not request_id:
            return RunOutcome.blocked(
                code=BlockerCode.RUNNER_FAILED, detail="request has no id"
            )

        taxa = _taxa_of(request)
        if not taxa:
            # Not a failure of the corpus. The request never named a taxon, and
            # inventing one to have something to search for would be the first
            # fabrication in the chain.
            return RunOutcome.blocked(
                code=BlockerCode.TAXON_UNRESOLVED,
                detail=(
                    "no scientific name could be resolved from the request title "
                    "or question; nothing was searched"
                ),
                evidence_summary={"taxa": [], "domains": {}},
            )

        # The project id IS the request id: one key for the request and the
        # research workspace it produced.
        project = self._station.create_project(
            self._owner_id,
            {
                "project_id": request_id,
                "title": str(request.get("title") or request_id),
                "objective": str(
                    request.get("research_question") or "governed evidence assembly"
                ),
                "created_at": self._now(),
            },
        )

        per_taxon: dict[str, dict[str, Any]] = {}
        artifact_ids: list[str] = []
        evidentiary_total = 0

        for taxon in taxa:
            readings = self._reads.read(taxon)
            summary = self._reads.summarize(readings)
            evidentiary_total += summary["domains_with_evidence"]
            per_taxon[taxon] = {
                "summary": summary,
                "domains": {
                    domain: reading.as_record() for domain, reading in readings.items()
                },
            }
            artifact_ids.append(self._record_evidence(request_id, taxon, readings))

        evidence_summary = {
            "taxa": taxa,
            "project_id": request_id,
            "project_created": bool(project.get("created")),
            "domains_with_evidence": evidentiary_total,
            "per_taxon": per_taxon,
        }

        if evidentiary_total == 0:
            # Every domain was empty or unconsultable. The distinction is kept
            # in per_taxon so a reader can tell "the Continuum holds nothing"
            # from "nothing was reachable from here".
            return RunOutcome.blocked(
                code=BlockerCode.INSUFFICIENT_EVIDENCE,
                detail=(
                    "no domain returned evidentiary records for "
                    + ", ".join(taxa)
                ),
                evidence_summary=evidence_summary,
            )

        return RunOutcome.completed(
            artifact_ids=artifact_ids, evidence_summary=evidence_summary
        )

    def _record_evidence(
        self, request_id: str, taxon: str, readings: Mapping[str, ScientificReading]
    ) -> str:
        """Persist one taxon's readings through the real evidence chain.

        Artifact → attachment → claim → evidence, using the Research Station's
        own contracts rather than a shortcut around them. The artifact is what
        makes the reading immutable and checksummed; the claim is what carries
        the state as ``needs_review``, because a read-through is material for
        review and not a finding.
        """
        import json

        from app.calyx_orchestrator.artifact_registry import ArtifactRegistration

        body = {
            "taxon": taxon,
            "request_id": request_id,
            "recorded_at": self._now(),
            "domains": {
                domain: reading.as_record() for domain, reading in readings.items()
            },
            "states_present": sorted({reading.state for reading in readings.values()}),
            "is_scientific_publication": False,
        }
        content = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        artifact_id = f"artifact-{request_id}-{_slug(taxon)}"

        self._station.artifact_registry.register(
            ArtifactRegistration(
                artifact_id=artifact_id,
                content=content,
                media_type="application/json",
                source_uri=f"calyx://research-request/{request_id}",
                producer_assignment_id="calyx-research-executor",
                metadata={"taxon": taxon, "domains": sorted(readings)},
            )
        )
        attachment = self._station.attach(
            self._owner_id,
            request_id,
            {"kind": "artifact_registry", "source_id": artifact_id},
        )
        attachment_id = attachment["attachment"]["attachment_id"]

        evidentiary = sorted(d for d, r in readings.items() if r.is_evidentiary)
        claim = self._station.add_claim(
            self._owner_id,
            request_id,
            {
                "statement": (
                    f"Canonical read-through for {taxon} returned evidentiary records "
                    f"in: {', '.join(evidentiary) or 'no domain'}."
                ),
                # Never "supported". A read-through is material for review; a
                # claim that marks itself supported is a finding nobody made.
                "state": "needs_review",
                "provenance": {
                    "request_id": request_id,
                    "artifact_id": artifact_id,
                    "origins": sorted(
                        {r.origin for r in readings.values() if r.origin}
                    ),
                },
            },
        )
        self._station.add_evidence(
            self._owner_id,
            request_id,
            {
                "attachment_id": attachment_id,
                "claim_id": claim["claim"]["claim_id"],
                "relation": "context",
            },
        )
        return artifact_id


def _slug(value: str) -> str:
    return "-".join("".join(ch if ch.isalnum() else " " for ch in value).split()).lower()
