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
    assert metrics_payload["extractor_runs"] == 4


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


def test_cli_extracts_entities_with_mentions_and_provenance(tmp_path: Path) -> None:
    source = tmp_path / "entities.txt"
    text = """ATP Response in Escherichia coli

Abstract
ATP was measured in Escherichia coli.

Methods
PCR quantified ATP, and pcr was repeated for confirmation.
"""
    source.write_text(text, encoding="utf-8")

    first_output = tmp_path / "first-entities"
    second_output = tmp_path / "second-entities"

    assert main([str(source), "--output", str(first_output)]) == 0
    assert main([str(source), "--output", str(second_output)]) == 0

    first = PaperKnowledge.model_validate_json(
        (first_output / "paper.json").read_text(encoding="utf-8")
    )
    second = PaperKnowledge.model_validate_json(
        (second_output / "paper.json").read_text(encoding="utf-8")
    )

    assert [entity.entity_id for entity in first.entities] == [
        "entity-1",
        "entity-2",
        "entity-3",
    ]
    assert [entity.entity_type for entity in first.entities] == [
        "chemical",
        "method",
        "taxon",
    ]
    assert [entity.normalized_name for entity in first.entities] == [
        "atp",
        "pcr",
        "escherichia coli",
    ]
    assert [len(entity.mentions) for entity in first.entities] == [3, 2, 2]

    for entity in first.entities:
        assert entity.provenance.method == "rule_extracted"
        assert entity.provenance.extractor == "entities"
        assert entity.provenance.extractor_version == "0.1.0"
        assert entity.provenance.confidence == 1.0
        assert entity.mentions
        for mention in entity.mentions:
            assert mention.char_start is not None
            assert mention.char_end is not None
            assert mention.char_start < mention.char_end
            assert text[mention.char_start : mention.char_end].casefold() == entity.normalized_name

    first_entities = [entity.model_dump(mode="json") for entity in first.entities]
    second_entities = [entity.model_dump(mode="json") for entity in second.entities]
    assert first_entities == second_entities


def test_cli_extracts_claims_with_linked_evidence(tmp_path: Path) -> None:
    source = tmp_path / "claims.txt"
    text = """Orchid Growth Study

Results
Growth increased by 20 percent. Flowering began two days earlier.

Discussion
The response may reflect improved nutrient availability.

Conclusion
The treatment appears beneficial.
"""
    source.write_text(text, encoding="utf-8")

    first_output = tmp_path / "first-claims"
    second_output = tmp_path / "second-claims"

    assert main([str(source), "--output", str(first_output)]) == 0
    assert main([str(source), "--output", str(second_output)]) == 0

    first = PaperKnowledge.model_validate_json(
        (first_output / "paper.json").read_text(encoding="utf-8")
    )
    second = PaperKnowledge.model_validate_json(
        (second_output / "paper.json").read_text(encoding="utf-8")
    )

    assert [claim.claim_id for claim in first.claims] == [
        "claim-1",
        "claim-2",
        "claim-3",
        "claim-4",
    ]
    assert [claim.claim_type for claim in first.claims] == [
        "result",
        "result",
        "interpretation",
        "interpretation",
    ]
    assert [evidence.evidence_id for evidence in first.evidence] == [
        "evidence-1",
        "evidence-2",
        "evidence-3",
        "evidence-4",
    ]

    for claim, evidence in zip(first.claims, first.evidence, strict=True):
        assert claim.evidence_ids == [evidence.evidence_id]
        assert evidence.supports_ids == [claim.claim_id]
        assert evidence.excerpt == claim.statement
        assert evidence.span.section_id is not None
        assert evidence.span.char_start is not None
        assert evidence.span.char_end is not None
        assert text[evidence.span.char_start : evidence.span.char_end] == evidence.excerpt
        assert claim.provenance.method == "rule_extracted"
        assert claim.provenance.extractor == "claims"
        assert claim.provenance.extractor_version == "0.1.0"
        assert claim.provenance.confidence == 0.8

    assert [claim.model_dump(mode="json") for claim in first.claims] == [
        claim.model_dump(mode="json") for claim in second.claims
    ]
    assert [evidence.model_dump(mode="json") for evidence in first.evidence] == [
        evidence.model_dump(mode="json") for evidence in second.evidence
    ]
