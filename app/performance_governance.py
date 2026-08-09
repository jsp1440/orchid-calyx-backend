from __future__ import annotations

import hashlib
import json
import os
import time
from collections import OrderedDict
from dataclasses import asdict, dataclass
from threading import RLock
from typing import Any, Callable, Iterable


@dataclass(frozen=True, slots=True)
class TimingRecord:
    operation: str
    elapsed_ms: float
    slow: bool
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class IndexRecommendation:
    code: str
    table: str
    columns: tuple[str, ...]
    query_contract: str
    rationale: str
    migration_authorized: bool = False


@dataclass(frozen=True, slots=True)
class CapacitySnapshot:
    queue_depth: int
    active_workers: int
    claimed_or_running_jobs: int
    retry_wait_jobs: int
    dead_lettered_jobs: int
    source: str


class TimingRecorder:
    def __init__(self, *, slow_ms: float = 250.0, clock: Callable[[], float] = time.perf_counter) -> None:
        if slow_ms <= 0:
            raise ValueError("PERFORMANCE_SLOW_THRESHOLD_INVALID")
        self.slow_ms = float(slow_ms)
        self.clock = clock
        self._records: list[TimingRecord] = []
        self._lock = RLock()

    def measure(self, operation: str, fn: Callable[[], Any], *, metadata: dict[str, Any] | None = None) -> Any:
        name = str(operation or "").strip()
        if not name:
            raise ValueError("PERFORMANCE_OPERATION_REQUIRED")
        started = self.clock()
        try:
            return fn()
        finally:
            elapsed_ms = max(0.0, (self.clock() - started) * 1000.0)
            record = TimingRecord(name, round(elapsed_ms, 3), elapsed_ms >= self.slow_ms, dict(metadata or {}))
            with self._lock:
                self._records.append(record)

    def records(self) -> tuple[TimingRecord, ...]:
        with self._lock:
            return tuple(self._records)


class TTLCache:
    """Small bounded in-process cache with explicit invalidation and deterministic eviction."""

    def __init__(self, *, max_entries: int = 256, ttl_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic) -> None:
        if max_entries < 1 or ttl_seconds <= 0:
            raise ValueError("CACHE_POLICY_INVALID")
        self.max_entries = int(max_entries)
        self.ttl_seconds = float(ttl_seconds)
        self.clock = clock
        self._values: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> Any | None:
        now = self.clock()
        with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._values.pop(key, None)
                return None
            self._values.move_to_end(key)
            return value

    def put(self, key: str, value: Any) -> None:
        now = self.clock()
        with self._lock:
            self._values[key] = (now + self.ttl_seconds, value)
            self._values.move_to_end(key)
            while len(self._values) > self.max_entries:
                self._values.popitem(last=False)

    def invalidate(self, key: str | None = None) -> int:
        with self._lock:
            if key is None:
                count = len(self._values)
                self._values.clear()
                return count
            return 1 if self._values.pop(key, None) is not None else 0

    def size(self) -> int:
        with self._lock:
            return len(self._values)


def validate_pagination(*, limit: int, offset: int, max_limit: int = 1000, max_offset: int = 1_000_000) -> tuple[int, int]:
    if limit < 1 or limit > max_limit:
        raise ValueError("PAGINATION_LIMIT_INVALID")
    if offset < 0 or offset > max_offset:
        raise ValueError("PAGINATION_OFFSET_INVALID")
    return int(limit), int(offset)


def mission_index_recommendations() -> tuple[IndexRecommendation, ...]:
    """Recommendations tied to executable mission-queue query contracts already used by the repository."""
    return (
        IndexRecommendation(
            code="MISSION_JOB_CLAIM_INDEX",
            table="oc_missions.mission_jobs",
            columns=("state", "available_at", "priority", "job_id"),
            query_contract=(
                "SELECT job_id FROM oc_missions.mission_jobs "
                "WHERE state IN ('available','retry_wait') AND available_at <= NOW() "
                "ORDER BY priority DESC, available_at ASC, job_id ASC LIMIT 1 FOR UPDATE SKIP LOCKED"
            ),
            rationale="Supports deterministic queue claiming without proposing or applying an index migration.",
        ),
        IndexRecommendation(
            code="MISSION_DUE_INDEX",
            table="oc_missions.missions",
            columns=("state", "next_run_at", "priority", "mission_id"),
            query_contract=(
                "SELECT * FROM oc_missions.missions WHERE state='approved' "
                "AND (next_run_at IS NULL OR next_run_at <= NOW()) "
                "ORDER BY priority DESC, mission_id FOR UPDATE SKIP LOCKED"
            ),
            rationale="Supports due-mission scheduling and preserves priority ordering.",
        ),
    )


