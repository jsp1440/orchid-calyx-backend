from runtime.knowledge_graph.source_coverage_audit import audit_source_coverage


class FakeCursor:
    def __init__(self):
        self.value = 0

    def execute(self, sql, params=()):
        normalized = " ".join(str(sql).split()).lower()
        if "from public.orchid_occurrence o" in normalized:
            self.value = 500
        elif normalized == "select count(*) from public.orchid_occurrence":
            self.value = 580
        elif "from public.oc_trait_consensus_normalized t" in normalized:
            self.value = 190
        elif normalized == "select count(*) from public.oc_trait_consensus_normalized":
            self.value = 200
        elif "from public.oc_species_habitat_claims h" in normalized:
            self.value = 60
        elif normalized == "select count(*) from public.oc_species_habitat_claims":
            self.value = 70
        elif normalized == "select count(*) from public.research_documents":
            self.value = 100
        elif "from oc_graph.kg_nodes where node_type=%s" in normalized:
            self.value = {
                "occurrence": 25,
                "trait": 40,
                "habitat": 6,
                "publication": 10,
            }[params[0]]
        elif "from oc_graph.kg_edges where edge_type=%s" in normalized:
            self.value = {
                "occurs_at": 25,
                "has_trait": 35,
                "occupies_habitat": 5,
                "documented_by": 8,
            }[params[0]]
        else:  # pragma: no cover - makes unexpected SQL obvious
            raise AssertionError(normalized)

    def fetchone(self):
        return (self.value,)


def test_source_coverage_uses_resolved_rows_as_materialization_denominator():
    report = audit_source_coverage(FakeCursor())
    occurrence = report["domains"]["occurrences"]
    trait = report["domains"]["traits"]
    literature = report["domains"]["literature"]

    assert report["read_only"] is True
    assert report["graph_mutation"] is False
    assert occurrence["source_rows"] == 580
    assert occurrence["taxon_resolved_source_rows"] == 500
    assert occurrence["graph_edges"] == 25
    assert occurrence["edge_coverage_of_resolved_source"] == 0.05
    assert occurrence["source_minus_graph_edges"] == 475

    assert trait["source_rows"] == 200
    assert trait["taxon_resolved_source_rows"] == 190
    assert trait["source_minus_graph_edges"] == 155

    assert literature["taxon_resolved_source_rows"] is None
    assert literature["edge_coverage_of_resolved_source"] == 0.08
