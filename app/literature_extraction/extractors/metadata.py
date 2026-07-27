from __future__ import annotations

import re

from ..context import PipelineContext
from ..ingest import read_text_exact
from ..models import Identifier, PaperKnowledge
from .base import Extractor


class MetadataExtractor(Extractor):
    name = "metadata"
    version = "0.1.0"

    async def run(
        self,
        context: PipelineContext,
        paper: PaperKnowledge,
    ) -> PaperKnowledge:
        text = read_text_exact(context.source_path)
        lines = [line.strip() for line in text.splitlines() if line.strip()]

        if paper.metadata.title is None and lines:
            paper.metadata.title = lines[0]

        doi = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", text, re.IGNORECASE)
        if doi and not any(
            identifier.scheme == "doi" for identifier in paper.metadata.identifiers
        ):
            paper.metadata.identifiers.append(
                Identifier(scheme="doi", value=doi.group(0).rstrip(".,;)"))
            )

        year = re.search(r"\b(19|20)\d{2}\b", text)
        if year and paper.metadata.publication_year is None:
            paper.metadata.publication_year = int(year.group(0))

        abstract = re.search(
            r"(?ims)^\s*abstract\s*\n(?P<body>.+?)(?=^\s*(?:keywords?\s*[:\-]|introduction|background)\s*|\Z)",
            text,
        )
        if abstract and paper.metadata.abstract is None:
            paper.metadata.abstract = abstract.group("body").strip()

        keywords = re.search(r"(?im)^\s*keywords?\s*[:\-]\s*(?P<body>.+)$", text)
        if keywords and not paper.metadata.keywords:
            values = re.split(r"\s*[;,]\s*", keywords.group("body").strip())
            paper.metadata.keywords = [value for value in values if value]

        return paper

    def output_count(self, paper: PaperKnowledge) -> int:
        metadata = paper.metadata
        return sum(
            [
                metadata.title is not None,
                metadata.publication_year is not None,
                metadata.abstract is not None,
                bool(metadata.identifiers),
                bool(metadata.keywords),
            ]
        )
