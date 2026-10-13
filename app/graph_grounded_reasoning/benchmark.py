"""Reproducible baseline-versus-graph-grounded comparison on a frozen fixture.

Both systems receive the same questions and are scored by the same criteria.
The baseline is the existing literature-only path: one hybrid
``RetrievalEngine`` search over the raw question text, answering from the top
lexically-matched documents (the shape of ``/calyx/query`` retrieval).  No
model provider is called by either system, so provider cost is zero by
construction rather than by measurement of a paid run.
"""

from __future__ import annotations

import json
import platform
import statistics
import time
from collections.abc import Callable
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.provider import DeterministicLocalProvider
from runtime.knowledge_graph.canonical_taxonomy import (
    WorldPlantsRelease,
    build_canonical_registry,
)
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository

from .contracts import CONTRACT_VERSION, ScientificQuestion
from .pipeline import GraphGroundedReasoner

BENCHMARK_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "graph_grounded_reasoning"
BASELINE_ID = "literature-only-hybrid-retrieval-085b"
BASELINE_TOP_K = 3
ABSTAIN = "INSUFFICIENT_EVIDENCE"


def load_json(name: str) -> dict[str, Any]:
    return json.loads((BENCHMARK_DIR / name).read_text())


def build_environment(fixture: dict[str, Any]):
    reg = fixture["registry"]
    release = WorldPlantsRelease(
        snapshot_id=reg["release"]["snapshot_id"],
        source_system="fixture",
        version_label=reg["release"]["version_label"],
        file_sha256=None,
        row_count=len(reg["load_rows"]),
        acquired_at=None,
        notes="synthetic fixture; not a World Plants release",
    )
    registry = build_canonical_registry(
        reg["load_rows"], reg["synonym_rows"], canonical_release=release
    )
    nodes = [
        Node(
            kg_node_id=n["id"],
            node_type=n["type"],
            canonical_key=n["key"],
            display_label=n["label"],
            source_table="fixture.nodes",
            source_pk=str(n["id"]),
            payload=n.get("payload", {}),
        )
        for n in fixture["graph"]["nodes"]
    ]
    edges = [
        Edge(
            kg_edge_id=e["id"],
            edge_type=e["type"],
            from_node_id=e["from"],
            to_node_id=e["to"],
            source_table="fixture.edges",
            source_pk=str(e["id"]),
            evidence_class="fixture",
            payload=e.get("payload", {}),
        )
        for e in fixture["graph"]["edges"]
    ]
    graph = InMemoryGraphRepository(nodes, edges)

    index = MemoryIndexRepository()
    provider = DeterministicLocalProvider()
    model = index.ensure_model(provider.metadata)
    for number, doc in enumerate(fixture["documents"], start=1):
        text = doc["text"]
        meta = {
            "display_policy": "FULL_TEXT_ALLOWED",
            "document_id": doc["id"],
            "document_title": doc["title"],
            "title": doc["title"],
            "verification_state": "VERIFIED",
            **doc.get("metadata", {}),
        }
        if doc.get("locator"):
            meta["locator"] = doc["locator"]
        index.documents.append(
            {
                "index_document_id": number,
                "source_object_type": "LITERATURE_PASSAGE",
                "source_object_id": number,
                "revision_id": f"{doc['id']}@r1",
                "parent_type": "LITERATURE_PASSAGE",
                "parent_id": number,
                "anchors": (number * 10,),
                "content_hash": sha256(text.encode()).hexdigest(),
                "metadata_hash": str(number),
                "model_id": model,
                "configuration_hash": "fixture",
                "active": True,
                "version": 1,
                "metadata": meta,
            }
        )
        index.lexical.append(
            {
                "index_document_id": number,
                "normalized_text": text.casefold(),
                "verbatim_text": text,
                "language": "en",
                "title": doc["title"],
            }
        )
        index.vectors.append(
            {
                "index_document_id": number,
                "vector": provider.embed_batch([text])[0],
                "active": True,
            }
        )
    engine = RetrievalEngine(index, provider)
    return registry, graph, engine


def fixture_taxon_node_key(fixture: dict[str, Any], registry) -> Callable[[int], str]:
    """Map registry ids to fixture graph keys by accepted name, never by id."""

    by_name = {n["label"]: n["key"] for n in fixture["graph"]["nodes"] if n["type"] == "taxon"}

    def key(canonical_id: int) -> str:
        name = registry.taxa[canonical_id].canonical_name
        return by_name.get(name, f"taxon:unmapped:{canonical_id}")

    return key


def baseline_answer(engine: RetrievalEngine, question: ScientificQuestion) -> dict[str, Any]:
    started = time.perf_counter()
    result = engine.search(
        RetrievalQuery(text=question.text, mode="HYBRID", limit=10, parent_expansion="NONE")
    )
    hits = [r for r in result["results"] if r["score_breakdown"]["lexical"] > 0][:BASELINE_TOP_K]
    docs = [r["citation"]["document_id"] for r in hits]
    return {
        "state": "CANDIDATE" if docs else ABSTAIN,
        "cited_documents": docs,
        "conflict_documents": [],
        "latency_ms": round((time.perf_counter() - started) * 1000, 3),
        "provider_calls": 0,
    }


