from __future__ import annotations

import json
from pathlib import Path

from app.literature_extraction.cli import main
from app.literature_extraction.models import AnalysisManifest, PaperKnowledge


def test_cli_writes_complete_output_bundle(tmp_path: Path) -> None:
    source = tmp_path / "sample.txt"
    source.write_text("orchid research\n", encoding="utf-8")
    output_dir = tmp_path / "artifacts"

    exit_code = main([str(source), "--output", str(output_dir)])

    assert exit_code == 0
    assert (output_dir / "raw.txt").read_text(encoding="utf-8") == "orchid research\n"

    paper_payload = json.loads((output_dir / "paper.json").read_text(encoding="utf-8"))
    manifest_payload = json.loads(
        (output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    metrics_payload = json.loads(
        (output_dir / "metrics.json").read_text(encoding="utf-8")
    )

    paper = PaperKnowledge.model_validate(paper_payload)
    manifest = AnalysisManifest.model_validate(manifest_payload)

    assert paper.analysis_manifest.status == "completed"
    assert manifest.analysis_id == paper.analysis_manifest.analysis_id
    assert metrics_payload["analysis_id"] == manifest.analysis_id
    assert metrics_payload["status"] == "completed"
    assert metrics_payload["extractor_runs"] == 0
