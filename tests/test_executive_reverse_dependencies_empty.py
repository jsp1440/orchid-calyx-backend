"""Tests for reverse_dependencies with explicit empty graph and default behavior."""

from runtime.executive.dependencies import dependency_graph, reverse_dependencies


def test_reverse_dependencies_empty_graph():
    """Empty graph {} should return empty dict, not the default graph."""
    result = reverse_dependencies({})
    assert result == {}
    assert len(result) == 0


def test_reverse_dependencies_default():
    """reverse_dependencies() with no args returns default built-in graph."""
    result = reverse_dependencies()
    assert len(result) > 0
    # Should match the result of calling with dependency_graph() explicitly
    assert result == reverse_dependencies(dependency_graph())


def test_reverse_dependencies_none_explicit():
    """reverse_dependencies(None) should return the default graph, same as no args."""
    result_default = reverse_dependencies()
    result_none = reverse_dependencies(None)
    assert result_default == result_none


def test_reverse_dependencies_single_edge():
    """Test with a simple one-edge graph."""
    graph = {"a": ["b"]}
    result = reverse_dependencies(graph)
    assert result == {"b": ["a"]}


def test_reverse_dependencies_multiple_edges():
    """Test with multiple edges to verify correctness."""
    graph = {
        "a": ["b", "c"],
        "d": ["b"],
    }
    result = reverse_dependencies(graph)
    assert result == {
        "b": ["a", "d"],
        "c": ["a"],
    }


def test_reverse_dependencies_no_dependencies():
    """Test with nodes that have no dependencies."""
    graph = {
        "a": [],
        "b": ["a"],
    }
    result = reverse_dependencies(graph)
    assert result == {"a": ["b"]}


def test_reverse_dependencies_sorts_dependents():
    """Verify that dependents are sorted in the result."""
    graph = {
        "z": ["m"],
        "a": ["m"],
        "x": ["m"],
    }
    result = reverse_dependencies(graph)
    assert result == {"m": ["a", "x", "z"]}
