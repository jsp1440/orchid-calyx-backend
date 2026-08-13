from __future__ import annotations

from app.trait_genomics.taxon_target_resolver import CanonicalTaxonTargetResolver


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.mode = None
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query, params=None):
        text = str(query)
        self.executed.append((text, params))
        self.mode = "presence" if "to_regclass" in text else "taxa"

    def fetchone(self):
        if self.mode == "presence":
            return {"present": True}
        return None

    def fetchall(self):
        return list(self.rows) if self.mode == "taxa" else []


class FakeConnection:
    def __init__(self, rows):
        self.cursor_instance = FakeCursor(rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self):
        return self.cursor_instance


def resolver(rows):
    connection = FakeConnection(rows)

    def factory(*args, **kwargs):
        return connection

    return CanonicalTaxonTargetResolver(
        database_url="postgresql://example/test",
        connection_factory=factory,
    ), connection


def test_exact_normalized_name_resolves_operational_taxon_id():
    service, connection = resolver(
        [
            {
                "id": 123,
                "scientific_name": "Dendrobium cuthbertsonii F.Muell.",
                "genus": "Dendrobium",
            }
        ]
    )
    result = service.resolve("Dendrobium cuthbertsonii")
    assert result.status == "resolved"
    assert result.target is not None
    assert result.target.canonical_taxon_id == "123"
    assert result.target.scientific_name == "Dendrobium cuthbertsonii"
    assert result.as_dict()["canonical_source"] == "public.orchid_taxonomy"
    query, params = connection.cursor_instance.executed[-1]
    assert "lower(scientific_name) LIKE lower(%s)" in query
    assert params == ("Dendrobium cuthbertsonii%",)


def test_unique_exact_text_breaks_authorship_only_duplicate_tie():
    service, _ = resolver(
        [
            {
                "id": 17235,
                "scientific_name": "Dendrobium cuthbertsonii F.Muell.",
                "genus": "Dendrobium",
            },
            {
                "id": 52090,
                "scientific_name": "Dendrobium cuthbertsonii",
                "genus": "Dendrobium",
            },
        ]
    )
    result = service.resolve("Dendrobium cuthbertsonii")
    assert result.status == "resolved"
    assert result.target is not None
    assert result.target.canonical_taxon_id == "52090"
    assert [item["canonical_taxon_id"] for item in result.candidates] == ["17235", "52090"]
    assert "sole row" in result.explanation


def test_infraspecific_name_does_not_collapse_to_species():
    service, connection = resolver(
        [
            {
                "id": 123,
                "scientific_name": "Example orchid",
                "genus": "Example",
            }
        ]
    )
    result = service.resolve("Example orchid var. alba")
    assert result.status == "unresolved"
    assert result.target is None
    assert connection.cursor_instance.executed[-1][1] == ("Example orchid var. alba%",)


def test_duplicate_canonical_rows_fail_closed_as_ambiguous():
    service, _ = resolver(
        [
            {"id": 10, "scientific_name": "Example orchid Author", "genus": "Example"},
            {"id": 11, "scientific_name": "Example orchid Other", "genus": "Example"},
        ]
    )
    result = service.resolve("Example orchid")
    assert result.status == "ambiguous"
    assert result.target is None
    assert [item["canonical_taxon_id"] for item in result.candidates] == ["10", "11"]


def test_duplicate_exact_text_rows_remain_ambiguous():
    service, _ = resolver(
        [
            {"id": 10, "scientific_name": "Example orchid", "genus": "Example"},
            {"id": 11, "scientific_name": "Example orchid", "genus": "Example"},
        ]
    )
    result = service.resolve("Example orchid")
    assert result.status == "ambiguous"
    assert result.target is None


def test_non_binomial_input_is_invalid_without_database_lookup():
    calls = []

    def factory(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("database should not be touched")

    service = CanonicalTaxonTargetResolver(
        database_url="postgresql://example/test",
        connection_factory=factory,
    )
    result = service.resolve("Dendrobium")
    assert result.status == "invalid"
    assert result.target is None
    assert calls == []


def test_resolve_or_raise_reports_ambiguity_without_guessing():
    service, _ = resolver(
        [
            {"id": 10, "scientific_name": "Example orchid Author", "genus": "Example"},
            {"id": 11, "scientific_name": "Example orchid Other", "genus": "Example"},
        ]
    )
    try:
        service.resolve_or_raise("Example orchid")
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("ambiguity must fail closed")
    assert "ambiguous" in message
    assert "10=Example orchid Author" in message
    assert "11=Example orchid Other" in message
