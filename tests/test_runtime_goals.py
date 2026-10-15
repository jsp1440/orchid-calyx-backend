from __future__ import annotations

from runtime.bottlenecks import BottleneckService
from runtime.goals import GoalPlannerService
from runtime.models import HealthCheckResult


class TestGoalPlannerService:
    """Test cases for GoalPlannerService.plan()"""

    def setup_method(self):
        self.planner = GoalPlannerService()
        self.bottleneck_service = BottleneckService()

    # Test critical service failure
    def test_critical_service_failure(self):
        """Critical service failure should return restore goal."""
        result = self.planner.plan("Critical service failure: auth_service — Authentication service is down")
        assert result == "Restore failed service and rerun health checks."

    def test_critical_service_failure_multiple(self):
        """Critical service failure with multiple services should return restore goal."""
        result = self.planner.plan("Critical service failure: auth_service — Down; database — Offline")
        assert result == "Restore failed service and rerun health checks."

    # Test no health checks reported (empty health list)
    def test_no_health_checks_reported_exact_match(self):
        """Empty health list message should return health checks goal."""
        result = self.planner.plan("Missing configuration or visibility: no health checks reported.")
        assert result == "Run the health checks; none were reported."

    def test_no_health_checks_reported_from_bottleneck_service(self):
        """Empty health list through BottleneckService should map correctly."""
        bottleneck = self.bottleneck_service.detect([])
        assert bottleneck == "Missing configuration or visibility: no health checks reported."
        result = self.planner.plan(bottleneck)
        assert result == "Run the health checks; none were reported."

    # Test missing configuration or visibility (other than empty health)
    def test_missing_configuration_single(self):
        """Missing configuration with single component should return configure goal."""
        result = self.planner.plan("Missing configuration or visibility: external_api")
        assert result == "Configure missing runtime environment variables and rerun health checks."

    def test_missing_configuration_multiple(self):
        """Missing configuration with multiple components should return configure goal."""
        result = self.planner.plan("Missing configuration or visibility: external_api, live_cds")
        assert result == "Configure missing runtime environment variables and rerun health checks."

    def test_missing_configuration_from_bottleneck_service(self):
        """Unknown health checks through BottleneckService should map correctly."""
        health = [
            HealthCheckResult(
                component="external_api",
                status="unknown",
                message="Configuration missing"
            )
        ]
        bottleneck = self.bottleneck_service.detect(health)
        assert bottleneck.startswith("Missing configuration or visibility: ")
        result = self.planner.plan(bottleneck)
        assert result == "Configure missing runtime environment variables and rerun health checks."

    # Test no critical bottleneck detected
    def test_no_critical_bottleneck_single_check(self):
        """No bottleneck with single healthy check should return continue monitoring goal."""
        result = self.planner.plan("No critical operational bottleneck detected across 1 health checks.")
        assert result == "No corrective goal; all health checks passed. Continue monitoring."

    def test_no_critical_bottleneck_multiple_checks(self):
        """No bottleneck with multiple healthy checks should return continue monitoring goal."""
        result = self.planner.plan("No critical operational bottleneck detected across 5 health checks.")
        assert result == "No corrective goal; all health checks passed. Continue monitoring."

    def test_no_critical_bottleneck_from_bottleneck_service(self):
        """All healthy checks through BottleneckService should map correctly."""
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
        ]
        bottleneck = self.bottleneck_service.detect(health)
        assert bottleneck.startswith("No critical operational bottleneck detected")
        result = self.planner.plan(bottleneck)
        assert result == "No corrective goal; all health checks passed. Continue monitoring."

    # Test unrecognized bottleneck (fallback)
    def test_unrecognized_bottleneck_empty_string(self):
        """Empty string should return investigate goal (never a roadmap item)."""
        result = self.planner.plan("")
        assert result == "Investigate unrecognized bottleneck report and rerun health checks."

    def test_unrecognized_bottleneck_arbitrary_string(self):
        """Arbitrary unknown string should return investigate goal."""
        result = self.planner.plan("Some unknown bottleneck type")
        assert result == "Investigate unrecognized bottleneck report and rerun health checks."

    def test_unrecognized_bottleneck_substring_not_prefix(self):
        """Substring matches should not trigger prefix rules (use startswith only)."""
        result = self.planner.plan("This has Critical service failure: in the middle")
        assert result == "Investigate unrecognized bottleneck report and rerun health checks."

    def test_unrecognized_bottleneck_missing_colon_space(self):
        """'Critical service failure' without colon-space should not match."""
        result = self.planner.plan("Critical service failure without proper format")
        assert result == "Investigate unrecognized bottleneck report and rerun health checks."

    def test_unrecognized_bottleneck_no_prefix_match(self):
        """String that contains known phrase but not at start should return investigate goal."""
        result = self.planner.plan("Something Missing configuration or visibility: test")
        assert result == "Investigate unrecognized bottleneck report and rerun health checks."

    # Integration tests with real BottleneckService outputs
    def test_integration_critical_failure(self):
        """Real critical failure from BottleneckService should map to restore goal."""
        health = [
            HealthCheckResult(
                component="auth_service",
                status="critical",
                message="Authentication service is down"
            )
        ]
        bottleneck = self.bottleneck_service.detect(health)
        goal = self.planner.plan(bottleneck)
        assert goal == "Restore failed service and rerun health checks."

    def test_integration_unknown_config(self):
        """Real unknown/config issue from BottleneckService should map to configure goal."""
        health = [
            HealthCheckResult(
                component="external_api",
                status="unknown",
                message="Configuration missing for external API"
            )
        ]
        bottleneck = self.bottleneck_service.detect(health)
        goal = self.planner.plan(bottleneck)
        assert goal == "Configure missing runtime environment variables and rerun health checks."

    def test_integration_empty_health(self):
        """Real empty health from BottleneckService should map to run health checks goal."""
        bottleneck = self.bottleneck_service.detect([])
        goal = self.planner.plan(bottleneck)
        assert goal == "Run the health checks; none were reported."

    def test_integration_all_healthy(self):
        """Real all-healthy from BottleneckService should map to continue monitoring goal."""
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
        bottleneck = self.bottleneck_service.detect(health)
        goal = self.planner.plan(bottleneck)
        assert goal == "No corrective goal; all health checks passed. Continue monitoring."

    # Ensure no hardcoded roadmap items
    def test_never_returns_roadmap_item_on_healthy(self):
        """Healthy bottleneck must never return the old hardcoded roadmap item."""
        result = self.planner.plan("No critical operational bottleneck detected across 3 health checks.")
        assert "Convert HealthMonitorService into a backend API endpoint" not in result
        assert "Mission Control" not in result

    def test_never_returns_roadmap_item_on_unknown(self):
        """Unknown bottleneck string must never return the old hardcoded roadmap item."""
        result = self.planner.plan("completely unknown bottleneck format")
        assert "Convert HealthMonitorService into a backend API endpoint" not in result
        assert "Mission Control" not in result

    def test_never_returns_roadmap_item_on_empty(self):
        """Empty string must never return the old hardcoded roadmap item."""
        result = self.planner.plan("")
        assert "Convert HealthMonitorService into a backend API endpoint" not in result
        assert "Mission Control" not in result
