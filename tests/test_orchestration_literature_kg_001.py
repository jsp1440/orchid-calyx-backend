"""ORCHESTRATION-LITERATURE-KG-001: literature harvest -> ingest -> extract ->
taxon-bind -> publication-eligibility -> KG-materialization mission lane.

Focused regressions for task seeding, agent assignment, priority ordering,
safe (read-only/audit-style) executor behavior, and the scientific-integrity
distinctions the issue requires: harvested != ingested != extracted !=
taxonomically bound != publication-eligible != materialized, and missing
telemetry must never be reported as a measured zero.
"""

from __future__ import annotations

from runtime.autonomous_orchestrator import (
    DEFAULT_AGENTS,
    DEFAULT_TASKS,
    LITERATURE_KG_TASK_TYPES,
    DefaultTaskExecutor,
    RISKY_ACTIONS,
)

LITERATURE_KG_TASKS = [task for task in DEFAULT_TASKS if task["task_type"] in LITERATURE_KG_TASK_TYPES]


def test_all_seven_required_task_types_are_defined():
    assert len(LITERATURE_KG_TASK_TYPES) == 7
    assert set(LITERATURE_KG_TASK_TYPES) == {
        "literature_harvest_freshness_audit",
        "literature_ingestion_provenance_audit",
        "literature_extraction_coverage_audit",
        "literature_methodology_extraction_audit",
        "literature_trait_measurement_extraction_audit",
        "literature_taxon_binding_integrity_audit",
        "literature_kg_materialization_readiness_audit",
    }


def test_default_seed_includes_a_task_for_every_required_task_type():
    seeded_types = {task["task_type"] for task in LITERATURE_KG_TASKS}
    assert seeded_types == set(LITERATURE_KG_TASK_TYPES)


def test_seeded_literature_kg_task_keys_are_stable_and_unique():
    keys = [task["task_key"] for task in LITERATURE_KG_TASKS]
    assert len(keys) == len(set(keys)), "task keys must be unique"
    for key in keys:
        assert key.startswith("orch-lit-kg-001:")

    # Task keys are a durable identity: renaming one silently orphans queue
    # history tied to the old key, so pin the exact set.
    assert set(keys) == {
        "orch-lit-kg-001:harvest-freshness-audit",
        "orch-lit-kg-001:ingestion-provenance-audit",
        "orch-lit-kg-001:extraction-coverage-audit",
        "orch-lit-kg-001:methodology-extraction-audit",
        "orch-lit-kg-001:trait-measurement-extraction-audit",
        "orch-lit-kg-001:taxon-binding-integrity-audit",
        "orch-lit-kg-001:materialization-readiness-audit",
    }


def test_literature_kg_tasks_seeded_as_needs_review_pending_live_telemetry():
    for task in LITERATURE_KG_TASKS:
        assert task.get("needs_review") is True, task["task_key"]


def test_literature_kg_task_priority_is_visible_without_displacing_safety_work():
    backend_safety_tasks = {
        "build-044:backend-health-check": 100,
        "build-044:runner-queue-audit": 90,
        "build-044:mycorrhiza-cache-audit": 80,
    }
    for task_key, expected_priority in backend_safety_tasks.items():
        matches = [task for task in DEFAULT_TASKS if task["task_key"] == task_key]
        assert matches and matches[0]["priority"] == expected_priority

    min_safety_priority = min(backend_safety_tasks.values())
    prior_audit_priorities = [
        task["priority"]
        for task in DEFAULT_TASKS
        if task["task_key"]
        in {
            "build-044:frontend-audit",
            "build-044:image-coverage-audit",
            "build-044:relationship-data-audit",
        }
    ]

    for task in LITERATURE_KG_TASKS:
        assert task["priority"] < min_safety_priority, (
            f"{task['task_key']} priority must not outrank/displace backend health/safety tasks"
        )
        assert task["priority"] > max(prior_audit_priorities), (
            f"{task['task_key']} priority must remain visible above pre-existing coverage-gap audits"
        )


def test_literature_kg_agent_is_registered_enabled_with_capability_statement():
    matches = [agent for agent in DEFAULT_AGENTS if agent["agent_name"] == "literature_kg"]
    assert len(matches) == 1
    agent = matches[0]

    assert agent["enabled"] is True
    assert isinstance(agent["capability"], str) and len(agent["capability"]) > 20
    assert set(agent["allowed_task_types"]) == set(LITERATURE_KG_TASK_TYPES)


