from __future__ import annotations

from collections import defaultdict

from pydantic import BaseModel, ConfigDict, Field

from .registry import CanonicalBrainRegistry


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GovernanceGap(StrictModel):
    object_id: str
    gap_type: str
    message: str
    severity: str = Field(pattern=r"^(warning|error)$")


class GovernanceReport(StrictModel):
    architecture_count: int = Field(ge=0)
    intent_count: int = Field(ge=0)
    aligned_architecture_count: int = Field(ge=0)
    intent_coverage_ratio: float = Field(ge=0, le=1)
    gaps: list[GovernanceGap]


def build_governance_report(registry: CanonicalBrainRegistry) -> GovernanceReport:
    snapshot = registry.snapshot()
    architectures = [item for item in snapshot.objects if item.object_type == "architecture"]
    intents = [item for item in snapshot.objects if item.object_type == "intent"]

    aligned: set[str] = set()
    incoming_decisions: dict[str, int] = defaultdict(int)
    for relation in snapshot.relationships:
        if relation.relationship_type == "aligned_to":
            subject = registry.get(relation.subject_id)
            target = registry.get(relation.object_id)
            if subject and target and subject.object_type == "architecture" and target.object_type == "intent":
                aligned.add(subject.object_id)
        if relation.relationship_type == "documents":
            subject = registry.get(relation.subject_id)
            target = registry.get(relation.object_id)
            if subject and target and subject.object_type == "decision" and target.object_type == "architecture":
                incoming_decisions[target.object_id] += 1

    gaps: list[GovernanceGap] = []
    for architecture in sorted(architectures, key=lambda item: item.object_id):
        if architecture.object_id not in aligned:
            gaps.append(
                GovernanceGap(
                    object_id=architecture.object_id,
                    gap_type="missing_intent_alignment",
                    message=f"{architecture.title} is not aligned to a registered intent.",
                    severity="error",
                )
            )
        if incoming_decisions[architecture.object_id] == 0:
            gaps.append(
                GovernanceGap(
                    object_id=architecture.object_id,
                    gap_type="missing_decision_record",
                    message=f"{architecture.title} has no decision record documenting its approved scope.",
                    severity="warning",
                )
            )

    ratio = 1.0 if not architectures else len(aligned) / len(architectures)
    return GovernanceReport(
        architecture_count=len(architectures),
        intent_count=len(intents),
        aligned_architecture_count=len(aligned),
        intent_coverage_ratio=ratio,
        gaps=gaps,
    )
