from runtime.knowledge_graph.source_coverage_audit import source_vs_graph_coverage_audit
from runtime.knowledge_graph.source_registry import SOURCE_QUERIES

_ENABLED_DOMAINS = {query.domain for query in SOURCE_QUERIES if query.enabled}
_BLOCKED_DOMAINS = {query.domain for query in SOURCE_QUERIES if not query.enabled}


def _domain_for_raw_table(table: str) -> str | None:
    for query in SOURCE_QUERIES:
        if query.enabled and query.expected_tables and query.expected_tables[0] == table:
            return query.domain
    return None


def _domain_embedded_in_sql(normalized_sql: str) -> str | None:
    for query in SOURCE_QUERIES:
        if query.enabled and query.expected_tables and query.expected_tables[0].lower() in normalized_sql:
            return query.domain
    return None


class Cursor:
    """SQL-aware cursor double. Responses are configured per-domain rather
    than by matching the registry's full multi-line SQL verbatim - each
    domain's raw source table name is unique, so it is used as the dispatch
    key for both the embedded-in-SQL lookups and the parameterized
    persisted-graph-row lookups."""

    def __init__(self, *, raw_counts=None, resolved_counts=None, graph_node_counts=None, graph_edge_counts=None):
        self.raw_counts = raw_counts or {}
        self.resolved_counts = resolved_counts or {}
        self.graph_node_counts = graph_node_counts or {}
        self.graph_edge_counts = graph_edge_counts or {}
        self.current = None
        self.calls: list[tuple[str, tuple | None]] = []

    def execute(self, sql, params=None):
        normalized = " ".join(sql.lower().split())
        self.calls.append((normalized, params))
        if "from oc_graph.kg_nodes where source_table" in normalized:
            domain = _domain_for_raw_table(params[0])
            self.current = [(self.graph_node_counts.get(domain, 0),)]
        elif "from oc_graph.kg_edges where source_table" in normalized:
            domain = _domain_for_raw_table(params[0])
            self.current = [(self.graph_edge_counts.get(domain, 0),)]
        elif normalized.startswith("select count(*) from (") and normalized.endswith("as resolved"):
            domain = _domain_embedded_in_sql(normalized)
            self.current = [(self.resolved_counts.get(domain, 0),)]
        elif normalized.startswith("select count(*) from"):
            domain = _domain_embedded_in_sql(normalized)
            self.current = [(self.raw_counts.get(domain, 0),)]
        else:
            raise AssertionError(f"Unrecognized SQL: {normalized}")

    def fetchone(self):
        return self.current[0]


def test_reports_exactly_the_registry_s_enabled_and_blocked_domains() -> None:
    cur = Cursor()
    report = source_vs_graph_coverage_audit(cur)

    assert report["contract"] == "calyx-kg-901a-source-coverage-audit-v1"
    assert report["graph_mutation"] is False
    assert {entry["domain"] for entry in report["domains"]} == _ENABLED_DOMAINS
    assert {entry["domain"] for entry in report["blocked_domains"]} == _BLOCKED_DOMAINS
    for entry in report["blocked_domains"]:
        assert entry["blocked_reason"]


def test_never_queries_a_table_for_an_unverified_blocked_domain() -> None:
    """Blocked domains (habitat, elevation, ...) must never be counted -
    this module makes no claim about a source it has not verified."""
    cur = Cursor()
    source_vs_graph_coverage_audit(cur)

    for query in SOURCE_QUERIES:
        if query.enabled:
            continue
        table = query.expected_tables[0] if query.expected_tables else None
        if not table:
            continue
        assert all(table.lower() not in sql for sql, _ in cur.calls), (
            f"unverified blocked domain {query.domain!r}'s table {table!r} was queried"
        )


def test_coverage_percent_reflects_real_gap_between_resolved_and_persisted() -> None:
    cur = Cursor(
        raw_counts={"occurrences": 580000},
        resolved_counts={"occurrences": 100},
        graph_node_counts={"occurrences": 80},
        graph_edge_counts={"occurrences": 0},
    )
    report = source_vs_graph_coverage_audit(cur)
    occurrences = next(entry for entry in report["domains"] if entry["domain"] == "occurrences")

    assert occurrences["raw_source_rows"] == 580000
    assert occurrences["exact_taxon_resolved_rows"] == 100
    assert occurrences["persisted_graph_rows"] == 80
    assert occurrences["coverage_pct"] == 0.8
    assert occurrences["missing_from_graph"] == 20


def test_zero_resolved_rows_reports_honest_zero_coverage_not_an_error() -> None:
    cur = Cursor(resolved_counts={"media": 0})
    report = source_vs_graph_coverage_audit(cur)
    media = next(entry for entry in report["domains"] if entry["domain"] == "media")

    assert media["exact_taxon_resolved_rows"] == 0
    assert media["coverage_pct"] == 0.0
    assert media["missing_from_graph"] == 0


def test_name_join_domain_is_reported_with_its_real_taxon_mapping_not_masked_as_exact() -> None:
    cur = Cursor()
    report = source_vs_graph_coverage_audit(cur)
    literature = next(entry for entry in report["domains"] if entry["domain"] == "literature")

    assert literature["taxon_mapping"] == "name_join"
