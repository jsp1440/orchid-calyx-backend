from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.health import router
from runtime.executive.dependencies import dependency_graph, reverse_dependencies
from runtime.executive.engine import build_executive_state, detect_changes, reset_previous_state
from runtime.executive.recommendations import generate_recommendations
from runtime.executive.scorer import ordered_priorities, score_priority
from runtime.executive.summarizer import executive_briefing, executive_summary


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def sample_subsystem(**overrides):
    base = {
        "id": "knowledge_graph",
        "name": "Knowledge Graph",
        "status": "warning",
        "completion": 35,
        "dependencies": ["taxonomy", "literature"],
        "blockers": ["Relationship coverage is incomplete."],
        "owner_required": True,
        "confidence": 0.55,
        "last_updated": "2026-07-10T00:00:00+00:00",
        "source": "relationships",
        "summary": "Knowledge Graph needs evidence.",
    }
    base.update(overrides)
    return base


def test_dependency_graph_contains_expected_edges():
    graph = dependency_graph()
    assert "knowledge_graph" in graph
    assert {"taxonomy", "literature", "pollinators", "mycorrhiza", "atlas"}.issubset(set(graph["knowledge_graph"]))
    reverse = reverse_dependencies(graph)
    assert "knowledge_graph" in reverse["literature"]


def test_priority_scoring_orders_blocking_systems():
    high = sample_subsystem()
    low = sample_subsystem(id="owner_manual", name="Owner Manual", completion=95, blockers=[], owner_required=False, confidence=0.9)
    priorities = ordered_priorities([low, high], {"knowledge_graph": ["grant_office", "partnership_generator"]})
    assert priorities[0]["subsystem_id"] == "knowledge_graph"
    assert priorities[0]["priority"] in {"critical", "high"}
    scored = score_priority(high, ["grant_office"])
    assert scored["factors"]["dependency_blocking"] > 0


def test_summary_and_briefing_are_deterministic():
    state = {
        "generated_at": "2026-07-10T00:00:00+00:00",
        "subsystems": [
            sample_subsystem(),
            sample_subsystem(id="atlas", name="Atlas", status="healthy", completion=90, blockers=[], owner_required=False, confidence=0.9),
        ],
        "priorities": [{"title": "Knowledge Graph", "score": 81, "priority": "critical"}],
        "changes": [{"type": "baseline", "summary": "Initial executive state baseline captured."}],
        "recommendations": [],
    }
    summary = executive_summary(state)
    briefing = executive_briefing(state)
    assert summary["system_health"]["total"] == 2
    assert summary["highest_priority"]["title"] == "Knowledge Graph"
    assert briefing["title"] == "Calyx Executive Intelligence Briefing"
    assert briefing["recommended_next_build"] == "Knowledge Graph"


def test_recommendations_require_evidence():
    subsystem = sample_subsystem()
    priorities = [{"subsystem_id": "knowledge_graph", "title": "Knowledge Graph", "score": 80, "priority": "critical"}]
    recommendations = generate_recommendations(priorities, [subsystem])
    assert recommendations
    assert recommendations[0]["evidence"]
    assert recommendations[0]["constitution_reference"]


def test_state_aggregation_includes_required_systems(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_previous_state()
    state = build_executive_state(update_cache=False)
    ids = {item["id"] for item in state["subsystems"]}
    for required in {"mission_control", "atlas", "species_explorer", "knowledge_graph", "harvesters", "runtime_jobs", "governance", "recommendations"}:
        assert required in ids
    assert state["priorities"]
    assert state["recommendations"]
    assert state["briefing"]["executive_summary"]
    assert state["completion_model"]["weights"]["functional_backend"] == 0.30
    assert state["activation_matrix"]
    knowledge_graph = next(item for item in state["subsystems"] if item["id"] == "knowledge_graph")
    assert "data_coverage" in knowledge_graph
    assert "source_record_counts" in knowledge_graph
    assert "telemetry_freshness" in knowledge_graph


def test_change_detector_reports_regressions_and_new_blockers():
    previous = {"subsystems": [sample_subsystem(completion=80, status="healthy", blockers=[])]}
    current = {"subsystems": [sample_subsystem(completion=30, status="warning", blockers=["New blocker"])]}
    changes = detect_changes(current, previous)
    assert any(change["type"] == "regression" for change in changes)
    assert any(change["type"] == "new_blocker" for change in changes)


def test_executive_api_endpoints_are_read_only(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    api = client()
    for endpoint in [
        "/api/executive/state",
        "/api/executive/summary",
        "/api/executive/priorities",
        "/api/executive/recommendations",
        "/api/executive/changes",
        "/api/executive/dependencies",
        "/api/executive/briefing",
    ]:
        response = api.get(endpoint)
        assert response.status_code == 200
        assert response.json()["build"] == "BUILD-064"
        assert api.post(endpoint).status_code in {404, 405}

