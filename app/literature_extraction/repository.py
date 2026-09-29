from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ingest import IngestedDocument
from .models import PaperKnowledge
from .output import OutputBundle, write_output_bundle


class PaperSummary(dict):
    """One row of the corpus index.

    A row is either readable, carrying identity and counts, or unreadable,
    carrying the reason. An unreadable extraction is still a paper the
    Continuum holds; dropping it would report a smaller corpus than exists
    and hide the damage instead of surfacing it for repair.

    The row is a mapping (so it serializes and compares as one) that also
    reads as a record (``summary.title``). Only the keys ``as_dict`` documents
    are ever present: an unreadable row carries identity and reason alone.
    """

    _FIELDS = (
        "paper_id",
        "readable",
        "reason",
        "title",
        "authors",
        "journal",
        "publication_year",
        "claim_count",
        "evidence_count",
        "review_decision_count",
    )

    def __init__(
        self,
        *,
        paper_id: str,
        readable: bool,
        reason: str | None = None,
        title: str | None = None,
        authors: tuple[str, ...] | list[str] = (),
        journal: str | None = None,
        publication_year: int | None = None,
        claim_count: int = 0,
        evidence_count: int = 0,
        review_decision_count: int = 0,
    ) -> None:
        if not readable:
            super().__init__(paper_id=paper_id, readable=False, reason=reason)
            return
        super().__init__(
            paper_id=paper_id,
            readable=True,
            title=title,
            authors=tuple(authors)[:10],
            journal=journal,
            publication_year=publication_year,
            claim_count=claim_count,
            evidence_count=evidence_count,
            review_decision_count=review_decision_count,
        )

    def __getattr__(self, name: str) -> Any:
        if name in self._FIELDS:
            try:
                return self[name]
            except KeyError:
                return None
        raise AttributeError(name)

    def as_dict(self) -> dict[str, Any]:
        payload = dict(self)
        if payload.get("readable"):
            payload["authors"] = list(payload.get("authors") or ())
        return payload


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

    def _entries(self) -> list[Path]:
        """Every paper directory, including ones whose record is missing.

        A directory without ``paper.json`` is an incomplete write; it is
        reported as an unreadable row rather than skipped, so ``total`` never
        understates what the store holds.
        """
        if not self.root.is_dir():
            return []
        return sorted(
            (entry for entry in self.root.iterdir() if entry.is_dir()),
            key=lambda entry: entry.name,
        )

    def count(self) -> int:
        """Size of the whole corpus, independent of any page."""
        return len(self._entries())

    def root_available(self) -> bool:
        return self.root.is_dir()

    def summarize(self, paper_id: str) -> PaperSummary:
        """Summarize one paper, reporting damage rather than hiding it."""
        directory = self.root / paper_id
        if not directory.is_dir():
            return PaperSummary(
                paper_id=paper_id, readable=False, reason="EXTRACTION_NOT_FOUND"
            )
        path = directory / "paper.json"
        if not path.is_file():
            return PaperSummary(
                paper_id=paper_id, readable=False, reason="PAPER_RECORD_MISSING"
            )
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return PaperSummary(
                paper_id=paper_id, readable=False, reason="PAPER_RECORD_UNREADABLE"
            )
        if not isinstance(record, dict):
            return PaperSummary(
                paper_id=paper_id, readable=False, reason="PAPER_RECORD_UNREADABLE"
            )
        metadata = record.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        return PaperSummary(
            paper_id=str(record.get("paper_id") or paper_id),
            readable=True,
            title=metadata.get("title"),
            authors=tuple(str(author) for author in (metadata.get("authors") or [])),
            journal=metadata.get("journal"),
            publication_year=metadata.get("publication_year"),
            claim_count=len(record.get("claims") or []),
            evidence_count=len(record.get("evidence") or []),
            review_decision_count=len(record.get("review_decisions") or []),
        )

    def list_summaries(
        self, *, limit: int = 50, offset: int = 0
    ) -> tuple[list[PaperSummary], int]:
        """One page of summaries, plus the size of the whole corpus.

        The total is returned alongside every page so a caller can tell "no
        more results" from "no results" -- the frontend renders those very
        differently, and conflating them would report an empty corpus.
        The page is bounded to 200 rows and the offset to zero or more.
        """
        entries = self._entries()
        bounded_limit = max(1, min(int(limit), 200))
        start = max(0, int(offset))
        page = entries[start : start + bounded_limit]
        return [self.summarize(entry.name) for entry in page], len(entries)

    def get_raw_bytes(self, paper_id: str) -> bytes | None:
        """Return the immutable-ingest bytes used for source hashing and offsets."""
        paper_dir = self._paper_dir(paper_id)
        if paper_dir is None:
            return None
        path = paper_dir / "raw.txt"
        if not path.is_file():
            return None
        return path.read_bytes()
