from runtime.knowledge_graph.dynamic_source_projection import build_projection, build_projection_report
from runtime.knowledge_graph.full_integration import DomainInventory


def inventory(**overrides):
    base = dict(
        domain="habitat",
        configured_status="production",
        configured_source="oc_habitat.*",
        discovered_sources=("oc_habitat.taxon_habitat",),
        state="available",
        row_count=3,
        taxon_key_columns=("taxon_id",),
        identity_columns=("id",),
        node_type="habitat",
        edge_type="occupies_habitat",
        limitation=None,
    )
    base.update(overrides)
    return DomainInventory(**base)


def test_direct_keyed_source_builds_safe_projection():
    plan = build_projection(inventory())
    assert plan.executable is True
    assert plan.source_pk_column == "id"
    assert plan.taxon_pk_column == "taxon_id"
    assert plan.sql.startswith("SELECT")
    assert "oc_graph.kg_nodes" in plan.sql


def test_name_only_source_is_blocked_not_guessed():
    plan = build_projection(inventory(taxon_key_columns=()))
    assert plan.executable is False
    assert plan.state == "blocked"
    assert "crosswalk" in plan.limitation


def test_missing_identity_is_blocked():
    plan = build_projection(inventory(identity_columns=()))
    assert plan.executable is False
    assert plan.state == "blocked"
    assert "identity" in plan.limitation


def test_staging_domain_is_withheld():
    plan = build_projection(inventory(configured_status="staging_only"))
    assert plan.state == "withheld"
    assert plan.executable is False


def test_projection_report_is_fail_closed():
    report = build_projection_report([
        inventory(domain="habitat"),
        inventory(domain="molecular", taxon_key_columns=()),
    ])
    assert report["fully_projectable"] is False
    assert report["ready_domains"] == ["habitat"]
    assert report["blocked_domains"] == ["molecular"]
