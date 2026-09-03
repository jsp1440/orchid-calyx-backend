"""NAOCC provenance-aware synthesis framework.

Assembles evidence records into a structured synthesis following the four-category
schema required by #1096:
1. Established findings — cross-source convergent, explicit in literature.
2. Cross-source convergences — patterns appearing in ≥2 independent sources.
3. Contradictions — conflicting claims between sources, documented with both sides.
4. Knowledge gaps — areas where evidence is absent or explicitly noted as unknown.
5. Testable hypotheses — only generated when justified by ≥1 convergence or gap.

Rules:
- Every claim must have at least one ProvenanceAnchor pointing to a reviewed source.
- No AI-generated synthesis claim may be accepted as scientific evidence.
- A valid null result (no convergent pattern found) is an acceptable output.
- Novelty must not be asserted without evidence from the actual source corpus.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.naocc.evidence_schema import NAOCCEvidenceRecord, ProvenanceAnchor

SCHEMA_VERSION = "naocc-synthesis/v1"


class SynthesisCategory(str, Enum):
    ESTABLISHED_FINDING = "established_finding"
    CROSS_SOURCE_CONVERGENCE = "cross_source_convergence"
    CONTRADICTION = "contradiction"
    KNOWLEDGE_GAP = "knowledge_gap"
    TESTABLE_HYPOTHESIS = "testable_hypothesis"


@dataclass(frozen=True)
class SynthesisItem:
    """One item in the synthesis output."""

    item_id: str
    category: SynthesisCategory
    claim: str
    supporting_source_ids: tuple[str, ...]
    contradicting_source_ids: tuple[str, ...]
    confidence_notes: str
    limitations: str
    is_ai_interpretation: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "category": self.category.value,
            "claim": self.claim,
            "supporting_source_ids": list(self.supporting_source_ids),
            "contradicting_source_ids": list(self.contradicting_source_ids),
            "confidence_notes": self.confidence_notes,
            "limitations": self.limitations,
            "is_ai_interpretation": self.is_ai_interpretation,
        }


@dataclass(frozen=True)
class ScientistReviewItem:
    """A statement a scientist can rapidly check as known/correct/incorrect."""

    statement: str
    basis_source_ids: tuple[str, ...]
    review_prompt: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "basis_source_ids": list(self.basis_source_ids),
            "review_prompt": self.review_prompt,
        }


@dataclass
class NAOCCSynthesis:
    """Provenance-aware synthesis of NAOCC corpus evidence.

    graph_mutation is always False. This synthesis is a structured summary,
    not a KG write. No claim in this output is automatically accepted as
    scientific truth.
    """

    schema_version: str
    generated_at: str
    graph_mutation: bool
    scientific_question: str
    source_ids_used: list[str]
    record_count: int
    items: list[SynthesisItem]
    scientist_review_section: list[ScientistReviewItem]
    null_result_declared: bool
    null_result_reason: str
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generated_at": self.generated_at,
            "graph_mutation": self.graph_mutation,
            "scientific_question": self.scientific_question,
            "source_ids_used": self.source_ids_used,
            "record_count": self.record_count,
            "item_count": len(self.items),
            "items": [item.to_dict() for item in self.items],
            "scientist_review_section": [r.to_dict() for r in self.scientist_review_section],
            "null_result_declared": self.null_result_declared,
            "null_result_reason": self.null_result_reason,
            "notes": self.notes,
        }

    def by_category(self, category: SynthesisCategory) -> list[SynthesisItem]:
        return [item for item in self.items if item.category == category]


def _count_sources(items: list[SynthesisItem]) -> set[str]:
    result: set[str] = set()
    for item in items:
        result.update(item.supporting_source_ids)
        result.update(item.contradicting_source_ids)
    return result


def build_provenance_aware_synthesis(
    scientific_question: str,
    records: list[NAOCCEvidenceRecord],
    items: list[SynthesisItem],
    scientist_review: list[ScientistReviewItem] | None = None,
) -> NAOCCSynthesis:
    """Assemble a synthesis from reviewed evidence records and explicitly authored items.

    Args:
        scientific_question: The exact question the synthesis addresses.
        records: Reviewed, validated NAOCCEvidenceRecords from extraction.
        items: Explicitly authored SynthesisItems (each must reference real source_ids).
        scientist_review: Items for the scientist-review section.

    Returns:
        NAOCCSynthesis with provenance, no KG mutation.
    """
    if not records and not items:
        return NAOCCSynthesis(
            schema_version=SCHEMA_VERSION,
            generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            graph_mutation=False,
            scientific_question=scientific_question,
            source_ids_used=[],
            record_count=0,
            items=[],
            scientist_review_section=scientist_review or [],
            null_result_declared=True,
            null_result_reason=(
                "No evidence records were provided. This is a valid null result: "
                "the corpus has not been extracted yet, not a finding that the "
                "pattern is absent."
            ),
            notes=(
                "Synthesis produced with zero evidence records. The corpus manifest "
                "must be populated and extraction must run before a non-null synthesis "
                "can be generated. A null result is scientifically valid and preferable "
                "to fabricating claims."
            ),
        )

    record_source_ids = {r.source_id for r in records}
    item_source_ids = _count_sources(items)
    all_source_ids = sorted(record_source_ids | item_source_ids)

    # Convergence check: only flag hypothesis if ≥2 independent sources support it.
    hypotheses = [i for i in items if i.category == SynthesisCategory.TESTABLE_HYPOTHESIS]
    for hyp in hypotheses:
        if len(hyp.supporting_source_ids) < 2:
            raise ValueError(
                f"Testable hypothesis {hyp.item_id!r} requires ≥2 independent "
                f"supporting sources; has {len(hyp.supporting_source_ids)}: "
                f"{hyp.supporting_source_ids}"
            )

    return NAOCCSynthesis(
        schema_version=SCHEMA_VERSION,
        generated_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        graph_mutation=False,
        scientific_question=scientific_question,
        source_ids_used=all_source_ids,
        record_count=len(records),
        items=items,
        scientist_review_section=scientist_review or [],
        null_result_declared=False,
        null_result_reason="",
        notes=(
            "This synthesis is AI-assisted. AI interpretation is not scientific "
            "authority. Every claim cites its source. Convergences require ≥2 "
            "independent sources. Hypotheses require ≥2 supporting sources. "
            "The scientist-review section contains statements for rapid human "
            "verification."
        ),
    )
