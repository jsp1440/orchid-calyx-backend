"""HARVESTER-PRODUCTIVITY-001 telemetry semantics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.readiness import harvester_productivity as hp

NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


class FakeCursor:
    """Replays a per-job run history against the module's two queries."""

    def __init__(self, runs_by_job: dict[str, list[dict]]):
        self.runs_by_job = runs_by_job
        self._result: list = []

    def execute(self, sql: str, params=()):
        job = params[0]
        runs = self.runs_by_job.get(job, [])
        if "lower(status) IN" in sql:
            ok = [r for r in runs if str(r.get("status", "")).lower() in hp.SUCCESS_STATUSES]
            self._result = [(ok[0]["finished_at"],)] if ok else []
            return
        since = params[1]
        self._result = [
            (r.get("status"), r.get("started_at"), r.get("finished_at"),
             r.get("updated_at"), r.get("error_text"), r.get("details"))
            for r in runs
            if r.get("finished_at") and r["finished_at"] >= since
        ]

    def fetchall(self):
        return self._result

    def fetchone(self):
        return self._result[0] if self._result else None


def run(status="completed", hours_ago=1, **details):
    return {
        "status": status,
        "started_at": NOW - timedelta(hours=hours_ago),
        "finished_at": NOW - timedelta(hours=hours_ago),
        "updated_at": NOW - timedelta(hours=hours_ago),
        "error_text": None,
        "details": details or {},
    }


def present(_cur, _table):
    return True


def absent(_cur, _table):
    return False


def by_id(report, harvester_id):
    return next(h for h in report["harvesters"] if h["harvester_id"] == harvester_id)


# --- unavailable is never zero -------------------------------------------------

def test_missing_jobs_table_reports_unavailable_not_a_table_of_zeros():
    report = hp.harvester_productivity(FakeCursor({}), absent, now=NOW)
    assert report["telemetry_state"] == hp.UNAVAILABLE
    for harvester in report["harvesters"]:
        assert harvester["telemetry_state"] == hp.UNAVAILABLE
        assert harvester["windows"] == {}