def deterministic_load_fixture(*, operations: int = 100, payload_bytes: int = 256) -> dict[str, int | bool]:
    """Synthetic capacity fixture only; this is not a production benchmark."""
    if operations < 1 or operations > 100_000 or payload_bytes < 0 or payload_bytes > 1_000_000:
        raise ValueError("LOAD_FIXTURE_BOUNDS_INVALID")
    total_bytes = operations * payload_bytes
    return {
        "operations": operations,
        "payload_bytes": payload_bytes,
        "total_payload_bytes": total_bytes,
        "production_benchmark": False,
        "production_load_test_authorized": False,
    }


class PerformanceReadiness:
    schema_version = "calyx-performance-observability/v1"

    def __init__(self, capacity_provider: Callable[[], CapacitySnapshot] | None = None) -> None:
        self.capacity_provider = capacity_provider

    @staticmethod
    def _digest(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def snapshot(self) -> dict[str, Any]:
        findings: list[dict[str, str]] = []
        capacity = None
        if self.capacity_provider is None:
            findings.append({
                "code": "CAPACITY_PROVIDER_NOT_CONFIGURED",
                "severity": "info",
                "remediation": "Bind a read-only queue/worker metrics provider before relying on live capacity telemetry.",
            })
        else:
            capacity = asdict(self.capacity_provider())
            if capacity["queue_depth"] > 0 and capacity["active_workers"] == 0:
                findings.append({
                    "code": "QUEUE_WITHOUT_ACTIVE_WORKERS",
                    "severity": "high",
                    "remediation": "Restore an authorized worker before queue depth grows; do not increase concurrency blindly.",
                })
            if capacity["retry_wait_jobs"] > capacity["queue_depth"]:
                findings.append({
                    "code": "RETRY_PRESSURE_ELEVATED",
                    "severity": "medium",
                    "remediation": "Inspect repeated job errors and retry policy before increasing worker capacity.",
                })

        cache_max_entries = int(os.getenv("CALYX_CACHE_MAX_ENTRIES", "256"))
        cache_ttl_seconds = int(os.getenv("CALYX_CACHE_TTL_SECONDS", "60"))
        slow_ms = float(os.getenv("CALYX_SLOW_PATH_MS", "250"))
        if cache_max_entries > 10_000:
            findings.append({
                "code": "CACHE_MEMORY_RISK",
                "severity": "medium",
                "remediation": "Reduce CALYX_CACHE_MAX_ENTRIES or validate memory use in a staging environment.",
            })
        if slow_ms < 1:
            findings.append({
                "code": "SLOW_PATH_THRESHOLD_INVALID",
                "severity": "high",
                "remediation": "Set CALYX_SLOW_PATH_MS to a positive operational threshold.",
            })

        base = {
            "schema_version": self.schema_version,
            "capacity": capacity,
            "cache_policy": {
                "max_entries": cache_max_entries,
                "ttl_seconds": cache_ttl_seconds,
                "explicit_invalidation": True,
            },
            "slow_path_threshold_ms": slow_ms,
            "pagination": {"max_limit": 1000, "max_offset": 1_000_000},
            "index_recommendations": [asdict(item) for item in mission_index_recommendations()],
            "findings": findings,
            "production_load_test_authorized": False,
            "index_migration_authorized": False,
            "deployment_authorized": False,
            "merge_authorized": False,
            "fabricated_benchmarks": False,
        }
        return {**base, "digest": self._digest(base)}
