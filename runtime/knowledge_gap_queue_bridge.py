"""Bridge canonical Calyx knowledge gaps into deterministic reserve work.

This module does not execute research. It converts gaps from closed domain
vocabularies into authorized objective candidates for the existing reserve
planner, which the frontend persistence plane already consumes:

* synthesis gaps (teaching-synthesis domains), via :func:`knowledge_gap_candidate`;
* per-taxon evidence-coverage gaps counted from the knowledge graph, via
  :func:`evidence_gap_candidate`. Locality-gated domains are not in its
  vocabulary, so ``sensitive_locality_disclosure`` stays false by construction.

Both emit the same ``source_payload`` keys and authority flags.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from typing import Any

from app.calyx_conversation.teaching_synthesis import (
    knowledge_gap_to_research_question,
)
from runtime.evidence_coverage_gaps import (
    EVIDENCE_COVERAGE_METHOD,
    EVIDENCE_DOMAINS,
    KNOWN_SOURCE_NAMES,
)
from scripts.oc_backlog_refiller import plan_refill

_SCHEMA = "oc.knowledge-gap-reserve-source.v1"
_SAFE_SOURCE_ID = re.compile(r"^[a-z0-9_.]{1,80}$")

#: Closed vocabulary of evidence-coverage research domains. Locality-gated
#: domains (distribution/habitat) are deliberately absent.
EVIDENCE_GAP_DOMAIN_LABELS: dict[str, str] = {
    "nomenclature": (
        "nomenclatural evidence (accepted name, synonymy, protologue publication "
        "and year, common names, infrageneric placement, etymology)"
    ),
    "morphology": (
        "morphological evidence (description, fruit capsule, scent, diagnostic "
        "comparison with similar species)"
    ),
    "phenology": "phenological evidence (flowering season)",
    "literature": "bibliographic evidence (primary scientific literature)",
    "conservation": "conservation-assessment evidence",
    "pollinators": "pollinator evidence",
    "mycorrhizae": "mycorrhizal-association evidence",
}
if set(EVIDENCE_GAP_DOMAIN_LABELS) & {
    d.name for d in EVIDENCE_DOMAINS if d.locality_gated
}:
    raise RuntimeError("locality-gated domains must never be reserve research domains")


def _normalize(value: str) -> str:
    return " ".join(value.split()).casefold()


def _fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def knowledge_gap_candidate(
    *,
    taxon_id: str,
    taxon_name: str,
    domain: str,
    research_question: str | None = None,
    priority: int = 1,
) -> dict[str, Any]:
    """Return one authorized reserve candidate from a canonical synthesis gap.

    The research question is always derived server-side. If a caller supplies
    one, it must exactly match the canonical normalized question; this prevents
    arbitrary instructions from entering the autonomous work queue.
    """

    normalized_taxon_id = _normalize(taxon_id)
    normalized_taxon_name = " ".join(taxon_name.split())
    normalized_domain = _normalize(domain)
    if not normalized_taxon_id:
        raise ValueError("CANONICAL_TAXON_ID_REQUIRED")
    if not normalized_taxon_name:
        raise ValueError("TAXON_NAME_REQUIRED")

    canonical_question = knowledge_gap_to_research_question(
        normalized_domain,
        normalized_taxon_name,
    )
    if canonical_question is None:
        raise ValueError("UNSUPPORTED_SYNTHESIS_DOMAIN")

    if research_question is not None:
        supplied = " ".join(research_question.split())
        if supplied != canonical_question:
            raise ValueError("NON_CANONICAL_RESEARCH_QUESTION")

    identity = {
        "schema": _SCHEMA,
        "taxon_id": normalized_taxon_id,
        "domain": normalized_domain,
        "research_question": canonical_question,
    }
    return _reserve_candidate(
        identity=identity,
        taxon_name=normalized_taxon_name,
        ref_prefix="calyx-synthesis-gap",
        fingerprint_material=identity,
        priority=priority,
    )


def evidence_coverage_research_question(
    domain: str, taxon_name: str, candidate_source_table: str | None = None
) -> str | None:
    """The canonical, single-line question for an evidence-coverage gap.

    Built only from the closed domain vocabulary, the KG-resolved taxon name and
    a source identifier; no caller text enters it. ``None`` for any domain
    outside the vocabulary (including every locality-gated domain).
    """
    label = EVIDENCE_GAP_DOMAIN_LABELS.get(domain)
    name = " ".join(taxon_name.split())
    if label is None or not name:
        return None
    source_clause = "No federated source in the knowledge graph covers it yet."
    if candidate_source_table:
        source_id = candidate_source_table.strip()
        if not _SAFE_SOURCE_ID.match(source_id):
            return None
        source_name = KNOWN_SOURCE_NAMES.get(source_id, source_id)
        source_clause = (
            f"{source_name} already holds evidence for this taxon in other domains and "
            f"supplies {domain} evidence for other taxa, so check its current record "
            "and underlying citations first."
        )
    return (
        f"Which published sources give {label} for {name}? The Orchid Continuum "
        f"knowledge graph holds no {domain} evidence for this taxon. {source_clause} "
        "Any evidence found enters as provisional candidate evidence for human "
        "review; nothing is published and the knowledge graph is not changed."
    )


def evidence_gap_candidate(
    *,
    taxon_id: str,
    taxon_name: str,
    domain: str,
    candidate_source_table: str | None = None,
    priority: int = 1,
) -> dict[str, Any]:
    """Return one authorized reserve candidate for a KG evidence-coverage gap.

    The fingerprint is ``schema + taxon_id + domain + method`` so the same gap
    is the same work across runs, whatever the run id or source wording.
    """
    normalized_taxon_id = _normalize(taxon_id)
    normalized_taxon_name = " ".join(taxon_name.split())
    normalized_domain = _normalize(domain)
    if not normalized_taxon_id:
        raise ValueError("CANONICAL_TAXON_ID_REQUIRED")
    if not normalized_taxon_name:
        raise ValueError("TAXON_NAME_REQUIRED")
    if normalized_domain not in EVIDENCE_GAP_DOMAIN_LABELS:
        raise ValueError("UNSUPPORTED_EVIDENCE_DOMAIN")
    question = evidence_coverage_research_question(
        normalized_domain, normalized_taxon_name, candidate_source_table
    )
    if question is None:
        raise ValueError("INVALID_CANDIDATE_SOURCE")
    identity = {
        "schema": _SCHEMA,
        "taxon_id": normalized_taxon_id,
        "domain": normalized_domain,
        "research_question": question,
    }
    return _reserve_candidate(
        identity=identity,
        taxon_name=normalized_taxon_name,
        ref_prefix="calyx-evidence-gap",
        fingerprint_material={
            "schema": _SCHEMA,
            "taxon_id": normalized_taxon_id,
            "domain": normalized_domain,
            "method": EVIDENCE_COVERAGE_METHOD,
        },
        priority=priority,
    )


def _reserve_candidate(
    *,
    identity: dict[str, Any],
    taxon_name: str,
    ref_prefix: str,
    fingerprint_material: dict[str, Any],
    priority: int,
) -> dict[str, Any]:
    fingerprint = _fingerprint(fingerprint_material)
    objective_key = fingerprint[:24]
    domain = identity["domain"]
    return {
        "source_kind": "objective",
        "queue_source_kind": "brain-knowledge-gap",
        "source_ref": f"{ref_prefix}:{objective_key}",
        "title": f"Research {domain.replace('_', ' ')} gap for {taxon_name}",
        "material_fingerprint": fingerprint,
        "semantic_key": f"{ref_prefix}:{identity['taxon_id']}:{domain}",
        "priority": max(0, min(5, int(priority))),
        "dependencies": [],
        "protected_boundaries": [],
        "source_payload": {
            **identity,
            "taxon_name": taxon_name,
            "execution_mode": "bounded_research_mission",
            "review_required": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
            "taxonomy_mutation": False,
            "sensitive_locality_disclosure": False,
        },
    }


def plan_knowledge_gap_refill(
    snapshot: dict[str, Any],
    gaps: Iterable[dict[str, Any]],
    *,
    taxon_id: str,
    taxon_name: str,
    reserve_depth: int = 2,
    planner_ok: bool = True,
) -> dict[str, Any]:
    """Create a bounded reserve plan from valid canonical knowledge gaps.

    Invalid or caller-altered gaps fail closed and are reported as source
    rejections. Valid gaps continue through the shared dependency, protected
    boundary, fingerprint, semantic-key, and reserve-depth gates.
    """

    candidates: list[dict[str, Any]] = []
    source_rejections: list[dict[str, Any]] = []

    for index, gap in enumerate(gaps):
        if not isinstance(gap, dict):
            source_rejections.append(
                {"gap_index": index, "reason": "invalid_gap_contract"}
            )
            continue
        try:
            candidates.append(
                knowledge_gap_candidate(
                    taxon_id=taxon_id,
                    taxon_name=taxon_name,
                    domain=str(gap.get("domain") or ""),
                    research_question=gap.get("research_question"),
                    priority=int(gap.get("priority", 1)),
                )
            )
        except (TypeError, ValueError) as exc:
            source_rejections.append(
                {
                    "gap_index": index,
                    "domain": str(gap.get("domain") or ""),
                    "reason": str(exc),
                }
            )

    result = plan_refill(
        snapshot,
        candidates,
        reserve_depth=reserve_depth,
        planner_ok=planner_ok,
    )
    result["source_schema"] = _SCHEMA
    result["source_candidate_count"] = len(candidates)
    result["source_rejections"] = source_rejections
    return result
