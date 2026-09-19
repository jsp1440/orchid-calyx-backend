"""Proofs for the Cognitive Integration path (backend #1502).

The path runs on the existing knowledge-graph repository protocol and the
existing ``ReasoningMapEngine``. These tests check it *reasons* — selects
capabilities, traverses relationships, finds the contradiction and the gaps in
the data rather than reciting them — and that it does so with no provider and no
locality leak.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.cognitive_integration.executor import (
    DETERMINISTIC_CAPABILITIES,
    OPTIONAL_CAPABILITY,
    CognitiveIntegrationError,
    execute,
)
from app.cognitive_integration.fixture import build_pollination_repository
from app.main import app
from app.provider_reservoir.capabilities import is_provider_capability
from runtime.knowledge_graph import Edge
from runtime.knowledge_graph.repository import InMemoryGraphRepository


@pytest.fixture(scope="module")
def reasoning_map() -> dict:
    return execute()


@pytest.fixture()
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# It runs with no provider, and every capability it uses is deterministic
# ---------------------------------------------------------------------------


def test_the_whole_path_runs_with_no_provider(reasoning_map):
    assert reasoning_map["execution"]["provider_calls"] == 0
    assert reasoning_map["execution"]["explanation_available"] is False
    assert reasoning_map["execution"]["explanation"] is None


def test_every_capability_the_path_uses_is_classified_deterministic():
    """Pinned against the router's own registry, not a local copy of it."""
    for capability in DETERMINISTIC_CAPABILITIES:
        assert is_provider_capability(capability) is False


def test_the_one_optional_capability_is_the_only_provider_one():
    assert is_provider_capability(OPTIONAL_CAPABILITY) is True


def test_optional_explanation_adds_prose_and_changes_nothing_else():
    without = execute()
    with_prose = execute(explanation="The bee orchid is a puzzle: ...")

    assert with_prose["execution"]["explanation_available"] is True
    assert with_prose["execution"]["provider_calls"] == 1
    for key in ("relationships", "mechanisms", "contradictions", "evidence_gaps",
                "known_unknowns", "confidence", "taxonomic_identity"):
        assert with_prose[key] == without[key], f"{key} changed when prose was added"


# ---------------------------------------------------------------------------
# It uses the real engine and the real graph, not a parallel structure
# ---------------------------------------------------------------------------


def test_the_traversal_runs_on_the_real_reasoning_engine(reasoning_map):
    traversal = reasoning_map["execution"]["traversal"]
    assert traversal["engine"] == "app.brain.reasoning_map.ReasoningMapEngine"
    assert traversal["path_count"] > 0
    assert traversal["edge_count"] > 0


def test_the_fixture_is_ordinary_graph_records():
    repo = build_pollination_repository()
    assert isinstance(repo, InMemoryGraphRepository)
    assert repo.get_node_by_key("taxon:ophrys-apifera") is not None
    assert all(isinstance(edge, Edge) for edge in repo.all_edges())


# ---------------------------------------------------------------------------
# It reasons: identity, evidence, contradiction, gaps
# ---------------------------------------------------------------------------


def test_it_resolves_a_taxonomic_identity_and_says_against_what(reasoning_map):
    identity = reasoning_map["taxonomic_identity"]
    assert identity["accepted_name"] == "Ophrys apifera"
    assert identity["authorship"] == "Huds."
    assert identity["resolved_against"]


def test_every_relationship_carries_provenance_and_a_permitted_state(reasoning_map):
    allowed = {"SUPPORTED", "CONTESTED", "REPORTED_UNVERIFIED", "REFUTED"}
    assert reasoning_map["relationships"]
    for relationship in reasoning_map["relationships"]:
        assert relationship["evidence_state"] in allowed
        assert relationship["provenance"]
        assert relationship["provenance"][0]["citation"].strip()


def test_nothing_is_presented_as_canonical_fact(reasoning_map):
    states = {r["evidence_state"] for r in reasoning_map["relationships"]}
    assert "FACT" not in states
    assert reasoning_map["governance"]["automatic_knowledge_promotion"] is False


