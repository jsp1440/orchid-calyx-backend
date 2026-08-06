from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def stable_checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# BUILD-KE-307 — privacy-preserving glossary usage analytics
class GlossaryUsageEvent(StrictModel):
    concept_id: str
    action: Literal["popover_open", "expanded_open", "media_open", "related_follow"]
    occurred_at: datetime


class GlossaryUsageSummary(StrictModel):
    concept_id: str
    action_counts: dict[str, int]
    total_events: int


def summarize_glossary_usage(events: list[GlossaryUsageEvent]) -> list[GlossaryUsageSummary]:
    counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for event in events:
        counts[event.concept_id][event.action] += 1
    return [
        GlossaryUsageSummary(
            concept_id=concept_id,
            action_counts=dict(sorted(action_counts.items())),
            total_events=sum(action_counts.values()),
        )
        for concept_id, action_counts in sorted(counts.items())
    ]


# BUILD-ATLAS-408 — candidate expedition planning
class ExpeditionSite(StrictModel):
    site_id: str
    conservation_priority: float = Field(ge=0, le=1)
    sampling_gap: float = Field(ge=0, le=1)
    access_feasibility: float = Field(ge=0, le=1)
    evidence_ids: list[str] = Field(min_length=1)


class ExpeditionPlanItem(StrictModel):
    site_id: str
    score: float
    evidence_ids: list[str]
    status: Literal["candidate"] = "candidate"


def rank_expedition_sites(sites: list[ExpeditionSite]) -> list[ExpeditionPlanItem]:
    items = [
        ExpeditionPlanItem(
            site_id=site.site_id,
            score=round((site.conservation_priority * 0.45) + (site.sampling_gap * 0.35) + (site.access_feasibility * 0.20), 8),
            evidence_ids=sorted(set(site.evidence_ids)),
        )
        for site in sites
    ]
    return sorted(items, key=lambda item: (-item.score, item.site_id))


# BUILD-RS-505 — scientific review packets
class ReviewPacket(StrictModel):
    packet_id: str
    hypothesis_ids: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    artifact_ids: list[str] = Field(min_length=1)
    required_review_classes: list[Literal["scientific", "licensing", "security", "operational"]] = Field(min_length=1)
    checksum: str


def build_review_packet(packet_id: str, hypothesis_ids: list[str], evidence_ids: list[str], artifact_ids: list[str], required_review_classes: list[str]) -> ReviewPacket:
    canonical = {
        "hypothesis_ids": sorted(set(hypothesis_ids)),
        "evidence_ids": sorted(set(evidence_ids)),
        "artifact_ids": sorted(set(artifact_ids)),
        "required_review_classes": sorted(set(required_review_classes)),
    }
    return ReviewPacket(packet_id=packet_id, checksum=stable_checksum(canonical), **canonical)


# BUILD-CON-605 — treatment and health-event tracking
class TreatmentEvent(StrictModel):
    treatment_id: str
    specimen_id: str
    diagnosis: str
    treatment: str
    started_at: datetime
    ended_at: datetime | None = None
    outcome: Literal["unknown", "improved", "resolved", "worsened"] = "unknown"

    def close(self, ended_at: datetime, outcome: Literal["improved", "resolved", "worsened"]) -> "TreatmentEvent":
        if self.ended_at is not None:
            raise ValueError("treatment is already closed")
        if ended_at <= self.started_at:
            raise ValueError("treatment end must occur after start")
        return self.model_copy(update={"ended_at": ended_at, "outcome": outcome})


# BUILD-MATRIX-705 — uncertainty explanations
class CharacterAssessment(StrictModel):
    character_id: str
    observed_state: str | None
    expected_state: str | None
    confidence: float = Field(ge=0, le=1)


class UncertaintyExplanation(StrictModel):
    matched: list[str]
    conflicting: list[str]
    missing: list[str]
    low_confidence: list[str]


def explain_identification_uncertainty(assessments: list[CharacterAssessment], threshold: float = 0.7) -> UncertaintyExplanation:
    matched: list[str] = []
    conflicting: list[str] = []
    missing: list[str] = []
    low_confidence: list[str] = []
    for item in assessments:
        if item.observed_state is None or item.expected_state is None:
            missing.append(item.character_id)
        elif item.observed_state == item.expected_state:
            matched.append(item.character_id)
        else:
            conflicting.append(item.character_id)
        if item.confidence < threshold:
            low_confidence.append(item.character_id)
    return UncertaintyExplanation(
        matched=sorted(matched),
        conflicting=sorted(conflicting),
        missing=sorted(missing),
        low_confidence=sorted(low_confidence),
    )


