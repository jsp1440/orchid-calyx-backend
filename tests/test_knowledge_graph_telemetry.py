"""Regression tests for the Knowledge Graph telemetry repair.

Root cause repaired: production stores the canonical knowledge graph in
``oc_graph.kg_nodes`` / ``oc_graph.kg_edges``, but the telemetry candidate
lists probed older table names that do not exist, so Mission Control showed
"not connected" / relationships: 0 despite a populated graph.

These tests pin the corrected candidate lists and verify that counts flow
from live queries (first available table) rather than constants, and that
absent tables still report honestly as unavailable.
"""

from app.routers.mission_control import METRIC_CANDIDATES, first_available_count
from runtime.scientific_intelligence.adapters import (
    _KG_ENTITY_CANDIDATES,
    _KG_RELATIONSHIP_CANDIDATES,
    _first_count,
)


class FakeCursor:
    """Minimal cursor emulating to_regclass + COUNT(*) behaviour."""

    def __init__(self, tables: dict[str, int]):
        self.tables = tables
        self._result = None

    def execute(self, sql, params=None):
        if "to_regclass" in sql:
            table = params[0]
            self._result = (table if table in self.tables else None,)
        elif sql.startswith("SELECT COUNT(*) FROM "):
            table = sql.removeprefix("SELECT COUNT(*) FROM ")
            self._result = (self.tables[table],)
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {sql}")

    def fetchone(self):
        return self._result


def test_relationships_metric_probes_canonical_kg_edges_first():
    candidates = METRIC_CANDIDATES["relationships"]
    assert candidates[0] == "oc_graph.kg_edges"
    # Legacy fallbacks retained for other environments.
    assert "oc_relationships.relationships" in candidates


def test_adapter_candidates_include_canonical_kg_tables_first():
    assert _KG_ENTITY_CANDIDATES[0] == "oc_graph.kg_nodes"
    assert _KG_RELATIONSHIP_CANDIDATES[0] == "oc_graph.kg_edges"


def test_first_available_count_uses_live_count_from_kg_edges():
    cur = FakeCursor({"oc_graph.kg_edges": 67572})
    result = first_available_count(cur, METRIC_CANDIDATES["relationships"])
    assert result["available"] is True
    assert result["table"] == "oc_graph.kg_edges"
    assert result["count"] == 67572


def test_first_available_count_reports_honestly_when_absent():
    cur = FakeCursor({})
    result = first_available_count(cur, METRIC_CANDIDATES["relationships"])
    assert result["available"] is False
    assert result["table"] is None
    assert result["count"] == 0


def test_adapter_first_count_prefers_canonical_tables():
    class AdapterCursor:
        """Handles adapters' composed-SQL count queries."""

        def __init__(self, tables):
            self.tables = tables
            self._result = None
            self._last_table = None

        def execute(self, sql, params=None):
            text = sql if isinstance(sql, str) else "SELECT COUNT(*)"
            if "to_regclass" in text:
                table = params[0]
                self._last_table = table if table in self.tables else None
                self._result = (self._last_table,)
            else:
                self._result = (self.tables[self._last_table],)

        def fetchone(self):
            return self._result

    cur = AdapterCursor({"oc_graph.kg_nodes": 34519, "oc_graph.kg_edges": 67572})
    table, count = _first_count(cur, _KG_ENTITY_CANDIDATES)
    assert (table, count) == ("oc_graph.kg_nodes", 34519)
    table, count = _first_count(cur, _KG_RELATIONSHIP_CANDIDATES)
    assert (table, count) == ("oc_graph.kg_edges", 67572)