def test_literature_and_dataset_evidence_are_both_present(reasoning_map):
    kinds = {p["source_type"] for r in reasoning_map["relationships"] for p in r["provenance"]}
    assert "peer_reviewed_literature" in kinds
    assert kinds & {"occurrence_dataset", "interaction_dataset", "human_observation"}


def test_the_contradiction_is_found_in_the_data_not_recited(reasoning_map):
    """Remove one side of the disagreement and the contradiction must disappear."""
    contradictions = reasoning_map["contradictions"]
    assert len(contradictions) == 1
    assert contradictions[0]["resolution"] == "unresolved_presented_as_contested"
    assert set(contradictions[0]["scopes"]) == {"Mediterranean range", "North-western range"}

    repo = build_pollination_repository()
    remaining = [e for e in repo.all_edges() if e.edge_type != "reported_pollinated_by"]
    reduced = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=remaining))
    assert reduced["contradictions"] == [], "the contradiction was hardcoded, not derived"


def test_a_contradiction_within_one_scope_is_resolved_by_scope_instead():
    """Two claims about the same place are a different finding from two about different ones."""
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        if edge.edge_type == "reported_reproductive_strategy":
            payload = dict(edge.payload)
            payload["geographic_scope"] = "Mediterranean range"
            edge = Edge(
                kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
                from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
                evidence_class=edge.evidence_class, payload=payload,
            )
        edges.append(edge)
    same_scope = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges))
    assert same_scope["contradictions"][0]["resolution"] == "resolved_by_scope"


def test_the_evidence_gaps_are_derived_from_what_the_graph_lacks(reasoning_map):
    gaps = " ".join(reasoning_map["evidence_gaps"])
    assert "pollination observation" in gaps
    assert "quantifies" in gaps
    # Derived by noticing the node's own payload, not written into the output.
    assert "genus, not species" in gaps


def test_adding_the_missing_evidence_removes_its_gap():
    repo = build_pollination_repository()
    nodes = list(repo.all_nodes())
    edges = list(repo.all_edges())
    edges.append(Edge(
        kg_edge_id=99, edge_type="observed_pollination_event",
        from_node_id=1, to_node_id=2, evidence_class="SUPPORTED",
        payload={"citation": "Field observation record", "source_type": "human_observation"},
    ))
    enriched = execute(repository=InMemoryGraphRepository(nodes=nodes, edges=edges))
    gaps = " ".join(enriched["evidence_gaps"])
    assert "no population-level pollination observation is held" not in gaps
    assert "No local observation supports any retrieved claim" not in gaps


def test_a_competing_mechanism_and_a_null_explanation_are_both_offered(reasoning_map):
    kinds = {m["kind"] for m in reasoning_map["mechanisms"]}
    assert kinds == {"proposed_mechanism", "competing_mechanism", "null_explanation"}


def test_confidence_is_qualitative_with_a_basis_and_no_invented_number(reasoning_map):
    confidence = reasoning_map["confidence"]
    assert confidence["numeric_precision_claimed"] is False
    assert confidence["qualitative"] == "moderate"
    assert confidence["basis"].strip()
    assert not any(ch.isdigit() for ch in confidence["qualitative"])


def test_known_unknowns_and_next_evidence_are_both_stated(reasoning_map):
    assert len(reasoning_map["known_unknowns"]) >= 3
    assert len(reasoning_map["recommended_next_evidence"]) >= 3


# ---------------------------------------------------------------------------
# Locality, handoffs, governance
# ---------------------------------------------------------------------------


def test_no_coordinate_appears_anywhere_in_the_map(reasoning_map):
    import re

    serialized = json.dumps(reasoning_map)
    assert not re.search(r"[-+]?\d{1,3}\.\d{3,}\s*,\s*[-+]?\d{1,3}\.\d{3,}", serialized)
    assert reasoning_map["geographic_context"]["coordinates_present"] is False
    assert reasoning_map["locality_policy"]["disclosure"] == "WITHHELD_PENDING_REVIEW"


