from runtime.discovery_memory import DiscoveryMemoryStore


def test_discovery_memory_capture_creates_snapshot(tmp_path):
    store = DiscoveryMemoryStore(memory_dir=tmp_path)
    snapshot = store.capture()

    assert snapshot["build"] == "BUILD-015"
    assert snapshot["snapshot_id"].startswith("DSM-")
    assert snapshot["summary"]["modules"] > 0


def test_discovery_memory_latest_returns_snapshot(tmp_path):
    store = DiscoveryMemoryStore(memory_dir=tmp_path)
    store.capture()
    latest = store.latest()

    assert latest["build"] == "BUILD-015"
    assert latest["snapshot_id"].startswith("DSM-")


def test_discovery_memory_diff_has_build_marker(tmp_path):
    store = DiscoveryMemoryStore(memory_dir=tmp_path)
    store.capture()
    store.capture()
    diff = store.diff_latest()

    assert diff["build"] == "BUILD-015"
    assert diff["status"] in {"compared", "insufficient_history"}


def test_discovery_memory_health(tmp_path):
    store = DiscoveryMemoryStore(memory_dir=tmp_path)
    store.capture()
    health = store.health()

    assert health["build"] == "BUILD-015"
    assert health["status"] == "healthy"
    assert health["snapshot_count"] >= 1
