import pytest

from runtime.knowledge_graph.verified_dynamic_materializer import (
    CONFIRMATION_TOKEN,
    DYNAMIC_DOMAINS,
    VerifiedProjection,
    _dynamic_adapter,
    materialize_dynamic_relationship,
    projection_sql,
)


def test_dynamic_domains_are_limited_to_audit_blockers():
    assert DYNAMIC_DOMAINS == ("habitat", "elevation")


def test_projection_sql_requires_same_relation_identity_and_taxon_columns():
    sql = projection_sql(
        source="oc_habitat.taxon_habitat",
        source_pk_column="id",
        taxon_pk_column="taxon_id",
    )
    normalized = " ".join(sql.split())
    assert "SELECT s.id AS source_pk" in normalized
    assert "s.taxon_id AS taxon_pk" in normalized
    assert "to_jsonb(s) AS source_payload" in normalized
    assert "FROM oc_habitat.taxon_habitat s" in normalized
    assert "k.node_type='taxon'" in normalized
    assert "k.source_pk=s.taxon_id::text" in normalized


def test_dynamic_adapter_preserves_complete_source_payload_and_taxon_edge():
    projection = VerifiedProjection(
        domain="habitat",
        source="oc_habitat.taxon_habitat",
        source_pk_column="id",
        taxon_pk_column="taxon_id",
        matched_rows=1,
        sql="SELECT 1",
        node_type="habitat",
        edge_type="occupies_habitat",
    )
    adapter = _dynamic_adapter(projection)
    nodes, edges = adapter.produce(
        [
            {
                "source_pk": 17,
                "taxon_pk": 991,
                "source_payload": {
                    "id": 17,
                    "taxon_id": 991,
                    "habitat_name": "montane oak forest",
                    "substrate": "epiphytic",
                },
            }
        ]
    )
    assert len(nodes) == 1
    assert nodes[0].display_label == "montane oak forest"
    assert nodes[0].payload["source_payload"]["substrate"] == "epiphytic"
    assert len(edges) == 1
    assert edges[0].edge_type == "occupies_habitat"
    assert edges[0].source_table == "oc_habitat.taxon_habitat"


def test_dynamic_publication_requires_confirmation_before_discovery(monkeypatch):
    called = False

    def fail_if_called(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("discovery must not run before authorization guard")

    monkeypatch.setattr(
        "runtime.knowledge_graph.verified_dynamic_materializer.discover_projection",
        fail_if_called,
    )
    with pytest.raises(PermissionError, match="GRAPH_PUBLICATION_CONFIRMATION_REQUIRED"):
        materialize_dynamic_relationship(
            "postgresql://not-opened",
            domain="habitat",
            execute=True,
            confirmation="yes",
        )
    assert called is False
    assert CONFIRMATION_TOKEN == "PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS"


def test_dynamic_materializer_rejects_invalid_batch_before_discovery(monkeypatch):
    monkeypatch.setattr(
        "runtime.knowledge_graph.verified_dynamic_materializer.discover_projection",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not discover")),
    )
    with pytest.raises(ValueError, match="BATCH_SIZE_OUT_OF_RANGE"):
        materialize_dynamic_relationship(
            "postgresql://not-opened",
            domain="elevation",
            batch_size=0,
        )