def test_an_uninstrumented_run_reports_unavailable_and_carries_no_number():
    runs = {"audit_traitbank_trait_coverage": [run()]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    traitbank = by_id(report, "eol_traitbank")
    assert traitbank["telemetry_state"] == "uninstrumented"
    fetched = traitbank["windows"]["24h"]["records_fetched"]
    assert fetched["state"] == hp.UNAVAILABLE
    # The value must be None, so a caller cannot format it as 0 by accident.
    assert fetched["value"] is None


def test_a_measured_zero_is_reported_as_measured_zero():
    runs = {"audit_traitbank_trait_coverage": [run(records_fetched=4200, records_inserted=0)]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    window = by_id(report, "eol_traitbank")["windows"]["24h"]
    assert window["records_new"] == {"state": hp.MEASURED, "value": 0}
    assert window["records_fetched"] == {"state": hp.MEASURED, "value": 4200}


def test_unavailable_and_measured_zero_are_distinguishable():
    silent = hp.harvester_productivity(FakeCursor({"audit_traitbank_trait_coverage": [run()]}), present, now=NOW)
    measured = hp.harvester_productivity(
        FakeCursor({"audit_traitbank_trait_coverage": [run(records_inserted=0)]}), present, now=NOW)
    a = by_id(silent, "eol_traitbank")["windows"]["24h"]["records_new"]
    b = by_id(measured, "eol_traitbank")["windows"]["24h"]["records_new"]
    assert a != b
    assert a["state"] == hp.UNAVAILABLE and b["state"] == hp.MEASURED


# --- activity is not yield -----------------------------------------------------

def test_a_busy_run_that_retained_nothing_is_not_productive():
    runs = {"audit_literature_extraction_coverage": [
        run(records_fetched=500_000, records_inserted=0),
        run(hours_ago=5, records_fetched=500_000, records_inserted=0),
    ]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    lit = by_id(report, "literature")
    window = lit["windows"]["24h"]
    assert window["records_fetched"]["value"] == 1_000_000
    assert window["records_new"]["value"] == 0
    assert window["marginal_yield_per_1000_fetched"] == 0.0
    assert "high_throughput_no_new_records" in lit["review_flags"]
    assert "repeated_runs_zero_new_records" in lit["review_flags"]


def test_a_productive_run_is_not_flagged_for_review():
    runs = {"audit_literature_extraction_coverage": [run(records_fetched=10_000, records_inserted=5_000)]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    lit = by_id(report, "literature")
    assert lit["review_flags"] == []
    assert lit["windows"]["24h"]["marginal_yield_per_1000_fetched"] == 500.0


def test_no_observation_does_not_become_a_yield_of_zero():
    runs = {"audit_literature_extraction_coverage": [run(records_fetched=0, records_inserted=0)]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    # 0 fetched and 0 new is not a rate of zero; it is nothing to divide.
    assert by_id(report, "literature")["windows"]["24h"]["marginal_yield_per_1000_fetched"] is None


# --- failure -------------------------------------------------------------------

def test_failing_harvester_reports_failure_rate_and_is_flagged():
    runs = {"audit_missing_mycorrhizal_data": [
        run(status="failed"), run(status="failed", hours_ago=3), run(status="completed", hours_ago=6),
    ]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    myc = by_id(report, "mycorrhizal_data")
    window = myc["windows"]["24h"]
    assert window["runs_attempted"] == 3
    assert window["runs_failed"] == 2
    assert window["runs_succeeded"] == 1
    assert window["failure_rate"] == pytest.approx(0.6667, abs=1e-4)
    assert "high_failure_rate" in myc["review_flags"]


def test_a_window_with_no_runs_has_no_failure_rate():
    report = hp.harvester_productivity(FakeCursor({}), present, now=NOW)
    window = by_id(report, "literature")["windows"]["24h"]
    assert window["runs_attempted"] == 0
    assert window["failure_rate"] is None


# --- staleness -----------------------------------------------------------------

def test_a_source_stale_beyond_thirty_days_is_flagged():
    old = run(hours_ago=24 * 45)
    report = hp.harvester_productivity(FakeCursor({"audit_missing_mycorrhizal_data": [old]}), present, now=NOW)
    assert "stale_beyond_30d" in by_id(report, "mycorrhizal_data")["review_flags"]


def test_windows_are_bounded_so_an_old_run_is_absent_from_24h():
    runs = {"audit_missing_mycorrhizal_data": [run(hours_ago=24 * 10, records_inserted=7)]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    windows = by_id(report, "mycorrhizal_data")["windows"]
    assert windows["24h"]["runs_attempted"] == 0
    assert windows["30d"]["runs_attempted"] == 1
    assert windows["30d"]["records_new"]["value"] == 7


# --- malformed payloads fail safely -------------------------------------------

@pytest.mark.parametrize("payload", [None, [], "not-a-mapping", 42, {"records_inserted": "many"},
                                     {"records_inserted": -5}, {"records_inserted": True}])
def test_a_malformed_details_payload_reports_unavailable_rather_than_raising(payload):
    assert hp.read_counter(payload, "records_new") is None


def test_one_malformed_run_does_not_discard_a_sibling_measurement():
    runs = {"audit_literature_extraction_coverage": [
        run(records_inserted=12), {**run(hours_ago=2), "details": "corrupt"},
    ]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    assert by_id(report, "literature")["windows"]["24h"]["records_new"]["value"] == 12


def test_an_unrecognised_counter_key_is_not_guessed_at():
    runs = {"audit_literature_extraction_coverage": [run(mystery_total=99)]}
    report = hp.harvester_productivity(FakeCursor(runs), present, now=NOW)
    assert by_id(report, "literature")["windows"]["24h"]["records_new"]["state"] == hp.UNAVAILABLE


# --- binding honesty -----------------------------------------------------------

def test_shared_job_bindings_are_declared_not_presented_as_independent():
    report = hp.harvester_productivity(FakeCursor({}), present, now=NOW)
    globi = by_id(report, "globi")
    pollinators = by_id(report, "pollinator_datasets")
    assert globi["job_name"] == pollinators["job_name"]
    assert globi["binding_confidence"] == "shared"
    assert pollinators["binding_confidence"] == "shared"
    assert any("shared job names" in w for w in report["warnings"])


def test_approximate_bindings_say_the_job_does_not_measure_the_harvester():
    report = hp.harvester_productivity(FakeCursor({}), present, now=NOW)
    gbif = by_id(report, "gbif")
    assert gbif["binding_confidence"] == "approximate"
    assert "does not record GBIF occurrence ingestion" in gbif["binding_note"]


def test_every_registered_harvester_is_reported():
    report = hp.harvester_productivity(FakeCursor({}), present, now=NOW)
    assert len(report["harvesters"]) == len(hp.BINDINGS) == 11


# --- endpoint ------------------------------------------------------------------

def test_endpoint_is_additive_and_fails_closed_without_a_database(monkeypatch):
    from app.routers import mission_control as mc

    monkeypatch.setattr(mc, "with_connection", lambda _cb: {
        "database_connected": False, "blockers": ["Database telemetry unavailable: no route to host"],
    })
    payload = mc.mission_control_harvester_productivity()
    assert payload["telemetry_state"] == "unavailable"
    assert payload["harvesters"] == []
    assert payload["blockers"]
    # No counter anywhere, so nothing can be mistaken for a measured zero.
    assert "0" not in str(payload.get("harvesters"))


def test_endpoint_returns_the_productivity_schema_when_the_database_answers(monkeypatch):
    from app.routers import mission_control as mc

    monkeypatch.setattr(mc, "table_exists", lambda _cur, _table: True)
    monkeypatch.setattr(mc, "with_connection",
                        lambda cb: cb(FakeCursor({"audit_literature_extraction_coverage": [run(records_inserted=3)]})))
    payload = mc.mission_control_harvester_productivity()
    assert payload["schema_version"] == "harvester-productivity-001"
    assert payload["telemetry_state"] == "available"
    assert by_id(payload, "literature")["windows"]["24h"]["records_new"]["value"] == 3


def test_the_existing_harvesters_endpoint_still_reports_its_original_shape(monkeypatch):
    from app.routers import mission_control as mc

    monkeypatch.setattr(mc, "harvester_rows", lambda: [{"id": "literature"}])
    payload = mc.mission_control_harvesters()
    assert set(payload) == {"build", "harvesters", "generated_at"}
