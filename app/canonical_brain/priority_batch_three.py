from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def stable_checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ExplorerConcept(StrictModel):
    concept_id: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    related_ids: list[str] = Field(default_factory=list)
    prerequisite_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)


class KnowledgeExplorerIndex:
    def __init__(self, concepts: list[ExplorerConcept]) -> None:
        self._concepts = {item.concept_id: item for item in concepts}
        for item in concepts:
            for ref in item.related_ids + item.prerequisite_ids:
                if ref not in self._concepts:
                    raise ValueError(f"unknown concept reference: {ref}")

    def search(self, query: str) -> list[ExplorerConcept]:
        needle = query.casefold().strip()
        if not needle:
            return []
        return sorted(
            [item for item in self._concepts.values() if needle in " ".join([item.label, *item.aliases]).casefold()],
            key=lambda item: item.concept_id,
        )

    def learning_path(self, target_id: str) -> list[str]:
        if target_id not in self._concepts:
            raise KeyError(target_id)
        ordered: list[str] = []
        seen: set[str] = set()

        def visit(concept_id: str) -> None:
            if concept_id in seen:
                return
            seen.add(concept_id)
            for prereq in sorted(self._concepts[concept_id].prerequisite_ids):
                visit(prereq)
            ordered.append(concept_id)

        visit(target_id)
        return ordered


class HabitatVariable(StrictModel):
    variable_id: str
    normalized_score: float = Field(ge=0, le=1)
    evidence_id: str
    weight: float = Field(gt=0)


class HabitatSuitabilityResult(StrictModel):
    taxon_id: str
    cell_id: str
    suitability_score: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    status: Literal["candidate"] = "candidate"


def calculate_habitat_suitability(taxon_id: str, cell_id: str, variables: list[HabitatVariable]) -> HabitatSuitabilityResult:
    if not variables:
        raise ValueError("at least one habitat variable is required")
    denominator = sum(item.weight for item in variables)
    score = sum(item.normalized_score * item.weight for item in variables) / denominator
    return HabitatSuitabilityResult(
        taxon_id=taxon_id,
        cell_id=cell_id,
        suitability_score=round(score, 8),
        evidence_ids=sorted({item.evidence_id for item in variables}),
    )


class ProtocolStep(StrictModel):
    step_id: str
    instruction: str
    input_artifact_ids: list[str] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)


class ResearchProtocol(StrictModel):
    protocol_id: str
    title: str
    version: str
    steps: list[ProtocolStep] = Field(min_length=1)
    source_uris: list[str] = Field(min_length=1)

    def reproducibility_checksum(self) -> str:
        return stable_checksum(self.model_dump(mode="json"))


class CareEvent(StrictModel):
    event_id: str
    specimen_id: str
    event_type: Literal["watered", "fertilized", "repotted", "moved", "treated", "bloomed"]
    occurred_at: str
    notes: str = ""
    sensor_snapshot_id: str | None = None


class ConservatoryTimeline:
    def __init__(self) -> None:
        self._events: dict[str, CareEvent] = {}

    def register(self, event: CareEvent) -> CareEvent:
        existing = self._events.get(event.event_id)
        if existing and existing != event:
            raise ValueError(f"conflicting care event identity: {event.event_id}")
        self._events[event.event_id] = event
        return event

    def for_specimen(self, specimen_id: str) -> list[CareEvent]:
        return sorted(
            [event for event in self._events.values() if event.specimen_id == specimen_id],
            key=lambda event: (event.occurred_at, event.event_id),
        )


class TaxonCandidate(StrictModel):
    taxon_id: str
    states: dict[str, str | None]


class IdentificationScore(StrictModel):
    taxon_id: str
    matched: int
    conflicting: int
    missing: int
    score: float


def rank_taxa(observed_states: dict[str, str], candidates: list[TaxonCandidate]) -> list[IdentificationScore]:
    results: list[IdentificationScore] = []
    for candidate in candidates:
        matched = conflicting = missing = 0
        for character_id, observed in observed_states.items():
            expected = candidate.states.get(character_id)
            if expected is None:
                missing += 1
            elif expected == observed:
                matched += 1
            else:
                conflicting += 1
        denominator = matched + conflicting + missing
        score = 0.0 if denominator == 0 else (matched - conflicting) / denominator
        results.append(IdentificationScore(taxon_id=candidate.taxon_id, matched=matched, conflicting=conflicting, missing=missing, score=score))
    return sorted(results, key=lambda item: (-item.score, item.conflicting, item.missing, item.taxon_id))


