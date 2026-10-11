from pathlib import Path

from openpyxl import Workbook

from runtime.federated_sources.iospe import (
    SOURCE_NAME,
    build_iospe_dry_run,
    publish_iospe_evidence,
    read_iospe_workbook,
)
from runtime.knowledge_graph.models import Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository


def _workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.append(
        [
            "name",
            "season",
            "temperature",
            "light",
            "description",
            "synonyms",
            "references",
            "main image",
            "main photo credit",
        ]
    )
    ws.append(
        [
            "~Paphiopedilum armeniacum S.C.Chen & F.Y.Liu 1982",
            "spring",
            "cool",
            "partial shade",
            "<p>Yellow flowers on limestone.</p>",
            "Paphiopedilum armeniacum var. example",
            "Flora of China; IPNI",
            "orphotdir/example.jpg",
            "Example photographer",
        ]
    )
    wb.save(path)


def _taxon_node() -> Node:
    return Node(
        kg_node_id=1,
        node_type="taxon",
        canonical_key="taxon:42",
        display_label="Paphiopedilum armeniacum S.C.Chen & F.Y.Liu",
        source_table="taxonomy",
        source_pk="42",
        payload={"canonical_name": "Paphiopedilum armeniacum"},
    )


def test_iospe_read_preserves_editorial_marker_and_source_digest(tmp_path: Path):
    path = tmp_path / "iospe.xlsx"
    _workbook(path)
    records = read_iospe_workbook(path)
    assert len(records) == 1
    assert records[0].scientific_name == "Paphiopedilum armeniacum"
    assert records[0].editorial_marker == "~"
    assert len(records[0].source_digest) == 64


def test_iospe_dry_run_reconciles_and_emits_reviewable_evidence(tmp_path: Path):
    path = tmp_path / "iospe.xlsx"
    _workbook(path)
    rows, report = build_iospe_dry_run(path, [_taxon_node()])
    assert report.matched == 1
    assert report.editorial_marked == 1
    assert report.unresolved == 0
    assert {row["evidence_type"] for row in rows} == {
        "phenology",
        "cultivation_temperature",
        "cultivation_light",
        "source_description",
        "nomenclature",
        "bibliography",
    }
    assert all(row["source_name"] == SOURCE_NAME for row in rows)
    assert all(row["editorial_marker"] == "~" for row in rows)


def test_iospe_publisher_reuses_existing_controlled_graph_path(tmp_path: Path):
    path = tmp_path / "iospe.xlsx"
    _workbook(path)
    taxon = _taxon_node()
    rows, _ = build_iospe_dry_run(path, [taxon])

    repo = InMemoryGraphRepository(nodes=[taxon])
    result = publish_iospe_evidence(repo, rows)

    assert result.invalid == []
    assert result.nodes_written == len(rows)
    assert result.edges_written == len(rows)
    assert all(edge.from_node_id == taxon.kg_node_id for edge in repo.all_edges())


def test_unresolved_iospe_taxon_is_not_projected(tmp_path: Path):
    path = tmp_path / "iospe.xlsx"
    _workbook(path)
    rows, report = build_iospe_dry_run(path, [])
    assert rows == []
    assert report.unresolved == 1
