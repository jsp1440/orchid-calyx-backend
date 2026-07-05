"""Tests for HealthConnector."""

from __future__ import annotations

from runtime.connectors.health_connector import HealthConnector


def test_health_connector_name():
    """Test health connector name."""
    connector = HealthConnector()
    assert connector.name == "health"


def test_health_connector_health():
    """Test health connector health check."""
    connector = HealthConnector()
    health = connector.health()
    assert health["status"] == "healthy"
    assert "timestamp" in health


def test_health_connector_status_task():
    """Test health connector status task."""
    connector = HealthConnector()
    result = connector.execute("status")
    assert result["status"] == "healthy"
    assert result["service"] == "health"
    assert "timestamp" in result


def test_health_connector_ping_task():
    """Test health connector ping task."""
    connector = HealthConnector()
    result = connector.execute("ping")
    assert result["message"] == "pong"
    assert "timestamp" in result


def test_health_connector_unknown_task():
    """Test health connector with unknown task."""
    connector = HealthConnector()
    try:
        connector.execute("unknown")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown task" in str(e)
