"""TraitBank as a pairwise Matrix evidence adapter (``morphology`` dimension).

Implements ``app.parallel_platform.matrix_adapters.MatrixEvidenceAdapter``.

Only current, taxon-level assertions compare two taxa. Specimen, population
and observation records describe individuals; they are counted and reported
in ``limitations`` but never contribute to a species-to-species score. No
confidence is invented: ``confidence`` is ``None`` unless every compared
assertion reported one, in which case it is the weakest reported value.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.parallel_platform.matrix_adapters import DimensionEvidence

from . import projection
from .models import AssertionIn
from .repository import TraitBankRepository, row_to_assertion


def _agree(left: AssertionIn, right: AssertionIn) -> bool:
    if left.value.kind == "categorical" and right.value.kind == "categorical":
        return left.value.state_id == right.value.state_id
    lb, rb = left.value.bounds(), right.value.bounds()
    return bool(lb and rb and not (lb[1] < rb[0] or rb[1] < lb[0]))


class TraitBankMorphologyAdapter:
    dimension = "morphology"

    def __init__(self, repository: TraitBankRepository) -> None:
        self.repository = repository

    def compare(self, subject_taxon_id: str, object_taxon_id: str) -> DimensionEvidence:
        rows = self.repository.assertions(
            taxon_ids=[subject_taxon_id, object_taxon_id], current_only=True
        )
        assertions = [row_to_assertion(r) for r in rows]
        return compare_assertions(subject_taxon_id, object_taxon_id, assertions)


def compare_assertions(
    subject_taxon_id: str, object_taxon_id: str, assertions: list[AssertionIn]
) -> DimensionEvidence:
    now = datetime.now(UTC)
    current = [a for a in projection.active(assertions) if a.value.kind != "missing"]
    individual = [a for a in current if a.level != "taxon"]
    taxon_level = [a for a in current if a.level == "taxon"]
    conflicted = {
        i for c in projection.conflicts(taxon_level) for i in c["assertion_ids"]
    }
    by_side: dict[str, dict[str, list[AssertionIn]]] = {
        subject_taxon_id: {},
        object_taxon_id: {},
    }
    for a in taxon_level:
        by_side.setdefault(a.subject.taxon_id, {}).setdefault(a.trait_id, []).append(a)
    shared = sorted(set(by_side[subject_taxon_id]) & set(by_side[object_taxon_id]))
    limitations: list[str] = []
    if individual:
        limitations.append(
            f"{len(individual)} specimen/population/observation record(s) describe individuals "
            "and were not used to compare species."
        )
    compared: list[str] = []
    agreeing = 0
    used: list[AssertionIn] = []
    for trait_id in shared:
        left = [
            a
            for a in by_side[subject_taxon_id][trait_id]
            if a.assertion_id not in conflicted
        ]
        right = [
            a
            for a in by_side[object_taxon_id][trait_id]
            if a.assertion_id not in conflicted
        ]
        if not left or not right:
            limitations.append(
                f"{trait_id}: sources disagree for at least one taxon; not scored."
            )
            continue
        compared.append(trait_id)
        used += left + right
        if all(_agree(lft, rgt) for lft in left for rgt in right):
            agreeing += 1
    if not compared:
        limitations.append("No shared, uncontested taxon-level trait to compare.")
        return DimensionEvidence(
            dimension="morphology",
            availability="unavailable",
            freshness_at=now,
            limitations=tuple(limitations),
        )
    reported = [a.confidence for a in used if a.confidence is not None]
    confidence = min(reported) if len(reported) == len(used) else None
    if confidence is None:
        limitations.append(
            "Confidence not reported for every compared assertion; left unknown."
        )
    return DimensionEvidence(
        dimension="morphology",
        availability="degraded" if len(compared) < len(shared) else "available",
        score=round(agreeing / len(compared), 6),
        confidence=confidence,
        evidence=tuple(compared),
        provenance=tuple(sorted({a.assertion_id for a in used})),
        freshness_at=now,
        limitations=tuple(limitations),
    )


def describe(evidence: DimensionEvidence) -> dict[str, Any]:
    return {**evidence.as_dict(), "source": "traitbank", "graph_mutation": False}
