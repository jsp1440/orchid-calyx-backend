"""Turn "the system could not answer that" into a bounded, actionable candidate.

When the reasoning map cannot settle a question, failing is the wrong response
and so is guessing. The useful response is to say *what kind of thing is
missing*, because that determines who can fix it and how: a missing source is a
librarian's problem, a missing validator is an engineer's, and a missing
ontology term is neither.

What this module may not do is as important as what it does. A candidate is a
**proposal to a human**. It never rewrites governance, never promotes a
hypothesis, and never activates a scientific conclusion. Those constraints are
invariants here, not conventions — a candidate constructed with any of them
relaxed raises.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

DISCOVERY_SCHEMA = "oc.improvement-candidate.v1"

#: Used where a candidate is worth recording but holds nothing up. Stated
#: rather than left empty, so a triager can see it at a glance.
NOTHING_BLOCKED = "none — the reasoning is complete without it"


class Deficiency(StrEnum):
    """Why the system could not answer. The kind determines who can fix it."""

    MISSING_RELATIONSHIP = "missing_relationship"
    MISSING_SOURCE = "missing_source"
    MISSING_INGESTION = "missing_ingestion"
    MISSING_ONTOLOGY_TERM = "missing_ontology_term"
    MISSING_EVIDENCE = "missing_evidence"
    MISSING_CAPABILITY = "missing_capability"
    MISSING_REASONING_OPERATION = "missing_reasoning_operation"
    MISSING_VALIDATOR = "missing_validator"
    MISSING_MODULE_HANDOFF = "missing_module_handoff"


#: Phrase fragments that identify a deficiency kind from a gap statement. Ordered
#: most specific first, because "no source quantifies X" is about a missing
#: measurement, not about lacking sources in general.
_CLASSIFIERS: tuple[tuple[re.Pattern[str], Deficiency, str], ...] = (
    (
        re.compile(r"identified to genus, not species", re.IGNORECASE),
        Deficiency.MISSING_ONTOLOGY_TERM,
        "The evidence names a genus where the question needs a species.",
    ),
    (
        re.compile(r"no (?:source|record) quantifies", re.IGNORECASE),
        Deficiency.MISSING_EVIDENCE,
        "The relationship is reported but never measured.",
    ),
    (
        re.compile(r"no (?:local )?observation|observation is held", re.IGNORECASE),
        Deficiency.MISSING_EVIDENCE,
        "Nothing observed locally supports the retrieved claims.",
    ),
    (
        re.compile(r"literature and aggregated records only", re.IGNORECASE),
        Deficiency.MISSING_INGESTION,
        "One evidence class is absent from the store entirely.",
    ),
)


@dataclass(frozen=True)
class ImprovementCandidate:
    """A bounded proposal. Never an action, and never self-approving."""

    deficiency: Deficiency
    statement: str
    why_it_matters: str
    bounded_next_step: str
    blocks_question: str
    schema: str = DISCOVERY_SCHEMA
    #: Invariants. A candidate that could approve itself is not a proposal.
    requires_human_review: bool = True
    may_modify_governance: bool = False
    may_promote_hypothesis: bool = False
    may_activate_scientific_conclusion: bool = False
    evidence: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.requires_human_review:
            raise ValueError(
                "DISCOVERY_REVIEW_INVARIANT: an improvement candidate is a proposal to a "
                "human; it may not mark itself reviewed"
            )
        for flag in (
            "may_modify_governance",
            "may_promote_hypothesis",
            "may_activate_scientific_conclusion",
        ):
            if getattr(self, flag):
                raise ValueError(
                    f"DISCOVERY_AUTHORITY_INVARIANT: {flag} must be False. Improvement "
                    "Discovery proposes work; it does not change what the system is "
                    "allowed to claim."
                )
        for name in ("statement", "why_it_matters", "bounded_next_step", "blocks_question"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"improvement candidate requires {name!r}")

    def to_record(self) -> dict[str, Any]:
        data = asdict(self)
        data["deficiency"] = self.deficiency.value
        return data


def classify(statement: str) -> tuple[Deficiency, str]:
    """Name the kind of thing that is missing, from how the gap was stated.

    Falls back to ``MISSING_EVIDENCE`` — the least actionable kind — rather than
    guessing a more specific one. A wrong specific classification sends the work
    to the wrong person; a vague one merely asks someone to look.
    """
    for pattern, kind, why in _CLASSIFIERS:
        if pattern.search(statement):
            return kind, why
    return (
        Deficiency.MISSING_EVIDENCE,
        (
            "The retrieved evidence does not cover this, and the shortfall is not "
            "specific enough to route further without a human reading it."
        ),
    )


def discover(reasoning_map: dict[str, Any]) -> list[ImprovementCandidate]:
    """Derive candidates from what a reasoning map could not settle.

    Sources, in order: the gaps the executor found in the graph, an unresolved
    contradiction (which is a *different* deficiency — evidence exists, it simply
    disagrees), and a capability the question needed but nothing deterministic
    supplies.
    """
    question = str(reasoning_map.get("question") or "")
    candidates: list[ImprovementCandidate] = []

    for gap in reasoning_map.get("evidence_gaps") or []:
        kind, why = classify(str(gap))
        candidates.append(
            ImprovementCandidate(
                deficiency=kind,
                statement=str(gap),
                why_it_matters=why,
                bounded_next_step=_next_step(kind),
                blocks_question=question,
                evidence=["reasoning_map.evidence_gaps"],
            )
        )

    for contradiction in reasoning_map.get("contradictions") or []:
        if contradiction.get("resolution") != "unresolved_presented_as_contested":
            continue
        candidates.append(
            ImprovementCandidate(
                deficiency=Deficiency.MISSING_REASONING_OPERATION,
                statement=(
                    "Two reports conflict and nothing retrieved distinguishes them: "
                    + "; ".join(contradiction.get("between") or [])
                ),
                why_it_matters=(
                    "This is not an absence of evidence. Evidence exists on both sides and "
                    "the system has no operation that would decide between them, so the "
                    "honest output is 'contested' and it will stay that way until one exists."
                ),
                bounded_next_step=(
                    "Define the comparison that would settle it — a scope test, a weighting "
                    "rule, or an explicit decision to leave it contested — and implement it "
                    "as a reasoning operation with its own tests."
                ),
                blocks_question=question,
                evidence=["reasoning_map.contradictions"],
            )
        )

    execution = reasoning_map.get("execution") or {}
    if execution.get("explanation_available") is False and execution.get("explanation_capability"):
        candidates.append(
            ImprovementCandidate(
                deficiency=Deficiency.MISSING_CAPABILITY,
                statement=(
                    f"The reasoning is assembled but {execution['explanation_capability']} is "
                    "unavailable, so it reaches a reader as structured fields rather than prose."
                ),
                why_it_matters=(
                    "This blocks nothing scientific. The reasoning, its evidence states and "
                    "its gaps are all present; only the connecting prose is absent."
                ),
                bounded_next_step=(
                    "Either authorize the capability for this path, or accept the structured "
                    "presentation as the release form. Both are legitimate; leaving it "
                    "unstated is not."
                ),
                # Named explicitly rather than left blank: a reader scanning the
                # report must be able to see at once that this one blocks nothing.
                blocks_question=NOTHING_BLOCKED,
                evidence=["reasoning_map.execution.explanation_available"],
            )
        )

    return candidates


def _next_step(kind: Deficiency) -> str:
    return {
        Deficiency.MISSING_RELATIONSHIP: "Add the relationship to the graph, with its source.",
        Deficiency.MISSING_SOURCE: "Identify a citable source and record it with provenance.",
        Deficiency.MISSING_INGESTION: (
            "Add an ingestion path for this evidence class, so the absence is a data "
            "question rather than a pipeline one."
        ),
        Deficiency.MISSING_ONTOLOGY_TERM: (
            "Resolve the term to the rank the question needs, or record that the source "
            "cannot support that resolution."
        ),
        Deficiency.MISSING_EVIDENCE: (
            "Record what observation or measurement would close this, and whether anyone "
            "can currently make it."
        ),
        Deficiency.MISSING_CAPABILITY: "Decide whether to add the capability or to do without it.",
        Deficiency.MISSING_REASONING_OPERATION: "Define and implement the missing operation.",
        Deficiency.MISSING_VALIDATOR: "Add a validator that would have caught this.",
        Deficiency.MISSING_MODULE_HANDOFF: "Wire the handoff and prove it carries evidence states.",
    }[kind]


def to_report(reasoning_map: dict[str, Any]) -> dict[str, Any]:
    """The discovery result, grouped by kind so it can be routed."""
    candidates = discover(reasoning_map)
    by_kind: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_kind.setdefault(candidate.deficiency.value, []).append(candidate.to_record())
    return {
        "schema": DISCOVERY_SCHEMA,
        "question": reasoning_map.get("question"),
        "candidate_count": len(candidates),
        "by_deficiency": by_kind,
        "authority": {
            "requires_human_review": True,
            "may_modify_governance": False,
            "may_promote_hypothesis": False,
            "may_activate_scientific_conclusion": False,
        },
    }
