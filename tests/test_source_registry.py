"""BUILD-062 source-registry, SQL-safety, mapping, and adapter tests.

No test opens a database connection. Expanded graph domains without a verified
source projection must remain explicitly registered and fail closed.
"""

from __future__ import annotations

import json as _json
import os as _os

import pytest

from runtime.knowledge_graph import (
    BuildOrchestrator,
    ExecutionMode,
    InMemoryCheckpointStore,
    InMemoryGraphRepository,
    InMemorySourceProvider,
    Node,
    PostgresSourceProvider,
    adapters_by_domain,
    canonical_key,
)
from runtime.knowledge_graph.source_registry import (
    CONTRACT_REQUIRED,
    SOURCE_QUERIES,
    UnsafeSQLError,
    assert_safe_sql,
    blocked_domains,
    enabled_queries,
    registry_by_domain,
)


DOMAINS = {
    "occurrences", "geography", "habitat", "climate", "elevation", "traits",
    "glossary", "literature", "evidence", "pollinators", "mycorrhiza",
    "conservation", "molecular", "education", "media",
}
ENABLED_DOMAINS = {
    "occurrences", "traits", "pollinators", "mycorrhiza",
    "conservation", "climate", "literature", "media",
}
BLOCKED_DOMAINS = DOMAINS - ENABLED_DOMAINS


# ---- registry coverage & contract ----

def test_registry_covers_every_adapter_domain():
    assert set(registry_by_domain()) == set(adapters_by_domain()) == DOMAINS


def test_every_query_declares_the_contract_columns():
    for query in SOURCE_QUERIES:
        for column in CONTRACT_REQUIRED:
            assert column in query.required_columns, f"{query.domain} missing {column}"


def test_enabled_queries_emit_contract_aliases_in_sql():
    for domain, sql in enabled_queries().items():
        low = sql.lower()
        assert "as source_pk" in low, f"{domain} lacks source_pk alias"
        assert "as taxon_pk" in low, f"{domain} lacks taxon_pk alias"


def test_every_enabled_query_filters_to_the_taxon_backbone():
    for domain, sql in enabled_queries().items():
        assert "oc_graph.kg_nodes" in sql, f"{domain} does not resolve to kg backbone"


def test_taxon_mapping_methods_are_known():
    for query in SOURCE_QUERIES:
        assert query.taxon_mapping in {"direct", "resolved_view", "name_join"}


def test_registry_to_dict_is_serialisable():
    for query in SOURCE_QUERIES:
        data = query.to_dict()
        assert data["domain"] == query.domain
        assert isinstance(data["expected_tables"], list)


# ---- blocked-domain handling ----

def test_unverified_expanded_domains_are_explicitly_blocked():
    assert set(blocked_domains()) == BLOCKED_DOMAINS
    assert set(enabled_queries()) == ENABLED_DOMAINS
    for domain in BLOCKED_DOMAINS:
        query = registry_by_domain()[domain]
        assert query.enabled is False
        assert query.sql is None
        assert query.blocked_reason
        assert query.metadata["status"] == "BLOCKED"


def test_blocked_domains_are_excluded_from_enabled_queries(monkeypatch):
    from runtime.knowledge_graph import source_registry as registry

    original = registry.SOURCE_QUERIES
    blocked = registry.SourceQuery(
        domain="occurrences",
        query_id="x",
        sql=None,
        required_columns=CONTRACT_REQUIRED,
        enabled=False,
        blocked_reason="SOURCE MISSING",
    )
    monkeypatch.setattr(registry, "SOURCE_QUERIES", (blocked,) + original[1:])
    assert "occurrences" not in registry.enabled_queries()
    assert registry.blocked_domains()["occurrences"] == "SOURCE MISSING"


# ---- SQL safety ----

@pytest.mark.parametrize("bad", [
    "insert into t values (1)",
    "update t set x=1",
    "delete from t",
    "drop table t",
    "truncate t",
    "alter table t add column c int",
    "grant select on t to public",
    "create table t (id int)",
    "select 1; drop table t",
    "select 1; select 2",
    "copy t to '/tmp/x'",
    "merge into t using s on (1=1)",
    "",
    "   ",
])
def test_unsafe_sql_is_rejected(bad):
    with pytest.raises(UnsafeSQLError):
        assert_safe_sql(bad)


@pytest.mark.parametrize("good", [
    "select 1",
    "SELECT a, b FROM oc_atlas.occurrences WHERE x IS NOT NULL",
    "with c as (select 1 as n) select n from c",
    "select 1 -- trailing comment\n",
    "select 1;",
])
def test_safe_select_is_accepted(good):
    assert_safe_sql(good)


