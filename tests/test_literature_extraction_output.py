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
    assert metrics_payload["extractor_runs"] == 2


def test_cli_extracts_metadata_and_sections_deterministically(tmp_path: Path) -> None:
    source = tmp_path / "paper.txt"
    source.write_text(
        """Ecology of Orchid Pollination
Alice Example; Bob Researcher
Journal of Orchid Studies, 2024
https://doi.org/10.1234/orchid.2024.7

Abstract
Pollination success varied across habitats.

Keywords: orchids; pollination; habitat

Introduction
Orchid pollination is ecologically important.

Materials and Methods
We surveyed 12 sites.

Results
Pollination success increased by 20 percent.

Discussion
Habitat structure may explain the pattern.

References
Example A. 2020. Prior orchid work.
""",
        encoding="utf-8",
    )

    first_output = tmp_path / "first"
    second_output = tmp_path / "second"

    assert main([str(source), "--output", str(first_output)]) == 0
    assert main([str(source), "--output", str(second_output)]) == 0

    first_payload = json.loads((first_output / "paper.json").read_text(encoding="utf-8"))
    second_payload = json.loads((second_output / "paper.json").read_text(encoding="utf-8"))

    first = PaperKnowledge.model_validate(first_payload)
    second = PaperKnowledge.model_validate(second_payload)

    assert first.metadata.title == "Ecology of Orchid Pollination"
    assert first.metadata.publication_year == 2024
    assert first.metadata.abstract == "Pollination success varied across habitats."
    assert first.metadata.keywords == ["orchids", "pollination", "habitat"]
    assert [(identifier.scheme, identifier.value) for identifier in first.metadata.identifiers] == [
        ("doi", "10.1234/orchid.2024.7")
    ]

    assert [section.canonical_type for section in first.sections] == [
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "references",
    ]
    assert [section.order for section in first.sections] == list(range(6))
    assert all(section.span.char_start is not None for section in first.sections)
    assert all(section.span.char_end is not None for section in first.sections)
    assert all(
        section.span.char_start < section.span.char_end
        for section in first.sections
        if section.span.char_start is not None and section.span.char_end is not None
    )

    def stable_payload(paper: PaperKnowledge) -> dict[str, object]:
        payload = paper.model_dump(mode="json")
        manifest = payload["analysis_manifest"]
        for field in ("analysis_id", "created_at", "completed_at"):
            manifest.pop(field, None)
        for run in manifest["extractors"]:
            run.pop("started_at", None)
            run.pop("completed_at", None)
        return payload

    assert stable_payload(first) == stable_payload(second)
