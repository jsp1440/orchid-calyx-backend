from app.readiness.live_graph_audit import Metric, run_live_graph_audit


class Cursor:
    def __init__(self):
        self.sql = ""
        self.params = ()

    def execute(self, sql, params=()):
        self.sql = " ".join(sql.split())
        self.params = tuple(params)

    def fetchone(self):
        sql = self.sql
        if "to_regclass" in sql:
            table = self.params[0]
            return (table in {"public.orchid_taxonomy", "public.orchid_images"},)
        if "COUNT(DISTINCT i.taxonomy_id)" in sql:
            return (30000,)
        if "LEFT JOIN public.orchid_taxonomy" in sql:
            return (25,)
        if "COUNT(*) FROM public.orchid_taxonomy" in sql:
            return (31840,)
        if "COUNT(*) FROM public.orchid_images WHERE taxonomy_id IS NOT NULL" in sql:
            return (5000000,)
        if "COUNT(*) FROM public.orchid_images" in sql:
            return (5070503,)
        raise AssertionError(sql)

    def fetchall(self):
        if self.params == ("public", "orchid_taxonomy"):
            return [("id",), ("scientific_name",)]
        if self.params == ("public", "orchid_images"):
            return [("id",), ("taxonomy_id",), ("image_url",)]
        return []


class GraphCursor(Cursor):
    EDGE_COUNTS = {
        "has_image": 100,
        "occurs_at": 50,
        "has_elevation": 0,
        "experiences_climate": 40,
        "documented_by": 30,
        "associated_with_pollinator": 5,
        "associated_with_mycorrhiza": 1,
        "occupies_habitat": 0,
        "has_conservation_assessment": 7,
    }

    def fetchone(self):
        sql = self.sql
        if "to_regclass" in sql:
            table = self.params[0]
            return (
                table
                in {
                    "public.orchid_taxonomy",
                    "public.orchid_images",
                    "oc_graph.kg_edges",
                    "oc_graph.kg_nodes",
                },
            )
        if "COUNT(*) FROM oc_graph.kg_edges WHERE edge_type IN" in sql:
            return (
                sum(self.EDGE_COUNTS.get(edge_type, 0) for edge_type in self.params),
            )
        if "COUNT(*) FROM oc_graph.kg_edges WHERE from_node_id IS NULL" in sql:
            return (0,)
        if "SELECT COALESCE(SUM(n - 1), 0)" in sql:
            return (0,)
        if "LEFT JOIN oc_graph.kg_nodes f" in sql:
            return (0,)
        if "COUNT(*) FROM oc_graph.kg_edges" in sql:
            return (233,)
        return super().fetchone()

    def fetchall(self):
        if self.params == ("oc_graph", "kg_edges"):
            return [
                ("kg_edge_id",),
                ("edge_type",),
                ("from_node_id",),
                ("to_node_id",),
            ]
        return super().fetchall()


class CompleteGraphCursor(GraphCursor):
    EDGE_COUNTS = {
        **GraphCursor.EDGE_COUNTS,
        "has_elevation": 11,
        "occupies_habitat": 12,
    }


def test_metric_percentage():
    assert Metric("available", 50, 200).as_dict()["percentage"] == 25.0


def test_audit_separates_relational_links_from_missing_graph_table():
    report = run_live_graph_audit(Cursor())
    images = report["relational"]["taxonomy_to_images"]

    assert images["state"] == "available"
    assert images["linked_images"]["value"] == 4_999_975
    assert images["broken_taxonomy_targets"]["value"] == 25
    assert images["interpretation"] == "relational_linkage_only"
    assert report["graph"]["state"] == "unavailable"
    assert report["homepage_ready"] is False
    assert "graph_materialization_measurement_unavailable" in report["blockers"]


def test_audit_measures_every_required_persisted_relationship_independently():
    report = run_live_graph_audit(GraphCursor())
    relationships = report["graph"]["relationships"]

    assert relationships["taxonomy_to_images"]["value"] == 100
    assert relationships["taxonomy_to_occurrences"]["value"] == 50
    assert relationships["taxonomy_to_literature"]["value"] == 30
    assert relationships["taxonomy_to_pollinators"]["value"] == 5
    assert relationships["taxonomy_to_mycorrhiza"]["value"] == 1
    assert relationships["taxonomy_to_conservation"]["value"] == 7
    assert report["missing_relationships"] == [
        "taxonomy_to_elevation",
        "taxonomy_to_habitat",
    ]
    assert report["knowledge_graph_node_edge_integrity"]["passed"] is True
    assert report["homepage_ready"] is False


def test_audit_can_become_ready_only_when_all_relationships_and_integrity_exist():
    report = run_live_graph_audit(CompleteGraphCursor())

    assert report["missing_relationships"] == []
    assert report["knowledge_graph_node_edge_integrity"]["passed"] is True
    assert report["blockers"] == []
    assert report["homepage_ready"] is True
