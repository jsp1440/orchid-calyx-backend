from runtime.knowledge_graph.post_publication_audit import persisted_graph_audit


class Cursor:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.current = None

    def execute(self, _sql):
        self.current = next(self.responses)

    def fetchone(self):
        return self.current[0]

    def fetchall(self):
        return self.current


def test_persisted_graph_audit_healthy():
    cur = Cursor([
        [(10,)],
        [(20,)],
        [("taxon", 5, 5), ("image", 5, 5)],
        [("has_image", 5, 5, 5)],
        [(0,)],
        [(0,)],
        [(0,)],
    ])
    report = persisted_graph_audit(cur)
    assert report["healthy"] is True
    assert report["total_nodes"] == 10
    assert report["total_edges"] == 20
    assert report["blockers"] == []


def test_persisted_graph_audit_blocks_integrity_failures():
    cur = Cursor([
        [(10,)],
        [(20,)],
        [("taxon", 10, 9)],
        [("has_image", 20, 10, 10)],
        [(2,)],
        [(1,)],
        [(3,)],
    ])
    report = persisted_graph_audit(cur)
    assert report["healthy"] is False
    assert "orphan_edges:2" in report["blockers"]
    assert "duplicate_node_keys:1" in report["blockers"]
    assert "duplicate_edges:3" in report["blockers"]
