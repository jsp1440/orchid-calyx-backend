"""Tests for BottleneckService.detect behavior."""

from __future__ import annotations

from runtime.bottlenecks import BottleneckService
from runtime.goals import GoalPlannerService
from runtime.models import HealthCheckResult


class TestBottleneckServiceDetect:
    """Test suite for BottleneckService.detect()."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.service = BottleneckService()
        self.goal_planner = GoalPlannerService()

    def test_empty_health_list(self) -> None:
        """Empty health list should return missing configuration message."""
        health: list[HealthCheckResult] = []
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: no health checks reported."

    def test_single_healthy_check(self) -> None:
        """Single healthy check should return bottleneck count message."""
        health = [HealthCheckResult(component="Database", status="healthy", message="OK")]
        result = self.service.detect(health)
        assert result == "No critical operational bottleneck detected across 1 health checks."

    def test_multiple_healthy_checks(self) -> None:
        """Multiple healthy checks should return bottleneck count message."""
        health = [
            HealthCheckResult(component="Database", status="healthy", message="OK"),
            HealthCheckResult(component="API", status="healthy", message="OK"),
            HealthCheckResult(component="Cache", status="healthy", message="OK"),
        ]
        result = self.service.detect(health)
        assert result == "No critical operational bottleneck detected across 3 health checks."

    def test_single_critical_check(self) -> None:
        """Single critical check should return critical prefix with component and message."""
        health = [
            HealthCheckResult(component="Database", status="critical", message="Connection timeout"),
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: Database — Connection timeout"

    def test_multiple_critical_checks(self) -> None:
        """Multiple critical checks should list all in input order, semicolon-separated."""
        health = [
            HealthCheckResult(component="Database", status="critical", message="Connection timeout"),
            HealthCheckResult(component="API", status="critical", message="Out of memory"),
            HealthCheckResult(component="Cache", status="healthy", message="OK"),
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: Database — Connection timeout; API — Out of memory"

    def test_critical_with_mixed_statuses(self) -> None:
        """Critical checks should be returned even with other statuses present."""
        health = [
            HealthCheckResult(component="Healthy1", status="healthy", message="OK"),
            HealthCheckResult(component="Critical1", status="critical", message="Failed"),
            HealthCheckResult(component="Healthy2", status="healthy", message="OK"),
            HealthCheckResult(component="Critical2", status="critical", message="Timeout"),
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: Critical1 — Failed; Critical2 — Timeout"

    def test_single_unknown_check(self) -> None:
        """Single unknown check should return missing configuration prefix with component."""
        health = [
            HealthCheckResult(component="Integration", status="unknown", message="No config found"),
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: Integration"

    def test_multiple_unknown_checks(self) -> None:
        """Multiple unknown checks should list all in input order, comma-separated."""
        health = [
            HealthCheckResult(component="Integration1", status="unknown", message="No config"),
            HealthCheckResult(component="Integration2", status="unknown", message="No config"),
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: Integration1, Integration2"

    def test_unknown_with_mixed_statuses(self) -> None:
        """Unknown checks should be returned (no critical) with other statuses present."""
        health = [
            HealthCheckResult(component="Healthy1", status="healthy", message="OK"),
            HealthCheckResult(component="Unknown1", status="unknown", message="No config"),
            HealthCheckResult(component="Healthy2", status="healthy", message="OK"),
            HealthCheckResult(component="Unknown2", status="unknown", message="No config"),
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: Unknown1, Unknown2"

    def test_critical_takes_precedence_over_unknown(self) -> None:
        """Critical checks should be returned even if unknown checks exist."""
        health = [
            HealthCheckResult(component="Unknown1", status="unknown", message="No config"),
            HealthCheckResult(component="Critical1", status="critical", message="Failed"),
            HealthCheckResult(component="Unknown2", status="unknown", message="No config"),
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: Critical1 — Failed"

    def test_goal_planner_matches_critical_message(self) -> None:
        """GoalPlannerService should recognize critical service failure message."""
        health = [
            HealthCheckResult(component="Database", status="critical", message="Connection timeout"),
        ]
        bottleneck = self.service.detect(health)
        goal = self.goal_planner.plan(bottleneck)
        assert "Critical service failure" in bottleneck
        assert goal == "Restore failed service and rerun health checks."

    def test_goal_planner_matches_unknown_message(self) -> None:
        """GoalPlannerService should recognize missing configuration message."""
        health = [
            HealthCheckResult(component="Integration", status="unknown", message="No config"),
        ]
        bottleneck = self.service.detect(health)
        goal = self.goal_planner.plan(bottleneck)
        assert "Missing configuration" in bottleneck
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_goal_planner_matches_healthy_message(self) -> None:
        """GoalPlannerService should recognize healthy bottleneck message."""
        health = [
            HealthCheckResult(component="Database", status="healthy", message="OK"),
        ]
        bottleneck = self.service.detect(health)
        goal = self.goal_planner.plan(bottleneck)
        # Should match the default goal since it doesn't contain critical or missing config
        assert goal == "Convert HealthMonitorService into a backend API endpoint and display it in Mission Control."

    def test_empty_list_produces_missing_config_message(self) -> None:
        """Empty health list should be treated as missing visibility, not healthy."""
        health: list[HealthCheckResult] = []
        bottleneck = self.service.detect(health)
        goal = self.goal_planner.plan(bottleneck)
        assert "Missing configuration" in bottleneck
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_no_next_bottleneck_assertion(self) -> None:
        """Healthy result should never mention 'next bottleneck'."""
        health = [
            HealthCheckResult(component="Database", status="healthy", message="OK"),
            HealthCheckResult(component="API", status="healthy", message="OK"),
        ]
        result = self.service.detect(health)
        assert "next bottleneck" not in result.lower()
        assert "cds" not in result.lower()
