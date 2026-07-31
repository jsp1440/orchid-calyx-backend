"""BUILD-093 offline validation for the harvester migration.

Proves the governed control plane dispatches integrated harvester ids to the
mature implementations, records real checkpoint/rows/status telemetry,
preserves the queued-stub behavior for the API path and unintegrated ids, and
that no live GBIF/iNat/TraitBank HTTP calls or production DB writes occur.
"""

import psycopg2
import pytest

import harvesters.execution as execution
from harvesters import base, state_helper, traitbank
from runtime.harvester_control import HarvesterControlPlane


# --------------------------------------------------------------------------
# Import-closure: the three harvesters + shared helpers import cleanly and the
# package does not pull in the wider recovered harvester set.
# --------------------------------------------------------------------------
def test_import_closure_is_minimal():
    import harvesters.inat  # noqa: F401  (state_helper + requests only)
    assert issubclass(traitbank.TraitBankHarvester, base.BaseHarvester)
    assert execution.INTEGRATED_HARVESTERS == {"inaturalist", "gbif", "eol_traitbank"}


# --------------------------------------------------------------------------
# Control plane dispatch: execute=True routes each integrated id to the adapter
# and records real telemetry on the HarvesterRun + harvester.
# --------------------------------------------------------------------------
@pytest.mark.parametrize("harvester_id", ["inaturalist", "gbif", "eol_traitbank"])
def test_run_once_execute_dispatches_and_records_telemetry(monkeypatch, harvester_id):
    calls = {}

    def fake_run_harvester(hid, limit=None, family_key=None):
        calls["id"] = hid
        return {
            "starting_checkpoint": "100",
            "ending_checkpoint": "250",
            "records_examined": 250,
            "inserted": 42,
            "source_response_metadata": {"harvester": "mock"},
        }

    monkeypatch.setattr(execution, "run_harvester", fake_run_harvester)

    plane = HarvesterControlPlane()
    result = plane.run_once(harvester_id, "calyx_worker", execute=True)

    assert calls["id"] == harvester_id
    assert result["status"] == "success"
    run = result["run"]
    assert run["status"] == "success"
    assert run["starting_checkpoint"] == "100"
    assert run["ending_checkpoint"] == "250"
    assert run["inserted"] == 42
    assert run["execution_log_reference"] == "harvesters.execution.run_harvester"
    # harvester telemetry updated + history preserved
    harvester = result["harvester"]
    assert harvester["checkpoint"] == "250"
    assert plane.get_runs(harvester_id)[0]["run_id"] == run["run_id"]


def test_run_once_without_execute_stays_queued_stub():
    """API run-once path (execute defaults False) must not run real work."""
    plane = HarvesterControlPlane()
    result = plane.run_once("gbif", "owner")
    assert result["status"] == "queued"
    assert result["run"]["execution_log_reference"] == "oc_admin.ocp_execution_jobs pending integration"


def test_run_once_execute_unintegrated_id_stays_queued(monkeypatch):
    """Unintegrated ids keep the queued-stub even when execute=True."""
    def boom(*a, **k):  # must never be called for unintegrated ids
        raise AssertionError("adapter should not run for unintegrated id")

    monkeypatch.setattr(execution, "run_harvester", boom)
    plane = HarvesterControlPlane()
    result = plane.run_once("world_plants_hassler", "calyx_worker", execute=True)
    assert result["status"] == "queued"


def test_run_once_execute_failure_is_recorded(monkeypatch):
    def failing(hid, limit=None, family_key=None):
        raise RuntimeError("simulated harvest failure")

    monkeypatch.setattr(execution, "run_harvester", failing)
    plane = HarvesterControlPlane()
    result = plane.run_once("inaturalist", "calyx_worker", execute=True)
    assert result["status"] == "failed"
    assert "simulated harvest failure" in result["run"]["errors"][0]
    # history is preserved even on failure
    assert len(plane.get_runs("inaturalist")) == 1


# --------------------------------------------------------------------------
# Adapter dispatch: each branch calls the mature harvester and returns
# normalized telemetry -- with all I/O mocked (no live HTTP, no real DB).
# --------------------------------------------------------------------------
def test_adapter_inaturalist(monkeypatch):
    import harvesters.inat as inat
    monkeypatch.setattr(inat, "get_state", lambda k: {"last_offset": 500})
    monkeypatch.setattr(inat, "harvest_all",
                        lambda limit=1: {"images": 7, "batches": 1, "cursor": 610})
    tel = execution.run_harvester("inaturalist", limit=1)
    assert tel["starting_checkpoint"] == "500"
    assert tel["ending_checkpoint"] == "610"
    assert tel["inserted"] == 7


