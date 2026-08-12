from app.readiness.owner_audit_relationships import (
    ALL_RELATIONSHIPS,
    merge_relationship_audit,
    relationship_audit_fields,
)


def test_missing_relationships_come_from_measured_graph_not_unrelated_subsystems():
    graph_audit = {
        "graph": {"state": "available"},
        "missing_relationships": ["taxonomy_to_literature", "taxonomy_to_habitat"],
        "knowledge_graph_node_edge_integrity": {"state": "available", "passed": True},
        "blockers": ["taxonomy_to_literature_graph_edges_absent", "taxonomy_to_habitat_graph_edges_absent"],
    }
    fields = relationship_audit_fields(graph_audit)
    assert fields["relationship_measurement_state"] == "incomplete"
    assert fields["missing_relationships"] == ["taxonomy_to_literature", "taxonomy_to_habitat"]
    assert "taxonomy_to_images" not in fields["missing_relationships"]


def test_complete_graph_reports_no_missing_relationships():
    fields = relationship_audit_fields(
        {
            "graph": {"state": "available"},
            "missing_relationships": [],
            "knowledge_graph_node_edge_integrity": {"state": "available", "passed": True},
            "blockers": [],
        }
    )
    assert fields["relationship_measurement_state"] == "complete"
    assert fields["missing_relationships"] == []


def test_unavailable_graph_fails_closed_without_claiming_measurement():
    fields = relationship_audit_fields(None)
    assert fields["relationship_measurement_state"] == "unavailable"
    assert tuple(fields["missing_relationships"]) == ALL_RELATIONSHIPS
    assert fields["knowledge_graph_node_edge_integrity"]["passed"] is False


def test_merge_replaces_legacy_placeholder_relationship_list():
    payload = {
        "source_systems": ["mission_control_metrics"],
        "missing_relationships": list(ALL_RELATIONSHIPS),
        "unresolved_failures": ["some_other_subsystem"],
    }
    merged = merge_relationship_audit(
        payload,
        {
            "graph": {"state": "available"},
            "missing_relationships": ["taxonomy_to_elevation"],
            "knowledge_graph_node_edge_integrity": {"state": "available", "passed": True},
            "blockers": ["taxonomy_to_elevation_graph_edges_absent"],
        },
    )
    assert merged["missing_relationships"] == ["taxonomy_to_elevation"]
    assert "persisted_knowledge_graph_audit" in merged["source_systems"]
    assert "taxonomy_to_elevation_graph_edges_absent" in merged["unresolved_failures"]
