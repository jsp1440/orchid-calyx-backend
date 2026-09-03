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
        if not self.root.is_dir():
            return [], 0
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
                summaries.append(
                    {"paper_id": entry.name, "readable": False, "reason": "PAPER_RECORD_MISSING"}
                )
                continue
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                summaries.append(
                    {"paper_id": entry.name, "readable": False, "reason": "PAPER_RECORD_UNREADABLE"}
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
                    "claim_count": len(record.get("claims") or []),
                    "evidence_count": len(record.get("evidence") or []),
                    "review_decision_count": len(record.get("review_decisions") or []),
                }
            )
        return summaries, total

    def get_raw_bytes(self, paper_id: str) -> bytes | None:
        paper_dir = self._paper_dir(paper_id)
        if paper_dir is None:
            return None
        path = paper_dir / "raw.txt"
        if not path.is_file():
            return None
        return path.read_bytes()

    def root_available(self) -> bool:
        return self.root.is_dir()

    def list_paper_ids(self) -> list[str]:
        if not self.root.is_dir():
            return []
        return sorted(
            entry.name
            for entry in self.root.iterdir()
            if entry.is_dir() and (entry / "paper.json").is_file()
        )