# BUILD-VISION-805 — pollinator observation candidates
class PollinatorObservationCandidate(StrictModel):
    observation_id: str
    image_id: str
    orchid_taxon_id: str
    pollinator_taxon_id: str | None = None
    interaction_type: Literal["approach", "contact", "pollinia_attachment", "pollination"]
    confidence: float = Field(ge=0, le=1)
    evidence_region_id: str
    status: Literal["candidate"] = "candidate"


def rank_pollinator_candidates(items: list[PollinatorObservationCandidate]) -> list[PollinatorObservationCandidate]:
    return sorted(items, key=lambda item: (-item.confidence, item.observation_id))


# BUILD-PUB-905 — manuscript section planning
class ManuscriptSectionPlan(StrictModel):
    section_id: str
    title: str
    required_evidence_classes: list[str] = Field(min_length=1)
    source_object_ids: list[str] = Field(min_length=1)


class ManuscriptPlan(StrictModel):
    manuscript_id: str
    sections: list[ManuscriptSectionPlan]
    checksum: str
    submission_enabled: bool = False


def build_manuscript_plan(manuscript_id: str, sections: list[ManuscriptSectionPlan]) -> ManuscriptPlan:
    ids = [section.section_id for section in sections]
    if not sections or len(ids) != len(set(ids)):
        raise ValueError("manuscript sections must be non-empty and unique")
    ordered = sorted(sections, key=lambda item: item.section_id)
    return ManuscriptPlan(
        manuscript_id=manuscript_id,
        sections=ordered,
        checksum=stable_checksum([item.model_dump(mode="json") for item in ordered]),
    )


# BUILD-INT-956 — integration contract test cases
class ContractTestCase(StrictModel):
    test_id: str
    contract_id: str
    payload: dict[str, object]
    expected_valid: bool


class ContractTestResult(StrictModel):
    test_id: str
    passed: bool
    payload_checksum: str


def run_contract_tests(cases: list[ContractTestCase], validator) -> list[ContractTestResult]:
    results: list[ContractTestResult] = []
    for case in sorted(cases, key=lambda item: item.test_id):
        actual = bool(validator(case.contract_id, case.payload))
        results.append(ContractTestResult(test_id=case.test_id, passed=actual == case.expected_valid, payload_checksum=stable_checksum(case.payload)))
    return results


# BUILD-MC-206 — agent capacity planning
class AgentCapacity(StrictModel):
    agent_id: str
    architecture_ids: list[str] = Field(min_length=1)
    capacity_units: int = Field(gt=0)
    active_units: int = Field(ge=0)


class CapacitySummary(StrictModel):
    available_units: int
    saturated_agent_ids: list[str]
    available_by_architecture: dict[str, int]


def summarize_capacity(agents: list[AgentCapacity]) -> CapacitySummary:
    by_architecture: dict[str, int] = defaultdict(int)
    saturated: list[str] = []
    available_total = 0
    for agent in agents:
        available = max(agent.capacity_units - agent.active_units, 0)
        available_total += available
        if available == 0:
            saturated.append(agent.agent_id)
        for architecture_id in agent.architecture_ids:
            by_architecture[architecture_id] += available
    return CapacitySummary(
        available_units=available_total,
        saturated_agent_ids=sorted(saturated),
        available_by_architecture=dict(sorted(by_architecture.items())),
    )


# BUILD-BRAIN-118 — governed supersession proposals
class SupersessionProposal(StrictModel):
    proposal_id: str
    old_object_id: str
    new_object_id: str
    rationale: str
    evidence_ids: list[str] = Field(min_length=1)
    status: Literal["proposed", "approved", "rejected"] = "proposed"


def propose_supersession(old_object_id: str, new_object_id: str, rationale: str, evidence_ids: list[str]) -> SupersessionProposal:
    if old_object_id == new_object_id:
        raise ValueError("an object cannot supersede itself")
    if not rationale.strip():
        raise ValueError("supersession requires rationale")
    canonical = {
        "old": old_object_id,
        "new": new_object_id,
        "rationale": rationale,
        "evidence_ids": sorted(set(evidence_ids)),
    }
    return SupersessionProposal(
        proposal_id=f"supersession:{stable_checksum(canonical)[:24]}",
        old_object_id=old_object_id,
        new_object_id=new_object_id,
        rationale=rationale,
        evidence_ids=canonical["evidence_ids"],
    )
