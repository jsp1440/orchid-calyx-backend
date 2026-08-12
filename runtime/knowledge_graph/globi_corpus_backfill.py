"""Read-only retrospective GloBI/RO screening of the existing literature corpus.

The scanner walks canonical literature-extraction bundles already present in the
Orchid Continuum, revalidates source integrity, resolves taxon entities exactly
against active Knowledge Graph taxa, applies the strict publication-eligible
paper projection, and emits only recognized GloBI/RO biotic-interaction edges.

It never mutates the Knowledge Graph and never submits data to GloBI.  Results are
contribution *candidates* requiring explicit human/governance review.  Novelty
against the live GloBI index is deliberately a separate step; absent a supplied
known-interaction set, candidates are marked ``not_checked_against_globi``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.source_binding import (
    FileLiteratureSourceBindingRepository,
    LiteratureSourceBindingError,
)

from .biotic_relation_ontology import GLOBI_RO_RELATIONS
from .exact_taxon_resolution import resolve_exact_taxon_keys_for_paper
from .publication_eligible_paper_graph import (
    build_publication_eligible_paper_graph_specs,
)

LITERATURE_SOURCE_OBJECT_TYPE = "LITERATURE_DOCUMENT"
DEFAULT_MAX_PAPERS = 250
MAX_PAPERS = 10_000


def _root(root: str | None) -> str:
    return root or os.getenv(
        "LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction"
    )


def _paper_ids(root: str, *, start_after: str | None, max_papers: int) -> list[str]:
    maximum = max(1, min(int(max_papers), MAX_PAPERS))
    base = Path(root)
    if not base.is_dir():
        return []
    ids = sorted(path.parent.name for path in base.glob("*/source-binding.json"))
    if start_after:
        ids = [paper_id for paper_id in ids if paper_id > start_after]
    return ids[:maximum]


def _entity_names(paper) -> dict[str, str]:
    return {
        entity.entity_id: str(entity.normalized_name or entity.name or "").strip()
        for entity in paper.entities
    }


def _claim_evidence(paper, claim_id: str) -> list[dict[str, Any]]:
    claim = next((item for item in paper.claims if item.claim_id == claim_id), None)
    if claim is None:
        return []
    wanted = set(claim.evidence_ids)
    rows: list[dict[str, Any]] = []
    for evidence in paper.evidence:
        if evidence.evidence_id not in wanted:
            continue
        span = evidence.span
        rows.append(
            {
                "evidence_id": evidence.evidence_id,
                "excerpt": evidence.excerpt,
                "evidence_type": evidence.evidence_type,
                "page_start": span.page_start,
                "page_end": span.page_end,
                "section_id": span.section_id,
                "char_start": span.char_start,
                "char_end": span.char_end,
            }
        )
    return rows


def _interaction_identity(candidate: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(candidate["source_taxon_name"]).casefold(),
        str(candidate["interaction_type"]),
        str(candidate["target_taxon_name"]).casefold(),
    )


def scan_existing_literature_for_globi_candidates(
    dsn: str,
    *,
    root: str | None = None,
    start_after: str | None = None,
    max_papers: int = DEFAULT_MAX_PAPERS,
    known_globi_interactions: Iterable[tuple[str, str, str]] | None = None,
) -> dict[str, Any]:
    """Screen existing extraction bundles for reviewed GloBI/RO interactions.

    ``known_globi_interactions`` may be supplied from a separately versioned GloBI
    snapshot.  Its identity is ``(sourceTaxonName, interactionTypeName,
    targetTaxonName)``.  Without that snapshot we do not claim novelty.
    """
    if not str(dsn or "").strip():
        raise ValueError("DATABASE_URL_REQUIRED")
    resolved_root = _root(root)
    paper_ids = _paper_ids(
        resolved_root, start_after=start_after, max_papers=max_papers
    )
    papers = LiteratureResultRepository(resolved_root)
    bindings = FileLiteratureSourceBindingRepository(resolved_root)
    known = {
        (str(a).casefold(), str(b), str(c).casefold())
        for a, b, c in (known_globi_interactions or ())
    }
    novelty_checked = known_globi_interactions is not None

    candidates: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    papers_with_interactions = 0

    for paper_id in paper_ids:
        try:
            binding = bindings.get(paper_id)
        except (OSError, ValueError, TypeError) as exc:
            failures.append({"paper_id": paper_id, "status": "binding_unreadable", "error": exc.__class__.__name__})
            continue
        if binding is None:
            continue
        if binding.source_object_type.casefold() != LITERATURE_SOURCE_OBJECT_TYPE.casefold():
            continue
        paper = papers.get(paper_id)
        raw_bytes = papers.get_raw_bytes(paper_id)
        if paper is None or raw_bytes is None:
            failures.append({"paper_id": paper_id, "status": "extraction_bundle_incomplete"})
            continue
        try:
            binding.validate_integrity(paper, raw_bytes)
        except LiteratureSourceBindingError as exc:
            failures.append({"paper_id": paper_id, "status": "source_integrity_failed", "error": exc.code})
            continue

        resolution = resolve_exact_taxon_keys_for_paper(dsn, paper)
        bundle = build_publication_eligible_paper_graph_specs(
            paper,
            taxon_keys_by_entity_id=resolution.keys_by_entity_id,
        )
        entity_names = _entity_names(paper)
        paper_candidates = 0

        for edge in bundle.edges:
            if edge.edge_type not in GLOBI_RO_RELATIONS:
                continue
            payload = dict(edge.payload or {})
            source_entity_id = str(payload.get("subject_entity_id") or "")
            target_entity_id = str(payload.get("object_entity_id") or "")
            source_name = entity_names.get(source_entity_id, "")
            target_name = entity_names.get(target_entity_id, "")
            if not source_name or not target_name:
                continue
            claim_id = str(payload.get("source_claim_id") or "")
            claim = next((item for item in paper.claims if item.claim_id == claim_id), None)
            doi = next(
                (
                    identifier.value
                    for identifier in paper.metadata.identifiers
                    if identifier.scheme == "doi"
                ),
                None,
            )
            candidate = {
                "candidate_status": "candidate_for_globi_review",
                "novelty_status": "not_checked_against_globi",
                "source_taxon_name": source_name,
                "source_taxon_key": edge.from_key,
                "interaction_type": edge.edge_type,
                "interaction_type_ro_uri": payload.get("ro_uri"),
                "target_taxon_name": target_name,
                "target_taxon_key": edge.to_key,
                "verbatim_predicate": payload.get("verbatim_predicate"),
                "paper_id": paper.paper_id,
                "literature_document_id": binding.source_object_id,
                "title": paper.metadata.title,
                "doi": doi,
                "claim_id": claim_id,
                "claim_statement": (claim.statement if claim is not None else None),
                "evidence": _claim_evidence(paper, claim_id),
                "publication_eligible_record_ids": list(
                    payload.get("publication_eligible_record_ids") or []
                ),
                "binding_fingerprint": binding.fingerprint,
                "source_hash": paper.source.content_hash,
                "confidence": edge.confidence_score,
                "provenance_rule": edge.rule_name,
            }
            if novelty_checked:
                candidate["novelty_status"] = (
                    "already_present_in_supplied_globi_snapshot"
                    if _interaction_identity(candidate) in known
                    else "candidate_new_to_supplied_globi_snapshot"
                )
            candidates.append(candidate)
            paper_candidates += 1

        if paper_candidates:
            papers_with_interactions += 1

    next_cursor = paper_ids[-1] if len(paper_ids) == min(max(1, int(max_papers)), MAX_PAPERS) else None
    counts_by_relation: dict[str, int] = {}
    counts_by_novelty: dict[str, int] = {}
    for item in candidates:
        relation = str(item["interaction_type"])
        novelty = str(item["novelty_status"])
        counts_by_relation[relation] = counts_by_relation.get(relation, 0) + 1
        counts_by_novelty[novelty] = counts_by_novelty.get(novelty, 0) + 1

    return {
        "contract": "calyx-globi-ro-literature-backfill-v1",
        "read_only": True,
        "knowledge_graph_mutation": False,
        "external_submission": False,
        "novelty_checked_against_globi": novelty_checked,
        "papers_scanned": len(paper_ids),
        "papers_with_interactions": papers_with_interactions,
        "candidate_count": len(candidates),
        "failure_count": len(failures),
        "counts_by_relation": counts_by_relation,
        "counts_by_novelty": counts_by_novelty,
        "next_start_after": next_cursor,
        "candidates": candidates,
        "failures": failures,
    }


def globi_tsv_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return GloBI-template-friendly rows from reviewed contribution candidates.

    These rows are an export staging format, not a submission.  They intentionally
    preserve the original reference and evidence identifiers so a future public
    dataset can remain attributable and auditable.
    """
    rows: list[dict[str, Any]] = []
    for item in report.get("candidates") or []:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "sourceTaxonName": item.get("source_taxon_name"),
                "interactionTypeName": item.get("interaction_type"),
                "interactionTypeId": item.get("interaction_type_ro_uri"),
                "targetTaxonName": item.get("target_taxon_name"),
                "referenceDoi": item.get("doi"),
                "referenceCitation": item.get("title"),
                "referenceUrl": None,
                "sourceId": (
                    f"orchid-continuum:{item.get('paper_id')}:"
                    f"{item.get('claim_id')}"
                ),
                "sourceCitation": "Orchid Continuum literature-derived interaction",
                "notes": item.get("claim_statement"),
            }
        )
    return rows
