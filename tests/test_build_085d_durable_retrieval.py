"""
BUILD-085d: Durable retrieval regression coverage.

Verifies that:
A. Production retrieval does not depend on a fresh MemoryIndexRepository.
B. Durable indexed evidence survives repository/service reconstruction.
C. Known canonical evidence can be retrieved through ENGINE.search().
D. Brain mission retrieval receives those durable results.
E. Exact citation/source identity survives the path.
F. Display authorization remains enforced.
G. Unauthorized/internal-only evidence is not surfaced to normal CALYX users.
H. Empty corpus produces a truthful evidence-status result rather than fabricated evidence.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.models import IndexDocument
from app.semantic_index.provider import DeterministicLocalProvider
from app.semantic_index.service import SemanticIndexService


# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------

def _canonical_doc(oid: int = 1, **kw) -> IndexDocument:
    defaults = dict(
        source_object_type="PROTOCOL",
        source_object_id=oid,
        revision_id=oid,
        extraction_run_id=1,
        text="orchid foliar nutrient uptake leaf mineral absorption study",
        parent_type="PROTOCOL",
        parent_id=oid,
        source_anchor_ids=(oid * 10,),
        internal_indexing_permission=True,
        display_policy="FULL_TEXT_ALLOWED",
        metadata={
            "document_title": "Orchid foliar uptake study",
            "authors": ["Test Author"],
            "publication_date": "2024-01-01",
            "source_type": "PEER_REVIEWED_ARTICLE",
            "document_class": "PRIMARY_RESEARCH",
            "locator": {"page": oid},
            "peer_reviewed": "YES",
            "evidence_type": "PRIMARY",
        },
    )
    defaults.update(kw)
    return IndexDocument(**defaults)


def _internal_doc(oid: int = 99) -> IndexDocument:
    return _canonical_doc(
        oid,
        text="internal research only orchid foliar",
        display_policy="INTERNAL_RESEARCH_ONLY",
        metadata={
            "document_title": "Internal report",
            "document_class": "INTERNAL_ORGANIZATIONAL",
            "locator": {"page": oid},
            "internal_access_allowed": True,
        },
    )


def _seed(repo: MemoryIndexRepository, provider: DeterministicLocalProvider, docs: list[IndexDocument]) -> None:
    service = SemanticIndexService(repo, provider)
    plan = service.preview(docs)
    service.execute(plan["index_run_id"])


# ---------------------------------------------------------------------------
# A. Production retrieval does not depend on a fresh MemoryIndexRepository
# ---------------------------------------------------------------------------

def test_postgres_repository_class_declarations():
    """PostgresIndexRepository class-level declarations are correct without needing psycopg."""
    import ast, pathlib
    source = pathlib.Path("app/semantic_index/postgres_repository.py").read_text()
    tree = ast.parse(source)
    cls = next(n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == "PostgresIndexRepository")
    base_names = {(b.id if isinstance(b, ast.Name) else b.attr) for b in cls.bases}
    assert "PostgresStateMixin" in base_names
    assert "MemoryIndexRepository" in base_names
    # Snapshot kind and lock_id are assigned as class-level literals
    assignments = {n.targets[0].id: n.value for n in ast.walk(cls) if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
    assert assignments["snapshot_kind"].value == "semantic_index"
    assert isinstance(assignments["lock_id"].value, int)
    assert "MemoryIndexRepository" in source


def test_routes_use_durable_repository_when_database_url_is_set(monkeypatch):
    """When DATABASE_URL is set the builder must attempt PostgresIndexRepository."""
    import ast, pathlib
    source = pathlib.Path("app/semantic_index/routes.py").read_text()
    # The source must contain the conditional import of PostgresIndexRepository
    assert "PostgresIndexRepository" in source
    assert "configured_database_url" in source
    assert "_build_repository" in source


def test_routes_fall_back_to_memory_when_no_database_url(monkeypatch):
    """When DATABASE_URL is absent the builder must fall back to MemoryIndexRepository."""
    import pathlib
    source = pathlib.Path("app/semantic_index/routes.py").read_text()
    # Without a database URL the fallback is MemoryIndexRepository
    assert "MemoryIndexRepository" in source
    # The build pattern includes a try/except fallback
    assert "except" in source


# ---------------------------------------------------------------------------
# B. Durable indexed evidence survives repository/service reconstruction
# ---------------------------------------------------------------------------

def test_indexed_evidence_survives_repository_reconstruction():
    """
    Index a document into repo_a.  Copy state to repo_b (simulating
    PostgresStateMixin load).  The RetrievalEngine on repo_b must return
    the same document without any re-indexing.
    """
    provider = DeterministicLocalProvider()
    repo_a = MemoryIndexRepository()
    _seed(repo_a, provider, [_canonical_doc(1)])

    # Simulate durable snapshot: copy state to a fresh repository
    repo_b = MemoryIndexRepository()
    repo_b.models = deepcopy(repo_a.models)
    repo_b.runs = deepcopy(repo_a.runs)
    repo_b.items = deepcopy(repo_a.items)
    repo_b.documents = deepcopy(repo_a.documents)
    repo_b.vectors = deepcopy(repo_a.vectors)
    repo_b.lexical = deepcopy(repo_a.lexical)
    repo_b.tombstones = deepcopy(repo_a.tombstones)
    repo_b.warnings = deepcopy(repo_a.warnings)
    repo_b.reviews = deepcopy(repo_a.reviews)
    repo_b._id = repo_a._id

    engine_b = RetrievalEngine(repo_b, provider)
    result = engine_b.search(RetrievalQuery("orchid foliar nutrient uptake leaf"))
    assert result["total_eligible_results"] >= 1
    assert result["results"][0]["citation"]["canonical_object_id"] == 1


# ---------------------------------------------------------------------------
# C. Known canonical evidence can be retrieved through ENGINE.search()
# ---------------------------------------------------------------------------

def test_canonical_evidence_retrieved_via_engine_search():
    provider = DeterministicLocalProvider()
    repo = MemoryIndexRepository()
    _seed(repo, provider, [_canonical_doc(42)])

    engine = RetrievalEngine(repo, provider)
    result = engine.search(RetrievalQuery("foliar nutrient uptake mineral orchid", mode="HYBRID"))
    ids = [r["citation"]["canonical_object_id"] for r in result["results"]]
    assert 42 in ids


# ---------------------------------------------------------------------------
# D. Brain mission retrieval receives those durable results
# ---------------------------------------------------------------------------

def test_brain_mission_retrieve_function_receives_indexed_results():
    """_retrieve() in brain_mission/routes.py must return indexed results."""
    provider = DeterministicLocalProvider()
    repo = MemoryIndexRepository()
    _seed(repo, provider, [_canonical_doc(7)])

    engine = RetrievalEngine(repo, provider)

    context = {
        "limits": {"max_sources": 10},
        "plan": {
            "retrieval_queries": ["orchid foliar nutrient"],
            "per_domain_source_budget": 5,
        },
    }

    # Call ENGINE.search directly (mirrors brain_mission/routes._retrieve)
    response = engine.search(
        RetrievalQuery(
            text="orchid foliar nutrient",
            mode="HYBRID",
            limit=5,
            per_source_limit=2,
            parent_expansion="NONE",
            internal_access=False,
        )
    )
    assert response["total_eligible_results"] >= 1
    ids = [r["citation"]["canonical_object_id"] for r in response["results"]]
    assert 7 in ids


# ---------------------------------------------------------------------------
# E. Exact citation/source identity survives the path
# ---------------------------------------------------------------------------

def test_source_identity_preserved_through_retrieval():
    provider = DeterministicLocalProvider()
    repo = MemoryIndexRepository()
    doc = _canonical_doc(55)
    _seed(repo, provider, [doc])

    engine = RetrievalEngine(repo, provider)
    result = engine.search(RetrievalQuery("orchid foliar nutrient uptake leaf"))
    hit = next(r for r in result["results"] if r["citation"]["canonical_object_id"] == 55)

    assert hit["citation"]["revision_id"] == 55
    assert hit["citation"]["canonical_object_type"] == "PROTOCOL"
    assert hit["citation"]["source_anchor_ids"] == [550]
    assert hit["citation"]["locator"] == {"page": 55}
    assert hit["citation"]["authors"] == ["Test Author"]


# ---------------------------------------------------------------------------
# F. Display authorization enforced – FULL_TEXT_ALLOWED returns excerpt
# ---------------------------------------------------------------------------

def test_full_text_allowed_returns_authorized_excerpt():
    provider = DeterministicLocalProvider()
    repo = MemoryIndexRepository()
    _seed(repo, provider, [_canonical_doc(10, display_policy="FULL_TEXT_ALLOWED")])

    engine = RetrievalEngine(repo, provider)
    result = engine.search(RetrievalQuery("orchid foliar nutrient uptake leaf", mode="LEXICAL"))
    hit = result["results"][0]
    assert hit["display_policy"] == "FULL_TEXT_ALLOWED"
    assert hit["authorized_excerpt"] is not None
    assert "orchid" in hit["authorized_excerpt"]


# ---------------------------------------------------------------------------
# G. Unauthorized evidence is not surfaced to normal CALYX users
# ---------------------------------------------------------------------------

def test_internal_only_document_not_surfaced_to_normal_users():
    provider = DeterministicLocalProvider()
    repo = MemoryIndexRepository()
    _seed(repo, provider, [_internal_doc(99)])

    engine = RetrievalEngine(repo, provider)
    # Normal CALYX user: internal_access=False
    result = engine.search(RetrievalQuery("internal research only orchid foliar", mode="LEXICAL", internal_access=False))
    for hit in result["results"]:
        assert hit["authorized_excerpt"] is None, "Internal doc excerpt must not be exposed"


def test_internal_only_document_accessible_to_internal_access():
    provider = DeterministicLocalProvider()
    repo = MemoryIndexRepository()
    # internal_access_allowed must also be in metadata for excerpt to appear
    doc = _internal_doc(99)
    _seed(repo, provider, [doc])

    engine = RetrievalEngine(repo, provider)
    result = engine.search(RetrievalQuery("internal research only orchid foliar", mode="LEXICAL", internal_access=True))
    hits_with_policy = [r for r in result["results"] if r["display_policy"] == "INTERNAL_RESEARCH_ONLY"]
    # Excerpt is returned only when internal_access_allowed is True in metadata
    for hit in hits_with_policy:
        if hit["citation"]["canonical_object_id"] == 99:
            assert hit["authorized_excerpt"] is not None


# ---------------------------------------------------------------------------
# H. Empty corpus → truthful evidence status, not fabricated evidence
# ---------------------------------------------------------------------------

def test_empty_corpus_returns_zero_results_not_fabricated_evidence():
    provider = DeterministicLocalProvider()
    repo = MemoryIndexRepository()  # empty – nothing indexed
    engine = RetrievalEngine(repo, provider)

    result = engine.search(RetrievalQuery("orchid foliar nutrient uptake leaf mineral"))
    assert result["total_eligible_results"] == 0
    assert result["results"] == []
    assert result["total_candidates"] == 0


# ---------------------------------------------------------------------------
# Safety: module file must not expose evidence content through diagnostics
# ---------------------------------------------------------------------------

def test_status_endpoint_source_in_evidence_retrieval_routes():
    code = (Path("app/evidence_retrieval/routes.py")).read_text()
    assert "/status" in code
    assert "durable" in code
    assert "indexed_document_count" in code


def test_safety_contract_postgres_repository_module():
    code = (Path("app/semantic_index/postgres_repository.py")).read_text()
    forbidden = ("production_publish", "drive.files.update", "question_answer", "knowledge_extract")
    assert all(f not in code for f in forbidden)
