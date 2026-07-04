from runtime.autonomous_discovery import AutonomousDiscoveryEngine


def test_autonomous_discovery_finds_modules(tmp_path):
    engine = AutonomousDiscoveryEngine(cache_path=tmp_path / "discovery.json")
    payload = engine.discover(write_cache=True)

    assert payload["build"] == "BUILD-014"
    assert payload["summary"]["modules"] > 0
    assert payload["summary"]["capabilities"] > 0


def test_autonomous_discovery_capabilities_report(tmp_path):
    engine = AutonomousDiscoveryEngine(cache_path=tmp_path / "discovery.json")
    engine.discover(write_cache=True)
    capabilities = engine.capabilities()

    assert capabilities["build"] == "BUILD-014"
    assert capabilities["count"] > 0


def test_autonomous_discovery_schedule(tmp_path):
    engine = AutonomousDiscoveryEngine(cache_path=tmp_path / "discovery.json")
    engine.discover(write_cache=True)
    schedule = engine.schedule()

    assert schedule["build"] == "BUILD-014"
    assert schedule["status"] == "scheduled"
