from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ingest import IngestedDocument
from .models import PaperKnowledge
from .output import OutputBundle, write_output_bundle


@dataclass(frozen=True, slots=True)
class PaperSummary:
    """One row of the corpus index.

    A row is either readable, carrying identity and counts, or unreadable,
    carrying the reason. An unreadable extraction is still a paper the
    Continuum holds; dropping it would report a smaller corpus than exists
    and hide the damage instead of surfacing it for repair.
    """

    paper_id: str
    readable: bool
    reason: str | None = None
    title: str | None = None
    authors: tuple[str, ...] = ()
    journal: str | None = None
    publication_year: int | None = None
    claim_count: int = 0
    evidence_count: int = 0
    review_decision_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        if not self.readable:
            return {
                "paper_id": self.paper_id,
                "readable": False,
                "reason": self.reason,
            }
        return {
            "paper_id": self.paper_id,
            "readable": True,
            "title": self.title,
            "authors": list(self.authors),
            "journal": self.journal,
            "publication_year": self.publication_year,
            "claim_count": self.claim_count,
            "evidence_count": self.evidence_count,
            "review_decision_count": self.review_decision_count,
        }


class LiteratureResultRepository:
    """Durable adapter over the established, inspectable output-bundle format."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)

    def _paper_dir(self, paper_id: str) -> Path | None:
        if not paper_id or Path(paper_id).name != paper_id:
            return None
        return self.root / paper_id

    def save(self, paper: PaperKnowledge, document: IngestedDocument) -> OutputBundle:
        return write_output_bundle(paper, document, self.root / paper.paper_id)

    def get(self, paper_id: str) -> PaperKnowledge | None:
        paper_dir = self._paper_dir(paper_id)
        if paper_dir is None:
            return None
        path = paper_dir / "paper.json"
        if not path.is_file():
            return None
        return PaperKnowledge.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def list_paper_ids(self) -> list[str]:
        """Every paper id in the corpus, in a stable order.

        Sorted so that paging is deterministic: an unordered listing would let
        the same offset return different rows between requests and silently
        skip papers as a reader pages through.
        """
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and (entry / "paper.json").is_file()
        )

    def count(self) -> int:
        """Size of the whole corpus, independent of any page."""
        return len(self.list_paper_ids())

    def summarize(self, paper_id: str) -> PaperSummary:
        """Summarize one paper, reporting damage rather than hiding it."""
        try:
            paper = self.get(paper_id)
        except Exception as exc:  # noqa: BLE001 - any fault is "unreadable"
            return PaperSummary(
                paper_id=paper_id,
                readable=False,
                reason=f"{type(exc).__name__}",
            )
        if paper is None:
            return PaperSummary(
                paper_id=paper_id, readable=False, reason="EXTRACTION_NOT_FOUND"
            )
        return PaperSummary(
            paper_id=paper.paper_id,
            readable=True,
            title=paper.metadata.title,
            authors=tuple(paper.metadata.authors),
            journal=paper.metadata.journal,
            publication_year=paper.metadata.publication_year,
            claim_count=len(paper.claims),
            evidence_count=len(paper.evidence),
            review_decision_count=len(paper.review_decisions),
        )

    def list_summaries(
        self, *, limit: int, offset: int
    ) -> tuple[list[PaperSummary], int]:
        """One page of summaries, plus the size of the whole corpus.

        The total is returned alongside every page so a caller can tell "no
        more results" from "no results" -- the frontend renders those very
        differently, and conflating them would report an empty corpus.
        """
        ids = self.list_paper_ids()
        page = ids[offset : offset + limit]
        return [self.summarize(paper_id) for paper_id in page], len(ids)

    def get_raw_bytes(self, paper_id: str) -> bytes | None:
        """Return the immutable-ingest bytes used for source hashing and offsets."""
        paper_dir = self._paper_dir(paper_id)
        if paper_dir is None:
            return None
        path = paper_dir / "raw.txt"
        if not path.is_file():
            return None
        return path.read_bytes()
