"""The Brain is a source of durable records, not a mandatory runtime dependency.

These tests pin the backend to the Brain's unavailable contract
(Orchid-Continuum-Brain ``contracts/federation_records_v1.json``,
``unavailable_contract``): ``hard_fail_permitted: false``; status values
``loaded | unavailable | stale | malformed``; required fields ``repo``, ``ref``,
``status``, ``last_known_at``, ``last_known_sha256``; display form
``Brain: unavailable, last known <last_known_at>``.

Every test is offline. The loader's HTTP fetch is replaced by a callable that
either returns bytes or raises, so no test depends on GitHub, a token, or the
network.
"""

from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime import router_fastapi
from runtime.config_loader import (
    BRAIN_SOURCE_REQUIRED_FIELDS,
    BRAIN_SOURCE_STATUSES,
    BrainConfigError,
    BrainConfigLoader,
    BrainConfigSource,
    LastKnownStore,
)
from runtime.infrastructure import InfrastructureRegistryService

MANIFEST = {"manifest_version": "1.0", "config_files": {}, "source_of_truth": "brain"}
REGISTRY = {"registry_version": "1.2", "services": [{"service_key": "calyx_backend"}]}


class Brain:
    """A Brain that can be switched off between requests."""

    def __init__(self, records: dict[str, dict]) -> None:
        self.records = records
        self.reachable = True
        self.calls = 0

    def fetch(self, url: str, headers) -> bytes:
        self.calls += 1
        if not self.reachable:
            raise OSError("connection refused")
        path = url.split("/contents/", 1)[1].split("?", 1)[0]
        return json.dumps(self.records[path]).encode("utf-8")


@pytest.fixture
def brain() -> Brain:
    return Brain(
        {
            "config/calyx_core_manifest.json": MANIFEST,
            "config/infrastructure_registry.json": REGISTRY,
        }
    )


@pytest.fixture
def loader(brain: Brain) -> BrainConfigLoader:
    ticks = iter(["2026-09-25T10:00:00+00:00", "2026-09-25T10:05:00+00:00"])
    store = LastKnownStore(clock=lambda: next(ticks))
    return BrainConfigLoader(
        BrainConfigSource(repo="example/brain", ref="main", token=None),
        last_known=store,
        fetch=brain.fetch,
    )


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, loader: BrainConfigLoader) -> TestClient:
    monkeypatch.setattr(router_fastapi, "BrainConfigLoader", lambda: loader)
    app = FastAPI()
    app.include_router(router_fastapi.config_router)
    return TestClient(app)


def _assert_contract_shape(source: dict) -> None:
    for name in BRAIN_SOURCE_REQUIRED_FIELDS:
        assert name in source, name
    assert source["status"] in BRAIN_SOURCE_STATUSES


# -- the loader ----------------------------------------------------------------


def test_reachable_brain_loads_and_reports_loaded(loader, brain):
    result = loader.load_with_source("config/calyx_core_manifest.json")
    assert result.available
    assert result.record == MANIFEST
    _assert_contract_shape(result.config_source)
    assert result.config_source["status"] == "loaded"
    assert result.config_source["last_known_at"] == "2026-09-25T10:00:00+00:00"
    expected = hashlib.sha256(json.dumps(MANIFEST).encode("utf-8")).hexdigest()
    assert result.config_source["last_known_sha256"] == expected


def test_unreachable_after_a_good_load_serves_last_known_and_says_so(loader, brain):
    first = loader.load_with_source("config/calyx_core_manifest.json")
    brain.reachable = False
    second = loader.load_with_source("config/calyx_core_manifest.json")
    assert second.available
    assert second.record == MANIFEST
    _assert_contract_shape(second.config_source)
    assert second.config_source["status"] == "unavailable"
    assert second.config_source["last_known_at"] == first.config_source["last_known_at"]
    assert (
        second.config_source["last_known_sha256"]
        == first.config_source["last_known_sha256"]
    )
    assert "connection refused" in second.config_source["error"]


def test_unreachable_and_never_loaded_has_no_record_and_no_last_known(loader, brain):
    brain.reachable = False
    result = loader.load_with_source("config/calyx_core_manifest.json")
    assert not result.available
    assert result.record is None
    _assert_contract_shape(result.config_source)
    assert result.config_source["status"] == "unavailable"
    assert result.config_source["last_known_at"] is None
    assert result.config_source["last_known_sha256"] is None


