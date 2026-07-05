"""Tests for ConnectorInterface."""

from __future__ import annotations

import pytest

from runtime.connector_interface import ConnectorInterface


class MockConnector(ConnectorInterface):
    """Mock connector for testing."""

    def __init__(self, name_value: str = "mock"):
        self._name = name_value

    @property
    def name(self) -> str:
        return self._name

    def health(self) -> dict:
        return {"status": "healthy"}

    def execute(self, task: str, **kwargs) -> dict:
        return {"status": "success", "task": task}


def test_connector_interface_implementation():
    """Test that mock connector implements interface."""
    connector = MockConnector()
    assert isinstance(connector, ConnectorInterface)
    assert connector.name == "mock"
    assert connector.health()["status"] == "healthy"
    result = connector.execute("test_task")
    assert result["status"] == "success"
    assert result["task"] == "test_task"


def test_connector_cannot_instantiate_directly():
    """Test that ConnectorInterface cannot be instantiated directly."""
    with pytest.raises(TypeError):
        ConnectorInterface()  # type: ignore