def test_literature_kg_task_types_are_not_accidentally_risky_actions():
    # These are audit tasks, not release actions; they must not collide with
    # the risky-action approval-gate vocabulary used for deploy/merge/delete/etc.
    assert set(LITERATURE_KG_TASK_TYPES).isdisjoint(RISKY_ACTIONS)


def test_only_literature_kg_agent_can_execute_these_task_types():
    other_agents = [agent for agent in DEFAULT_AGENTS if agent["agent_name"] != "literature_kg"]
    for agent in other_agents:
        allowed = set(agent.get("allowed_task_types") or [])
        assert allowed.isdisjoint(LITERATURE_KG_TASK_TYPES), agent["agent_name"]


def _execute(task_type: str, payload: dict | None = None):
    executor = DefaultTaskExecutor()
    task = {"task_type": task_type, "payload": payload or {}}
    agent = {"agent_name": "literature_kg"}
    return executor.execute(task, agent)


def test_executor_is_read_only_and_needs_review_for_every_literature_kg_task_type():
    for task_type in LITERATURE_KG_TASK_TYPES:
        seeded_payload = next(
            (task["payload"] for task in LITERATURE_KG_TASKS if task["task_type"] == task_type),
            {},
        )
        outcome = _execute(task_type, seeded_payload)

        assert outcome.status == "needs_review", task_type
        assert outcome.evaluation_result == "needs_review", task_type
        assert outcome.result["changed"] == [], task_type
        assert "graph_publication" in outcome.result["skipped"], task_type
        assert "graph_materialization" in outcome.result["skipped"], task_type


def test_missing_telemetry_is_unavailable_never_a_fabricated_zero():
    for task_type in LITERATURE_KG_TASK_TYPES:
        outcome = _execute(task_type)
        result = outcome.result

        # Flatten one level so the materialization audit's nested
        # pipeline_stage_counts is checked alongside the flat fields.
        values = dict(result)
        values.update(result.get("pipeline_stage_counts", {}))

        for key, value in values.items():
            if key in {"changed", "skipped", "inspected", "message", "next_action"}:
                continue
            # Booleans (e.g. "dedicated_methodology_extractor_registered": False)
            # are real static facts, not counts, and must not trip a "fabricated
            # zero" check just because False == 0 in Python.
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)) and value == 0:
                raise AssertionError(
                    f"{task_type}.{key} reported a fabricated zero instead of 'unavailable'/'unknown'"
                )


def test_harvested_ingested_extracted_bound_eligible_materialized_are_distinct_fields():
    outcome = _execute("literature_kg_materialization_readiness_audit")
    stage_counts = outcome.result["pipeline_stage_counts"]

    expected_stage_keys = {
        "harvested",
        "ingested",
        "extracted",
        "taxonomically_bound",
        "publication_eligible",
        "materialized",
    }
    assert set(stage_counts.keys()) == expected_stage_keys

    # Every stage is reported independently (all currently unavailable without
    # a live connection) -- none may be silently aliased to another stage.
    assert len(stage_counts) == len(expected_stage_keys)
    for stage_key in expected_stage_keys:
        assert stage_counts[stage_key] == "unavailable"


def test_materialization_readiness_audit_never_claims_production_graph_truth():
    outcome = _execute("literature_kg_materialization_readiness_audit")
    result = outcome.result

    assert outcome.status == "needs_review"
    assert result["pipeline_stage_counts"]["materialized"] == "unavailable"
    assert "graph_publication" in result["skipped"]
    assert "graph_materialization" in result["skipped"]
    assert isinstance(result["materialization_blockers"], list) and result["materialization_blockers"]


def test_extraction_coverage_audit_distinguishes_extracted_from_registered_capability():
    outcome = _execute("literature_extraction_coverage_audit")
    result = outcome.result

    # "registered_extractors" describes pipeline *capability* (or explicit
    # unavailability when the pydantic-based extraction stack cannot be
    # imported); it must never be conflated with a live "extracted" count.
    assert result["extracted"] == "unavailable"
    assert result["registered_extractors"] == "unavailable" or isinstance(result["registered_extractors"], list)


def test_taxon_binding_audit_distinguishes_binding_contract_from_bound_count():
    outcome = _execute("literature_taxon_binding_integrity_audit")
    result = outcome.result

    assert result["taxonomically_bound"] == "unavailable"
    assert result["taxon_mapping"] == "unavailable" or isinstance(result["taxon_mapping"], str)