def test_a_coordinate_in_the_graph_is_redacted_rather_than_served():
    repo = build_pollination_repository()
    edges = []
    for edge in repo.all_edges():
        payload = dict(edge.payload)
        if edge.edge_type == "co_occurs_with":
            payload["citation"] = "Recorded at -8.1234, -35.6789 on the ridge"
        edges.append(Edge(
            kg_edge_id=edge.kg_edge_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            evidence_class=edge.evidence_class, payload=payload,
        ))
    leaky = execute(repository=InMemoryGraphRepository(
        nodes=list(repo.all_nodes()), edges=edges))
    serialized = json.dumps(leaky)
    assert "-8.1234" not in serialized
    assert "locality withheld" in serialized


def test_an_unpermitted_evidence_state_fails_closed():
    repo = build_pollination_repository()
    edges = [Edge(
        kg_edge_id=e.kg_edge_id, edge_type=e.edge_type, from_node_id=e.from_node_id,
        to_node_id=e.to_node_id, evidence_class="FACT", payload=e.payload,
    ) if e.kg_edge_id == 1 else e for e in repo.all_edges()]
    with pytest.raises(CognitiveIntegrationError, match="evidence state"):
        execute(repository=InMemoryGraphRepository(
            nodes=list(repo.all_nodes()), edges=edges))


def test_both_handoffs_are_available_and_bounded(reasoning_map):
    handoffs = reasoning_map["handoffs"]
    assert handoffs["research_station"]["carries_evidence_states"] is True
    assert handoffs["education"]["audience_adaptation_may_change_meaning"] is False


def test_the_path_activates_no_scientific_or_taxonomic_state(reasoning_map):
    governance = reasoning_map["governance"]
    assert governance["scientific_review_required"] is True
    for flag in ("automatic_publication", "automatic_candidate_knowledge",
                 "automatic_knowledge_promotion", "production_runtime_enabled"):
        assert governance[flag] is False


# ---------------------------------------------------------------------------
# Over HTTP, which is how Calyx will reach it
# ---------------------------------------------------------------------------


def test_calyx_can_fetch_the_reasoning_map(client):
    response = client.get("/api/cognitive-integration/reasoning-map")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["taxonomic_identity"]["accepted_name"] == "Ophrys apifera"
    assert body["execution"]["provider_calls"] == 0
    assert body["contradictions"]


def test_an_unsupported_question_is_refused_with_what_it_would_take(client):
    response = client.get(
        "/api/cognitive-integration/reasoning-map",
        params={"question": "Why are orchid seeds so small?"},
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["required_capability"] == "free-text-intent-parsing"
    assert detail["supported_questions"]


def test_the_capability_route_states_no_provider_is_needed_to_reason(client):
    body = client.get("/api/cognitive-integration/capabilities").json()
    assert body["provider_required_for_reasoning"] is False
    assert body["optional_provider"] == [OPTIONAL_CAPABILITY]


def test_the_backend_map_satisfies_the_brain_scientific_contract(reasoning_map):
    """The two repositories must agree about the science, not merely coexist.

    The Brain's validator is the authority on what a reasoning map must
    demonstrate. Running it against the backend's output is what makes the
    contract real rather than a shared intention.
    """
    import importlib.util
    import pathlib

    brain = pathlib.Path("/home/user/orchid-continuum-brain")
    script = brain / "scripts" / "oc_brain_validate_cognitive_integration.py"
    if not script.exists():
        pytest.skip("Brain checkout not present in this environment")

    spec = importlib.util.spec_from_file_location("brain_validator", script)
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)

    assert validator.check_pollination_fixture(reasoning_map) == []

    schema = json.loads((brain / validator.REASONING_MAP_SCHEMA).read_text())
    structural = validator.check_fixture_against_schema(reasoning_map, schema)
    undeclared = [f for f in structural if "undeclared key" in f]

    # Execution metadata is additive. A Brain checkout that already declares it
    # accepts the map outright; one that predates the declaration reports only
    # that single key. Anything else is a real divergence in the contract.
    assert undeclared in ([], ["fixture carries undeclared key 'execution'"]), structural
    assert [f for f in structural if "undeclared key" not in f] == [], structural
