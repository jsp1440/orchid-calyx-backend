from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict


class RuntimeMemoryWriter:
    """Temporary local memory writer.

    Production should write to approved Engineering Memory tables.
    """

    def __init__(self, path: str = "calyx_runtime_journal.jsonl") -> None:
        self.path = Path(path)

    def write_event(self, event: Dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, default=str) + "\n")