class VisionReviewItem(StrictModel):
    observation_id: str
    image_id: str
    proposed_character_id: str
    proposed_state: str
    confidence: float = Field(ge=0, le=1)
    status: Literal["queued", "approved", "rejected"] = "queued"


class VisionReviewQueue:
    def __init__(self) -> None:
        self._items: dict[str, VisionReviewItem] = {}

    def submit(self, item: VisionReviewItem) -> VisionReviewItem:
        if item.status != "queued":
            raise ValueError("new visual observations must enter queued")
        existing = self._items.get(item.observation_id)
        if existing and existing != item:
            raise ValueError("conflicting observation identity")
        self._items[item.observation_id] = item
        return item

    def decide(self, observation_id: str, decision: Literal["approved", "rejected"]) -> VisionReviewItem:
        item = self._items.get(observation_id)
        if item is None:
            raise KeyError(observation_id)
        if item.status != "queued":
            raise ValueError("visual review decision is terminal")
        updated = item.model_copy(update={"status": decision})
        self._items[observation_id] = updated
        return updated


class ReportSection(StrictModel):
    section_id: str
    title: str
    body: str
    evidence_ids: list[str] = Field(min_length=1)


class ReportPackage(StrictModel):
    report_id: str
    title: str
    sections: list[ReportSection] = Field(min_length=1)
    checksum: str
    publication_enabled: bool = False


def assemble_report(report_id: str, title: str, sections: list[ReportSection]) -> ReportPackage:
    ids = [section.section_id for section in sections]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate report section IDs")
    ordered = sorted(sections, key=lambda item: item.section_id)
    checksum = stable_checksum([item.model_dump(mode="json") for item in ordered])
    return ReportPackage(report_id=report_id, title=title, sections=ordered, checksum=checksum)


class RoutedEvent(StrictModel):
    event_id: str
    event_type: str
    source: str
    destinations: list[str] = Field(min_length=1)
    payload_checksum: str = Field(min_length=64, max_length=64)


class EventRouter:
    def __init__(self, routes: dict[str, list[str]]) -> None:
        self._routes = {key: sorted(set(value)) for key, value in routes.items()}
        self._events: dict[str, RoutedEvent] = {}

    def route(self, event_id: str, event_type: str, source: str, payload: dict[str, object]) -> RoutedEvent:
        destinations = self._routes.get(event_type)
        if not destinations:
            raise ValueError(f"no route for event type: {event_type}")
        candidate = RoutedEvent(event_id=event_id, event_type=event_type, source=source, destinations=destinations, payload_checksum=stable_checksum(payload))
        existing = self._events.get(event_id)
        if existing and existing != candidate:
            raise ValueError("conflicting routed event identity")
        self._events[event_id] = candidate
        return candidate


class RiskItem(StrictModel):
    risk_id: str
    architecture_id: str
    severity: Literal["low", "medium", "high", "critical"]
    status: Literal["open", "mitigated"] = "open"
    blocker_build_ids: list[str] = Field(default_factory=list)


class RiskSummary(StrictModel):
    open_count: int
    critical_count: int
    blocked_build_ids: list[str]


def summarize_risks(items: list[RiskItem]) -> RiskSummary:
    open_items = [item for item in items if item.status == "open"]
    return RiskSummary(
        open_count=len(open_items),
        critical_count=sum(item.severity == "critical" for item in open_items),
        blocked_build_ids=sorted({build_id for item in open_items for build_id in item.blocker_build_ids}),
    )


class ArchitectureChangeProposal(StrictModel):
    proposal_id: str
    title: str
    affected_architecture_ids: list[str] = Field(min_length=1)
    rationale: str
    source_uri: str
    proposed_object_types: list[Literal["architecture", "decision", "dependency", "risk", "intent"]] = Field(min_length=1)
    status: Literal["proposed"] = "proposed"


def propose_architecture_change(title: str, affected_architecture_ids: list[str], rationale: str, source_uri: str, proposed_object_types: list[str]) -> ArchitectureChangeProposal:
    if not rationale.strip():
        raise ValueError("architecture changes require rationale")
    canonical = {
        "title": title,
        "affected": sorted(set(affected_architecture_ids)),
        "rationale": rationale,
        "source_uri": source_uri,
        "object_types": sorted(set(proposed_object_types)),
    }
    return ArchitectureChangeProposal(
        proposal_id=f"arch-change:{stable_checksum(canonical)[:24]}",
        title=title,
        affected_architecture_ids=canonical["affected"],
        rationale=rationale,
        source_uri=source_uri,
        proposed_object_types=canonical["object_types"],
    )
