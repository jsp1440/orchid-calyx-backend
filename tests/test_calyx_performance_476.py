from __future__ import annotations

from app.performance_governance import (
    CapacitySnapshot,
    PerformanceReadiness,
    TTLCache,
    TimingRecorder,
    deterministic_load_fixture,
    mission_index_recommendations,
    validate_pagination,
)


def test_timing_recorder_marks_slow_path_with_deterministic_clock():
    ticks = iter([1.0, 1.300])
    recorder = TimingRecorder(slow_ms=250, clock=lambda: next(ticks))
    assert recorder.measure("query.species", lambda: 42) == 42
    record = recorder.records()[0]
    assert record.elapsed_ms == 300.0
    assert record.slow is True


def test_cache_ttl_eviction_and_explicit_invalidation():
    now = [0.0]
    cache = TTLCache(max_entries=2, ttl_seconds=10, clock=lambda: now[0])
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None
    assert cache.get("b") == 2
    assert cache.invalidate("b") == 1
    assert cache.get("b") is None
    now[0] = 11.0
    assert cache.get("c") is None


def test_pagination_safeguards():
    assert validate_pagination(limit=100, offset=0) == (100, 0)
    for kwargs in ({"limit": 0, "offset": 0}, {"limit": 1001, "offset": 0}, {"limit": 1, "offset": -1}):
        try:
            validate_pagination(**kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid pagination accepted")


def test_index_recommendations_are_query_grounded_and_never_migrations():
    recommendations = mission_index_recommendations()
    assert recommendations
    assert all("SELECT" in item.query_contract for item in recommendations)
    assert all(item.migration_authorized is False for item in recommendations)
    assert any(item.table == "oc_missions.mission_jobs" for item in recommendations)


def test_capacity_findings_are_deterministic():
    snapshot = CapacitySnapshot(
        queue_depth=3,
        active_workers=0,
        claimed_or_running_jobs=0,
        retry_wait_jobs=4,
        dead_lettered_jobs=1,
        source="fixture",
    )
    payload = PerformanceReadiness(lambda: snapshot).snapshot()
    codes = {item["code"] for item in payload["findings"]}
    assert "QUEUE_WITHOUT_ACTIVE_WORKERS" in codes
    assert "RETRY_PRESSURE_ELEVATED" in codes
    assert payload["production_load_test_authorized"] is False
    assert payload["index_migration_authorized"] is False
    assert payload["fabricated_benchmarks"] is False


def test_load_fixture_is_bounded_and_not_a_benchmark():
    fixture = deterministic_load_fixture(operations=200, payload_bytes=128)
    assert fixture["operations"] == 200
    assert fixture["total_payload_bytes"] == 25_600
    assert fixture["production_benchmark"] is False
    assert fixture["production_load_test_authorized"] is False
