from __future__ import annotations

from pathlib import Path

import runtime.globi_canonical_harvester as canonical
from app.calyx_conversation.interaction_discovery_ingest import (
    document_from_globi_interaction,
    ingest_globi_interactions_for_canonical_dataset,
)


def _write_tsv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    lines = ["\t".join(header)]
    lines.extend("\t".join(row) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_read_globi_dataset_rows_parses_stable_export_headers(tmp_path: Path) -> None:
    tsv_path = tmp_path / "interactions.tsv"
    _write_tsv(
        tsv_path,
        [
            "sourceTaxonName",
            "sourceTaxonId",
            "interactionTypeName",
            "targetTaxonName",
            "targetTaxonId",
            "referenceCitation",
            "sourceCitation",
        ],
        [
            [
                "Orchis mascula",
                "GBIF:123",
                "pollinatedBy",
                "Bombus terrestris",
                "GBIF:456",
                "Example study 2020",
                "GloBI dataset v1",
            ]
        ],
    )
    rows = list(canonical.read_globi_dataset_rows(tsv_path))
    assert len(rows) == 1
    assert rows[0]["sourceTaxonName"] == "Orchis mascula"
    assert rows[0]["interactionTypeName"] == "pollinatedBy"
    assert rows[0]["referenceCitation"] == "Example study 2020"


def test_read_globi_dataset_rows_drops_empty_values(tmp_path: Path) -> None:
    tsv_path = tmp_path / "interactions.tsv"
    _write_tsv(
        tsv_path,
        ["sourceTaxonName", "targetTaxonName", "referenceCitation"],
        [["Orchis mascula", "Bombus terrestris", ""]],
    )
    rows = list(canonical.read_globi_dataset_rows(tsv_path))
    assert "referenceCitation" not in rows[0]


def test_read_globi_dataset_rows_honors_csv_extension(tmp_path: Path) -> None:
    csv_path = tmp_path / "interactions.csv"
    csv_path.write_text(
        "sourceTaxonName,targetTaxonName,interactionTypeName\nOrchis mascula,Bombus terrestris,pollinatedBy\n",
        encoding="utf-8",
    )
    rows = list(canonical.read_globi_dataset_rows(csv_path))
    assert rows[0]["interactionTypeName"] == "pollinatedBy"


def test_stable_dataset_record_maps_to_a_review_bound_document() -> None:
    document = document_from_globi_interaction(
        {
            "sourceTaxonName": "Orchis mascula",
            "sourceTaxonId": "GBIF:123",
            "interactionTypeName": "pollinatedBy",
            "targetTaxonName": "Bombus terrestris",
            "targetTaxonId": "GBIF:456",
            "referenceCitation": "Example study 2020",
            "sourceCitation": "GloBI dataset v1",
        },
        query_role="canonical_dataset",
        provider_stability="VERSIONED_STABLE_DATASET",
        dataset_version="globi-2026-08",
    )
    assert document is not None
    assert document.metadata["interaction_type"] == "pollinatedBy"
    assert document.metadata["provider_stability"] == "VERSIONED_STABLE_DATASET"
    assert document.metadata["dataset_version"] == "globi-2026-08"
    # Once we ARE the stable snapshot, preferring one over the current source is moot.
    assert document.metadata["stable_research_snapshot_preferred"] is False
    assert document.metadata["scientific_review_required"] is True
    assert document.metadata["automatic_publication"] is False
    assert document.metadata["knowledge_graph_mutation"] is False


def test_record_missing_interaction_type_name_is_not_silently_indexed() -> None:
    # Guards the exact bug this module fixes: before the camelCase alias was
    # added, a stable-dataset row using interactionTypeName (GloBI's real
    # column name) mapped to nothing and was silently dropped.
    document = document_from_globi_interaction(
        {"sourceTaxonName": "Orchis mascula", "targetTaxonName": "Bombus terrestris"},
        query_role="canonical_dataset",
    )
    assert document is None


def test_ingest_for_canonical_dataset_tags_documents_with_dataset_version(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_ingest_documents(documents, *, discovered, configuration):
        captured["documents"] = documents
        captured["discovered"] = discovered
        captured["configuration"] = configuration
        return {"status": "indexed_for_research", "indexed": len(documents)}

    import app.calyx_conversation.interaction_discovery_ingest as ingest_module

    monkeypatch.setattr(ingest_module, "_ingest_globi_documents", fake_ingest_documents)

    result = ingest_globi_interactions_for_canonical_dataset(
        [
            {
                "sourceTaxonName": "Orchis mascula",
                "interactionTypeName": "pollinatedBy",
                "targetTaxonName": "Bombus terrestris",
            }
        ],
        dataset_version="globi-2026-08",
    )
    assert result["indexed"] == 1
    assert captured["discovered"] == 1
    assert captured["configuration"]["dataset_version"] == "globi-2026-08"
    assert captured["configuration"]["provenance_contract"] == "globi-canonical-dataset-review-bound-v1"
    documents = captured["documents"]
    assert len(documents) == 1
    assert documents[0].metadata["provider_stability"] == "VERSIONED_STABLE_DATASET"


def test_harvest_canonical_dataset_file_end_to_end(tmp_path: Path, monkeypatch) -> None:
    tsv_path = tmp_path / "interactions.tsv"
    _write_tsv(
        tsv_path,
        ["sourceTaxonName", "interactionTypeName", "targetTaxonName"],
        [
            ["Orchis mascula", "pollinatedBy", "Bombus terrestris"],
            ["Vanilla planifolia", "pollinatedBy", "Eulaema meriana"],
        ],
    )

    def fake_ingest(rows, *, dataset_version):
        assert dataset_version == "globi-2026-08"
        assert len(rows) == 2
        return {"status": "indexed_for_research", "indexed": 2}

    monkeypatch.setattr(canonical, "ingest_globi_interactions_for_canonical_dataset", fake_ingest)

    result = canonical.harvest_canonical_dataset_file(tsv_path, dataset_version="globi-2026-08")
    assert result["status"] == "indexed_for_research"
    assert result["discovered"] == 2
    assert result["indexed"] == 2
    assert result["source_kind"] == "versioned_stable_dataset"
    assert result["review_required"] is True
    assert result["automatic_publication"] is False
    assert result["knowledge_graph_mutation"] is False


def test_harvest_canonical_dataset_file_respects_limit(tmp_path: Path, monkeypatch) -> None:
    tsv_path = tmp_path / "interactions.tsv"
    _write_tsv(
        tsv_path,
        ["sourceTaxonName", "interactionTypeName", "targetTaxonName"],
        [
            ["Orchis mascula", "pollinatedBy", "Bombus terrestris"],
            ["Vanilla planifolia", "pollinatedBy", "Eulaema meriana"],
            ["Ophrys apifera", "pollinatedBy", "Andrena nigroaenea"],
        ],
    )

    def fake_ingest(rows, *, dataset_version):
        return {"status": "indexed_for_research", "indexed": len(rows)}

    monkeypatch.setattr(canonical, "ingest_globi_interactions_for_canonical_dataset", fake_ingest)

    result = canonical.harvest_canonical_dataset_file(tsv_path, dataset_version="globi-2026-08", limit=2)
    assert result["discovered"] == 2