def test_every_registered_query_is_safe():
    for query in SOURCE_QUERIES:
        if query.sql:
            assert_safe_sql(query.sql)


def test_provider_rejects_unsafe_sql_on_construction():
    with pytest.raises(UnsafeSQLError):
        PostgresSourceProvider("postgresql://ignored", {"x": "delete from t"})


def test_provider_from_registry_builds_without_db():
    provider = PostgresSourceProvider.from_registry("postgresql://ignored")
    assert set(provider._queries) == ENABLED_DOMAINS  # noqa: SLF001


# ---- taxon mapping & adapter output shape ----

def _backbone():
    return InMemoryGraphRepository([
        Node(1, "taxon", canonical_key("taxon", 1001), "Cattleya labiata",
             "public.taxonomy_species", "1001", "curated", 1.0, "high"),
        Node(2, "taxon", canonical_key("taxon", 2001), "Dracula vampira",
             "public.taxonomy_species", "2001", "curated", 1.0, "high"),
    ])


def test_direct_mapped_occurrence_row_projects_node_and_edge():
    adapter = adapters_by_domain()["occurrences"]
    nodes, edges = adapter.produce([
        {"source_pk": 7, "taxon_pk": 1001, "locality": "Bahia",
         "latitude": -12.0, "longitude": -38.0, "source_name": "GBIF"},
    ])
    assert len(nodes) == 1 and len(edges) == 1
    assert nodes[0].node_type == "occurrence"
    assert nodes[0].source_table == "oc_atlas.occurrences"
    assert nodes[0].payload["latitude"] == -12.0
    assert edges[0].edge_type == "occurs_at"
    assert edges[0].from_key == canonical_key("taxon", 1001)
    assert edges[0].to_key == canonical_key("occurrence", 7)
    assert edges[0].rule_name == "occurrences_build"


def test_name_join_pollinator_row_carries_provenance_and_quality():
    adapter = adapters_by_domain()["pollinators"]
    nodes, edges = adapter.produce([
        {"source_pk": 3, "taxon_pk": 1001, "partner_taxon_name": "Euglossa",
         "interaction_type": "pollinates", "evidence_class": "globi",
         "confidence_score": 0.8, "evidence_citation": "Doe 2020"},
    ])
    assert nodes[0].display_label == "Euglossa"
    assert nodes[0].evidence_class == "globi"
    assert nodes[0].confidence_score == 0.8
    assert edges[0].source_table == "oc_interactions.orchid_interaction_edges"


def test_adapter_refuses_unvalidated_rows_missing_taxon_pk():
    adapter = adapters_by_domain()["traits"]
    with pytest.raises(ValueError, match="without source_pk/taxon_pk"):
        adapter.produce([
            {"source_pk": "a", "trait_name": "flower_color"},
            {"source_pk": "b", "taxon_pk": 2001, "trait_name": "habit"},
        ])


def test_adapter_never_emits_a_taxon_node():
    for adapter in adapters_by_domain().values():
        nodes, _ = adapter.produce([{"source_pk": 1, "taxon_pk": 1001}])
        assert all(node.node_type != "taxon" for node in nodes)


# ---- zero-write guarantees with registry-shaped rows ----

def _shaped_source():
    return InMemorySourceProvider({
        "occurrences": [{"source_pk": 7, "taxon_pk": 1001, "locality": "Bahia"}],
        "traits": [{"source_pk": "t1", "taxon_pk": 1001, "trait_name": "habit",
                    "trait_value": "epiphyte", "confidence_score": 0.9}],
        "pollinators": [{"source_pk": 3, "taxon_pk": 2001,
                         "partner_taxon_name": "Euglossa"}],
        "mycorrhiza": [{"source_pk": 40, "taxon_pk": 2001, "fungal_name": "Tulasnella"}],
        "conservation": [{"source_pk": 9, "taxon_pk": 1001, "iucn_category": "EN"}],
        "climate": [{"source_pk": 1001, "taxon_pk": 1001,
                     "environmental_readiness_label": "ready"}],
        "literature": [{"source_pk": 5, "taxon_pk": 2001, "title": "A paper"}],
        "media": [{"source_pk": "m1", "taxon_pk": 1001, "caption": "flower"}],
    })


def test_audit_reads_availability_without_writing():
    repo = _backbone()
    report = BuildOrchestrator(repo, _shaped_source()).run(ExecutionMode.AUDIT)
    assert report["build"]["wrote_to_production"] is False
    assert report["preflight"]["source_availability"]["occurrences"] == 1
    assert repo.all_edges() == []


