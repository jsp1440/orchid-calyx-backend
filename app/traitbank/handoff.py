"""Handoff from the literature-extraction pipeline into TraitBank.

The extraction pipeline persists one ``paper.json`` per paper through
``app.literature_extraction.repository.LiteratureResultRepository``; this
module reads that same repository (it does not walk the directory itself) and
sends each paper through the TraitBank adapter and ``TraitBankRepository.ingest``.

Bounded and resumable: papers are processed in the repository's stable order,
at most ``limit`` per call, starting after ``after_paper_id``. Each paper is its
own batch with a content-derived ``batch_key``, so re-running is idempotent
and one refused paper never blocks the rest. Dry-run is the default.

Nothing here schedules itself. A recurring run would be added to the existing
harvester/orchestrator scheduling under its own owner-approved change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.literature_extraction.models import PaperKnowledge
from app.literature_extraction.repository import LiteratureResultRepository

from .adapters import TraitIndex, from_paper_knowledge
from .repository import TraitBankRefused, TraitBankRepository

MAX_PAPERS_PER_RUN = 200


def ingest_paper(
    repo: TraitBankRepository,
    paper: PaperKnowledge,
    *,
    ingested_by: str,
    apply: bool = False,
    traits: TraitIndex | None = None,
) -> dict[str, Any]:
    traits = traits or TraitIndex(repo.definitions())
    normalized = from_paper_knowledge(paper, traits, repo.resolve_species)
    result: dict[str, Any] = {
        "paper_id": paper.paper_id,
        "unmapped": normalized.unmapped,
    }
    if normalized.batch is None:
        return {**result, "state": "NOTHING_TO_INGEST"}
    try:
        report = repo.ingest(
            normalized.batch,
            ingested_by=ingested_by,
            live=True,
            dry_run=not apply,
            crosswalk=normalized.crosswalk,
        )
    except TraitBankRefused as refused:
        return {**result, "state": "REFUSED", "violations": refused.violations}
    return {**result, **report}


def ingest_literature_root(
    repo: TraitBankRepository,
    root: str | Path,
    *,
    ingested_by: str,
    apply: bool = False,
    limit: int = 50,
    after_paper_id: str | None = None,
) -> dict[str, Any]:
    if not 1 <= limit <= MAX_PAPERS_PER_RUN:
        raise ValueError(f"limit must be between 1 and {MAX_PAPERS_PER_RUN}")
    literature = LiteratureResultRepository(root)
    ids = literature.list_paper_ids()
    if after_paper_id is not None:
        ids = [i for i in ids if i > after_paper_id]
    selected = ids[:limit]
    traits = TraitIndex(repo.definitions())
    papers = []
    for paper_id in selected:
        try:
            paper = literature.get(paper_id)
        except ValueError:  # malformed paper.json (pydantic ValidationError)
            papers.append({"paper_id": paper_id, "state": "PAPER_INVALID"})
            continue
        if paper is None:  # incomplete write; reported, never guessed
            papers.append({"paper_id": paper_id, "state": "PAPER_UNREADABLE"})
            continue
        papers.append(
            ingest_paper(
                repo, paper, ingested_by=ingested_by, apply=apply, traits=traits
            )
        )
    states: dict[str, int] = {}
    for item in papers:
        states[item["state"]] = states.get(item["state"], 0) + 1
    return {
        "root_available": literature.root_available(),
        "dry_run": not apply,
        "processed": len(selected),
        "remaining": max(len(ids) - len(selected), 0),
        "resume_after_paper_id": selected[-1] if selected else after_paper_id,
        "states": states,
        "papers": papers,
    }
