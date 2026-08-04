from runtime.knowledge_graph.post_publication_audit import persisted_graph_audit


class Cursor:
    """SQL-aware cursor double that fails loudly on unknown or ambiguous queries."""

    def __init__(self, responses):
        self.responses = responses
        self.current = None

    @staticmethod
    def _normalize(sql: str) -> str:
        return " ".join(sql.lower().split())

    def execute(self, sql):
        normalized = self._normalize(sql)
        matches = []
        for marker, response in self.responses.items():
            if marker.startswith("="):
                matched = normalized == marker[1:]
            else:
                matched = marker in normalized
            if matched:
                matches.append(response)
        if len(matches) != 1:
            raise AssertionError(
                f"Expected exactly one SQL fixture match, found {len(matches)} for: {normalized}"
            )
        self.current = matches[0]

    def fetchone(self):
        return self.current[0]

    def fetchall(self):
        return self.current


def audit_responses(*, orphan_edges=0, duplicate_node_keys=0, duplicate_edges=0):
    return {
        "=select count(*) from oc_graph.kg_nodes": [(10,)],
        "=select count(*) from oc_graph.kg_edges": [(20,)],
        "select node_type, count(*) as records": [
            ("taxon", 5, 5),
            ("image", 5, 5),
        ],
        "select edge_type, count(*) as records": [
            ("has_image", 5, 5, 5),
        ],
        "left join oc_graph.kg_nodes f": [(orphan_edges,)],
        "select canonical_key from oc_graph.kg_nodes": [(duplicate_node_keys,)],
        "select edge_type, from_node_id, to_node_id": [(duplicate_edges,)],
    }


def test_persisted_graph_audit_healthy():
    report = persisted_graph_audit(Cursor(audit_responses()))
    assert report["healthy"] is True
    assert report["total_nodes"] == 10
    assert report["total_edges"] == 20
    assert report["blockers"] == []


def test_persisted_graph_audit_blocks_integrity_failures():
    report = persisted_graph_audit(Cursor(audit_responses(
        orphan_edges=2,
        duplicate_node_keys=1,
        duplicate_edges=3,
    )))
    assert report["healthy"] is False
    assert "orphan_edges:2" in report["blockers"]
    assert "duplicate_node_keys:1" in report["blockers"]
    assert "duplicate_edges:3" in report["blockers"]


def test_cursor_rejects_unrecognized_sql():
    cur = Cursor(audit_responses())
    try:
        cur.execute("SELECT something_new FROM oc_graph.kg_nodes")
    except AssertionError as exc:
        assert "Expected exactly one SQL fixture match" in str(exc)
    else:
        raise AssertionError("Unknown SQL should fail loudly")
