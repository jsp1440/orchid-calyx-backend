from __future__ import annotations

import re
from dataclasses import dataclass

from ..context import PipelineContext
from ..ingest import read_text_exact
from ..models import Entity, PaperKnowledge, Provenance, SourceSpan
from .base import Extractor


@dataclass(frozen=True, slots=True)
class EntityRule:
    entity_type: str
    pattern: re.Pattern[str]


class EntityExtractor(Extractor):
    """Deterministically extract a conservative set of scientific entities."""

    name = "entities"
    version = "0.1.0"

    _rules = (
        EntityRule(
            entity_type="chemical",
            pattern=re.compile(
                r"\b(?:ATP|ADP|DNA|RNA|glucose|ethanol|methanol|acetone|"
                r"sodium chloride|NaCl|calcium|magnesium|potassium)\b",
                re.IGNORECASE,
            ),
        ),
        EntityRule(
            entity_type="method",
            pattern=re.compile(
                r"\b(?:PCR|qPCR|western blot|RNA sequencing|RNA-seq|"
                r"mass spectrometry|flow cytometry|ELISA|microscopy)\b",
                re.IGNORECASE,
            ),
        ),
        EntityRule(
            entity_type="taxon",
            pattern=re.compile(
                r"\b(?:Homo sapiens|Mus musculus|Arabidopsis thaliana|"
                r"Escherichia coli|Saccharomyces cerevisiae)\b",
                re.IGNORECASE,
            ),
        ),
    )

    async def run(
        self,
        context: PipelineContext,
        paper: PaperKnowledge,
    ) -> PaperKnowledge:
        text = read_text_exact(context.source_path)
        matches: list[tuple[int, int, str, str]] = []

        for rule in self._rules:
            for match in rule.pattern.finditer(text):
                matches.append(
                    (match.start(), match.end(), rule.entity_type, match.group(0))
                )

        matches.sort(key=lambda item: (item[0], item[1], item[2], item[3].casefold()))

        grouped: dict[tuple[str, str], list[SourceSpan]] = {}
        surface_forms: dict[tuple[str, str], str] = {}
        for start, end, entity_type, surface in matches:
            key = (entity_type, surface.casefold())
            grouped.setdefault(key, []).append(
                SourceSpan(char_start=start, char_end=end)
            )
            surface_forms.setdefault(key, surface)

        entities: list[Entity] = []
        for index, key in enumerate(
            sorted(grouped, key=lambda item: (item[0], item[1]))
        ):
            entity_type, normalized = key
            entities.append(
                Entity(
                    entity_id=f"entity-{index + 1}",
                    entity_type=entity_type,
                    name=surface_forms[key],
                    normalized_name=normalized,
                    mentions=grouped[key],
                    provenance=Provenance(
                        method="rule_extracted",
                        confidence=1.0,
                        extractor=self.name,
                        extractor_version=self.version,
                    ),
                )
            )

        paper.entities = entities
        return paper

    def output_count(self, paper: PaperKnowledge) -> int:
        return len(paper.entities)
