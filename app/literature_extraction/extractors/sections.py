from __future__ import annotations

import re
from dataclasses import dataclass
from typing import ClassVar

from ..context import PipelineContext
from ..ingest import read_text_exact
from ..models import PaperKnowledge, Section, SourceSpan
from .base import Extractor


@dataclass(frozen=True, slots=True)
class HeadingMatch:
    heading: str
    canonical_type: str
    start: int
    end: int


class SectionExtractor(Extractor):
    name = "sections"
    version = "0.1.0"

    _heading_pattern = re.compile(
        r"(?im)^(?P<heading>abstract|introduction|background|materials and methods|methods|methodology|results|discussion|conclusion|conclusions|acknowledg(?:e)?ments|references|bibliography|supplementary information|supplement)\s*$"
    )

    _canonical: ClassVar[dict[str, str]] = {
        "abstract": "abstract",
        "introduction": "introduction",
        "background": "introduction",
        "materials and methods": "methods",
        "methods": "methods",
        "methodology": "methods",
        "results": "results",
        "discussion": "discussion",
        "conclusion": "conclusion",
        "conclusions": "conclusion",
        "acknowledgements": "acknowledgements",
        "acknowledgments": "acknowledgements",
        "references": "references",
        "bibliography": "references",
        "supplementary information": "supplement",
        "supplement": "supplement",
    }

    async def run(
        self,
        context: PipelineContext,
        paper: PaperKnowledge,
    ) -> PaperKnowledge:
        text = read_text_exact(context.source_path)
        matches = [
            HeadingMatch(
                heading=match.group("heading").strip(),
                canonical_type=self._canonical[match.group("heading").strip().lower()],
                start=match.start(),
                end=match.end(),
            )
            for match in self._heading_pattern.finditer(text)
        ]

        sections: list[Section] = []
        for index, match in enumerate(matches):
            body_start = match.end
            body_end = (
                matches[index + 1].start if index + 1 < len(matches) else len(text)
            )
            body = text[body_start:body_end].strip()
            sections.append(
                Section(
                    section_id=f"section-{index + 1}",
                    heading=match.heading,
                    canonical_type=match.canonical_type,
                    text=body,
                    order=index,
                    span=SourceSpan(
                        section_id=f"section-{index + 1}",
                        char_start=match.start,
                        char_end=body_end,
                    ),
                )
            )

        paper.sections = sections
        return paper

    def output_count(self, paper: PaperKnowledge) -> int:
        return len(paper.sections)
