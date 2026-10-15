from __future__ import annotations

from runtime.bottlenecks import BottleneckService
from runtime.goals import GoalPlannerService
from runtime.models import HealthCheckResult


class TestBottleneckService:
    """Test cases for BottleneckService.detect()"""

    def setup_method(self):
        self.service = BottleneckService()
        self.goal_planner = GoalPlannerService()

    def test_empty_health_list(self):
        """Empty health list should report no checks reported."""
        result = self.service.detect([])
        assert result == "Missing configuration or visibility: no health checks reported."

    def test_no_critical_no_unknown_single_check(self):
        """One healthy check should report the count."""
        health = [
            HealthCheckResult(
                component="database",
                status="healthy",
                message="Database connection successful"
            )
        ]
        result = self.service.detect(health)
        assert result == "No critical operational bottleneck detected across 1 health checks."

    def test_no_critical_no_unknown_multiple_checks(self):
        """Multiple healthy checks should report the count."""
        health = [
            HealthCheckResult(
                component="database",
                status="healthy",
                message="Database connection successful"
            ),
            HealthCheckResult(
                component="cache",
                status="healthy",
                message="Cache is responsive"
            ),
            HealthCheckResult(
                component="api",
                status="healthy",
                message="API is responding"
            ),
        ]
        result = self.service.detect(health)
        assert result == "No critical operational bottleneck detected across 3 health checks."
        # Verify that GoalPlannerService maps to continue monitoring goal
        goal = self.goal_planner.plan(result)
        assert goal == "No corrective goal; all health checks passed. Continue monitoring."

    def test_single_critical_check(self):
        """Single critical check should report it."""
        health = [
            HealthCheckResult(
                component="auth_service",
                status="critical",
                message="Authentication service is down"
            )
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: auth_service — Authentication service is down"
        # Verify that GoalPlannerService maps to restore goal
        goal = self.goal_planner.plan(result)
        assert goal == "Restore failed service and rerun health checks."

    def test_multiple_critical_checks(self):
        """Multiple critical checks should all be reported."""
        health = [
            HealthCheckResult(
                component="auth_service",
                status="critical",
                message="Authentication service is down"
            ),
            HealthCheckResult(
                component="database",
                status="critical",
                message="Database connection failed"
            ),
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: auth_service — Authentication service is down; database — Database connection failed"
        # Verify that GoalPlannerService still recognizes it as critical
        goal = self.goal_planner.plan(result)
        assert goal == "Restore failed service and rerun health checks."

    def test_single_unknown_check(self):
        """Single unknown check should report it."""
        health = [
            HealthCheckResult(
                component="external_api",
                status="unknown",
                message="Configuration missing for external API"
            )
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: external_api"
        # Verify that GoalPlannerService maps to configuration goal
        goal = self.goal_planner.plan(result)
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_multiple_unknown_checks(self):
        """Multiple unknown checks should all be reported."""
        health = [
            HealthCheckResult(
                component="external_api",
                status="unknown",
                message="Configuration missing for external API"
            ),
            HealthCheckResult(
                component="live_cds",
                status="unknown",
                message="CDS integration not configured"
            ),
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: external_api, live_cds"
        # Verify that GoalPlannerService still recognizes it as missing configuration
        goal = self.goal_planner.plan(result)
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_critical_takes_priority_over_unknown(self):
        """When both critical and unknown exist, critical should be reported."""
        health = [
            HealthCheckResult(
                component="database",
                status="critical",
                message="Database is offline"
            ),
            HealthCheckResult(
                component="external_api",
                status="unknown",
                message="Configuration missing"
            ),
            HealthCheckResult(
                component="cache",
                status="healthy",
                message="Cache is working"
            ),
        ]
        result = self.service.detect(health)
        assert result == "Critical service failure: database — Database is offline"
        goal = self.goal_planner.plan(result)
        assert goal == "Restore failed service and rerun health checks."

    def test_unknown_with_healthy_checks(self):
        """Unknown checks should be reported even with healthy checks present."""
        health = [
            HealthCheckResult(
                component="cache",
                status="healthy",
                message="Cache is working"
            ),
            HealthCheckResult(
                component="external_api",
                status="unknown",
                message="Configuration missing"
            ),
        ]
        result = self.service.detect(health)
        assert result == "Missing configuration or visibility: external_api"
        goal = self.goal_planner.plan(result)
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_preserves_input_order_for_critical(self):
        """Critical checks should appear in input order."""
        health = [
            HealthCheckResult(
                component="service_c",
                status="critical",
                message="Failed"
            ),
            HealthCheckResult(
                component="service_a",
                status="critical",
                message="Down"
            ),
            HealthCheckResult(
                component="service_b",
                status="critical",
                message="Offline"
            ),
        ]
        result = self.service.detect(health)
        # Should maintain input order, not alphabetical
        assert result == "Critical service failure: service_c — Failed; service_a — Down; service_b — Offline"

    def test_preserves_input_order_for_unknown(self):
        """Unknown checks should appear in input order."""
        health = [
            HealthCheckResult(
                component="zebra_api",
                status="unknown",
                message="Missing"
            ),
            HealthCheckResult(
                component="alpha_api",
                status="unknown",
                message="Not configured"
            ),
            HealthCheckResult(
                component="beta_api",
                status="unknown",
                message="No visibility"
            ),
        ]
        result = self.service.detect(health)
        # Should maintain input order, not alphabetical
        assert result == "Missing configuration or visibility: zebra_api, alpha_api, beta_api"

    def test_no_next_bottleneck_assertion(self):
        """The report should never include unobserved 'next bottleneck' claims."""
        health = [
            HealthCheckResult(
                component="database",
                status="healthy",
                message="Database working"
            ),
        ]
        result = self.service.detect(health)
        # Should not contain the old hardcoded "Next bottleneck" claim
        assert "Next bottleneck" not in result
        assert "live CDS integration" not in result
