#!/usr/bin/env python3
"""Quick verification script for warning status changes."""
from runtime.bottlenecks import BottleneckService
from runtime.goals import GoalPlannerService
from runtime.models import HealthCheckResult

# Initialize services
bottleneck_service = BottleneckService()
goal_planner = GoalPlannerService()

# Test 1: Single warning check
print("Test 1: Single warning check")
health = [HealthCheckResult(component="backend", status="warning", message="HTTP 500")]
result = bottleneck_service.detect(health)
print(f"  Bottleneck: {result}")
goal = goal_planner.plan(result)
print(f"  Goal: {goal}")
assert result == "Degraded service: backend — HTTP 500", f"Failed: {result}"
assert goal == "Investigate degraded service and rerun health checks.", f"Failed: {goal}"
print("  ✓ PASSED\n")

# Test 2: Multiple warning checks
print("Test 2: Multiple warning checks (order preserved)")
health = [
    HealthCheckResult(component="backend", status="warning", message="HTTP 500"),
    HealthCheckResult(component="frontend", status="warning", message="HTTP 503")
]
result = bottleneck_service.detect(health)
print(f"  Bottleneck: {result}")
goal = goal_planner.plan(result)
print(f"  Goal: {goal}")
assert result == "Degraded service: backend — HTTP 500; frontend — HTTP 503", f"Failed: {result}"
assert goal == "Investigate degraded service and rerun health checks.", f"Failed: {goal}"
print("  ✓ PASSED\n")

# Test 3: Warning with healthy checks
print("Test 3: Warning with healthy checks")
health = [
    HealthCheckResult(component="database", status="healthy", message="OK"),
    HealthCheckResult(component="backend", status="warning", message="HTTP 500"),
]
result = bottleneck_service.detect(health)
print(f"  Bottleneck: {result}")
goal = goal_planner.plan(result)
print(f"  Goal: {goal}")
assert result == "Degraded service: backend — HTTP 500", f"Failed: {result}"
assert goal == "Investigate degraded service and rerun health checks.", f"Failed: {goal}"
print("  ✓ PASSED\n")

# Test 4: Critical takes priority over warning
print("Test 4: Critical takes priority over warning")
health = [
    HealthCheckResult(component="database", status="critical", message="Offline"),
    HealthCheckResult(component="backend", status="warning", message="HTTP 500"),
]
result = bottleneck_service.detect(health)
print(f"  Bottleneck: {result}")
goal = goal_planner.plan(result)
print(f"  Goal: {goal}")
assert result == "Critical service failure: database — Offline", f"Failed: {result}"
assert goal == "Restore failed service and rerun health checks.", f"Failed: {goal}"
print("  ✓ PASSED\n")

# Test 5: Unknown takes priority over warning
print("Test 5: Unknown takes priority over warning")
health = [
    HealthCheckResult(component="backend", status="warning", message="HTTP 500"),
    HealthCheckResult(component="external_api", status="unknown", message="Missing"),
]
result = bottleneck_service.detect(health)
print(f"  Bottleneck: {result}")
goal = goal_planner.plan(result)
print(f"  Goal: {goal}")
assert result == "Missing configuration or visibility: external_api", f"Failed: {result}"
assert goal == "Configure missing runtime environment variables and rerun health checks.", f"Failed: {goal}"
print("  ✓ PASSED\n")

# Test 6: All healthy still works
print("Test 6: All healthy checks still works")
health = [
    HealthCheckResult(component="database", status="healthy", message="OK"),
]
result = bottleneck_service.detect(health)
print(f"  Bottleneck: {result}")
goal = goal_planner.plan(result)
print(f"  Goal: {goal}")
assert result == "No critical operational bottleneck detected across 1 health checks.", f"Failed: {result}"
assert goal == "No corrective goal; all health checks passed. Continue monitoring.", f"Failed: {goal}"
print("  ✓ PASSED\n")

# Test 7: Empty health checks still works
print("Test 7: Empty health checks still works")
result = bottleneck_service.detect([])
print(f"  Bottleneck: {result}")
goal = goal_planner.plan(result)
print(f"  Goal: {goal}")
assert result == "Missing configuration or visibility: no health checks reported.", f"Failed: {result}"
assert goal == "Run the health checks; none were reported.", f"Failed: {goal}"
print("  ✓ PASSED\n")

print("=" * 60)
print("ALL VERIFICATION TESTS PASSED! ✓")
print("=" * 60)
