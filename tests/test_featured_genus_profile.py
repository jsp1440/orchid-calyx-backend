import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.featured_genus import profile as profile_module
from app.featured_genus import routes as featured_genus_routes
from app.featured_genus.profile import build_featured_genus_profile


class FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None

    def mappings(self):
        return self

    def all(self):
        return self._rows


class FakeConnection:
    """Dispatches on the SQL text so each composer query gets its fixture."""

    def __init__(self, *, exists=True, count=2, sample=None, widget=None, media_rows=None, media_error=False):
        self.exists = exists
        self.count = count
        self.sample = sample if sample is not None else [
            {"scientific_name": "Cattleya labiata Lindl."},
            {"scientific_name": "Cattleya trianae Linden & Rchb.f."},
        ]
        self.widget = widget
        self.media_rows = media_rows if media_rows is not None else []
        self.media_error = media_error

    def execute(self, sql, params):
        statement = str(sql)
        if "FROM public.orchid_images" in statement:
            if self.media_error:
                raise RuntimeError("media store down")
            return FakeResult(self.media_rows)
        if "v_genus_of_day_cards" in statement:
            return FakeResult([self.widget] if self.widget else [])
        if "COUNT(DISTINCT scientific_name)" in statement:
            return FakeResult([{"recorded_names": self.count}])
        if "SELECT DISTINCT scientific_name" in statement:
            return FakeResult(self.sample)
        return FakeResult([{"exists": 1}] if self.exists else [])

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return self._conn


def _install(monkeypatch, conn):
    monkeypatch.setattr(profile_module, "get_engine", lambda: FakeEngine(conn))


def _image_row(image_id, scientific_name, url):
    return {
        "image_id": image_id,
        "taxonomy_id": 100,
        "scientific_name": scientific_name,
        "genus": "Cattleya",
        "image_url": url,
        "image_source": "GBIF",
        "image_license": "CC-BY",
        "image_rights_holder": "An Observer",
        "observer_name": "An Observer",
        "gbif_occurrence_key": "12345",
        "image_type": "photograph",
        "image_description": "",
        "alt_text": "",
        "is_duplicate": False,
    }


def _graph_payload():
    return {
        "focal_node": {"id": 1, "label": "Cattleya"},
        "graph": {"node_count": 40, "edge_count": 55},
        "pagination": {"truncated": False, "next_offset": None},
        "domain_coverage": {
            "literature": {"nodes": 3, "edges": 2},
            "conservation": {"nodes": 0, "edges": 0},
        },
    }


def test_profile_composes_canonical_evidence_with_states(monkeypatch):
    conn = FakeConnection(
        widget={
            "genus": "Cattleya",
            "taxonomy_id": 7,
            "accepted_scientific_name": "Cattleya trianae Linden & Rchb.f.",
            "species": "Cattleya trianae",
            "hero_image": None,
            "image_count": 41,
            "climate_tag": "cool-intermediate",
            "collection_tag": "andean",
            "min_elevation": 800,
            "max_elevation": 2400,
        },
        media_rows=[
            _image_row(1, "Cattleya labiata Lindl.", "https://example.org/labiata-1.jpg"),
            _image_row(2, "Cattleya labiata Lindl.", "https://example.org/labiata-2.jpg"),
            _image_row(3, "Cattleya trianae Linden & Rchb.f.", "https://example.org/trianae.jpg"),
        ],
    )
    _install(monkeypatch, conn)

    profile = build_featured_genus_profile(
        "Cattleya", graph_loader=lambda genus: ("ok", _graph_payload())
    )

    assert profile["contract"] == "featured-genus-profile/v1"
    assert profile["status"] == "ok"
    assert profile["accepted_genus"] == "Cattleya"

    taxonomy = profile["taxonomy"]
    assert taxonomy["state"] == "known"
    assert taxonomy["recorded_species_count"] == 2
    assert taxonomy["representative_names"] == [
        "Cattleya labiata Lindl.",
        "Cattleya trianae Linden & Rchb.f.",
    ]
    assert "not a global monographic census" in taxonomy["recorded_species_count_scope"]

    habitat = profile["habitat"]
    assert habitat["state"] == "known"
    assert habitat["min_elevation_m"] == 800
    assert habitat["max_elevation_m"] == 2400
    assert habitat["source"] == "oc_widget.v_genus_of_day_cards"

    media = profile["media"]
    assert media["state"] == "known"
    assert media["status"] == "ok"
    # The shared selection policy: one photograph per species.
    assert [item["scientific_name"] for item in media["items"]] == [
        "Cattleya labiata Lindl.",
        "Cattleya trianae Linden & Rchb.f.",
    ]

    assert profile["knowledge_graph"]["state"] == "known"
    assert profile["knowledge_graph"]["node_count"] == 40
    assert profile["domains"]["literature"] == {"state": "known", "linked_nodes": 3, "linked_edges": 2}
    # A zero-coverage domain is a knowledge gap, never a claim of absence.
    assert profile["domains"]["conservation"]["state"] == "unknown"
    assert "conservation" in profile["gaps"]
    assert "literature" not in profile["gaps"]


