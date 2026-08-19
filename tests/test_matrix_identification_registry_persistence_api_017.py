import pytest
from fastapi import HTTPException

import app.routers.matrix_identification_registry as registry_router


def test_registry_list_translates_persistence_failure_to_503(monkeypatch):
    monkeypatch.setattr(
        registry_router,
        "list_registry_versions",
        lambda: (_ for _ in ()).throw(RuntimeError("MATRIX_REGISTRY_SCHEMA_NOT_READY")),
    )

    with pytest.raises(HTTPException) as raised:
        registry_router.list_versions({"auth_type": "session", "actor": "owner"})

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "MATRIX_REGISTRY_PERSISTENCE_UNAVAILABLE"
    assert "SCHEMA_NOT_READY" in raised.value.detail["message"]


def test_registry_get_translates_persistence_failure_to_503(monkeypatch):
    monkeypatch.setattr(
        registry_router,
        "get_registry_version",
        lambda registry_id, version: (_ for _ in ()).throw(RuntimeError("MATRIX_REGISTRY_DATABASE_URL_REQUIRED")),
    )

    with pytest.raises(HTTPException) as raised:
        registry_router.get_version(
            "demo",
            "1",
            {"auth_type": "session", "actor": "owner"},
        )

    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "MATRIX_REGISTRY_PERSISTENCE_UNAVAILABLE"
    assert "DATABASE_URL_REQUIRED" in raised.value.detail["message"]
