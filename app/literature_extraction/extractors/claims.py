from __future__ import annotations

import re
from typing import ClassVar

from ..context import PipelineContext
from ..ingest import read_text_exact
from ..models import Claim, Evidence, PaperKnowledge, Provenance, SourceSpan
from .base import Extractor


class ClaimExtractor(Extractor):
    """Extract sentence-level claims with directly linked textual evidence."""

    name = "claims"
    version = "0.1.0"

    _claim_types: ClassVar[dict[str, str]] = {
        "results": "result",
        "discussion": "interpretation",
        "conclusion": "interpretation",
    }
    _sentence_pattern = re.compile(r"[^.!?\n]+(?:[.!?]+|$)")

    async def run(
        self,
        context: PipelineContext,
        paper: PaperKnowledge,
    ) -> PaperKnowledge:
        text = read_text_exact(context.source_path)
        claims: list[Claim] = []
        evidence_items: list[Evidence] = []

        for section in paper.sections:
            claim_type = self._claim_types.get(section.canonical_type)
            if claim_type is None:
                continue
            if section.span.char_start is None or section.span.char_end is None:
                continue

            section_source = text[section.span.char_start : section.span.char_end]
            heading_offset = section_source.find("\n")
            body_offset = heading_offset + 1 if heading_offset >= 0 else 0
            body_source = section_source[body_offset:]

            for sentence_match in self._sentence_pattern.finditer(body_source):
                raw_sentence = sentence_match.group(0)
                statement = raw_sentence.strip()
                if not statement:
                    continue

                leading = len(raw_sentence) - len(raw_sentence.lstrip())
                trailing = len(raw_sentence.rstrip())
                char_start = (
                    section.span.char_start
                    + body_offset
                    + sentence_match.start()
                    + leading
                )
                char_end = (
                    section.span.char_start
                    + body_offset
                    + sentence_match.start()
                    + trailing
                )

                evidence_id = f"evidence-{len(evidence_items) + 1}"
                claim_id = f"claim-{len(claims) + 1}"
                evidence_items.append(
                    Evidence(
                        evidence_id=evidence_id,
                        excerpt=statement,
                        span=SourceSpan(
                            section_id=section.section_id,
                            char_start=char_start,
                            char_end=char_end,
                        ),
                        evidence_type="text",
                        supports_ids=[claim_id],
                    )
                )
                claims.append(
                    Claim(
                        claim_id=claim_id,
                        statement=statement,
                        claim_type=claim_type,
                        subject_ids=sorted(
                            entity.entity_id
                            for entity in paper.entities
                            if any(
                                mention.char_start is not None
                                and mention.char_end is not None
                                and mention.char_start >= char_start
                                and mention.char_end <= char_end
                                for mention in entity.mentions
                            )
                        ),
                        evidence_ids=[evidence_id],
                        polarity="uncertain",
                        provenance=Provenance(
                            method="rule_extracted",
                            confidence=0.8,
                            extractor=self.name,
                            extractor_version=self.version,
                        ),
                    )
                )

        paper.claims = claims
        paper.evidence = evidence_items
        return paper

    def output_count(self, paper: PaperKnowledge) -> int:
        return len(paper.claims)
