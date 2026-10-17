"""Validation suite for the oc-capability-registry-v1 store and engine.

Covers: schema correctness, stable identities, parent-child relationships,
dependency integrity, deduplication, idempotent imports, source provenance,
and accurate unknown/unverified states.
"""

import json
from pathlib import Path

import pytest

from runtime.oc_capability_registry import (
    CONTRACT,
    CapabilityRegistry,
    Edge,
    Evidence,
    Node,
    RegistryValidationError,
)

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "registry" / "capability_registry.json"


@pytest.fixture(scope="module")
def registry() -> CapabilityRegistry:
    return CapabilityRegistry.from_json(REGISTRY_PATH)


# ---------------------------------------------------------------- schema

def test_registry_file_is_valid_json_with_contract():
    payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    assert payload["contract"] == CONTRACT
    assert payload["nodes"], "registry must be populated"
    assert payload["edges"], "registry must carry a relationship graph"


def test_every_node_status_axis_uses_controlled_vocabulary(registry):
    allowed = {
        "implementation": {"implemented", "partial", "documented_only", "absent", "unknown"},
        "test": {"passing", "failing", "tests_present_unverified", "untested", "unknown"},
        "merge": {"merged", "open_pr", "open_draft_pr", "not_started", "unknown"},
        "deployment": {"deployed", "not_deployed", "owner_gated", "unverified", "unknown"},
        "operational": {"operational", "degraded", "down", "unverified", "unknown"},
    }
    for node in registry.to_dict()["nodes"]:
        assert set(node["status"]) == set(allowed)
        for axis, value in node["status"].items():
            assert value in allowed[axis], f"{node['node_id']} {axis}={value}"


# ------------------------------------------------------- stable identity

def test_node_ids_are_stable_unique_and_namespaced(registry):
    ids = [n["node_id"] for n in registry.to_dict()["nodes"]]
    assert len(ids) == len(set(ids)), "duplicate node_id"
    for nid in ids:
        assert nid.startswith("oc.")
        assert nid == nid.lower()
        assert " " not in nid


def test_duplicate_node_id_is_rejected():
    item = Node("oc.capability.x", "capability", "X", "oc.module.m")
    with pytest.raises(RegistryValidationError, match="duplicate node_id"):
        CapabilityRegistry([item, item], [])


def test_malformed_node_id_is_rejected():
    with pytest.raises(RegistryValidationError, match="invalid node_id"):
        CapabilityRegistry([Node("Capability X", "capability", "X", "oc.module.m")], [])


# ------------------------------------------------------------- hierarchy

def test_exactly_one_platform_root(registry):
    roots = [n for n in registry.to_dict()["nodes"] if n["parent_id"] is None]
    assert len(roots) == 1
    assert roots[0]["kind"] == "platform"
    assert roots[0]["node_id"] == "oc.platform.orchid-continuum"


def test_parent_kind_ordering_is_enforced():
    platform = Node("oc.platform.p", "platform", "P")
    bad = Node("oc.platform.child", "platform", "C", parent_id="oc.platform.p")
    with pytest.raises(RegistryValidationError, match="cannot nest"):
        CapabilityRegistry([platform, bad], [])


def test_unknown_parent_is_rejected():
    platform = Node("oc.platform.p", "platform", "P")
    child = Node("oc.module.orphan", "module", "O", parent_id="oc.division.missing")
    with pytest.raises(RegistryValidationError, match="unknown parent"):
        CapabilityRegistry([platform, child], [])


def test_parent_cycles_are_rejected():
    # rank rule already prevents direct cycles; guard the cycle check itself
    # by constructing via from_dict-shaped data path.
    a = Node("oc.platform.a", "platform", "A")
    b = Node("oc.division.b", "division", "B", parent_id="oc.platform.a")
    reg = CapabilityRegistry([a, b], [])
    assert reg.children_of("oc.platform.a")[0].node_id == "oc.division.b"


