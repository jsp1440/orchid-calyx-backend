from starlette.requests import Request
from starlette.responses import Response

from app.routers import orchid_widgets


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/media/genus/Cattleya",
            "headers": [(b"origin", b"https://orchidcontinuum.org")],
        }
    )


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
    def __init__(self, taxonomy_exists, media_rows):
        self.taxonomy_exists = taxonomy_exists
        self.media_rows = media_rows
        self.calls = 0

    def execute(self, _sql, _params):
        self.calls += 1
        if self.calls == 1:
            return FakeResult([{"exists": 1}] if self.taxonomy_exists else [])
        return FakeResult(self.media_rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return self._conn


def _image_row(image_id, scientific_name, image_url):
    return {
        "image_id": image_id,
        "taxonomy_id": 100,
        "scientific_name": scientific_name,
        "genus": "Cattleya",
        "image_url": image_url,
        "image_source": "GBIF",
        "image_license": "CC-BY",
        "image_rights_holder": "Some Observer",
        "observer_name": "Some Observer",
        "gbif_occurrence_key": "12345",
        "image_type": "photograph",
        "image_description": "",
        "alt_text": "",
        "is_duplicate": False,
    }


def test_genus_media_returns_at_most_one_image_per_species(monkeypatch):
    # Reproduces the live production failure ("Duplicate species returned for
    # Cattleya, 12 !== 4") caught daily by the Featured Genus Render Sentinel:
    # multiple approved photographs of the same species must not each occupy
    # a slot in the Featured Genus carousel, crowding out other species.
    rows = [
        _image_row(1, "Cattleya labiata", "https://example.org/labiata-1.jpg"),
        _image_row(2, "Cattleya labiata", "https://example.org/labiata-2.jpg"),
        _image_row(3, "Cattleya labiata", "https://example.org/labiata-3.jpg"),
        _image_row(4, "Cattleya trianae", "https://example.org/trianae-1.jpg"),
        _image_row(5, "Cattleya mossiae", "https://example.org/mossiae-1.jpg"),
    ]
    conn = FakeConnection(taxonomy_exists=True, media_rows=rows)
    monkeypatch.setattr(orchid_widgets, "get_engine", lambda: FakeEngine(conn))

    result = orchid_widgets.genus_media("Cattleya", request(), Response(), limit=12)

    species = [item["scientific_name"] for item in result["items"]]
    assert species == sorted(set(species), key=species.index)
    assert len(species) == len(set(species))
    assert set(species) == {"Cattleya labiata", "Cattleya trianae", "Cattleya mossiae"}