def test_profile_invalid_genus_returns_no_scientific_content(monkeypatch):
    _install(monkeypatch, FakeConnection(exists=False))
    profile = build_featured_genus_profile("Notagenus", graph_loader=lambda genus: ("unknown", None))
    assert profile["status"] == "invalid_genus"
    assert profile["accepted_genus"] is None
    assert "taxonomy" not in profile


def test_missing_widget_card_is_unknown_never_zero_elevation(monkeypatch):
    _install(monkeypatch, FakeConnection(widget=None))
    profile = build_featured_genus_profile("Cattleya", graph_loader=lambda genus: ("unknown", None))
    habitat = profile["habitat"]
    assert habitat["state"] == "unknown"
    assert habitat.get("min_elevation_m") is None
    assert habitat.get("max_elevation_m") is None


def test_media_failure_is_unavailable_and_does_not_empty_the_profile(monkeypatch):
    _install(monkeypatch, FakeConnection(media_error=True))
    profile = build_featured_genus_profile("Cattleya", graph_loader=lambda genus: ("unknown", None))
    assert profile["status"] == "ok"
    assert profile["taxonomy"]["state"] == "known"
    assert profile["media"]["state"] == "unavailable"
    assert profile["media"]["status"] == "service_error"
    assert profile["media"]["items"] == []


def test_graph_unavailable_marks_domains_unavailable_not_unknown(monkeypatch):
    _install(monkeypatch, FakeConnection())
    profile = build_featured_genus_profile("Cattleya", graph_loader=lambda genus: ("unavailable", None))
    assert profile["knowledge_graph"]["state"] == "unavailable"
    assert profile["domains"]["literature"]["state"] == "unavailable"
    # Unavailable is not a knowledge gap: no coverage claim in either direction.
    assert profile["gaps"] == []


def test_taxonomy_failure_fails_closed_with_503(monkeypatch):
    class BrokenConnection(FakeConnection):
        def execute(self, sql, params):
            raise RuntimeError("taxonomy store unreachable")

    _install(monkeypatch, BrokenConnection())
    with pytest.raises(HTTPException) as excinfo:
        build_featured_genus_profile("Cattleya", graph_loader=lambda genus: ("unknown", None))
    assert excinfo.value.status_code == 503


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/featured-genus/v1/profile/Cattleya",
            "headers": [(b"origin", b"https://orchidcontinuum.org")],
        }
    )


def test_profile_route_rejects_non_genus_input_with_400():
    with pytest.raises(HTTPException) as excinfo:
        featured_genus_routes.featured_genus_profile("Cattleya labiata", _request(), Response(), media_limit=12)
    assert excinfo.value.status_code == 400


def test_profile_route_normalizes_case_and_sets_frontend_cors(monkeypatch):
    _install(monkeypatch, FakeConnection())
    response = Response()
    payload = featured_genus_routes.featured_genus_profile(
        "cattleya", _request(), response, media_limit=12
    )
    assert payload["accepted_genus"] == "Cattleya"
    assert response.headers["Access-Control-Allow-Origin"] == "https://orchidcontinuum.org"


def test_selection_route_reports_contract():
    payload = featured_genus_routes.featured_genus_selection(_request(), Response(), at=0)
    assert payload["contract"] == "featured-genus-selection/v1"
    assert payload["genus"] == "Cattleya"
