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
