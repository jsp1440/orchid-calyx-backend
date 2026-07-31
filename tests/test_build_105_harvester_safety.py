from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient

from app.main import app
from harvesters.execution import run_harvester
from harvesters.safety import (
    BudgetExceeded,
    CircuitBreaker,
    CircuitOpen,
    CursorGuard,
    CursorRegression,
    RepeatedPageDetector,
    WorkBudget,
    enforce_gbif_offset,
)
from harvesters.safety_store import record_dead_letter, record_safety_snapshot


def test_work_budget_caps_requests_records_and_writes():
    budget = WorkBudget(max_runtime_seconds=60, max_requests=1, max_records=1, max_db_writes=1)
    budget.add_requests(1)
    budget.add_records(1)
    budget.add_writes(1)
    with pytest.raises(BudgetExceeded):
        budget.add_requests(1)


def test_circuit_breaker_opens_after_empty_threshold():
    breaker = CircuitBreaker(empty_threshold=2)
    breaker.record_page(is_empty=True)
    assert not breaker.is_open
    breaker.record_page(is_empty=True)
    assert breaker.is_open
    with pytest.raises(CircuitOpen):
        breaker.check()


def test_circuit_breaker_opens_on_total_failure():
    breaker = CircuitBreaker(empty_threshold=10, failure_rate_threshold=1.0)
    breaker.record_page(is_empty=False, failure_rate=1.0, had_attempts=True)
    assert breaker.is_open


def test_cursor_guard_rejects_reset_or_regression():
    guard = CursorGuard()
    assert guard.validate(200) == 200
    with pytest.raises(CursorRegression):
        guard.validate(0)


def test_repeated_page_detector_rejects_identical_page():
    detector = RepeatedPageDetector()
    records = [{"id": 1}, {"id": 2}]
    assert detector.is_repeat(records) is False
    assert detector.is_repeat(records) is True


def test_gbif_offset_ceiling_is_enforced():
    enforce_gbif_offset(99_000, 1_000)
    with pytest.raises(BudgetExceeded):
        enforce_gbif_offset(99_500, 1_000)


def test_inaturalist_audit_only_does_not_execute(monkeypatch):
    fake = types.ModuleType("harvesters.inat")
    fake.SOURCE_KEY = "inat"
    fake.get_state = lambda _key: {"last_offset": 42}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("harvest_all must not run in audit-only mode")

    fake.harvest_all = forbidden
    monkeypatch.setitem(sys.modules, "harvesters.inat", fake)

    result = run_harvester("inaturalist", audit_only=True)
    assert result["starting_checkpoint"] == "42"
    assert result["ending_checkpoint"] == "42"
    assert result["inserted"] == 0
    assert result["source_response_metadata"]["writes_enabled"] is False


def test_gbif_dry_run_enforces_window_without_execution(monkeypatch):
    fake = types.ModuleType("harvesters.gbif_api")

    class Conn:
        def close(self):
            return None

    fake.get_conn = lambda: Conn()
    fake.load_state = lambda _conn: {"offset": 99_500}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("GBIF run must not execute in dry-run mode")

    fake.run = forbidden
    monkeypatch.setitem(sys.modules, "harvesters.gbif_api", fake)

    with pytest.raises(BudgetExceeded):
        run_harvester("gbif", limit=1_000, dry_run=True)


def test_traitbank_audit_only_reads_without_database_writes(monkeypatch):
    helper = types.ModuleType("harvesters.state_helper")
    helper.get_state = lambda _key: {"last_offset": 1}
    helper.save_state = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("save_state must not run in audit-only mode")
    )

    traitbank = types.ModuleType("harvesters.traitbank")

    class FakeTraitBankHarvester:
        def iter_records(self, limit=None, allow_download=False):
            assert allow_download is False
            yield {"id": 1}
            yield {"id": 2}
            yield {"id": 3}

    traitbank.TraitBankHarvester = FakeTraitBankHarvester
    monkeypatch.setitem(sys.modules, "harvesters.state_helper", helper)
    monkeypatch.setitem(sys.modules, "harvesters.traitbank", traitbank)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")

    result = run_harvester("eol_traitbank", audit_only=True)
    assert result["records_examined"] == 2
    assert result["inserted"] == 0
    assert result["ending_checkpoint"] == "1"
    assert result["source_response_metadata"]["writes_enabled"] is False
    assert result["source_response_metadata"]["rejected"] == 2