def test_dry_run_projects_edges_into_staging_only():
    repo = _backbone()
    report = BuildOrchestrator(
        repo, _shaped_source(), checkpoint_store=InMemoryCheckpointStore()
    ).run(ExecutionMode.DRY_RUN)
    assert report["build"]["wrote_to_production"] is False
    assert report["totals"]["edges_written"] == 8
    assert repo.all_edges() == []


def test_publish_authorization_remains_disabled_by_default():
    repo = _backbone()
    report = BuildOrchestrator(repo, _shaped_source()).run(ExecutionMode.PUBLISH)
    assert report["build"]["wrote_to_production"] is False
    assert report["build"]["publish_authorized"] is False
    assert repo.all_edges() == []


def test_vocabulary_is_compliant_for_every_registry_domain():
    repo = _backbone()
    report = BuildOrchestrator(
        repo, _shaped_source(), checkpoint_store=InMemoryCheckpointStore()
    ).run(ExecutionMode.DRY_RUN)
    assert report["cross_domain_validation"]["vocabulary_compliance"]["compliant"] is True


# --- BUILD-064 metadata and crosswalk evidence ----

_DOCS = _os.path.join(_os.path.dirname(__file__), "..", "docs", "crosswalks")
_B064_REQUIRED_META = (
    "status", "identifier_strategy", "join_strategy", "crosswalk_required",
    "confidence", "expected_record_count", "actual_record_count",
    "last_verification", "operator_notes",
)
_VALID_STATUS = {
    "READY", "READY WITH OPERATOR REVIEW", "PARTIALLY READY", "BLOCKED",
}


def test_every_domain_has_complete_build064_metadata():
    for domain, query in registry_by_domain().items():
        metadata = query.metadata
        for key in _B064_REQUIRED_META:
            assert key in metadata, f"{domain} missing metadata key {key}"
        assert metadata["status"] in _VALID_STATUS
        assert isinstance(metadata["crosswalk_required"], bool)
        assert isinstance(metadata["actual_record_count"], int)
        assert isinstance(metadata["expected_record_count"], int)


def test_metadata_survives_to_dict():
    for query in SOURCE_QUERIES:
        assert query.to_dict()["metadata"]["status"] in _VALID_STATUS


def test_climate_is_classified_blocked_as_proxy():
    metadata = registry_by_domain()["climate"].metadata
    assert metadata["status"] == "BLOCKED"
    assert metadata["confidence"] == "low"
    assert "proxy" in metadata["operator_notes"].lower()
    assert "bioclim" in metadata["operator_notes"].lower()


def test_name_join_domains_flag_crosswalk_required():
    for domain in ("pollinators", "mycorrhiza", "literature"):
        assert registry_by_domain()[domain].metadata["crosswalk_required"] is True


def test_literature_has_no_upstream_id_so_not_upgradable():
    metadata = registry_by_domain()["literature"].metadata
    assert metadata["join_strategy"] == "name_join"
    assert "no taxon id" in metadata["identifier_strategy"].lower()


def test_direct_id_domains_do_not_require_crosswalk():
    for domain in ("occurrences", "conservation", "media", "traits"):
        assert registry_by_domain()[domain].metadata["crosswalk_required"] is False


def _load_json(name):
    path = _os.path.join(_DOCS, name)
    if not _os.path.exists(path):
        pytest.skip(f"artifact {name} not generated in this environment")
    with open(path) as file:
        return _json.load(file)


def test_name_collision_stats_shape_and_rates():
    stats = _load_json("name_collision_statistics.json")
    for domain in ("pollinators", "mycorrhiza", "literature"):
        data = stats[domain]
        assert data["distinct_names"] >= data["names_matched_backbone"]
        assert 0.0 <= data["match_rate"] <= 1.0
        assert 0.0 <= data["orphan_rate"] <= 1.0
        assert data["orphan_names"] + data["names_matched_backbone"] >= data["distinct_names"]


def test_mycorrhiza_collision_detected():
    mycorrhiza = _load_json("name_collision_statistics.json")["mycorrhiza"]
    assert mycorrhiza["edges_after_join_fanout"] > mycorrhiza["source_rows"]
    assert mycorrhiza["colliding_names_gt1_node"] > 0


def test_crosswalk_confidence_bounds():
    crosswalk = _load_json("crosswalk_statistics.json")["orchid_taxonomy_to_backbone"]
    assert crosswalk["total_pairs"] >= crosswalk["distinct_source_ids"]
    assert crosswalk["distinct_destination_ids"] > 0
