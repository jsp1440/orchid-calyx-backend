"""Tests for connector API routes."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI

from runtime.connector_interface import ConnectorInterface
from runtime.connector_routes import router
from runtime.connector_registry import ConnectorRegistry


class TestConnector(ConnectorInterface):
    """Test connector for routes."""

    def __init__(self, name_value: str = "test"):
        self._name = name_value

    @property
    def name(self) -> str:
        return self._name

    def health(self) -> dict:
        return {"status": "healthy", "connector": self._name}

    def execute(self, task: str, **kwargs) -> dict:
        if task == "error":
            raise RuntimeError("Test error")
        return {"status": "success", "task": task}


@pytest.fixture
def client():
    """Create test client with sample connectors."""
    app = FastAPI()
    app.include_router(router)

    # Override registry to use test connectors
    from runtime import connector_routes

    with tempfile.TemporaryDirectory() as tmpdir:
        registry = ConnectorRegistry(Path(tmpdir))
        registry.connectors["github"] = TestConnector("github")
        registry.connectors["gmail"] = TestConnector("gmail")
        connector_routes._registry = registry

        yield TestClient(app)


def test_list_connectors(client):
    """Test GET /api/connectors."""
    response = client.get("/api/connectors")
    assert response.status_code == 200
    data = response.json()
    assert "connectors" in data
    assert len(data["connectors"]) == 2
    assert data["total"] == 2
    assert data["healthy"] == 2

    # Check connector names
    names = [c["name"] for c in data["connectors"]]
    assert "github" in names
    assert "gmail" in names


def test_connector_health(client):
    """Test GET /api/connectors/health."""
    response = client.get("/api/connectors/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "connectors" in data
    assert data["status"] == "healthy"
    assert len(data["connectors"]) == 2


def test_execute_task_success(client):
    """Test POST /api/connectors/execute with successful task."""
    response = client.post(
        "/api/connectors/execute",
        params={"connector": "github", "task": "status"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["connector"] == "github"
    assert data["task"] == "status"
    assert "execution_time_ms" in data


def test_execute_task_connector_not_found(client):
    """Test POST /api/connectors/execute with non-existent connector."""
    response = client.post(
        "/api/connectors/execute",
        params={"connector": "nonexistent", "task": "status"},
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_execute_task_missing_connector_param(client):
    """Test POST /api/connectors/execute without connector parameter."""
    response = client.post(
        "/api/connectors/execute",
        params={"task": "status"},
    )
    assert response.status_code == 422  # Missing required parameter


def test_execute_task_missing_task_param(client):
    """Test POST /api/connectors/execute without task parameter."""
    response = client.post(
        "/api/connectors/execute",
        params={"connector": "github"},
    )
    assert response.status_code == 422  # Missing required parameter


def test_execute_task_failure(client):
    """Test POST /api/connectors/execute with failing task."""
    response = client.post(
        "/api/connectors/execute",
        params={"connector": "github", "task": "error"},
    )
    assert response.status_code == 400
    assert "Test error" in response.json()["detail"]
