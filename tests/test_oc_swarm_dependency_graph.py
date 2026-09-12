from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "oc_swarm_dependency_graph", ROOT / "scripts" / "oc_swarm_dependency_graph.py"
)
assert SPEC is not None and SPEC.loader is not None
deps = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deps)


def issue(number, *, body="", state="OPEN", labels=()):
    return {
        "number": number,
        "body": body,
        "state": state,
        "labels": list(labels),
    }


def test_explicit_dependencies_are_parsed_deterministically():
    row = issue(10, body="OC-SWARM-DEPENDS-ON: #3, #2, #3")
    assert deps.dependencies(row) == [2, 3]


def test_closed_dependency_unlocks_candidate():
    graph = deps.build_dependency_graph(
        [
            issue(1, state="CLOSED"),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["status"][2]["ready"] is True
    assert graph["status"][2]["unsatisfied"] == []


def test_done_label_unlocks_candidate_even_if_issue_remains_open():
    graph = deps.build_dependency_graph(
        [
            issue(1, labels=("oc-done",)),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["status"][2]["ready"] is True


def test_open_dependency_blocks_candidate():
    graph = deps.build_dependency_graph(
        [
            issue(1),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["status"][2]["ready"] is False
    assert graph["status"][2]["unsatisfied"] == [1]


def test_missing_dependency_fails_closed():
    graph = deps.build_dependency_graph(
        [issue(2, body="OC-SWARM-DEPENDS-ON: #9999")]
    )
    assert graph["status"][2]["ready"] is False
    assert graph["status"][2]["missing"] == [9999]


def test_dependency_cycle_fails_closed():
    graph = deps.build_dependency_graph(
        [
            issue(1, body="OC-SWARM-DEPENDS-ON: #2"),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["cycle_nodes"] == [1, 2]
    assert graph["status"][1]["ready"] is False
    assert graph["status"][2]["ready"] is False


def test_self_dependency_is_a_cycle_and_fails_closed():
    graph = deps.build_dependency_graph(
        [issue(1, body="OC-SWARM-DEPENDS-ON: #1")]
    )
    assert graph["cycle_nodes"] == [1]
    assert graph["status"][1]["ready"] is False


def test_filter_ready_candidates_reports_block_reason():
    graph = deps.build_dependency_graph(
        [
            issue(1),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
            issue(3),
        ]
    )
    ready, blocked = deps.filter_ready_candidates(
        [{"number": 2}, {"number": 3}], graph
    )
    assert ready == [{"number": 3}]
    assert blocked[0]["issue_number"] == 2
    assert blocked[0]["reason"] == "dependency-blocked"


# ============================================================================
# REGRESSION TESTS: Malformed Dependency Declarations
# ============================================================================


def test_no_declaration_means_no_dependencies_and_remains_eligible():
    """No OC-SWARM-DEPENDS-ON declaration = no dependencies, stays ready."""
    graph = deps.build_dependency_graph([issue(1)])
    assert graph["status"][1]["dependencies"] == []
    assert graph["status"][1]["ready"] is True


def test_valid_single_declaration_with_single_issue():
    """Single valid issue reference keeps existing behavior."""
    graph = deps.build_dependency_graph(
        [
            issue(1, state="CLOSED"),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1"),
        ]
    )
    assert graph["status"][2]["dependencies"] == [1]
    assert graph["status"][2]["ready"] is True


def test_valid_declaration_with_comma_separated_issues():
    """Comma-separated valid references work correctly."""
    graph = deps.build_dependency_graph(
        [
            issue(1, state="CLOSED"),
            issue(2, state="CLOSED"),
            issue(3, body="OC-SWARM-DEPENDS-ON: #1, #2"),
        ]
    )
    assert sorted(graph["status"][3]["dependencies"]) == [1, 2]
    assert graph["status"][3]["ready"] is True


def test_duplicate_references_on_same_line_remain_harmless():
    """Duplicate references are deduplicated, no error."""
    graph = deps.build_dependency_graph(
        [
            issue(1, state="CLOSED"),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1, #1, #1"),
        ]
    )
    assert graph["status"][2]["dependencies"] == [1]
    assert graph["status"][2]["ready"] is True


def test_empty_declaration_fails_closed():
    """OC-SWARM-DEPENDS-ON: (empty or whitespace only) is malformed."""
    graph = deps.build_dependency_graph(
        [issue(1, body="OC-SWARM-DEPENDS-ON:")]
    )
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["malformed"] == "dependency-declaration-empty"


def test_whitespace_only_declaration_fails_closed():
    """OC-SWARM-DEPENDS-ON: (spaces only) is malformed."""
    graph = deps.build_dependency_graph(
        [issue(1, body="OC-SWARM-DEPENDS-ON:   \t  ")]
    )
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["malformed"] == "dependency-declaration-empty"


def test_non_reference_declaration_fails_closed():
    """OC-SWARM-DEPENDS-ON: unknown is malformed (no #numbers)."""
    graph = deps.build_dependency_graph(
        [issue(1, body="OC-SWARM-DEPENDS-ON: unknown")]
    )
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["malformed"] == "dependency-declaration-no-references"


def test_mixed_valid_and_invalid_content_fails_closed():
    """OC-SWARM-DEPENDS-ON: #1 and something invalid fails."""
    graph = deps.build_dependency_graph(
        [issue(1, body="OC-SWARM-DEPENDS-ON: #5 unknown text")]
    )
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["malformed"] == "dependency-declaration-mixed-content"


def test_partial_invalid_reference_fails_closed():
    """#abc (not a valid issue number) in declaration is malformed."""
    graph = deps.build_dependency_graph(
        [issue(1, body="OC-SWARM-DEPENDS-ON: #abc")]
    )
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["malformed"] == "dependency-declaration-no-references"


def test_multiple_declaration_lines_first_one_validated():
    """First declaration line is parsed; subsequent lines ignored."""
    # The regex only matches the first occurrence
    graph = deps.build_dependency_graph(
        [
            issue(1, state="CLOSED"),
            issue(2, body="OC-SWARM-DEPENDS-ON: #1\nOC-SWARM-DEPENDS-ON: #99999"),
        ]
    )
    # Should only parse the first line
    assert graph["status"][2]["dependencies"] == [1]
    assert graph["status"][2]["ready"] is True


def test_malformed_declaration_blocks_independent_tasks():
    """When one issue is malformed, independent tasks remain eligible."""
    graph = deps.build_dependency_graph(
        [
            issue(1, body="OC-SWARM-DEPENDS-ON: invalid"),
            issue(2),  # No dependency
            issue(3, body="OC-SWARM-DEPENDS-ON: #2"),  # Depends on 2
        ]
    )
    # Issue 1 is malformed, so not ready
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["malformed"] == "dependency-declaration-no-references"
    
    # Issue 2 has no dependencies, should be ready
    assert graph["status"][2]["ready"] is True
    
    # Issue 3 depends on issue 2, which is ready, so issue 3 is ready
    assert graph["status"][3]["ready"] is True


def test_malformed_reason_passed_to_filter_ready_candidates():
    """filter_ready_candidates reports malformed as reason."""
    graph = deps.build_dependency_graph(
        [issue(1, body="OC-SWARM-DEPENDS-ON: xyz")]
    )
    ready, blocked = deps.filter_ready_candidates([{"number": 1}], graph)
    
    assert ready == []
    assert len(blocked) == 1
    assert blocked[0]["reason"] == "dependency-declaration-no-references"


def test_empty_string_body_is_valid_no_declaration():
    """Empty issue body means no dependencies."""
    graph = deps.build_dependency_graph([issue(1, body="")])
    assert graph["status"][1]["dependencies"] == []
    assert graph["status"][1]["ready"] is True


def test_declaration_with_special_characters_fails():
    """Text with special chars mixed with references fails."""
    graph = deps.build_dependency_graph(
        [issue(1, body="OC-SWARM-DEPENDS-ON: #5 [invalid]")]
    )
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["malformed"] == "dependency-declaration-mixed-content"


def test_case_insensitive_marker_still_validated():
    """Marker is case-insensitive, but content is still validated."""
    graph = deps.build_dependency_graph(
        [issue(1, body="oc-swarm-depends-on: unknown")]
    )
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["malformed"] == "dependency-declaration-no-references"


def test_graph_construction_completes_with_malformed_issue():
    """Graph builds successfully even with one malformed issue."""
    issues = [
        issue(1, body="OC-SWARM-DEPENDS-ON: not-a-reference"),
        issue(2, state="CLOSED"),
        issue(3, body="OC-SWARM-DEPENDS-ON: #2"),
    ]
    # This should not raise an exception
    graph = deps.build_dependency_graph(issues)
    
    assert "status" in graph
    assert 1 in graph["status"]
    assert 2 in graph["status"]
    assert 3 in graph["status"]
    
    # Issue 1: malformed
    assert graph["status"][1]["ready"] is False
    
    # Issue 2: no dependencies, is ready
    assert graph["status"][2]["ready"] is True
    
    # Issue 3: depends on ready issue 2
    assert graph["status"][3]["ready"] is True
