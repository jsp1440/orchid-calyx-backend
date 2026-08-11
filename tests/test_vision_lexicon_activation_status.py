from app.vision_lexicon import activation


class _FakeCursor:
    def __init__(self, *, missing_table: str | None = None, valid_constraint: bool = True):
        self.missing_table = missing_table
        self.valid_constraint = valid_constraint
        self._result = (True,)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        if "to_regnamespace" in query:
            self._result = (True,)
            return
        if "to_regclass" in query:
            qualified = params[0]
            table = qualified.split(".", 1)[1]
            self._result = (table != self.missing_table,)
            return
        if "pg_get_constraintdef" in query:
            self._result = (
                "CHECK ((review_state = ANY (ARRAY['MACHINE_GENERATED'::text])))",
            ) if self.valid_constraint else None
            return
        raise AssertionError(f"Unexpected SQL: {query}")

    def fetchone(self):
        return self._result


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self._cursor


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


def test_schema_probe_requires_all_tables_and_governance_constraint(monkeypatch):
    monkeypatch.setattr(activation, "_postgres_url", lambda: "postgresql://example/db")

    def connect_complete(url, **kwargs):
        assert url == "postgresql://example/db"
        assert kwargs["connect_timeout"] == activation._SCHEMA_PROBE_CONNECT_TIMEOUT_SECONDS
        return _FakeConnection(_FakeCursor())

    monkeypatch.setattr(activation.psycopg, "connect", connect_complete)
    assert activation.schema_ready() is True

    def connect_missing(url, **kwargs):
        return _FakeConnection(_FakeCursor(missing_table="character_conformance_checks"))

    monkeypatch.setattr(activation.psycopg, "connect", connect_missing)
    assert activation.schema_ready() is False

    def connect_unhardened(url, **kwargs):
        return _FakeConnection(_FakeCursor(valid_constraint=False))

    monkeypatch.setattr(activation.psycopg, "connect", connect_unhardened)
    assert activation.schema_ready() is False
