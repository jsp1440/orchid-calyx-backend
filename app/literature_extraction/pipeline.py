from __future__ import annotations

from collections.abc import Iterable

from .context import PipelineContext
from .extractors.base import Extractor
from .models import PaperKnowledge


class PipelineRunner:
    """Execute literature extractors in a deterministic order."""

    def __init__(self, extractors: Iterable[Extractor]) -> None:
        self._extractors = tuple(extractors)

    async def run(
        self,
        context: PipelineContext,
        paper: PaperKnowledge,
    ) -> PaperKnowledge:
        current = paper
        for extractor in self._extractors:
            current = await extractor.execute(context, current)
        return current
