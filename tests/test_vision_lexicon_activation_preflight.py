from app.vision_lexicon import activation, preflight


class _Cursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Connection:
    def __init__(self):
        self._cursor = _Cursor()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


def test_preflight_distinguishes_persistence_readiness_from_live_inference():
    result = preflight._build_preflight(
        database_url_configured=True,
        connectivity=True,
        schema_problem=None,
        durable_requested=False,
        provider_status="PROVIDER_NOT_CONFIGURED",
        live_inference_enabled=False,
    )

    assert result["read_only"] is True
    assert result["mutations_performed"] is False
    assert result["persistence_activation_ready"] is True
    assert result["persistence_active"] is False
    assert result["provider_ready"] is False
    assert result["live_inference_activation_ready"] is False
    assert "VISION_DURABLE_PERSISTENCE_DISABLED" in result["blockers"]
    assert "VISION_PROVIDER_NOT_CONFIGURED" in result["blockers"]
    assert "VISION_LIVE_INFERENCE_DISABLED" in result["blockers"]


def test_preflight_never_reports_clear_when_durable_persistence_is_disabled():
    result = preflight._build_preflight(
        database_url_configured=True,
        connectivity=True,
        schema_problem=None,
        durable_requested=False,
        provider_status="READY",
        live_inference_enabled=True,
    )

    assert result["persistence_activation_ready"] is True
    assert result["persistence_active"] is False
    assert result["live_inference_activation_ready"] is False
    assert result["blockers"] == ["VISION_DURABLE_PERSISTENCE_DISABLED"]


def test_preflight_reports_missing_database_without_claiming_schema_failure():
    result = preflight._build_preflight(
        database_url_configured=False,
        connectivity=False,
        schema_problem=None,
        durable_requested=False,
        provider_status="PROVIDER_NOT_CONFIGURED",
        live_inference_enabled=False,
        inspection_error="VISION_POSTGRES_REQUIRED",
    )

    assert result["schema_ready"] is False
    assert result["schema_problem"] is None
    assert result["blockers"][0] == "VISION_DATABASE_URL_NOT_CONFIGURED"
    assert result["inspection_error"] == "VISION_POSTGRES_REQUIRED"


def test_preflight_preserves_specific_schema_governance_blocker():
    result = preflight._build_preflight(
        database_url_configured=True,
        connectivity=True,
        schema_problem="VISION_SCHEMA_GOVERNANCE_CONSTRAINT_MISSING",
        durable_requested=True,
        provider_status="PERSISTENCE_NOT_READY",
        live_inference_enabled=False,
    )

    assert result["schema_ready"] is False
    assert result["persistence_activation_ready"] is False
    assert result["persistence_active"] is False
    assert "VISION_SCHEMA_GOVERNANCE_CONSTRAINT_MISSING" in result["blockers"]
    assert "VISION_PROVIDER_PERSISTENCE_NOT_READY" in result["blockers"]


def test_schema_inspection_failure_preserves_successful_connectivity():
    result = preflight._build_preflight(
        database_url_configured=True,
        connectivity=True,
        schema_problem=None,
        durable_requested=True,
        provider_status="PERSISTENCE_NOT_READY",
        live_inference_enabled=False,
        inspection_error="permission denied",
    )

    assert result["connectivity"] is True
    assert result["schema_ready"] is False
    assert "VISION_SCHEMA_INSPECTION_FAILED" in result["blockers"]
    assert "VISION_DATABASE_UNREACHABLE" not in result["blockers"]


def test_live_inference_ready_requires_active_persistence_provider_and_enabled_inference():
    result = preflight._build_preflight(
        database_url_configured=True,
        connectivity=True,
        schema_problem=None,
        durable_requested=True,
        provider_status="READY",
        live_inference_enabled=True,
    )

    assert result["persistence_active"] is True
    assert result["provider_ready"] is True
    assert result["live_inference_activation_ready"] is True
    assert result["blockers"] == []


def test_runtime_preflight_uses_schema_probe_without_mutation(monkeypatch):
    monkeypatch.delenv("CALYX_VISION_DURABLE_ENABLED", raising=False)
    monkeypatch.setattr(activation, "_postgres_url", lambda: "postgresql://example/db")
    monkeypatch.setattr(activation, "_schema_problem", lambda cursor: None)

    def connect(url, **kwargs):
        assert url == "postgresql://example/db"
        assert kwargs["connect_timeout"] == activation._SCHEMA_PROBE_CONNECT_TIMEOUT_SECONDS
        return _Connection()

    monkeypatch.setattr(preflight.psycopg, "connect", connect)

    result = preflight.vision_activation_preflight()

    assert result["database_url_configured"] is True
    assert result["connectivity"] is True
    assert result["schema_ready"] is True
    assert result["persistence_activation_ready"] is True
    assert result["persistence_active"] is False
    assert result["provider_status"] == "PROVIDER_NOT_CONFIGURED"
    assert result["live_inference_enabled"] is False
    assert "VISION_DURABLE_PERSISTENCE_DISABLED" in result["blockers"]
    assert result["mutations_performed"] is False


def test_runtime_schema_probe_failure_is_not_reported_as_unreachable(monkeypatch):
    monkeypatch.setenv("CALYX_VISION_DURABLE_ENABLED", "true")
    monkeypatch.setattr(activation, "_postgres_url", lambda: "postgresql://example/db")

    def fail_schema_probe(cursor):
        raise RuntimeError("schema inspection denied")

    monkeypatch.setattr(activation, "_schema_problem", fail_schema_probe)
    monkeypatch.setattr(preflight.psycopg, "connect", lambda *args, **kwargs: _Connection())

    result = preflight.vision_activation_preflight()

    assert result["database_url_configured"] is True
    assert result["connectivity"] is True
    assert result["schema_ready"] is False
    assert result["inspection_error"] == "schema inspection denied"
    assert "VISION_SCHEMA_INSPECTION_FAILED" in result["blockers"]
    assert "VISION_DATABASE_UNREACHABLE" not in result["blockers"]