def test_adapter_gbif(monkeypatch):
    import harvesters.gbif_api as gbif

    class FakeConn:
        def close(self):
            pass

    monkeypatch.setattr(gbif, "get_conn", lambda: FakeConn())
    monkeypatch.setattr(gbif, "load_state", lambda conn: {"offset": 1000, "total": 5})
    monkeypatch.setattr(gbif, "run",
                        lambda **k: {"occurrences_added": 3, "images_added": 4, "next_offset": 1500})
    tel = execution.run_harvester("gbif")
    assert tel["starting_checkpoint"] == "1000"
    assert tel["ending_checkpoint"] == "1500"
    assert tel["inserted"] == 7


# --- TraitBank persistence glue (mirrors recovered offline pipeline test) ---
class _Cur:
    rowcount = 1

    def __init__(self, sink):
        self.sink = sink

    def execute(self, sql, params=None):
        self.sink.append((" ".join(sql.split()), params))

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Conn:
    def __init__(self, sink):
        self.sink = sink

    def cursor(self):
        return _Cur(self.sink)

    def commit(self):
        pass

    def close(self):
        pass


def test_adapter_traitbank_persists_checkpoints_and_bootstraps(monkeypatch):
    recs = [
        {"scientific_name": "Cattleya labiata", "trait_raw": "leaf_color",
         "value_raw": "green", "reference_raw": "eol"},
        {"scientific_name": "Dendrobium nobile", "trait_raw": "growth_habit",
         "value_raw": "epiphyte", "reference_raw": "eol"},
    ]
    # allow_download stays False -> _download_to_local_cache never called
    monkeypatch.setattr(
        traitbank.TraitBankHarvester, "iter_records",
        lambda self, limit=None, allow_download=True: iter(recs))

    saved = []
    monkeypatch.setattr(state_helper, "get_state", lambda k: {"last_offset": 0})
    monkeypatch.setattr(
        state_helper, "save_state",
        lambda k, last_offset=None, increment_total=0: saved.append((last_offset, increment_total)))

    sink = []
    monkeypatch.setattr(psycopg2, "connect", lambda url: _Conn(sink))

    tel = execution.run_harvester("eol_traitbank", limit=None)

    stmts = [sql for sql, _ in sink]
    assert any("CREATE TABLE IF NOT EXISTS trait_observations" in s for s in stmts)
    inserts = [p for sql, p in sink if "INSERT INTO trait_observations" in sql]
    assert len(inserts) == 2  # one persist per record
    assert saved  # checkpoint written
    assert tel["records_examined"] == 2
    assert tel["inserted"] == 2
    assert tel["ending_checkpoint"] == "2"


def test_adapter_traitbank_resume_skips_processed(monkeypatch):
    recs = [
        {"scientific_name": "A", "trait_raw": "t", "value_raw": "v", "reference_raw": "r"},
        {"scientific_name": "B", "trait_raw": "t", "value_raw": "v", "reference_raw": "r"},
        {"scientific_name": "C", "trait_raw": "t", "value_raw": "v", "reference_raw": "r"},
    ]
    monkeypatch.setattr(
        traitbank.TraitBankHarvester, "iter_records",
        lambda self, limit=None, allow_download=True: iter(recs))
    monkeypatch.setattr(state_helper, "get_state", lambda k: {"last_offset": 2})
    monkeypatch.setattr(state_helper, "save_state",
                        lambda k, last_offset=None, increment_total=0: None)
    sink = []
    monkeypatch.setattr(psycopg2, "connect", lambda url: _Conn(sink))

    tel = execution.run_harvester("eol_traitbank")
    inserts = [p for sql, p in sink if "INSERT INTO trait_observations" in sql]
    assert len(inserts) == 1  # first two skipped on resume
    assert tel["records_examined"] == 1


def test_no_live_http_during_dispatch(monkeypatch):
    """A hard guard: real requests.* must never fire during mocked dispatch."""
    import requests

    def forbidden(*a, **k):
        raise AssertionError("live HTTP call attempted during offline test")

    monkeypatch.setattr(requests, "get", forbidden)
    monkeypatch.setattr(requests.Session, "get", forbidden, raising=False)

    import harvesters.inat as inat
    monkeypatch.setattr(inat, "get_state", lambda k: {"last_offset": 0})
    monkeypatch.setattr(inat, "harvest_all", lambda limit=1: {"images": 0, "batches": 0, "cursor": 0})
    execution.run_harvester("inaturalist")  # must not raise
