from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from .ingest import IngestedDocument
from .models import PaperKnowledge


@dataclass(frozen=True, slots=True)
class OutputBundle:
    output_dir: Path
    paper_path: Path
    manifest_path: Path
    metrics_path: Path
    raw_text_path: Path


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_bytes_atomic(
        path,
        (
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
        ).encode("utf-8"),
    )


def _write_bytes_atomic(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        temporary.write_bytes(payload)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_metrics(paper: PaperKnowledge) -> dict[str, Any]:
    manifest = paper.analysis_manifest
    return {
        "paper_id": paper.paper_id,
        "analysis_id": manifest.analysis_id,
        "status": manifest.status,
        "extractor_runs": len(manifest.extractors),
        "failed_extractors": sum(run.status == "failed" for run in manifest.extractors),
        "sections": len(paper.sections),
        "entities": len(paper.entities),
        "glossary_terms": len(paper.glossary_terms),
        "measurements": len(paper.measurements),
        "claims": len(paper.claims),
        "evidence": len(paper.evidence),
        "relationships": len(paper.relationships),
        "figures": len(paper.figures),
        "tables": len(paper.tables),
        "references": len(paper.references),
        "unknown_terms": len(paper.unknown_terms),
    }


def write_output_bundle(
    paper: PaperKnowledge,
    document: IngestedDocument,
    output_dir: str | Path,
) -> OutputBundle:
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)

    paper_path = destination / "paper.json"
    manifest_path = destination / "manifest.json"
    metrics_path = destination / "metrics.json"
    raw_text_path = destination / "raw.txt"

    _write_json(paper_path, paper.model_dump(mode="json"))
    _write_json(manifest_path, paper.analysis_manifest.model_dump(mode="json"))
    _write_json(metrics_path, build_metrics(paper))
    _write_bytes_atomic(raw_text_path, document.raw_bytes)

    return OutputBundle(
        output_dir=destination,
        paper_path=paper_path,
        manifest_path=manifest_path,
        metrics_path=metrics_path,
        raw_text_path=raw_text_path,
    )