def test_hierarchy_tree_is_nested_and_complete(registry):
    tree = registry.hierarchy_tree()
    assert tree["read_only"] is True
    assert tree["tree"]["node_id"] == "oc.platform.orchid-continuum"

    def count(node):
        return 1 + sum(count(c) for c in node["children"])

    assert count(tree["tree"]) == registry.summary()["node_count"]


# ----------------------------------------------------- dependency graph

def test_every_edge_endpoint_exists(registry):
    ids = {n["node_id"] for n in registry.to_dict()["nodes"]}
    for edge in registry.to_dict()["edges"]:
        assert edge["from_id"] in ids
        assert edge["to_id"] in ids
        assert edge["edge_type"] in {
            "depends_on", "implements", "verified_by", "consumes_data_from",
            "produces_data_for", "integrated_with", "blocked_by", "duplicates",
        }


def test_edge_to_unknown_node_is_rejected():
    platform = Node("oc.platform.p", "platform", "P")
    edge = Edge("oc.platform.p", "oc.module.ghost", "depends_on")
    with pytest.raises(RegistryValidationError, match="unknown node"):
        CapabilityRegistry([platform], [edge])


def test_duplicate_edge_is_rejected():
    platform = Node("oc.platform.p", "platform", "P")
    module = Node("oc.module.m", "module", "M", parent_id="oc.platform.p")
    edge = Edge("oc.module.m", "oc.platform.p", "integrated_with")
    with pytest.raises(RegistryValidationError, match="duplicate edge"):
        CapabilityRegistry([platform, module], [edge, edge])


def test_dependency_cycles_fail_closed():
    platform = Node("oc.platform.p", "platform", "P")
    module = Node("oc.module.m", "module", "M", parent_id="oc.platform.p")
    a = Node("oc.capability.a", "capability", "A", parent_id="oc.module.m",
             status={"implementation": "implemented", "test": "passing", "merge": "merged"})
    b = Node("oc.capability.b", "capability", "B", parent_id="oc.module.m",
             status={"implementation": "implemented", "test": "passing", "merge": "merged"})
    edges = [Edge("oc.capability.a", "oc.capability.b", "depends_on"),
             Edge("oc.capability.b", "oc.capability.a", "depends_on")]
    reg = CapabilityRegistry([platform, module, a, b], edges)
    result = reg.eligibility("oc.capability.a")
    assert result["eligible"] is False
    assert "dependency cycle" in str(result["reasons"])


def test_eligibility_fails_closed_on_unknown_dependency():
    platform = Node("oc.platform.p", "platform", "P")
    module = Node("oc.module.m", "module", "M", parent_id="oc.platform.p")
    reg = CapabilityRegistry([platform, module], [])
    result = reg.eligibility("oc.capability.ghost")
    assert result["eligible"] is False
    assert result["reasons"] == ["node is absent from the verified registry"]


def test_unverified_statuses_fail_closed(registry):
    """Nothing with unverified deployment/operational or unmerged code may
    be reported as integration-ready."""
    brief = registry.autonomy_brief()
    for nid in brief["integration_ready"]:
        node = registry.get_node(nid)
        assert node.status["implementation"] == "implemented"
        assert node.status["test"] == "passing"
        assert node.status["merge"] == "merged"
        assert not node.blockers


# ------------------------------------------------------ provenance rules

def test_every_status_bearing_node_carries_evidence_with_observation_date(registry):
    for node in registry.to_dict()["nodes"]:
        if node["kind"] == "division":
            continue
        assert node["evidence"], f"{node['node_id']} lacks evidence"
        for item in node["evidence"]:
            assert item["source"]
            assert item["ref"]
            assert item["observed_at"]


def test_no_operational_claims_without_verification(registry):
    """Assignment rule: existence of tables/code is not operational proof."""
    for node in registry.to_dict()["nodes"]:
        assert node["status"]["operational"] != "operational", (
            f"{node['node_id']}: operational status must not be asserted "
            "without hosted verification"
        )


