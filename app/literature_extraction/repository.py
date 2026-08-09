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

    def get_raw_bytes(self, paper_id: str) -> bytes | None:
        """Return the immutable-ingest bytes used for source hashing and offsets."""
        paper_dir = self._paper_dir(paper_id)
        if paper_dir is None:
            return None
        path = paper_dir / "raw.txt"
        if not path.is_file():
            return None
        return path.read_bytes()
