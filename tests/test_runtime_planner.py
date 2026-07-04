from runtime.runtime_planner import RuntimePlanner


def test_runtime_planner_discovery_reports_modules():
    discovery = RuntimePlanner().discovery()
    assert discovery["build"] == "BUILD-012C"
    assert discovery["module_count"] >= 1


def test_runtime_planner_queue_contains_selectable_modules():
    queue = RuntimePlanner().queue()
    assert queue["build"] == "BUILD-012C"
    assert queue["queue_depth"] >= 1
    assert any(item["module_name"] == "DatabaseInspector" for item in queue["queue"])


def test_runtime_planner_skips_planned_modules():
    queue = RuntimePlanner().queue()
    assert any(item["reason"] == "module is still planned" for item in queue["skipped"])