def test_last_known_is_keyed_by_ref_so_one_ref_is_never_served_as_another(brain):
    store = LastKnownStore()
    main = BrainConfigLoader(
        BrainConfigSource(repo="example/brain", ref="main"),
        last_known=store,
        fetch=brain.fetch,
    )
    pinned = BrainConfigLoader(
        BrainConfigSource(repo="example/brain", ref="old"),
        last_known=store,
        fetch=brain.fetch,
    )
    main.load_with_source("config/calyx_core_manifest.json")
    brain.reachable = False
    assert pinned.load_with_source("config/calyx_core_manifest.json").record is None


def test_a_served_last_known_record_is_a_copy_not_the_cache(loader, brain):
    loader.load_with_source("config/calyx_core_manifest.json")
    brain.reachable = False
    served = loader.load_with_source("config/calyx_core_manifest.json").record
    served["manifest_version"] = "tampered"
    again = loader.load_with_source("config/calyx_core_manifest.json").record
    assert again["manifest_version"] == "1.0"


def test_a_non_object_record_is_malformed_not_remembered(loader, brain):
    brain.records["config/calyx_core_manifest.json"] = ["not", "an", "object"]
    result = loader.load_with_source("config/calyx_core_manifest.json")
    assert result.record is None
    assert "not a JSON object" in result.config_source["error"]


def test_load_json_still_raises_for_callers_that_need_a_fresh_record(loader, brain):
    brain.reachable = False
    with pytest.raises(BrainConfigError):
        loader.load_json("config/calyx_core_manifest.json")
    assert loader.load_json("config/calyx_core_manifest.json", required=False) == {}


# -- the endpoints -------------------------------------------------------------


def test_endpoint_reachable_returns_the_record_with_its_source(client):
    response = client.get("/api/config/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["manifest_version"] == "1.0"
    _assert_contract_shape(body["config_source"])
    assert body["config_source"]["status"] == "loaded"


def test_endpoint_unreachable_after_a_good_load_serves_last_known_not_500(
    client, brain
):
    good = client.get("/api/config/manifest").json()
    brain.reachable = False
    response = client.get("/api/config/manifest")
    assert response.status_code == 200
    body = response.json()
    assert body["manifest_version"] == "1.0"
    source = body["config_source"]
    _assert_contract_shape(source)
    assert source["status"] == "unavailable"
    assert source["last_known_at"] == good["config_source"]["last_known_at"]
    assert source["last_known_sha256"] == good["config_source"]["last_known_sha256"]
    assert "connection refused" in source["error"]


def test_endpoint_unreachable_and_never_loaded_is_503_with_null_last_known(
    client, brain
):
    brain.reachable = False
    response = client.get("/api/config/manifest")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["last_known_at"] is None
    assert body["last_known_sha256"] is None
    assert "connection refused" in body["reason"]
    assert body["repo"] == "example/brain"
    assert body["ref"] == "main"
    assert body["path"] == "config/calyx_core_manifest.json"
    assert "manifest_version" not in body


@pytest.mark.parametrize(
    "route",
    [
        "/api/config/runtime-services",
        "/api/config/governance-policy",
        "/api/config/knowledge-preservation-policy",
    ],
)
def test_every_config_endpoint_degrades_the_same_way(client, brain, route):
    brain.reachable = False
    response = client.get(route)
    assert response.status_code == 503
    assert response.json()["status"] == "unavailable"
    assert response.json()["last_known_at"] is None


# -- the infrastructure registry --------------------------------------------------


def test_registry_reachable_reports_loaded(loader):
    registry = InfrastructureRegistryService(loader).registry()
    assert registry["registry_version"] == "1.2"
    _assert_contract_shape(registry["config_source"])
    assert registry["config_source"]["status"] == "loaded"


def test_registry_unreachable_after_a_good_load_serves_last_known(loader, brain):
    service = InfrastructureRegistryService(loader)
    first = service.registry()
    brain.reachable = False
    second = service.registry()
    assert second["services"] == REGISTRY["services"]
    source = second["config_source"]
    _assert_contract_shape(source)
    assert source["status"] == "unavailable"
    assert source["last_known_at"] == first["config_source"]["last_known_at"]
    assert source["last_known_sha256"] == first["config_source"]["last_known_sha256"]


def test_registry_unreachable_and_never_loaded_is_empty_and_honest(loader, brain):
    brain.reachable = False
    registry = InfrastructureRegistryService(loader).registry()
    assert registry["registry_version"] == "unknown"
    assert registry["services"] == []
    source = registry["config_source"]
    _assert_contract_shape(source)
    assert source["status"] == "unavailable"
    assert source["last_known_at"] is None
    assert "connection refused" in source["error"]


def test_registry_health_carries_the_same_source(loader, brain):
    brain.reachable = False
    health = InfrastructureRegistryService(loader).health()
    assert health["config_source"]["status"] == "unavailable"
    assert health["config_source"]["last_known_at"] is None
    assert health["summary"]["total"] == 0
