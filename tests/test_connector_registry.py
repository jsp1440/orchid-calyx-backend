"""Tests for ConnectorRegistry."""

from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from runtime.connector_interface import ConnectorInterface
from runtime.connector_registry import ConnectorRegistry


class TestConnector(ConnectorInterface):
    """Test connector."""

    def __init__(self, name_value: str = "test", should_fail_health: bool = False):
        self._name = name_value
        self._should_fail_health = should_fail_health

    @property
    def name(self) -> str:
        return self._name

    def health(self) -> dict:
        if self._should_fail_health:
            raise RuntimeError("Health check failed")
        return {"status": "healthy", "connector": self._name}

    def execute(self, task: str, **kwargs) -> dict:
        if task == "fail":
            raise RuntimeError("Task failed")
        return {"status": "success", "task": task, "connector": self._name}


def test_registry_initialization():
    """Test registry initialization."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        assert registry.connectors_dir == Path(tmpdir)
        assert len(registry.connectors) == 0


def test_registry_manual_registration():
    """Test manual connector registration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        connector = TestConnector("test1")
        registry.connectors["test1"] = connector

        assert registry.get_connector("test1") == connector
        assert "test1" in registry.list_connectors()


def test_registry_execute_success():
    """Test successful task execution."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        connector = TestConnector("test")
        registry.connectors["test"] = connector

        result = registry.execute("test", "my_task")
        assert result["status"] == "success"
        assert result["connector"] == "test"
        assert result["task"] == "my_task"
        assert "execution_time_ms" in result
        assert "timestamp" in result


def test_registry_execute_connector_not_found():
    """Test execution with non-existent connector."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        with pytest.raises(ValueError, match="Connector not found"):
            registry.execute("nonexistent", "task")


def test_registry_execute_task_failure():
    """Test task execution failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        connector = TestConnector("test")
        registry.connectors["test"] = connector

        result = registry.execute("test", "fail")
        assert result["status"] == "failure"
        assert result["connector"] == "test"
        assert "error" in result
        assert "execution_time_ms" in result


def test_registry_health_all_healthy():
    """Test health check with all connectors healthy."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        registry.connectors["test1"] = TestConnector("test1")
        registry.connectors["test2"] = TestConnector("test2")

        health = registry.health()
        assert health["status"] == "healthy"
        assert health["summary"]["total"] == 2
        assert health["summary"]["healthy"] == 2
        assert health["summary"]["unhealthy"] == 0
        assert "timestamp" in health
        assert "startup_time" in health


def test_registry_health_one_unhealthy():
    """Test health check with one unhealthy connector."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        registry.connectors["healthy"] = TestConnector("healthy")
        registry.connectors["unhealthy"] = TestConnector("unhealthy", should_fail_health=True)

        health = registry.health()
        assert health["status"] == "degraded"
        assert health["summary"]["total"] == 2
        assert health["summary"]["healthy"] == 1
        assert health["summary"]["unhealthy"] == 1
        assert health["connectors"]["unhealthy"]["status"] == "unhealthy"


def test_registry_health_no_connectors():
    """Test health check with no connectors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        health = registry.health()
        assert health["status"] == "no_connectors"
        assert health["summary"]["total"] == 0


def test_registry_list_connectors():
    """Test listing connectors."""
    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        registry.connectors["github"] = TestConnector("github")
        registry.connectors["gmail"] = TestConnector("gmail")

        names = registry.list_connectors()
        assert "github" in names
        assert "gmail" in names
        assert len(names) == 2
