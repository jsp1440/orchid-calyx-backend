"""Contract tests for the read-only Brain-consumable query interface
(oc-registry-query-v1 over oc-capability-registry-v1).

Covers: API contract shape, capability discovery, status lookup,
module/dependency relationships, missing/blocked surfacing, provenance,
next engineering tasks, Mission Control exports, unknown-status handling,
read-only behavior, and backward compatibility with
calyx-brain-capability-registry-v1.
"""

import pytest

from runtime.oc_capability_registry import CONTRACT, CapabilityRegistry
from runtime.oc_registry_query import INTERFACE, RegistryQuery

AXES = ("implementation", "test", "merge", "deployment", "operational")


@pytest.fixture(scope="module")
def query() -> RegistryQuery:
    return RegistryQuery.from_default_store()


# ---------------------------------------------------------- API contract

def test_every_response_carries_contract_envelope(query):
    responses = [
        query.discover_capabilities(),
        query.status_lookup("oc.module.brain"),
        query.module_relationships("oc.module.brain"),
        query.missing_and_blocked(),
        query.provenance("oc.module.brain"),
        query.next_engineering_tasks(),
        query.mission_control_export(),
    ]
    for response in responses:
        assert response["contract"] == CONTRACT
        assert response["interface"] == INTERFACE
        assert response["compatible_with"] == "calyx-brain-capability-registry-v1"
        assert response["read_only"] is True
        assert response["execution_authority"] is False
        assert response["publication_authority"] is False


def test_interface_exposes_no_mutation_methods():
    for forbidden in ("import_records", "add_node", "add_edge", "update", "delete"):
        assert not hasattr(RegistryQuery, forbidden), (
            f"read-only interface must not expose {forbidden}"
        )


def test_repeated_queries_do_not_mutate_registry(query):
    before = query._registry.to_dict()  # noqa: SLF001
    query.discover_capabilities(query="matrix")
    query.status_lookup("oc.module.calyx")
    query.missing_and_blocked()
    query.mission_control_export()
    assert query._registry.to_dict() == before  # noqa: SLF001


def test_default_store_loader_reads_repo_layout(query):
    summary = query._registry.summary()  # noqa: SLF001
    assert summary["contract"] == CONTRACT
    assert summary["node_count"] > 0


# ------------------------------------------------------------- discovery

def test_discover_returns_only_capability_kinds(query):
    result = query.discover_capabilities()
    assert result["count"] == len(result["capabilities"]) > 0
    for cap in result["capabilities"]:
        assert cap["kind"] in ("capability", "subcapability")


def test_discover_text_query_matches_title(query):
    result = query.discover_capabilities(query="traitbank")
    ids = {c["node_id"] for c in result["capabilities"]}
    assert "oc.capability.traitbank.v1-vertical-slice" in ids
    assert all("traitbank" in c["node_id"] or "TraitBank" in c["title"]
               for c in result["capabilities"])


def test_discover_module_filter_scopes_results(query):
    result = query.discover_capabilities(module_id="oc.module.calyx")
    assert result["count"] > 0
    assert all(c["parent_id"] == "oc.module.calyx" for c in result["capabilities"])


def test_discover_status_filter_matches_exact_axes(query):
    result = query.discover_capabilities(statuses={"merge": "open_draft_pr"})
    assert result["count"] > 0
    assert all(c["status"]["merge"] == "open_draft_pr"
               for c in result["capabilities"])


# ---------------------------------------------------------- status lookup

def test_status_lookup_known_node_is_complete(query):
    result = query.status_lookup("oc.capability.calyx.capability-memory")
    assert result["found"] is True
    assert set(result["status"]) == set(AXES)
    assert result["status"]["test"] == "passing"
    assert result["evidence"], "status lookup must carry provenance"
    for item in result["evidence"]:
        assert item["source"] and item["ref"] and item["observed_at"]
    assert result["eligibility"]["eligible"] is True


