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


# Regression tests for malformed declarations.

def test_no_declaration_is_valid():
    """No OC-SWARM-DEPENDS-ON line means no dependencies."""
    row = issue(10, body="This is a regular issue with no declaration.")
    error = deps._validate_dependencies_declaration(row)
    assert error is None


def test_empty_declaration_is_malformed():
    """Empty declaration (no text after colon) fails closed."""
    row = issue(10, body="OC-SWARM-DEPENDS-ON:")
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-empty"


def test_whitespace_only_declaration_is_malformed():
    """Whitespace-only declaration fails closed."""
    row = issue(10, body="OC-SWARM-DEPENDS-ON:   \n  \t")
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-empty"


def test_non_reference_declaration_is_malformed():
    """Declaration with text but no #NNN references fails closed."""
    row = issue(10, body="OC-SWARM-DEPENDS-ON: no numbers here")
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-non-reference"


def test_zero_reference_is_malformed():
    """#0 reference fails closed."""
    row = issue(10, body="OC-SWARM-DEPENDS-ON: #0")
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-zero-reference"


def test_zero_mixed_with_valid_references_is_malformed():
    """#0 mixed with valid references fails closed."""
    row = issue(10, body="OC-SWARM-DEPENDS-ON: #1, #0, #2")
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-zero-reference"


def test_mixed_valid_and_invalid_content_is_malformed():
    """Declaration with valid references plus invalid text fails closed."""
    row = issue(10, body="OC-SWARM-DEPENDS-ON: #1, invalid text, #2")
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-mixed-invalid"


def test_repeated_declaration_lines_fail_closed():
    """Multiple OC-SWARM-DEPENDS-ON lines fail closed."""
    body = "OC-SWARM-DEPENDS-ON: #1\nSome text in between\nOC-SWARM-DEPENDS-ON: #2"
    row = issue(10, body=body)
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-repeated"


def test_repeated_declaration_with_case_insensitive_matching():
    """Case-insensitive repeated declarations fail closed."""
    body = "OC-SWARM-DEPENDS-ON: #1\nSome text\noc-swarm-depends-on: #2"
    row = issue(10, body=body)
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-repeated"


def test_blank_declaration_does_not_consume_following_line():
    """Empty declaration followed by content doesn't try to parse next line."""
    body = "OC-SWARM-DEPENDS-ON:\n#1 is on the next line but should not be parsed"
    row = issue(10, body=body)
    error = deps._validate_dependencies_declaration(row)
    assert error == "malformed-declaration-empty"


def test_malformation_blocks_only_affected_issue():
    """Malformed dependency on one issue doesn't affect unrelated issues."""
    graph = deps.build_dependency_graph(
        [
            issue(1, body="OC-SWARM-DEPENDS-ON:"),  # Malformed
            issue(2, state="CLOSED"),  # Valid, no dependencies, closed
            issue(3, body="OC-SWARM-DEPENDS-ON: #2"),  # Valid, depends on closed issue
        ]
    )
    # Issue 1 should be blocked with error.
    assert graph["status"][1]["ready"] is False
    assert graph["status"][1]["error"] == "malformed-declaration-empty"
    # Issue 2 should be ready.
    assert graph["status"][2]["ready"] is True
    # Issue 3 should be ready (depends on ready issue 2).
    assert graph["status"][3]["ready"] is True


def test_dependencies_function_preserves_idempotence():
    """Calling dependencies() multiple times on same issue dict returns same result."""
    row = issue(10, body="OC-SWARM-DEPENDS-ON: #1, #2, #3")
    result1 = deps.dependencies(row)
    result2 = deps.dependencies(row)
    result3 = deps.dependencies(row)
    assert result1 == result2 == result3


def test_build_dependency_graph_does_not_mutate_input_issues():
    """build_dependency_graph should not modify input issue dictionaries."""
    issues = [
        issue(1, body="OC-SWARM-DEPENDS-ON: #2"),
        issue(2, state="CLOSED"),
    ]
    # Take snapshots of the issues.
    snapshot1 = [dict(i) for i in issues]
    # Build graph.
    deps.build_dependency_graph(issues)
    # Verify no mutations.
    assert issues == snapshot1


def test_empty_declaration_on_one_line_valid_on_next_line():
    """Two sequential declarations where first is empty still rejects both."""
    body = "OC-SWARM-DEPENDS-ON:\nOC-SWARM-DEPENDS-ON: #1"
    row = issue(10, body=body)
    deps_list, error = deps.dependencies(row)
    assert deps_list == []
    assert error == "malformed-declaration-repeated"