def test_preview_endpoint_requires_authentication(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    client = TestClient(app)
    response = client.post("/api/harvesters/inaturalist/preview", json={"mode": "dry_run"})
    assert response.status_code in {401, 403}


def test_preview_endpoint_returns_no_write_contract(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "build105-test-key")
    fake = types.ModuleType("harvesters.inat")
    fake.SOURCE_KEY = "inat"
    fake.get_state = lambda _key: {"last_offset": 42}
    fake.harvest_all = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("preview endpoint must not run the live harvester")
    )
    monkeypatch.setitem(sys.modules, "harvesters.inat", fake)

    client = TestClient(app)
    response = client.post(
        "/api/harvesters/inaturalist/preview",
        headers={"X-API-Key": "build105-test-key"},
        json={"mode": "dry_run", "limit": 25},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["scheduled"] is False
    assert payload["writes_enabled"] is False
    assert payload["result"]["inserted"] == 0


def test_safety_store_is_noop_without_database_url(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert record_safety_snapshot(
        "gbif",
        cursor=100,
        mode="audit_only",
        budget={"records": 10},
        audit={"status": "ok"},
    ) is False
    assert record_dead_letter(
        "eol_traitbank",
        source_record_id="bad-1",
        reason="missing scientific_name",
        payload={"trait_raw": "height"},
    ) is False


def test_run_persists_optional_safety_snapshot(monkeypatch):
    fake = types.ModuleType("harvesters.inat")
    fake.SOURCE_KEY = "inat"
    fake.get_state = lambda _key: {"last_offset": 7}
    fake.harvest_all = lambda limit=1: {"cursor": 8, "batches": 1, "images": 0}
    monkeypatch.setitem(sys.modules, "harvesters.inat", fake)

    calls = []
    monkeypatch.setattr(
        "harvesters.execution.record_safety_snapshot",
        lambda harvester_id, **kwargs: calls.append((harvester_id, kwargs)) or True,
    )
    result = run_harvester("inaturalist", limit=1)
    assert result["ending_checkpoint"] == "8"
    assert calls[0][0] == "inaturalist"
    assert calls[0][1]["mode"] == "live"


def test_traitbank_live_rejects_malformed_record_and_continues(monkeypatch):
    helper = types.ModuleType("harvesters.state_helper")
    helper.get_state = lambda _key: {"last_offset": 0}
    helper.save_state = lambda *_args, **_kwargs: None

    traitbank = types.ModuleType("harvesters.traitbank")

    class FakeTraitBankHarvester:
        def iter_records(self, limit=None, allow_download=False):
            yield {"trait_raw": "height"}

    traitbank.TraitBankHarvester = FakeTraitBankHarvester
    monkeypatch.setitem(sys.modules, "harvesters.state_helper", helper)
    monkeypatch.setitem(sys.modules, "harvesters.traitbank", traitbank)
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")

    class Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args, **_kwargs):
            return None

    class Conn:
        def cursor(self):
            return Cursor()

        def commit(self):
            return None

        def close(self):
            return None

    psycopg2 = types.ModuleType("psycopg2")
    psycopg2.connect = lambda _url: Conn()
    monkeypatch.setitem(sys.modules, "psycopg2", psycopg2)

    dead_letters = []
    monkeypatch.setattr(
        "harvesters.execution.record_dead_letter",
        lambda harvester_id, **kwargs: dead_letters.append((harvester_id, kwargs)) or True,
    )
    monkeypatch.setattr("harvesters.execution.record_safety_snapshot", lambda *_args, **_kwargs: True)

    result = run_harvester("eol_traitbank", limit=1)
    assert result["inserted"] == 0
    assert result["source_response_metadata"]["rejected"] == 1
    assert dead_letters[0][0] == "eol_traitbank"