def test_status_lookup_unknown_node_fails_closed(query):
    result = query.status_lookup("oc.capability.ghost.never-existed")
    assert result["found"] is False
    assert all(value == "unknown" for value in result["status"].values())
    assert "absent from the verified registry" in result["note"]


# ---------------------------------------------------------- relationships

def test_module_relationships_returns_children_and_edges(query):
    result = query.module_relationships("oc.module.matrix")
    assert result["found"] is True
    child_ids = {c["node_id"] for c in result["children"]}
    assert "oc.capability.matrix.identification-sessions" in child_ids
    # typed edges attach to capability nodes, not module nodes
    cap = query.module_relationships("oc.capability.matrix.identification-sessions")
    in_types = {e["edge_type"] for e in cap["incoming_edges"]}
    out_types = {e["edge_type"] for e in cap["outgoing_edges"]}
    assert "consumes_data_from" in out_types
    assert "produces_data_for" in in_types


def test_relationships_unknown_node_fails_closed(query):
    result = query.module_relationships("oc.module.ghost")
    assert result["found"] is False
    assert all(value == "unknown" for value in result["status"].values())


def test_dependency_edges_carry_evidence(query):
    result = query.module_relationships("oc.capability.brain.autonomy-loop")
    deps = [e for e in result["outgoing_edges"] if e["edge_type"] == "depends_on"]
    assert deps, "autonomy loop must record its dependencies"
    for dep in deps:
        assert dep["evidence"], f"edge {dep['to_id']} lacks provenance"


# --------------------------------------------------- missing/blocked/tasks

def test_missing_and_blocked_surfaces_known_gaps(query):
    result = query.missing_and_blocked()
    blocked_ids = {n["node_id"] for n in result["blocked"]}
    unmerged_ids = {n["node_id"] for n in result["unmerged"]}
    assert "oc.capability.brain.autonomy-loop" in blocked_ids
    assert "oc.capability.traitbank.v1-vertical-slice" in unmerged_ids
    assert result["counts"]["blocked"] == len(result["blocked"])


def test_next_engineering_tasks_are_deterministic(query):
    first = query.next_engineering_tasks()
    second = query.next_engineering_tasks()
    assert first == second
    assert first["count"] == len(first["tasks"]) > 0
    for task in first["tasks"]:
        assert task["kind"] in ("next_action", "blocker")
        assert task["node_id"].startswith("oc.")
    details = {t["detail"] for t in first["tasks"]}
    assert any("stacked autonomy PR chain" in d for d in details)


# ------------------------------------------------------------- provenance

def test_provenance_includes_edge_evidence(query):
    result = query.provenance("oc.capability.matrix.identification-sessions")
    assert result["found"] is True
    assert result["evidence"]
    touched = {(e["from_id"], e["to_id"]) for e in result["edge_evidence"]}
    assert ("oc.capability.matrix.identification-sessions",
            "oc.capability.lexicon.concept-registry") in touched


# ----------------------------------------------------- Mission Control export

def test_mission_control_export_is_consistent_bundle(query):
    bundle = query.mission_control_export()
    assert bundle["hierarchy"]["node_id"] == "oc.platform.orchid-continuum"
    assert bundle["relationship_graph"]["read_only"] is True
    summary = bundle["summary"]

    def count(node):
        return 1 + sum(count(c) for c in node["children"])

    assert count(bundle["hierarchy"]) == summary["node_count"]
    graph_ids = {n["node_id"] for n in bundle["relationship_graph"]["nodes"]}
    assert len(graph_ids) == summary["node_count"]


# ----------------------------------------------------- backward compatibility

def test_autonomy_brief_passthrough_keeps_v1_compatibility(query):
    brief = query.autonomy_brief()
    assert brief["contract"] == CONTRACT
    assert brief["compatible_with"] == "calyx-brain-capability-registry-v1"
    assert brief["read_only"] is True
    assert brief["execution_authority"] is False
    for key in ("untested_capabilities", "unmerged_work", "blocked_or_absent",
                "missing_verified_data_support", "duplicated_work",
                "integration_ready"):
        assert key in brief
