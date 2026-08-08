from __future__ import annotations

import hashlib
import re
from typing import ClassVar

from ..context import PipelineContext
from ..ingest import read_text_exact
from ..models import GlossaryTerm, PaperKnowledge, Provenance, SourceSpan
from .base import Extractor


class GlossaryExtractor(Extractor):
    """Extract conservative glossary candidates without canonical promotion.

    This stage is intentionally deterministic. It creates reviewable vocabulary
    candidates from supported scientific entity types, publication keywords,
    and a small orchid-morphology seed lexicon. Resolution to the canonical
    Concept Registry happens downstream and is never guessed here.
    """

    name = "glossary"
    version = "0.1.0"

    _entity_types: ClassVar[set[str]] = {
        "anatomical_structure",
        "trait",
        "method",
        "chemical",
        "environmental_factor",
        "habitat",
    }

    _seed_patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("velamen", re.compile(r"\bvelamen\b", re.IGNORECASE)),
        ("pollinium", re.compile(r"\bpollini(?:um|a)\b", re.IGNORECASE)),
        ("rostellum", re.compile(r"\brostellum\b", re.IGNORECASE)),
        ("labellum", re.compile(r"\b(?:labellum|labella)\b", re.IGNORECASE)),
        ("pseudobulb", re.compile(r"\bpseudobulbs?\b", re.IGNORECASE)),
        ("gynostemium", re.compile(r"\bgynostemium\b", re.IGNORECASE)),
        ("sepal", re.compile(r"\bsepals?\b", re.IGNORECASE)),
        ("petal", re.compile(r"\bpetals?\b", re.IGNORECASE)),
    )

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(value.casefold().strip().split())

    @classmethod
    def _term_id(cls, paper: PaperKnowledge, normalized: str) -> str:
        payload = f"{paper.source.content_hash}\x1f{normalized}\x1f{cls.version}"
        return f"glossary-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:20]}"

    async def run(
        self,
        context: PipelineContext,
        paper: PaperKnowledge,
    ) -> PaperKnowledge:
        text = read_text_exact(context.source_path)
        candidates: dict[str, dict[str, object]] = {}

        def add_candidate(
            surface: str,
            *,
            mentions: list[SourceSpan] | None = None,
            confidence: float = 0.85,
        ) -> None:
            normalized = self._normalize(surface)
            if not normalized:
                return
            current = candidates.setdefault(
                normalized,
                {
                    "term": surface.strip(),
                    "mentions": [],
                    "confidence": confidence,
                },
            )
            current["confidence"] = max(float(current["confidence"]), confidence)
            if mentions:
                existing = {
                    (span.char_start, span.char_end, span.section_id)
                    for span in current["mentions"]  # type: ignore[index]
                }
                for span in mentions:
                    key = (span.char_start, span.char_end, span.section_id)
                    if key not in existing:
                        current["mentions"].append(span)  # type: ignore[index]
                        existing.add(key)

        for entity in paper.entities:
            if entity.entity_type in self._entity_types:
                add_candidate(
                    entity.name,
                    mentions=list(entity.mentions),
                    confidence=entity.provenance.confidence,
                )

        for keyword in paper.metadata.keywords:
            value = keyword.strip()
            if 2 <= len(value) <= 120 and any(char.isalpha() for char in value):
                add_candidate(value, confidence=0.7)

        for canonical_term, pattern in self._seed_patterns:
            spans = [
                SourceSpan(char_start=match.start(), char_end=match.end())
                for match in pattern.finditer(text)
            ]
            if spans:
                add_candidate(canonical_term, mentions=spans, confidence=1.0)

        glossary_terms: list[GlossaryTerm] = []
        for normalized in sorted(candidates):
            item = candidates[normalized]
            mentions = sorted(
                item["mentions"],  # type: ignore[arg-type]
                key=lambda span: (
                    span.char_start if span.char_start is not None else -1,
                    span.char_end if span.char_end is not None else -1,
                    span.section_id or "",
                ),
            )
            glossary_terms.append(
                GlossaryTerm(
                    term_id=self._term_id(paper, normalized),
                    term=str(item["term"]),
                    normalized_term=normalized,
                    status="candidate",
                    mentions=mentions,
                    provenance=Provenance(
                        method="rule_extracted",
                        confidence=float(item["confidence"]),
                        extractor=self.name,
                        extractor_version=self.version,
                    ),
                )
            )

        paper.glossary_terms = glossary_terms
        return paper

    def output_count(self, paper: PaperKnowledge) -> int:
        return len(paper.glossary_terms)
