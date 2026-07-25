from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone

from ..context import PipelineContext
from ..models import ExtractorRun, PaperKnowledge


class Extractor(ABC):
    name: str
    version: str = "0.1.0"

    @abstractmethod
    async def run(
        self,
        context: PipelineContext,
        paper: PaperKnowledge,
    ) -> PaperKnowledge:
        """Return a new or enriched PaperKnowledge object."""

    async def execute(
        self,
        context: PipelineContext,
        paper: PaperKnowledge,
    ) -> tuple[PaperKnowledge, ExtractorRun]:
        started_at = datetime.now(timezone.utc)
        try:
            result = await self.run(context, paper)
        except Exception as exc:
            completed_at = datetime.now(timezone.utc)
            return paper, ExtractorRun(
                name=self.name,
                version=self.version,
                status="failed",
                started_at=started_at,
                completed_at=completed_at,
                error=str(exc),
                output_count=0,
            )

        completed_at = datetime.now(timezone.utc)
        return result, ExtractorRun(
            name=self.name,
            version=self.version,
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            output_count=self.output_count(result),
        )

    def output_count(self, paper: PaperKnowledge) -> int:
        return 0
