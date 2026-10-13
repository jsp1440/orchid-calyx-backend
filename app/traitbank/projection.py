"""Pure projections of stored TraitBank evidence into existing consumers.

- Matrix: ``RelationshipAssertion`` records (``runtime/matrix_relationship.py``)
  that the existing ``/api/matrix-relationship/build`` and ``/compare``
  accept unchanged. Taxon-level assertions use the ``trait`` dimension with the
  same ``trait:{name}={value}`` object identity as the governed source;
  specimen / population / observation evidence uses
  ``trait_individual_evidence`` so it never enters taxon-to-taxon comparison.
- Calyx: an ``oc-parallel-v1`` reasoning envelope (the shape the Brain's
  ``calyx_brain.reasoning_contracts.build_reasoning_envelope`` produces) and
  ``BrainCandidateHandoffRequest`` objects for the canonical candidate-knowledge
  pipeline (``app/parallel_platform/brain_candidate_handoff.py``).

Confidence that a source did not report stays ``None``. The envelope says so
(``confidence_state``) and such evidence is not handed to candidate-knowledge,
whose request model requires a number: TraitBank does not supply one for it.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from app.parallel_platform.brain_candidate_handoff import (
    BrainCandidateHandoffRequest,
    BrainEvidenceAnchor,
)
from runtime.matrix_relationship import RelationshipAssertion

from .contract import CONTRACT_VERSION
from .models import AssertionIn, EnvironmentRelationIn, TraitDefinitionIn

INACTIVE_STATES = {"REJECTED", "SUPERSEDED"}
NON_VALUE_STATES = {"UNKNOWN", "UNAVAILABLE", "WITHHELD", "ABSENT"}
LEVELS = ("taxon", "population", "specimen", "observation")
GOVERNANCE = {
    "human_review_required": True,
    "graph_mutation": False,
    "automatic_publication": False,
}
_MAX_MATRIX_ID = 200


def active(assertions: list[AssertionIn]) -> list[AssertionIn]:
    return [a for a in assertions if a.evidence_state not in INACTIVE_STATES]


def value_text(definition: TraitDefinitionIn | None, a: AssertionIn) -> str:
    v = a.value
    if v.kind == "quantitative":
        stat = "" if v.statistic == "single" else f"{v.statistic} "
        spread = f" ± {v.sd:g} SD" if v.sd is not None else ""
        err = f" (± {v.uncertainty:g} measurement uncertainty)" if v.uncertainty else ""
        n = f", n={v.n}" if v.n is not None else ""
        return f"{stat}{v.numeric:g} {v.unit}{spread}{err}{n}"
    if v.kind == "range":
        n = f", n={v.n}" if v.n is not None else ""
        return f"{v.minimum:g}–{v.maximum:g} {v.unit}{n}"
    if v.kind == "categorical":
        state = definition.state(v.state_id or "") if definition else None
        return state.label if state else str(v.state_id)
    return f"missing ({v.missing_reason})"


def describe(definition: TraitDefinitionIn | None, a: AssertionIn) -> str:
    label = definition.label if definition else a.trait_id
    s = a.subject
    who = {
        "taxon": f"{s.verbatim_taxon_name} (taxon-level, {a.scope_basis.replace('_', ' ')})",
        "population": f"population {s.population_id} of {s.verbatim_taxon_name}",
        "specimen": f"specimen {s.specimen_id} of {s.verbatim_taxon_name}",
        "observation": f"observation {s.observation_id} of {s.verbatim_taxon_name}",
    }[a.level]
    where = f", {a.provenance.locator}" if a.provenance.locator else ""
    return f"{label} of {who}: {value_text(definition, a)} [{a.evidence_state}; {a.provenance.citation.rstrip('.')}{where}]"


# ---------------------------------------------------------------- conflicts
def _disagreement(left: AssertionIn, right: AssertionIn) -> str | None:
    lv, rv = left.value, right.value
    if lv.kind == "categorical" and rv.kind == "categorical":
        return "different categorical states" if lv.state_id != rv.state_id else None
    lb, rb = lv.bounds(), rv.bounds()
    if lb and rb and (lb[1] < rb[0] or rb[1] < lb[0]):
        return "non-overlapping quantitative values"
    return None


def conflicts(assertions: list[AssertionIn]) -> list[dict[str, Any]]:
    """Disagreement about the same subject. Different specimens are variation."""
    groups: dict[tuple, list[AssertionIn]] = defaultdict(list)
    for a in active(assertions):
        if a.value.kind == "missing":
            continue
        s = a.subject
        groups[
            (
                a.trait_id,
                s.taxon_id,
                a.level,
                s.specimen_id,
                s.population_id,
                s.observation_id,
            )
        ].append(a)
    found = []
    for (trait_id, taxon_id, level, *_), members in sorted(
        groups.items(), key=lambda kv: str(kv[0])
    ):
        ids: set[str] = set()
        reasons: set[str] = set()
        for left, right in combinations(members, 2):
            reason = _disagreement(left, right)
            if reason:
                ids.update((left.assertion_id, right.assertion_id))
                reasons.add(reason)
        if ids:
            found.append(
                {
                    "trait_id": trait_id,
                    "taxon_id": taxon_id,
                    "level": level,
                    "assertion_ids": sorted(ids),
                    "reason": "; ".join(sorted(reasons)),
                    "resolution": "preserved_not_collapsed",
                }
            )
    return found


# ---------------------------------------------------------------- summaries
def summarize(
    definition: TraitDefinitionIn,
    taxon_id: str,
    assertions: list[AssertionIn],
    relations: list[EnvironmentRelationIn] = (),  # type: ignore[assignment]
) -> dict[str, Any]:
    members = [
        a
        for a in active(assertions)
        if a.subject.taxon_id == taxon_id and a.trait_id == definition.trait_id
    ]
    found = [c for c in conflicts(members)]
    by_level: dict[str, Any] = {}
    for level in LEVELS:
        rows = [a for a in members if a.level == level]
        if not rows:
            continue
        entry: dict[str, Any] = {
            "assertion_ids": sorted(a.assertion_id for a in rows),
            "sources": sorted({a.provenance.source_id for a in rows}),
        }
        valued = [a for a in rows if a.value.kind != "missing"]
        if definition.value_kind == "quantitative":
            bounds = [a.value.bounds() for a in valued if a.value.bounds()]
            entry["reported_interval"] = (
                [min(b[0] for b in bounds), max(b[1] for b in bounds)]
                if bounds
                else None
            )
            entry["unit"] = definition.unit
        else:
            entry["state_counts"] = dict(Counter(a.value.state_id for a in valued))
        entry["missing"] = [
            {"assertion_id": a.assertion_id, "reason": a.value.missing_reason}
            for a in rows
            if a.value.kind == "missing"
        ]
        by_level[level] = entry
    caveats = []
    if members and "taxon" not in by_level:
        lower = ", ".join(
            f"{len(by_level[lv]['assertion_ids'])} {lv}-level" for lv in by_level
        )
        caveats.append(
            f"No taxon-level assertion exists; only {lower} evidence. "
            "These values describe the individuals measured, not the species."
        )
    if found:
        caveats.append(
            f"{len(found)} unresolved conflict(s) preserved; sources disagree."
        )
    states = {a.evidence_state for a in members}
    if found:
        state = "CONTRADICTORY"
    elif not members:
        state = "UNKNOWN"
    elif states == {"VERIFIED"}:
        state = "VERIFIED"
    elif states <= NON_VALUE_STATES:
        state = next(
            s for s in ("WITHHELD", "UNAVAILABLE", "UNKNOWN", "ABSENT") if s in states
        )
    else:
        state = "PROVISIONAL" if states - {"AVAILABLE"} else "AVAILABLE"
    return {
        "contract_version": CONTRACT_VERSION,
        "taxon_id": taxon_id,
        "trait_id": definition.trait_id,
        "trait_label": definition.label,
        "evidence_state": state,
        "levels": by_level,
        "conflicts": found,
        "caveats": caveats,
        "environment_relations": [
            {
                "relation_id": r.relation_id,
                "claim_kind": r.claim_kind,
                "text": r.describe(),
                "source_id": r.provenance.source_id,
            }
            for r in relations
            if r.trait_id == definition.trait_id
            and (not r.taxon_scope or taxon_id in r.taxon_scope)
        ],
    }


# -------------------------------------------------------------------- Matrix
def _bounded_id(text: str) -> str:
    if len(text) <= _MAX_MATRIX_ID:
        return text
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    return f"{text[: _MAX_MATRIX_ID - 17]}#{digest}"


def matrix_assertions(
    definitions: dict[str, TraitDefinitionIn],
    assertions: list[AssertionIn],
    subject_labels: dict[str, str],
) -> list[dict[str, Any]]:
    conflicted = {i for c in conflicts(assertions) for i in c["assertion_ids"]}
    out = []
    for a in sorted(active(assertions), key=lambda x: x.assertion_id):
        d = definitions.get(a.trait_id)
        if d is None:
            continue
        shown = value_text(d, a)
        if a.value.kind == "missing":
            # A missing value is never absence of the trait.
            state = (
                "unknown"
                if a.value.missing_reason == "indeterminate"
                else "not_recorded"
            )
        elif a.assertion_id in conflicted:
            state = "conflicting"
        else:
            state = "present"
        key = f"{d.label.casefold()}={shown.casefold()}"
        if a.level != "taxon":
            key += f"@{a.level}"
        assertion = RelationshipAssertion(
            subject_id=a.subject.taxon_id,
            subject_label=subject_labels.get(
                a.subject.taxon_id, a.subject.verbatim_taxon_name
            )[:300],
            dimension="trait" if a.level == "taxon" else "trait_individual_evidence",
            object_id=_bounded_id(f"trait:{key}"),
            object_label=f"{d.label}: {shown}"[:300],
            state=state,
            confidence=a.confidence,
            provenance={
                "source_domain": "traitbank",
                "source_pk": a.assertion_id,
                "trait_id": a.trait_id,
                "trait_name": d.label,
                "trait_value": shown,
                "assertion_level": a.level,
                "scope_basis": a.scope_basis,
                "evidence_state": a.evidence_state,
                "source_id": a.provenance.source_id,
                "original_record_id": a.provenance.original_record_id,
                "citation": a.provenance.citation,
                "license": a.provenance.license,
                "verbatim_value": a.value.verbatim,
                "confidence_state": "reported"
                if a.confidence is not None
                else "unknown",
            },
        )
        out.append({**assertion.__dict__, **GOVERNANCE})
    return out


# --------------------------------------------------------------------- Calyx
def _confidence(members: list[AssertionIn]) -> tuple[float | None, str]:
    known = [a.confidence for a in members if a.confidence is not None]
    if not known:
        return None, "unknown"
    if len(known) < len(members):
        # The weakest evidence bounds the candidate; an unreported value could
        # be the weakest, so no number is given.
        return None, "partially_unknown"
    return min(known), "reported"


def calyx_envelope(
    definition: TraitDefinitionIn,
    taxon_id: str,
    assertions: list[AssertionIn],
    relations: list[EnvironmentRelationIn] = (),  # type: ignore[assignment]
) -> dict[str, Any]:
    summary = summarize(definition, taxon_id, assertions, relations)
    members = [
        a
        for a in active(assertions)
        if a.subject.taxon_id == taxon_id
        and a.trait_id == definition.trait_id
        and a.value.kind != "missing"
    ]
    base = {
        "contract_version": CONTRACT_VERSION,
        "taxon_id": taxon_id,
        "trait_id": definition.trait_id,
        **GOVERNANCE,
    }
    if not members:
        return {
            **base,
            "statement": "TraitBank holds no value for this trait of this taxon. This is an evidence gap, not evidence of absence.",
            "summary": summary,
            "reasoning_envelope": None,
        }
    has_taxon_level = any(a.level == "taxon" for a in members)
    confidence, confidence_state = _confidence(members)
    contradictions = sorted(
        {i for c in summary["conflicts"] for i in c["assertion_ids"]}
    )
    envelope = {
        "contract_version": "oc-parallel-v1",
        "candidate_knowledge": {
            "candidate_id": f"traitbank:{taxon_id}:{definition.trait_id}",
            "subject_id": f"taxon:{taxon_id}",
            "predicate": "has_trait"
            if has_taxon_level
            else "has_trait_evidence_from_individuals",
            "object_id": definition.trait_id,
            "evidence_ids": [a.assertion_id for a in members],
            "confidence": confidence,
            "review_state": "review_required" if contradictions else "candidate",
        },
        "contradictions": contradictions,
        "validation_pathways": (
            ["curator review against cited sources"]
            if has_taxon_level
            else [
                "curator review against cited source",
                "additional specimens or populations before any taxon-level generalisation",
            ]
        ),
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
        "private_chain_of_thought_stored": False,
    }
    levels = summary["levels"]
    parts = []
    if "taxon" in levels:
        parts.append(
            f"{len(levels['taxon']['assertion_ids'])} taxon-level statement(s) from "
            f"{len(levels['taxon']['sources'])} source(s) report {definition.label.lower()} for this taxon"
        )
    for level in ("population", "specimen", "observation"):
        if level in levels:
            parts.append(
                f"{len(levels[level]['assertion_ids'])} {level}-level record(s)"
            )
    statement = "; ".join(parts) + "."
    if summary["conflicts"]:
        statement += " Sources disagree; both values are kept and neither is preferred."
    if not has_taxon_level:
        statement += (
            " No source states this at the species level, so these values describe the "
            "individuals measured and must not be presented as typical of the species."
        )
    if summary["evidence_state"] in ("PROVISIONAL", "AVAILABLE"):
        statement += " Evidence has not been verified by a reviewer."
    if confidence_state != "reported":
        statement += (
            " Confidence was not reported for all evidence and is left unknown."
        )
    return {
        **base,
        "statement": statement,
        "evidence": [
            {
                "evidence_id": a.assertion_id,
                "statement": describe(definition, a),
                "confidence": a.confidence,
                "level": a.level,
                "source_id": a.provenance.source_id,
            }
            for a in members
        ],
        "confidence": confidence,
        "confidence_state": confidence_state,
        "confidence_semantics": "fidelity_to_source_not_biological_generality",
        "caveats": summary["caveats"],
        "environment_relations": summary["environment_relations"],
        "summary": summary,
        "reasoning_envelope": envelope,
    }


def candidate_handoff_requests(
    definition: TraitDefinitionIn,
    stored_rows: list[dict[str, Any]],
) -> tuple[list[BrainCandidateHandoffRequest], list[dict[str, str]]]:
    """Requests for the candidate-knowledge pipeline, plus what was withheld and why.

    ``stored_rows`` are repository rows (they carry the integer ``assertion_pk``
    and ``batch_pk`` the handoff contract requires as database keys).
    """
    from .repository import row_to_assertion

    requests: list[BrainCandidateHandoffRequest] = []
    withheld: list[dict[str, str]] = []
    for row in stored_rows:
        a = row_to_assertion(row)
        if a.trait_id != definition.trait_id:
            continue
        reason = None
        if a.evidence_state in INACTIVE_STATES:
            reason = "INACTIVE_EVIDENCE_STATE"
        elif a.evidence_state in NON_VALUE_STATES:
            reason = "NON_VALUE_EVIDENCE_STATE"
        elif a.value.kind == "missing":
            reason = "MISSING_VALUE_IS_NOT_A_CANDIDATE"
        elif a.confidence is None:
            reason = "CONFIDENCE_NOT_REPORTED_NOT_DEFAULTED"
        elif (
            a.provenance.source_kind == "living_collection"
            and a.provenance.review_status not in ("accepted", "corrected")
        ):
            reason = "GROWER_RECORD_REQUIRES_REVIEW_BEFORE_ADMISSION"
        if reason:
            withheld.append({"assertion_id": a.assertion_id, "reason": reason})
            continue
        shown = value_text(definition, a)
        requests.append(
            BrainCandidateHandoffRequest(
                reasoning_id=f"traitbank:{a.assertion_id}"[:240],
                domain="measurement"
                if a.value.kind in ("quantitative", "range")
                else "trait",
                subject=f"taxon:{a.subject.taxon_id} {a.subject.verbatim_taxon_name}"[
                    :500
                ],
                predicate="has_trait"
                if a.level == "taxon"
                else "has_trait_evidence_from_individuals",
                object_value=f"{definition.label}: {shown}"[:12000],
                numeric_value=a.value.numeric
                if a.value.kind == "quantitative"
                else None,
                unit=a.value.unit,
                confidence=a.confidence,
                evidence_text=(
                    describe(definition, a)
                    + (
                        f"\n\nSource text: {a.provenance.original_text}"
                        if a.provenance.original_text
                        else ""
                    )
                )[:50000],
                source_object_type="oc_traitbank.assertion",
                source_object_id=int(row["assertion_pk"]),
                revision_id=1,
                extraction_run_id=int(row["batch_pk"]),
                source_anchors=[
                    BrainEvidenceAnchor(
                        anchor_id=int(row["assertion_pk"]),
                        logical_unit=a.provenance.locator
                        or a.provenance.original_record_id,
                        locator={
                            "source_id": a.provenance.source_id,
                            "original_record_id": a.provenance.original_record_id,
                            "locator": a.provenance.locator,
                        },
                    )
                ],
                provenance={
                    "contract_version": CONTRACT_VERSION,
                    "source_id": a.provenance.source_id,
                    "citation": a.provenance.citation,
                    "license": a.provenance.license,
                    "evidence_type": a.provenance.evidence_type,
                    "original_record_id": a.provenance.original_record_id,
                },
                qualifiers={
                    "assertion_level": a.level,
                    "scope_basis": a.scope_basis,
                    "evidence_state": a.evidence_state,
                    "trait_id": a.trait_id,
                    "verbatim_value": a.value.verbatim,
                },
            )
        )
    return requests, withheld
