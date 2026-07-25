from __future__ import annotations

import json
from pathlib import Path

from app.literature_extraction.cli import main
from app.literature_extraction.models import PaperKnowledge


def test_cli_emits_review_ready_normalized_records(tmp_path: Path) -> None:
    source = tmp_path / "paper.txt"
    source.write_text(
        """Orchid Growth Study

Results
Growth increased by 20 percent. Growth increased by 20 percent.

Discussion
The habitat may explain flowering behavior.
""",
        encoding="utf-8",
    )
    output = tmp_path / "artifacts"

    assert main([str(source), "--output", str(output)]) == 0

    payload = json.loads((output / "paper.json").read_text(encoding="utf-8"))
    paper = PaperKnowledge.model_validate(payload)

    assert paper.normalized_evidence_records
    assert len(paper.normalized_evidence_records) == len(paper.claims)
    assert all(record.review_status == "unreviewed" for record in paper.normalized_evidence_records)
    assert all(record.evidence_ids for record in paper.normalized_evidence_records)
    assert all(record.source_excerpts for record in paper.normalized_evidence_records)
    assert all(record.provenance.extractor == "claims" for record in paper.normalized_evidence_records)

    duplicate_relations = [
        relation
        for relation in paper.reconciliation_relations
        if relation.relation_type == "duplicate"
    ]
    assert duplicate_relations
    duplicate_ids = {
        duplicate_relations[0].subject_record_id,
        duplicate_relations[0].object_record_id,
    }
    duplicate_records = [
        record for record in paper.normalized_evidence_records if record.record_id in duplicate_ids
    ]
    assert len(duplicate_records) == 2
    assert duplicate_records[0].reconciliation_group_id == duplicate_records[1].reconciliation_group_id


def test_normalized_records_are_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "paper.txt"
    source.write_text(
        """Orchid Habitat Study

Results
The orchid occurred in wet forest habitat.
""",
        encoding="utf-8",
    )
    first = tmp_path / "first"
    second = tmp_path / "second"

    assert main([str(source), "--output", str(first)]) == 0
    assert main([str(source), "--output", str(second)]) == 0

    first_paper = PaperKnowledge.model_validate_json(
        (first / "paper.json").read_text(encoding="utf-8")
    )
    second_paper = PaperKnowledge.model_validate_json(
        (second / "paper.json").read_text(encoding="utf-8")
    )

    assert [item.model_dump(mode="json") for item in first_paper.normalized_evidence_records] == [
        item.model_dump(mode="json") for item in second_paper.normalized_evidence_records
    ]
    assert [item.model_dump(mode="json") for item in first_paper.reconciliation_relations] == [
        item.model_dump(mode="json") for item in second_paper.reconciliation_relations
    ]
    assert first_paper.normalized_evidence_records[0].domain == "occurrence"
