import pytest

from runtime.knowledge_graph.production_materializer import (
    AUDIT_PRIORITY_DOMAINS,
    CONFIRMATION_TOKEN,
    materialize_verified_relationships,
    select_domains,
)


def test_audit_priority_domains_are_backed_by_verified_queries_and_adapters():
    selection = select_domains()
    assert selection.requested == AUDIT_PRIORITY_DOMAINS
    assert selection.valid is True
    assert selection.unavailable == ()
    assert set(selection.selected) == set(AUDIT_PRIORITY_DOMAINS)


def test_unverified_domain_fails_closed():
    selection = select_domains(["literature", "habitat"])
    assert selection.selected == ("literature",)
    assert selection.unavailable == ("habitat",)
    assert selection.valid is False

    with pytest.raises(ValueError, match="UNVERIFIED_OR_UNAVAILABLE_GRAPH_DOMAINS:habitat"):
        materialize_verified_relationships(
            "postgresql://not-opened",
            domains=["literature", "habitat"],
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


def test_empty_database_url_fails_before_any_execution():
    with pytest.raises(ValueError, match="DATABASE_URL_REQUIRED"):
        materialize_verified_relationships("")
