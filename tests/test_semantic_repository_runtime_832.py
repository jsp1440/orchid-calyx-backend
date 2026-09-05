from app.evidence_retrieval import routes as evidence_routes
from app.semantic_index import repository_runtime, routes as semantic_routes
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.repository_runtime import SemanticIndexRepositoryRuntime


def test_semantic_and_evidence_routes_share_one_repository_runtime(monkeypatch):
    runtime = SemanticIndexRepositoryRuntime(database_url="")
    repository = MemoryIndexRepository()
    runtime._activate(repository)
    monkeypatch.setattr(repository_runtime, "RUNTIME", runtime)

    assert semantic_routes.get_repository_for_read() is repository
    assert evidence_routes._repo() is repository
    assert evidence_routes._engine().repo is repository


def test_evidence_route_does_not_own_repository_or_engine_globals():
    assert not hasattr(evidence_routes, "REPO")
    assert not hasattr(evidence_routes, "ENGINE")


def test_runtime_recreation_can_attach_fresh_repository_without_route_mutation(
    monkeypatch,
):
    first = SemanticIndexRepositoryRuntime(database_url="")
    first_repository = MemoryIndexRepository()
    first._activate(first_repository)
    monkeypatch.setattr(repository_runtime, "RUNTIME", first)

    assert evidence_routes._repo() is first_repository

    recreated = SemanticIndexRepositoryRuntime(database_url="")
    recreated_repository = MemoryIndexRepository()
    recreated._activate(recreated_repository)
    monkeypatch.setattr(repository_runtime, "RUNTIME", recreated)

    assert semantic_routes.get_repository_for_read() is recreated_repository
    assert evidence_routes._repo() is recreated_repository
    assert recreated_repository is not first_repository


def test_runtime_status_preserves_unavailable_not_zero_semantics():
    runtime = SemanticIndexRepositoryRuntime(database_url="postgresql://configured")
    runtime._mark_unavailable()

    status = runtime.status()

    assert status["retrieval_backend"] == "UNAVAILABLE"
    assert status["degraded"] is True
    assert status["unavailable"] is True
    assert status["index_error"] == "SEMANTIC_INDEX_DATABASE_UNAVAILABLE"
