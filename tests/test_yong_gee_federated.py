from pathlib import Path

from openpyxl import Workbook

from runtime.federated_sources.yong_gee import (
    build_dry_run,
    clean_html,
    publish_matched_evidence,
    read_workbook,
)
from runtime.knowledge_graph.models import Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository


def _workbook(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Chosen"
    ws.append(
        [
            "id",
            "genusId",
            "speciesName",
            "author",
            "characteristicsp",
            "habitat",
            "referencesp",
            "websiteInformalName",
            "websiteFormalName",
            "websiteSlug",
        ]
    )
    ws.append(
        [
            3,
            213,
            "armeniacum",
            "S.C.Chen & F.Y.Liu",
            "<p>Leaves <b>tessellated</b>; flowers golden yellow.</p>",
            "<span>limestone; 1,400-2,100 m</span>",
            "Flora of China<br />IPNI",
            "<em>Paphiopedilum armeniacum</em>",
            "<em>Paphiopedilum armeniacum</em> S.C.Chen & F.Y.Liu",
            "armeniacum",
        ]
    )
    wb.save(path)


def _taxon_node(pk: str = "42") -> Node:
    return Node(
        kg_node_id=1,
        node_type="taxon",
        canonical_key=f"taxon:{pk}",
        display_label="Paphiopedilum armeniacum S.C.Chen & F.Y.Liu",
        source_table="taxonomy",
        source_pk=pk,
        payload={"canonical_name": "Paphiopedilum armeniacum"},
    )


def test_clean_html_preserves_readable_text():
    assert clean_html("<p>golden&nbsp;yellow<br>flower</p>") == "golden yellow\nflower"


def test_read_and_reconcile_workbook(tmp_path: Path):
    path = tmp_path / "yong.xlsx"
    _workbook(path)
    records = read_workbook(path)
    assert len(records) == 1
    assert records[0].scientific_name == "Paphiopedilum armeniacum"

    rows, report = build_dry_run(path, [_taxon_node()])
    assert report.total_records == 1
    assert report.matched == 1
    assert report.unresolved == 0
    assert report.evidence_rows == 3
    assert {row["evidence_type"] for row in rows} == {
        "morphology",
        "habitat",
        "bibliography",
    }
    assert all(row["taxon_pk"] == "42" for row in rows)


def test_unresolved_taxon_is_not_projected(tmp_path: Path):
    path = tmp_path / "yong.xlsx"
    _workbook(path)
    rows, report = build_dry_run(path, [])
    assert rows == []
    assert report.unresolved == 1


def test_existing_graph_publisher_attaches_evidence_to_taxon(tmp_path: Path):
    path = tmp_path / "yong.xlsx"
    _workbook(path)
    taxon = _taxon_node()
    rows, _ = build_dry_run(path, [taxon])

    repo = InMemoryGraphRepository(nodes=[taxon])
    result = publish_matched_evidence(repo, rows)

    assert result.invalid == []
    assert result.nodes_written == 3
    assert result.edges_written == 3
    assert all(edge.from_node_id == taxon.kg_node_id for edge in repo.all_edges())
    assert {edge.edge_type for edge in repo.all_edges()} == {"supported_by_evidence"}
