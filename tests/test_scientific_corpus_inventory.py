from runtime.knowledge_graph.scientific_corpus_inventory import (
    CANDIDATES,
    inventory_scientific_corpora,
)


class FakeCursor:
    def __init__(self):
        self._rows = []
        self._one = None

    def execute(self, query, params=None):
        q = " ".join(str(query).split())
        if q.startswith("SELECT to_regclass"):
            relation = params[0]
            present = relation in {
                "oc_atlas.occurrences",
                "oc_views.trait_resolved_v4",
                "oc_literature.documents",
            }
            self._one = (relation if present else None,)
            return
        if q.startswith("SELECT COUNT(*) FROM oc_atlas.occurrences"):
            self._one = (580612,)
            return
        if q.startswith("SELECT COUNT(*) FROM oc_views.trait_resolved_v4"):
            self._one = (78225,)
            return
        if q.startswith("SELECT COUNT(*) FROM oc_literature.documents"):
            self._one = (408,)
            return
        if "information_schema.columns" in q:
            table = params[1]
            cols = {
                "occurrences": [
                    ("taxon_id",), ("country",), ("latitude",),
                    ("longitude",), ("elevation",), ("event_date",),
                ],
                "trait_resolved_v4": [
                    ("taxonomy_id",), ("trait_name",), ("trait_value",),
                ],
                "documents": [("title",), ("doi",)],
            }
            self._rows = cols.get(table, [])
            return
        if "FROM oc_graph.kg_nodes WHERE node_type=%s" in q:
            counts = {"occurrence": 26, "trait": 2807, "publication": 29}
            self._one = (counts.get(params[0], 0),)
            return
        if "FROM oc_graph.kg_edges WHERE edge_type=%s" in q:
            counts = {"occurs_at": 26, "has_trait": 2807, "documented_by": 29}
            self._one = (counts.get(params[0], 0),)
            return
        raise AssertionError(f"Unexpected query: {query!r} params={params!r}")

    def fetchone(self):
        return self._one

    def fetchall(self):
        return list(self._rows)


def test_inventory_is_read_only_and_exposes_source_graph_gap():
    report = inventory_scientific_corpora(FakeCursor())
    assert report["read_only"] is True
    assert report["graph_mutation"] is False
    assert report["contract"] == "calyx-scientific-corpus-inventory-v1"

    rows = {row["relation"]: row for row in report["candidates"]}
    occurrence = rows["oc_atlas.occurrences"]
    assert occurrence["source_rows"] == 580612
    assert occurrence["graph_nodes"] == 26
    assert occurrence["graph_edges"] == 26
    assert occurrence["source_minus_graph_nodes"] == 580586
    assert {"country", "latitude", "longitude", "elevation"}.issubset(
        occurrence["scientific_columns"]
    )

    trait = rows["oc_views.trait_resolved_v4"]
    assert trait["source_rows"] == 78225
    assert trait["graph_nodes"] == 2807
    assert {"trait_name", "trait_value"}.issubset(trait["scientific_columns"])

    literature = rows["oc_literature.documents"]
    assert literature["source_rows"] == 408
    assert literature["graph_nodes"] == 29
    assert {"title", "doi"}.issubset(literature["scientific_columns"])


def test_inventory_candidate_set_includes_scientific_priority_domains():
    domains = {candidate.domain for candidate in CANDIDATES}
    assert {
        "occurrences",
        "traits",
        "literature",
        "evidence",
        "relationships",
        "habitat",
        "elevation",
        "pollinators",
        "mycorrhiza",
        "conservation",
    }.issubset(domains)
