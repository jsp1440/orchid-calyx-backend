from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from .context import PipelineContext
from .ingest import build_empty_paper, ingest_text
from .models import PaperKnowledge
from .normalization import normalize_and_reconcile
from .pipeline import PipelineRunner
from .registry import DEFAULT_REGISTRY, ExtractorRegistry
from .repository import LiteratureResultRepository
from .review import build_review_queue, refresh_publication_decisions


class LiteraturePipelineError(RuntimeError):
    def __init__(self, stage: str, code: str, detail: str) -> None:
        self.stage, self.code, self.detail = stage, code, detail
        super().__init__(f"{stage}:{code}: {detail}")


def _validate(paper: PaperKnowledge, raw_text: str) -> None:
    required = {
        "metadata": bool(paper.metadata.title),
        "sections": bool(paper.sections),
        "entities": bool(paper.entities),
        "claims": bool(paper.claims),
        "evidence": bool(paper.evidence),
    }
    for stage, present in required.items():
        if not present:
            raise LiteraturePipelineError(
                stage, "EMPTY_REQUIRED_OUTPUT", f"{stage} produced no records"
            )
    for evidence in paper.evidence:
        start, end = evidence.span.char_start, evidence.span.char_end
        if start is None or end is None or raw_text[start:end] != evidence.excerpt:
            raise LiteraturePipelineError(
                "evidence", "INVALID_SOURCE_SPAN", evidence.evidence_id
            )
    if any(not claim.evidence_ids for claim in paper.claims):
        raise LiteraturePipelineError(
            "claims", "MISSING_EVIDENCE_LINK", "claim lacks evidence"
        )


async def extract_and_persist(
    source: str | Path,
    repository: LiteratureResultRepository,
    *,
    registry: ExtractorRegistry = DEFAULT_REGISTRY,
) -> PaperKnowledge:
    source_path = Path(source)
    document = ingest_text(source_path)
    context = PipelineContext(source_path=source_path, output_dir=repository.root)
    paper = build_empty_paper(
        document, pipeline_version=context.config.pipeline_version
    )
    paper.analysis_manifest.configuration_fingerprint = sha256(
        json.dumps(
            {
                "pipeline_version": context.config.pipeline_version,
                "extractors": registry.names(),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    result = await PipelineRunner(registry.ordered()).run(context, paper)
    failed = next(
        (run for run in result.analysis_manifest.extractors if run.status == "failed"),
        None,
    )
    if failed:
        repository.save(result, document)
        raise LiteraturePipelineError(
            failed.name, "EXTRACTOR_FAILED", failed.error or "unknown error"
        )
    try:
        _validate(result, document.raw_text)
    except LiteraturePipelineError:
        result.analysis_manifest.status = "failed"
        repository.save(result, document)
        raise
    result = refresh_publication_decisions(
        build_review_queue(normalize_and_reconcile(result))
    )
    repository.save(result, document)
    return result
