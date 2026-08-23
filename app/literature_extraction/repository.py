from __future__ import annotations

import json
from pathlib import Path

from .ingest import IngestedDocument
from .models import PaperKnowledge
from .output import OutputBundle, write_output_bundle


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

    def list_summaries(self, *, limit: int = 50, offset: int = 0) -> tuple[list[dict], int]:
        """Bounded, identity-only summaries of the stored extraction results.

        Discovery was the missing half of this module: papers could be fetched
        by id and there was no way to learn which ids exist, so the frontend
        could not build an index without inventing one.

        Summaries carry bibliographic identity and counts, never bodies. That
        is a deliberate boundary rather than an optimisation: section text,
        claims and evidence carry their own display policies, and a list
        endpoint is the wrong place to adjudicate those. A caller who wants
        content asks for the paper.

        Returns the page and the total, so a caller can tell "no more results"
        from "no results".
        """
        if not self.root.is_dir():
            # An absent store is not an empty corpus. The caller sees zero with
            # a zero total and can distinguish that from a page past the end.
            return [], 0

        # Sorted so paging is stable across calls; a directory listing is not.
        paper_dirs = sorted(
            (entry for entry in self.root.iterdir() if entry.is_dir()),
            key=lambda entry: entry.name,
        )
        total = len(paper_dirs)

        bounded_limit = max(1, min(int(limit), 200))
        start = max(0, int(offset))
        summaries: list[dict] = []

        for entry in paper_dirs[start : start + bounded_limit]:
            path = entry / "paper.json"
            if not path.is_file():
                # A directory without a paper.json is an incomplete write, not
                # a paper. Skipping it silently would hide that, so it is
                # reported as unreadable rather than omitted.
                summaries.append(
                    {
                        "paper_id": entry.name,
                        "readable": False,
                        "reason": "PAPER_RECORD_MISSING",
                    }
                )
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                summaries.append(
                    {
                        "paper_id": entry.name,
                        "readable": False,
                        "reason": "PAPER_RECORD_UNREADABLE",
                    }
                )
                continue

            metadata = record.get("metadata") or {}
            summaries.append(
                {
                    "paper_id": record.get("paper_id") or entry.name,
                    "readable": True,
                    "title": metadata.get("title"),
                    "authors": list(metadata.get("authors") or [])[:10],
                    "journal": metadata.get("journal"),
                    "publication_year": metadata.get("publication_year"),
                    # Counts, not contents: enough to tell a rich extraction
                    # from an empty one without releasing either.
                    "claim_count": len(record.get("claims") or []),
                    "evidence_count": len(record.get("evidence") or []),
                    "review_decision_count": len(record.get("review_decisions") or []),
                }
            )

        return summaries, total

    def get_raw_bytes(self, paper_id: str) -> bytes | None:
        """Return the immutable-ingest bytes used for source hashing and offsets."""
        paper_dir = self._paper_dir(paper_id)
        if paper_dir is None:
            return None
        path = paper_dir / "raw.txt"
        if not path.is_file():
            return None
        return path.read_bytes()
