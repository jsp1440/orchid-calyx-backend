from app.calyx_orchestrator.lane_queue import TaskStatus
from app.calyx_orchestrator.lane_queue_backlog import (
    TWO_DAY_BACKLOG_REFS,
    TWO_DAY_BACKLOG_TASKS,
    build_two_day_lane_queue,
)


def test_seed_has_exactly_the_34_item_issue_1024_backlog():
    assert len(TWO_DAY_BACKLOG_TASKS) == 34


def test_seed_task_keys_are_unique_and_stable():
    keys = [task.task_key for task in TWO_DAY_BACKLOG_TASKS]
    assert len(keys) == len(set(keys))
    assert keys[0] == "two-day-001-audit-data-integration-convergence"
    assert keys[-1] == "two-day-034-two-day-final-evidence-packet"


def test_seed_priority_strictly_decreases_in_issue_order():
    priorities = [task.priority for task in TWO_DAY_BACKLOG_TASKS]
    assert priorities == sorted(priorities, reverse=True)
    assert len(set(priorities)) == len(priorities)


def test_seed_refs_cover_every_task_key_and_only_those_keys():
    task_keys = {task.task_key for task in TWO_DAY_BACKLOG_TASKS}
    assert set(TWO_DAY_BACKLOG_REFS) == task_keys


def test_seed_links_canonical_issues_instead_of_duplicating_them():
    audit_convergence = TWO_DAY_BACKLOG_REFS["two-day-001-audit-data-integration-convergence"]
    assert "#1020" in audit_convergence

    literature_kg = TWO_DAY_BACKLOG_REFS["two-day-004-literature-kg-orchestration"]
    assert "#1021" in literature_kg and "#901" in literature_kg


def test_build_two_day_lane_queue_admits_the_five_highest_priority_p0_items():
    queue = build_two_day_lane_queue(width=5)
    status = queue.status()
    assert len(status["active"]) == 5
    assert [item["task_key"] for item in status["active"]] == [
        "two-day-001-audit-data-integration-convergence",
        "two-day-002-audit-followthrough",
        "two-day-003-event-driven-continuation",
        "two-day-004-literature-kg-orchestration",
        "two-day-005-living-atlas-convergence",
    ]


def test_build_two_day_lane_queue_admits_p1_item_when_a_p0_lane_frees_up():
    queue = build_two_day_lane_queue(width=5)
    result = queue.advance(
        "two-day-001-audit-data-integration-convergence", TaskStatus.VERIFIED
    )
    assert result["admitted"] == ["two-day-006-featured-genus-convergence"]


def test_build_two_day_lane_queue_never_leaves_a_lane_idle_while_backlog_remains():
    queue = build_two_day_lane_queue(width=5)
    for _ in range(29):
        active_key = queue.status()["active"][0]["task_key"]
        queue.advance(active_key, TaskStatus.VERIFIED)
    status = queue.status()
    assert len(status["active"]) == 5
    assert status["queued_next"] == []