def grounded_answer(reasoner: GraphGroundedReasoner, question: ScientificQuestion) -> dict[str, Any]:
    started = time.perf_counter()
    result = reasoner.answer(question)
    latency = round((time.perf_counter() - started) * 1000, 3)
    docs = sorted({c["document_id"] for c in result["citations"].values() if c})
    packet = {i["ref"]: i for i in result["evidence_packet"]["items"]}
    conflict_docs = sorted(
        {
            packet[ref]["provenance"]["source_document_id"]
            for pair in result["conflicts"]
            for ref in pair
            if packet[ref]["provenance"]["source_document_id"]
        }
    )
    return {
        "state": result["state"],
        "cited_documents": docs,
        "conflict_documents": conflict_docs,
        "latency_ms": latency,
        "provider_calls": result["governance"]["provider_calls"],
        "validation_passed": result["validation"]["passed"],
        "resolution_state": result["resolution"]["state"],
    }


def score_case(case: dict[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    expected = set(case["expected_documents"])
    cited = set(answer["cited_documents"])
    unsupported = sorted(cited - expected)
    precision = len(cited & expected) / len(cited) if cited else (1.0 if not expected else 0.0)
    recall = len(cited & expected) / len(expected) if expected else (1.0 if not cited else 0.0)
    expected_conflict = set(case["expected_conflict_documents"])
    return {
        "case_id": case["case_id"],
        "category": case["category"],
        "expected_state": case["expected_state"],
        "state": answer["state"],
        "state_correct": answer["state"] == case["expected_state"],
        "answer_abstain_correct": (answer["state"] == ABSTAIN) == (case["expected_state"] == ABSTAIN),
        "citation_precision": round(precision, 4),
        "citation_recall": round(recall, 4),
        "unsupported_citations": unsupported,
        "conflict_retained": (
            expected_conflict <= set(answer["conflict_documents"]) if expected_conflict else None
        ),
        "latency_ms": answer["latency_ms"],
        "provider_calls": answer["provider_calls"],
    }


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    expected_abstain = [r for r in rows if r["expected_state"] == ABSTAIN]
    abstained = [r for r in rows if r["state"] == ABSTAIN]
    correct_abstain = [r for r in abstained if r["expected_state"] == ABSTAIN]
    conflicts = [r for r in rows if r["conflict_retained"] is not None]
    return {
        "cases": n,
        "state_accuracy": round(sum(r["state_correct"] for r in rows) / n, 4),
        "answer_abstain_accuracy": round(sum(r["answer_abstain_correct"] for r in rows) / n, 4),
        "mean_citation_precision": round(statistics.mean(r["citation_precision"] for r in rows), 4),
        "mean_citation_recall": round(statistics.mean(r["citation_recall"] for r in rows), 4),
        "unsupported_citation_count": sum(len(r["unsupported_citations"]) for r in rows),
        "abstention_precision": (
            round(len(correct_abstain) / len(abstained), 4) if abstained else None
        ),
        "abstention_recall": (
            round(len(correct_abstain) / len(expected_abstain), 4) if expected_abstain else None
        ),
        "conflict_retention_rate": (
            round(sum(bool(r["conflict_retained"]) for r in conflicts) / len(conflicts), 4)
            if conflicts
            else None
        ),
        "median_latency_ms": round(statistics.median(r["latency_ms"] for r in rows), 3),
        "provider_calls": sum(r["provider_calls"] or 0 for r in rows),
        "provider_cost_usd": 0.0,
    }


def run_benchmark(clock: Callable[[], str] | None = None) -> dict[str, Any]:
    fixture = load_json("fixture.json")
    suite = load_json("cases.json")
    registry, graph, engine = build_environment(fixture)
    reasoner = GraphGroundedReasoner(
        registry, graph, fixture_taxon_node_key(fixture, registry), search=engine.search
    )
    systems: dict[str, list[dict[str, Any]]] = {BASELINE_ID: [], CONTRACT_VERSION: []}
    for case in suite["cases"]:
        question = ScientificQuestion(case["question"], case["facet"])
        systems[BASELINE_ID].append(score_case(case, baseline_answer(engine, question)))
        systems[CONTRACT_VERSION].append(score_case(case, grounded_answer(reasoner, question)))
    return {
        "benchmark_id": suite["benchmark_id"],
        "fixture_id": suite["fixture_id"],
        "fixture_sha256": sha256((BENCHMARK_DIR / "fixture.json").read_bytes()).hexdigest(),
        "cases_sha256": sha256((BENCHMARK_DIR / "cases.json").read_bytes()).hexdigest(),
        "label_source": suite["label_source"],
        "expert_reviewed": suite["expert_reviewed"],
        "interpretation": (
            "Synthetic contract benchmark. Differences show which safeguards each "
            "path enforces on identical inputs; they are not estimates of botanical "
            "accuracy on real orchid literature."
        ),
        "generated_at": clock() if clock else None,
        "environment": {"python": platform.python_version()},
        "systems": {
            name: {"summary": aggregate(rows), "cases": rows} for name, rows in systems.items()
        },
    }
