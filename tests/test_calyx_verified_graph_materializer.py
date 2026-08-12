import pytest

import runtime.knowledge_graph.production_materializer as materializer
from runtime.knowledge_graph.production_materializer import (
    AUDIT_PRIORITY_DOMAINS,
    CONFIRMATION_TOKEN,
    DEFAULT_DRY_RUN_MAX_ROWS_PER_DOMAIN,
    materialize_verified_relationships,
    select_domains,
)


def test_audit_priority_domains_are_backed_by_verified_queries_and_adapters():
    selection = select_domains()
    assert selection.requested == AUDIT_PRIORITY_DOMAINS
    assert selection.valid is True
    assert selection.unavailable == ()
    assert set(selection.selected) == set(AUDIT_PRIORITY_DOMAINS)


def test_unverified_domain_fails_closed_before_database_access():
    selection = select_domains(["literature", "habitat"])
    assert selection.selected == ("literature",)
    assert selection.unavailable == ("habitat",)
    assert selection.valid is False

    with pytest.raises(
        ValueError,
        match="UNVERIFIED_OR_UNAVAILABLE_GRAPH_DOMAINS:habitat",
    ):
        materialize_verified_relationships(
            "postgresql://not-opened",
            domains=["literature", "habitat"],
        )


def test_production_requires_explicit_domain_list():
    with pytest.raises(ValueError, match="EXPLICIT_PRODUCTION_DOMAINS_REQUIRED"):
        materialize_verified_relationships(
            "postgresql://not-opened",
            execute=True,
            confirmation=CONFIRMATION_TOKEN,
        )


def test_production_publication_requires_exact_confirmation_before_database_write():
    with pytest.raises(PermissionError, match="GRAPH_PUBLICATION_CONFIRMATION_REQUIRED"):
        materialize_verified_relationships(
            "postgresql://not-opened",
            domains=["literature"],
            execute=True,
            confirmation="yes",
        )

    assert CONFIRMATION_TOKEN == "PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS"


def test_dry_run_is_bounded_and_uses_controlled_two_pass_engine(monkeypatch):
    captured = {}

    class DummySource:
        def __init__(self, dsn, queries):
            captured["source_dsn"] = dsn
            captured["queries"] = tuple(queries)

    def fake_dry_run(repo, source, *, adapters, max_rows_per_domain, batch_size):
        captured["repo"] = repo
        captured["source"] = source
        captured["domains"] = tuple(adapter.domain for adapter in adapters)
        captured["maximum"] = max_rows_per_domain
        captured["batch_size"] = batch_size
        return {
            "contract": "calyx-controlled-graph-dry-run-v1",
            "graph_mutation": False,
            "publication_authorization_ready": False,
        }

    monkeypatch.setattr(materializer, "PostgresSourceProvider", DummySource)
    monkeypatch.setattr(
        materializer,
        "PostgresGraphRepository",
        lambda dsn: ("readonly-graph", dsn),
    )
    monkeypatch.setattr(materializer, "run_controlled_dry_run", fake_dry_run)

    report = materialize_verified_relationships(
        "postgresql://example",
        domains=["literature", "occurrences"],
        batch_size=250,
    )

    assert captured["domains"] == ("literature", "occurrences")
    assert captured["maximum"] == DEFAULT_DRY_RUN_MAX_ROWS_PER_DOMAIN
    assert captured["batch_size"] == 250
    assert report["materialization"]["production_graph_mutation"] is False
    assert report["materialization"]["bounded_validation"] is True


def test_production_delegates_to_transactional_single_writer_publisher(monkeypatch):
    captured = {}

    def fake_publish(dsn, *, adapters, batch_size):
        captured["dsn"] = dsn
        captured["domains"] = tuple(adapter.domain for adapter in adapters)
        captured["batch_size"] = batch_size
        return {
            "healthy": True,
            "committed": True,
            "per_domain": [
                {
                    "domain": "literature",
                    "status": "completed",
                    "rows_processed": 8,
                    "nodes_written": 7,
                    "edges_written": 8,
                    "error": None,
                }
            ],
        }

    monkeypatch.setattr(materializer, "publish_to_production", fake_publish)

    report = materialize_verified_relationships(
        "postgresql://example",
        domains=["literature"],
        execute=True,
        confirmation=CONFIRMATION_TOKEN,
        batch_size=100,
    )

    assert captured == {
        "dsn": "postgresql://example",
        "domains": ("literature",),
        "batch_size": 100,
    }
    status = report["materialization"]
    assert status["transactional"] is True
    assert status["single_writer_lock"] is True
    assert status["production_graph_mutation"] is True
    assert status["publication_summary"]["rows_processed"] == 8
    assert status["publication_summary"]["edges_written"] == 8


def test_failed_transaction_is_not_reported_as_production_mutation(monkeypatch):
    monkeypatch.setattr(
        materializer,
        "publish_to_production",
        lambda *_args, **_kwargs: {
            "healthy": False,
            "committed": False,
            "per_domain": [
                {
                    "domain": "literature",
                    "status": "failed",
                    "rows_processed": 2,
                    "nodes_written": 1,
                    "edges_written": 0,
                    "error": "source contract mismatch",
                }
            ],
        },
    )

    report = materialize_verified_relationships(
        "postgresql://example",
        domains=["literature"],
        execute=True,
        confirmation=CONFIRMATION_TOKEN,
    )

    status = report["materialization"]
    assert status["production_graph_mutation"] is False
    assert status["publication_summary"]["committed"] is False
    assert status["publication_summary"]["failed_domains"] == ["literature"]


def test_limits_and_empty_database_url_fail_before_execution():
    with pytest.raises(ValueError, match="DATABASE_URL_REQUIRED"):
        materialize_verified_relationships("")

    with pytest.raises(ValueError, match="BATCH_SIZE_OUT_OF_RANGE"):
        materialize_verified_relationships(
            "postgresql://not-opened",
            domains=["literature"],
            batch_size=0,
        )

    with pytest.raises(ValueError, match="DRY_RUN_ROW_LIMIT_MUST_BE_POSITIVE"):
        materialize_verified_relationships(
            "postgresql://not-opened",
            domains=["literature"],
            max_dry_run_rows_per_domain=0,
        )
