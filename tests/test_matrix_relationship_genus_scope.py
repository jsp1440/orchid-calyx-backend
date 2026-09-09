import pytest
from pydantic import ValidationError

from app.routers.matrix_relationship import CanonicalSourceMatrixRequest
from runtime import matrix_relationship_sources as sources


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("Phalaenopsis", "Phalaenopsis"),
        ("  Laelia  ", "Laelia"),
    ],
)
def test_canonical_genus_scope_accepts_only_bounded_genus_identity(value, expected):
    assert sources.canonical_genus_scope(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "phalaenopsis",
        "Phalaenopsis amabilis",
        "Phalaenopsis%",
        "Phalaenopsis/../../taxon",
        "",
    ],
)
def test_canonical_genus_scope_fails_closed(value):
    with pytest.raises(ValueError, match="canonical single-token genus"):
        sources.canonical_genus_scope(value)


def test_api_schema_rejects_noncanonical_genus_before_source_read():
    with pytest.raises(ValidationError):
        CanonicalSourceMatrixRequest(dimension="trait", genus="Phalaenopsis amabilis")


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Connection:
    def __init__(self):
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def transaction(self):
        return self

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        if sql == "set transaction read only":
            return _Result([])
        return _Result(
            [
                {
                    "source_pk": "trait-1",
                    "taxon_pk": 101,
                    "subject_label": "Phalaenopsis amabilis",
                    "trait_name": "growth_habit",
                    "trait_value": "epiphytic",
                }
            ]
        )


def test_governed_source_read_applies_genus_and_subject_filters(monkeypatch):
    connection = _Connection()
    monkeypatch.setattr(sources.psycopg, "connect", lambda *_args, **_kwargs: connection)

    assertions = sources.load_governed_assertions(
        "postgresql://unused",
        dimension="trait",
        subject_ids=["101"],
        genus="Phalaenopsis",
        limit=25,
    )

    assert len(assertions) == 1
    sql, params = connection.calls[-1]
    assert "s.taxon_pk::text = any(%s)" in sql
    assert "k.display_label = %s or k.display_label like %s" in sql
    assert params == [["101"], "Phalaenopsis", "Phalaenopsis %", 25]
    assert "set transaction read only" == connection.calls[0][0]
