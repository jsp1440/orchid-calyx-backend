"""Home-page widgets report an honest 503 when their database is absent.

Release 1 journeys 1/14: a local run with no DATABASE_URL made
``GET /api/media/genus/{genus}`` and ``GET /api/widgets/genus-of-day`` answer
HTTP 500. A missing or unreachable database is an expected degraded state, so
both routes must answer 503 with a stable code, while genuine programming or
schema errors keep their 500 and the data path is unchanged.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.exc import InterfaceError, OperationalError, ProgrammingError

from app.routers import orchid_widgets

MEDIA_PATH = "/api/media/genus/Catasetum?limit=12"
GENUS_OF_DAY_PATH = "/api/widgets/genus-of-day"


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(orchid_widgets.router)
    return TestClient(app, raise_server_exceptions=False)


def _empty_sqlite_engine(tmp_path):
    # Exactly what app.database.get_engine() builds when neither PGHOST nor
    # DATABASE_URL is set: a SQLite file with none of the canonical tables.
    return create_engine(
        f"sqlite:///{tmp_path / 'calyx.db'}",
        connect_args={"check_same_thread": False},
    )


class _RaisingConnection:
    def __init__(self, exc: Exception):
        self._exc = exc

    def execute(self, *_args, **_kwargs):
        raise self._exc

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _RaisingEngine:
    """Engine whose statements fail with a chosen exception."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def connect(self):
        return _RaisingConnection(self._exc)


class _RefusingEngine:
    """Engine whose connection attempt itself fails (server unreachable)."""

    def __init__(self, exc: Exception):
        self._exc = exc

    def connect(self):
        raise self._exc


def _connection_refused() -> OperationalError:
    return OperationalError("SELECT 1", {}, ConnectionRefusedError("connection refused"))


@pytest.mark.parametrize(
    ("path", "code"),
    [
        (MEDIA_PATH, orchid_widgets.GENUS_MEDIA_DATABASE_UNAVAILABLE),
        (GENUS_OF_DAY_PATH, orchid_widgets.GENUS_OF_DAY_DATABASE_UNAVAILABLE),
    ],
)
def test_database_absent_returns_503_with_stable_code(client, monkeypatch, tmp_path, path, code):
    engine = _empty_sqlite_engine(tmp_path)
    monkeypatch.setattr(orchid_widgets, "get_engine", lambda: engine)

    response = client.get(path, headers={"Origin": "https://orchidcontinuum.org"})

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": code}}
    assert "Traceback" not in response.text
    assert "sqlite" not in response.text.lower()


@pytest.mark.parametrize(
    ("path", "code"),
    [
        (MEDIA_PATH, orchid_widgets.GENUS_MEDIA_DATABASE_UNAVAILABLE),
        (GENUS_OF_DAY_PATH, orchid_widgets.GENUS_OF_DAY_DATABASE_UNAVAILABLE),
    ],
)
@pytest.mark.parametrize(
    "engine_factory",
    [
        lambda: _RefusingEngine(_connection_refused()),
        lambda: _RaisingEngine(_connection_refused()),
        lambda: _RaisingEngine(InterfaceError("SELECT 1", {}, Exception("connection already closed"))),
    ],
    ids=["connect_refused", "statement_operational_error", "interface_error"],
)
def test_database_unreachable_returns_503_with_stable_code(client, monkeypatch, path, code, engine_factory):
    engine = engine_factory()
    monkeypatch.setattr(orchid_widgets, "get_engine", lambda: engine)

    response = client.get(path)

    assert response.status_code == 503
    assert response.json() == {"detail": {"code": code}}
    assert "connection refused" not in response.text


@pytest.mark.parametrize(
    ("path", "detail"),
    [
        (MEDIA_PATH, "Unable to query canonical Orchid Continuum media."),
        (GENUS_OF_DAY_PATH, "Unable to load genus-of-day widget data."),
    ],
)
@pytest.mark.parametrize(
    "exc",
    [
        ProgrammingError("SELECT missing_column", {}, Exception("column does not exist")),
        KeyError("image_url"),
    ],
    ids=["schema_or_sql_defect", "programming_error"],
)
def test_genuine_defects_are_not_reported_as_unavailable(client, monkeypatch, path, detail, exc):
    engine = _RaisingEngine(exc)
    monkeypatch.setattr(orchid_widgets, "get_engine", lambda: engine)

    response = client.get(path)

    assert response.status_code == 500
    assert response.json() == {"detail": detail}


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _RowsConnection:
    def __init__(self, *results):
        self._results = list(results)

    def execute(self, *_args, **_kwargs):
        return _Result(self._results.pop(0))

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class _RowsEngine:
    def __init__(self, *results):
        self._results = results

    def connect(self):
        return _RowsConnection(*self._results)


def test_genus_of_day_data_path_is_unchanged(client, monkeypatch):
    # Synthetic row shape (clearly not real data): the route passes rows through.
    row = {"genus": "Examplegenus", "taxonomy_id": 1, "image_count": 0}
    monkeypatch.setattr(orchid_widgets, "get_engine", lambda: _RowsEngine([row]))

    response = client.get(GENUS_OF_DAY_PATH)

    assert response.status_code == 200
    assert response.json() == {"widget": "genus_of_day", "count": 1, "items": [row]}


def test_genus_media_data_path_is_unchanged(client, monkeypatch):
    # Synthetic row shape (clearly not real data) exercising the normal path.
    media_row = {
        "image_id": 7,
        "taxonomy_id": 100,
        "scientific_name": "Catasetum exampleum",
        "genus": "Catasetum",
        "image_url": "https://images.example.org/orchids/catasetum.jpg",
        "image_source": "GBIF",
        "image_license": "CC-BY",
        "image_rights_holder": "Example Holder",
        "observer_name": None,
        "gbif_occurrence_key": "123",
        "image_type": "photograph",
        "image_description": "",
        "alt_text": "",
        "is_duplicate": False,
    }
    monkeypatch.setattr(orchid_widgets, "get_engine", lambda: _RowsEngine([{"exists": 1}], [media_row]))

    response = client.get(MEDIA_PATH)

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["accepted_genus"] == "Catasetum"
    assert [item["media_id"] for item in payload["items"]] == ["oc-image:7"]
    assert payload["items"][0]["source_record_url"] == "https://www.gbif.org/occurrence/123"


def test_invalid_genus_is_still_rejected_before_any_database_access(client, monkeypatch):
    def _no_engine():
        raise AssertionError("database must not be touched for an invalid genus")

    monkeypatch.setattr(orchid_widgets, "get_engine", _no_engine)

    response = client.get("/api/media/genus/C4t")

    assert response.status_code == 400
