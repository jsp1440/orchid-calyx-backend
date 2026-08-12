from types import SimpleNamespace

import pytest

from runtime.knowledge_graph.paper_knowledge_graph import PaperGraphBundle
from runtime.knowledge_graph.reviewed_literature_materializer import (
    CONFIRMATION_TOKEN,
    PreparedLiteratureGraph,
    materialize_reviewed_literature_graph,
)


def _prepared(document_id: int = 101) -> PreparedLiteratureGraph:
    return PreparedLiteratureGraph(
        document_id=document_id,
        paper_id="paper-1",
        binding_fingerprint="binding-1",
        source_hash="0123456789abcdef",
        bundle=PaperGraphBundle(
            nodes=(),
            edges=(),
            candidate_objects_omitted=0,
            publication_key="publication:paper-1",
        ),
        exact_taxon_resolutions=0,
        unresolved_taxon_entity_ids=(),
        ambiguous_taxon_entity_ids=(),
    )


def _valid_report(document_id: int = 101):
    return {
        "contract": "calyx-reviewed-literature-graph-materialization-v1",
        "requested_document_ids": [document_id],
        "ready_document_ids": [document_id],
        "documents": {str(document_id): {"status": "ready", "valid": True}},
        "valid": True,
        "production_graph_mutation": False,
        "confirmation_required": CONFIRMATION_TOKEN,
    }


def test_explicit_document_ids_are_required_before_any_plan(monkeypatch):
    called = False

    def fake_prepare(*args, **kwargs):
        nonlocal called
        called = True
        return [], {}

    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer._prepare",
        fake_prepare,
    )
    with pytest.raises(ValueError, match="EXPLICIT_LITERATURE_DOCUMENT_IDS_REQUIRED"):
        materialize_reviewed_literature_graph("postgres://example", document_ids=[])
    assert called is False


def test_dry_run_never_requests_writable_repository(monkeypatch):
    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer._prepare",
        lambda *args, **kwargs: ([_prepared()], _valid_report()),
    )

    def forbidden_writer(*args, **kwargs):
        raise AssertionError("dry run must not open writable graph repository")

    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer.WritablePostgresGraphRepository",
        forbidden_writer,
    )
    result = materialize_reviewed_literature_graph(
        "postgres://example",
        document_ids=[101],
        execute=False,
    )
    assert result["mode"] == "dry_run"
    assert result["production_graph_mutation"] is False
    assert result["bounded_validation"] is True


def test_execute_requires_exact_confirmation_before_preparation(monkeypatch):
    called = False

    def fake_prepare(*args, **kwargs):
        nonlocal called
        called = True
        return [_prepared()], _valid_report()

    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer._prepare",
        fake_prepare,
    )
    with pytest.raises(
        PermissionError,
        match="REVIEWED_LITERATURE_PUBLICATION_CONFIRMATION_REQUIRED",
    ):
        materialize_reviewed_literature_graph(
            "postgres://example",
            document_ids=[101],
            execute=True,
            confirmation="wrong",
        )
    assert called is False


def test_invalid_plan_blocks_before_writable_repository(monkeypatch):
    report = _valid_report()
    report["valid"] = False
    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer._prepare",
        lambda *args, **kwargs: ([], report),
    )

    def forbidden_writer(*args, **kwargs):
        raise AssertionError("invalid plan must not open writable graph repository")

    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer.WritablePostgresGraphRepository",
        forbidden_writer,
    )
    with pytest.raises(ValueError, match="REVIEWED_LITERATURE_PUBLICATION_PLAN_INVALID"):
        materialize_reviewed_literature_graph(
            "postgres://example",
            document_ids=[101],
            execute=True,
            confirmation=CONFIRMATION_TOKEN,
        )


def test_authorized_valid_slice_commits_once(monkeypatch):
    prepared = _prepared()
    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer._prepare",
        lambda *args, **kwargs: ([prepared], _valid_report()),
    )

    class FakeRepo:
        def __init__(self):
            self.locked = 0
            self.committed = 0
            self.rolled_back = 0
            self.closed = 0

        def acquire_publication_lock(self):
            self.locked += 1

        def commit(self):
            self.committed += 1

        def rollback(self):
            self.rolled_back += 1

        def close(self):
            self.closed += 1

    repo = FakeRepo()
    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer.WritablePostgresGraphRepository",
        lambda dsn: repo,
    )
    monkeypatch.setattr(
        "runtime.knowledge_graph.reviewed_literature_materializer.publish_domain",
        lambda *args, **kwargs: SimpleNamespace(
            nodes_written=3,
            edges_written=4,
            skipped_existing_nodes=0,
            skipped_existing_edges=0,
            invalid=[],
        ),
    )

    result = materialize_reviewed_literature_graph(
        "postgres://example",
        document_ids=[101],
        execute=True,
        confirmation=CONFIRMATION_TOKEN,
    )

    assert result["committed"] is True
    assert result["production_graph_mutation"] is True
    assert repo.locked == 1
    assert repo.committed == 1
    assert repo.rolled_back == 0
    assert repo.closed == 1
