"""Tests for BottleneckService.detect()"""
from runtime.bottlenecks import BottleneckService
from runtime.goals import GoalPlannerService
from runtime.models import HealthCheckResult


class TestBottleneckServiceDetect:
    """Test BottleneckService.detect() with all branches."""

    def setup_method(self):
        self.service = BottleneckService()
        self.goal_planner = GoalPlannerService()

    def test_empty_health_list(self):
        """Empty health list returns no checks reported message."""
        result = self.service.detect([])
        assert result == "Missing configuration or visibility: no health checks reported."
        # Verify it maps to the correct goal
        goal = self.goal_planner.plan(result)
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_single_critical_check(self):
        """Single critical check returns Critical service failure with component and message."""
        health = [
            HealthCheckResult(
                component="database",
                status="critical",
                message="Connection timeout",
            )
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: database — Connection timeout"
        # Verify it maps to the correct goal
        goal = self.goal_planner.plan(result)
        assert goal == "Restore failed service and rerun health checks."

    def test_multiple_critical_checks(self):
        """Multiple critical checks returns all critical components with messages."""
        health = [
            HealthCheckResult(
                component="database",
                status="critical",
                message="Connection timeout",
            ),
            HealthCheckResult(
                component="cache",
                status="critical",
                message="Service unavailable",
            ),
        ]
        result = self.service.detect(health)
        assert (
            result
            == "Critical service failure: database — Connection timeout; cache — Service unavailable"
        )
        # Verify it maps to the correct goal
        goal = self.goal_planner.plan(result)
        assert goal == "Restore failed service and rerun health checks."

    def test_single_unknown_check(self):
        """Single unknown check returns Missing configuration or visibility with component."""
        health = [
            HealthCheckResult(
                component="api_key",
                status="unknown",
                message="Not provided",
            )
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: api_key"
        # Verify it maps to the correct goal
        goal = self.goal_planner.plan(result)
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_multiple_unknown_checks(self):
        """Multiple unknown checks returns all unknown components."""
        health = [
            HealthCheckResult(
                component="api_key",
                status="unknown",
                message="Not provided",
            ),
            HealthCheckResult(
                component="db_password",
                status="unknown",
                message="Not provided",
            ),
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: api_key, db_password"
        # Verify it maps to the correct goal
        goal = self.goal_planner.plan(result)
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_single_healthy_check(self):
        """Single healthy check returns count of checks."""
        health = [
            HealthCheckResult(
                component="database",
                status="healthy",
                message="Connected",
            )
        ]
        result = self.service.detect(health)
        assert result == "No critical operational bottleneck detected across 1 health checks."

    def test_multiple_healthy_checks(self):
        """Multiple healthy checks returns count of checks."""
        health = [
            HealthCheckResult(
                component="database",
                status="healthy",
                message="Connected",
            ),
            HealthCheckResult(
                component="cache",
                status="healthy",
                message="Connected",
            ),
            HealthCheckResult(
                component="api",
                status="healthy",
                message="Responding",
            ),
        ]
        result = self.service.detect(health)
        assert result == "No critical operational bottleneck detected across 3 health checks."

    def test_mixed_healthy_and_warning(self):
        """Mixed healthy and warning (non-critical, non-unknown) checks returns count."""
        health = [
            HealthCheckResult(
                component="database",
                status="healthy",
                message="Connected",
            ),
            HealthCheckResult(
                component="cache",
                status="warning",
                message="High memory usage",
            ),
        ]
        result = self.service.detect(health)
        assert result == "No critical operational bottleneck detected across 2 health checks."

    def test_critical_takes_precedence_over_unknown(self):
        """Critical checks take precedence over unknown checks."""
        health = [
            HealthCheckResult(
                component="database",
                status="critical",
                message="Connection timeout",
            ),
            HealthCheckResult(
                component="api_key",
                status="unknown",
                message="Not provided",
            ),
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: database — Connection timeout"

    def test_unknown_takes_precedence_over_healthy(self):
        """Unknown checks take precedence over healthy checks."""
        health = [
            HealthCheckResult(
                component="database",
                status="healthy",
                message="Connected",
            ),
            HealthCheckResult(
                component="api_key",
                status="unknown",
                message="Not provided",
            ),
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: api_key"

    def test_preserves_input_order_for_critical(self):
        """Critical checks are reported in input order."""
        health = [
            HealthCheckResult(
                component="z_service",
                status="critical",
                message="Failed",
            ),
            HealthCheckResult(
                component="a_service",
                status="critical",
                message="Failed",
            ),
        ]
        result = self.service.detect(health)
        assert (
            result
            == "Critical service failure: z_service — Failed; a_service — Failed"
        )

    def test_preserves_input_order_for_unknown(self):
        """Unknown checks are reported in input order."""
        health = [
            HealthCheckResult(
                component="z_variable",
                status="unknown",
                message="Not provided",
            ),
            HealthCheckResult(
                component="a_variable",
                status="unknown",
                message="Not provided",
            ),
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: z_variable, a_variable"
