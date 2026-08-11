from app.vision_lexicon import activation


def test_schema_activation_is_reported_before_durable_writes(monkeypatch):
    monkeypatch.delenv("CALYX_VISION_DURABLE_ENABLED", raising=False)
    monkeypatch.setattr(activation, "schema_ready", lambda: True)

    status = activation.capability_status()

    assert status["migration_activated"] is True
    assert status["schema_ready"] is True
    assert status["durable_persistence_enabled"] is False
    assert status["persistence_mode"] == "memory"
    assert status["live_inference_enabled"] is False


def test_durable_request_reports_postgres_only_when_explicitly_enabled(monkeypatch):
    monkeypatch.setenv("CALYX_VISION_DURABLE_ENABLED", "true")
    monkeypatch.setattr(activation, "schema_ready", lambda: True)

    status = activation.capability_status()

    assert status["migration_activated"] is True
    assert status["durable_persistence_enabled"] is True
    assert status["persistence_mode"] == "postgres"
    assert status["live_inference_enabled"] is False


def test_durable_request_fails_closed_when_schema_is_not_ready(monkeypatch):
    monkeypatch.setenv("CALYX_VISION_DURABLE_ENABLED", "true")
    monkeypatch.setattr(activation, "schema_ready", lambda: False)

    status = activation.capability_status()

    assert status["migration_activated"] is False
    assert status["durable_persistence_enabled"] is True
    assert status["provider_status"] == "PERSISTENCE_NOT_READY"
    assert status["live_inference_enabled"] is False
