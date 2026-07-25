from __future__ import annotations

from pathlib import Path

import pytest

from app.literature_extraction.context import PipelineContext
from app.literature_extraction.extractors.base import Extractor
from app.literature_extraction.ingest import build_empty_paper, ingest_text
from app.literature_extraction.pipeline import PipelineRunner


class RecordingExtractor(Extractor):
    name = "recording"
    version = "1.0.0"

    async def run(self, context, paper):
        paper.metadata.title = context.source_path.stem
        return paper


def test_ingest_text_builds_valid_empty_paper(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("orchid research", encoding="utf-8")

    document = ingest_text(source)
    paper = build_empty_paper(document)

    assert document.raw_text == "orchid research"
    assert paper.source.original_filename == "sample.txt"
    assert paper.analysis_manifest.input_fingerprint == document.content_hash
    assert paper.analysis_manifest.status == "pending"


@pytest.mark.asyncio
async def test_pipeline_runner_executes_extractors(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("orchid research", encoding="utf-8")
    document = ingest_text(source)
    paper = build_empty_paper(document)
    context = PipelineContext(source_path=source)

    result = await PipelineRunner([RecordingExtractor()]).run(context, paper)

    assert result.metadata.title == "sample"
    assert result.analysis_manifest.extractors[0].name == "recording"
    assert result.analysis_manifest.extractors[0].status == "completed"
