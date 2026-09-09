from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_write_set_verifier", ROOT / "scripts" / "oc_swarm_write_set_verifier.py"
)
assert SPEC is not None and SPEC.loader is not None
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


def lease(reads=(), writes=()):
    return {"reads": list(reads), "writes": list(writes)}


def test_parse_lease_claim_from_v2_receipt():
    comment = (
        '[OC-SWARM-V2] Resource-aware worker lease claimed: '
        '`{"reads":["taxonomy"],"writes":["literature"]}`. Controller run: x'
    )
    claim = verifier.parse_lease_claim(comment)
    assert claim == {"reads": ["taxonomy"], "writes": ["literature"]}


def test_parse_lease_claim_from_v4_dependency_resource_receipt():
    comment = (
        '[OC-SWARM-V4] Dependency/resource lease claimed: '
        '`{"reads":["taxonomy"],"writes":["atlas"],"dependencies":[1201]}`. Wave 2/4.'
    )
    claim = verifier.parse_lease_claim(comment)
    assert claim == {"reads": ["taxonomy"], "writes": ["atlas"]}


def test_declared_write_allows_matching_runtime_change():
    result = verifier.verify_write_set(
        ["app/literature_extraction/routes.py", "tests/test_literature_binding.py"],
        lease(writes=["literature"]),
    )
    assert result["passed"] is True
    assert result["violations"] == []


def test_read_claim_never_authorizes_write():
    result = verifier.verify_write_set(
        ["app/literature_extraction/routes.py"],
        lease(reads=["literature"], writes=[]),
    )
    assert result["passed"] is False
    assert result["violations"][0]["missing_writes"] == ["literature"]


def test_cross_resource_drift_fails_closed():
    result = verifier.verify_write_set(
        ["app/calyx_orchestrator/atlas_product_path.py"],
        lease(writes=["literature"]),
    )
    assert result["passed"] is False
    assert "atlas" in result["violations"][0]["missing_writes"]


def test_control_plane_change_requires_control_plane_write():
    result = verifier.verify_write_set(
        [".github/workflows/orchid-continuous-completion.yml"],
        lease(writes=["frontend-api"]),
    )
    assert result["passed"] is False
    assert result["violations"][0]["missing_writes"] == ["control-plane"]


def test_migration_requires_database_schema_plus_domain_when_classified():
    result = verifier.verify_write_set(
        ["migrations/116_literature_source_binding.sql"],
        lease(writes=["literature"]),
    )
    assert result["passed"] is False
    assert result["violations"][0]["missing_writes"] == ["database-schema"]

    passed = verifier.verify_write_set(
        ["migrations/116_literature_source_binding.sql"],
        lease(writes=["database-schema", "literature"]),
    )
    assert passed["passed"] is True


def test_unknown_runtime_path_requires_repo_global_or_coarse_lane_fallback():
    path = "app/new_subsystem/worker.py"
    failed = verifier.verify_write_set([path], lease(writes=["literature"]))
    assert failed["passed"] is False
    assert failed["violations"][0]["missing_writes"] == ["repo-global"]

    explicit = verifier.verify_write_set([path], lease(writes=["repo-global"]))
    assert explicit["passed"] is True

    fallback = verifier.verify_write_set([path], lease(writes=["lane-l3"]))
    assert fallback["passed"] is True
    assert fallback["checked"][0]["classification"] == "coarse-lane-fallback"


def test_ancillary_docs_and_tests_do_not_expand_runtime_authority():
    result = verifier.verify_write_set(
        ["docs/NEW-NOTE.md", "tests/test_misc_contract.py"],
        lease(writes=["literature"]),
    )
    assert result["passed"] is True


def test_global_dependency_file_requires_repo_global():
    failed = verifier.verify_write_set(["requirements.txt"], lease(writes=["literature"]))
    assert failed["passed"] is False
    assert failed["violations"][0]["missing_writes"] == ["repo-global"]


def test_write_claim_dominates_duplicate_read_claim():
    comment = (
        '[OC-SWARM-V2] Resource-aware worker lease claimed: '
        '`{"reads":["literature"],"writes":["literature"]}`. Controller run: x'
    )
    assert verifier.parse_lease_claim(comment) == {"reads": [], "writes": ["literature"]}
