"""Tests for GRAPH-001B: persisted analysis-run records.

Matches the established convention for runtime.autonomous_runner-coupled code
(see tests/test_autonomous_runner.py): DB-touching functions require a real
Postgres connection unavailable in unit tests, so this module tests every
pure-logic path directly (hash determinism, dedup-key construction, the
validation errors that must fire before any connection is ever opened) and
otherwise confirms the module imports cleanly through the package's own
public API - no production writes are ever attempted here.
"""

from __future__ import annotations

import pytest

from runtime.knowledge_graph import (
    GRAPH_ANALYSIS_JOB_PREFIX,
    graph_analysis_dedup_key,
    record_graph_analysis_run,
)
from runtime.knowledge_graph.analysis_runs import _stable_hash


def test_module_exports_are_importable_from_the_package():
    assert callable(record_graph_analysis_run)
    assert callable(graph_analysis_dedup_key)
    assert GRAPH_ANALYSIS_JOB_PREFIX == "graph_analysis:"


def test_stable_hash_is_deterministic_regardless_of_key_order():
    a = _stable_hash({"depth": 1, "node_types": ["genus"]})
    b = _stable_hash({"node_types": ["genus"], "depth": 1})
    assert a == b


def test_stable_hash_differs_for_different_payloads():
    assert _stable_hash({"depth": 1}) != _stable_hash({"depth": 2})


def test_dedup_key_is_deterministic_and_prefixed():
    params = {"depth": 1, "limit": 200}
    key_a = graph_analysis_dedup_key(algorithm="connected_components", scope="genus:560", parameters=params)
    key_b = graph_analysis_dedup_key(algorithm="connected_components", scope="genus:560", parameters=params)
    assert key_a == key_b
    assert key_a.startswith(GRAPH_ANALYSIS_JOB_PREFIX)
    assert "connected_components" in key_a
    assert "genus:560" in key_a


def test_dedup_key_differs_when_parameters_differ():
    key_a = graph_analysis_dedup_key(algorithm="degree", scope="genus:560", parameters={"weighted": True})
    key_b = graph_analysis_dedup_key(algorithm="degree", scope="genus:560", parameters={"weighted": False})
    assert key_a != key_b


def test_dedup_key_rejects_empty_algorithm_before_any_db_access():
    with pytest.raises(ValueError, match="GRAPH_ANALYSIS_ALGORITHM_REQUIRED"):
        graph_analysis_dedup_key(algorithm="  ", scope="genus:560", parameters={})


def test_dedup_key_rejects_empty_scope_before_any_db_access():
    with pytest.raises(ValueError, match="GRAPH_ANALYSIS_SCOPE_REQUIRED"):
        graph_analysis_dedup_key(algorithm="degree", scope="", parameters={})