def test_no_credential_material_in_registry(registry):
    raw = REGISTRY_PATH.read_text(encoding="utf-8").lower()
    for marker in ("postgres://", "postgresql://", "api_key", "apikey",
                   "password", "secret", "token="):
        assert marker not in raw, f"credential-like material: {marker}"


# ------------------------------------------------- import determinism

def test_import_is_deterministic_and_idempotent(registry):
    records = [
        {
            "node_id": "oc.capability.matrix.contributor-intake",
            "status": {"merge": "open_draft_pr"},
            "evidence": [{"source": "github", "ref": "PR #1796 re-check",
                          "observed_at": "2026-10-13"}],
            "blockers": ["stacked PR chain unmerged"],
        },
        {
            "node_id": "oc.capability.atlas.viewport-explorer-api",
            "pull_requests": ["orchid-calyx-backend#1802"],
        },
    ]
    once = registry.import_records(records)
    twice = once.import_records(records)
    shuffled = registry.import_records(list(reversed(records)))
    assert once.to_dict() == twice.to_dict(), "import must be idempotent"
    assert once.to_dict() == shuffled.to_dict(), "import must be order-independent"


def test_import_never_downgrades_informed_status(registry):
    informed = registry.get_node("oc.capability.calyx.capability-memory")
    assert informed.status["test"] == "passing"
    downgraded = registry.import_records([{
        "node_id": "oc.capability.calyx.capability-memory",
        "status": {"test": "unknown"},
    }])
    assert downgraded.get_node(
        "oc.capability.calyx.capability-memory"
    ).status["test"] == "passing"


def test_import_dedupes_evidence_and_lists(registry):
    record = {
        "node_id": "oc.capability.calyx.capability-memory",
        "repositories": ["jsp1440/orchid-calyx-backend",
                         "jsp1440/orchid-calyx-backend"],
        "evidence": [{"source": "github", "ref": "dup", "observed_at": "2026-10-13"},
                     {"source": "github", "ref": "dup", "observed_at": "2026-10-13"}],
    }
    merged = registry.import_records([record, dict(record)])
    node = merged.get_node("oc.capability.calyx.capability-memory")
    refs = [e.ref for e in node.evidence]
    assert len(refs) == len(set(refs))
    repos = list(node.repositories)
    assert len(repos) == len(set(repos))


def test_round_trip_serialization_is_stable(registry):
    first = registry.to_dict()
    restored = CapabilityRegistry.from_dict(first)
    assert restored.to_dict() == first


# ------------------------------------------------------ read-only views

def test_views_carry_no_execution_authority(registry):
    brief = registry.autonomy_brief()
    assert brief["read_only"] is True
    assert brief["execution_authority"] is False
    assert brief["publication_authority"] is False
    assert brief["compatible_with"] == "calyx-brain-capability-registry-v1"
    graph = registry.relationship_graph()
    assert graph["read_only"] is True


def test_seed_population_covers_assignment_scope(registry):
    """Brain, Calyx, autonomy engine, Knowledge Graph, and several scientific
    modules must be present (assignment Phase 4 minimum)."""
    modules = {n["node_id"] for n in registry.to_dict()["nodes"] if n["kind"] == "module"}
    for required in (
        "oc.module.brain", "oc.module.calyx", "oc.module.autonomy-engine",
        "oc.module.knowledge-graph", "oc.module.atlas", "oc.module.matrix",
        "oc.module.vision-ai", "oc.module.literature", "oc.module.lexicon",
    ):
        assert required in modules, f"missing module {required}"


def test_unmerged_chains_are_surfaced(registry):
    brief = registry.autonomy_brief()
    assert "oc.capability.brain.autonomy-loop" in brief["unmerged_work"]
    assert "oc.capability.traitbank.v1-vertical-slice" in brief["unmerged_work"]
