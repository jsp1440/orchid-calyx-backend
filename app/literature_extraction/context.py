from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class PipelineConfig:
    pipeline_version: str = "0.2.0"
    analysis_version: int = 1
    extractor_settings: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PipelineContext:
    source_path: Path
    output_dir: Path
    config: PipelineConfig = field(default_factory=PipelineConfig)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.source_path.exists():
            raise FileNotFoundError(self.source_path)
        if not self.source_path.is_file():
            raise ValueError(f"source_path must be a file: {self.source_path}")
