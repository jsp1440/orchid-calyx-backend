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

    def save(self, paper: PaperKnowledge, document: IngestedDocument) -> OutputBundle:
        return write_output_bundle(paper, document, self.root / paper.paper_id)

    def get(self, paper_id: str) -> PaperKnowledge | None:
        if not paper_id or Path(paper_id).name != paper_id:
            return None
        path = self.root / paper_id / "paper.json"
        if not path.is_file():
            return None
        return PaperKnowledge.model_validate(
            json.loads(path.read_text(encoding="utf-8"))
        )
