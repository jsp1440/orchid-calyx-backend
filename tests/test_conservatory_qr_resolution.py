"""A QR tag must keep meaning the same plant, and must never mean the wrong one.

A tag is glued to a plant for years and read back in a greenhouse, where it
will be faded, wet or chewed. Two properties matter more than convenience:

  it resolves          every durable way the accession is written comes back
                       to the same record, including the URN already printed
                       on existing tags;

  it never guesses     a damaged or unknown identifier returns nothing. A
                       near match would silently attach one plant's history
                       to another, and the grower would have no way to notice.

The second is the one these tests exist for.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.conservatory import create_conservatory_router
from runtime.conservatory_store import ConservatoryStore


def _client(tmp_path: Path, monkeypatch=None) -> tuple[TestClient, ConservatoryStore]:
    store = ConservatoryStore(tmp_path)
    app = FastAPI()
    app.include_router(
        create_conservatory_router(
            get_store=lambda: store,
            require_owner=lambda: {"sub": "owner"},
        )
    )
    return TestClient(app), store


def _plant(store: ConservatoryStore, name: str = "Cattleya skinneri alba") -> dict:
    return store.create(display_name=name, location="Greenhouse bench 2")


class TestResolvesEveryDurableForm:
    def test_resolves_the_urn_printed_on_existing_tags(self, tmp_path: Path):
        # The form already in the world. If this ever stops resolving, every
        # tag printed before today becomes scrap.
        client, store = _client(tmp_path)
        plant = _plant(store)
        response = client.get(f"/api/conservatory/resolve/{plant['qr_identifier']}")
        assert response.status_code == 200
        assert response.json()["id"] == plant["id"]

    def test_resolves_the_bare_accession_id(self, tmp_path: Path):
        client, store = _client(tmp_path)
        plant = _plant(store)
        assert client.get(f"/api/conservatory/resolve/{plant['id']}").json()["id"] == plant["id"]

    def test_resolves_the_accession_number_a_human_can_read(self, tmp_path: Path):
        # The recovery path: a tag too damaged to scan but still legible.
        client, store = _client(tmp_path)
        plant = _plant(store)
        number = plant["accession_number"]
        assert client.get(f"/api/conservatory/resolve/{number}").json()["id"] == plant["id"]

    def test_accession_number_is_case_insensitive(self, tmp_path: Path):
        client, store = _client(tmp_path)
        plant = _plant(store)
        lowered = plant["accession_number"].lower()
        assert client.get(f"/api/conservatory/resolve/{lowered}").json()["id"] == plant["id"]

    def test_resolves_a_scan_url_wrapping_the_identity(self, tmp_path: Path):
        # What a phone actually hands back after scanning a configured tag.
        _, store = _client(tmp_path)
        plant = _plant(store)
        store_result = store.resolve(
            f"https://continuum.example.org/conservatory/scan/{plant['qr_identifier']}"
        )
        assert store_result is not None and store_result["id"] == plant["id"]

    def test_ignores_query_and_fragment_on_a_scan_url(self, tmp_path: Path):
        _, store = _client(tmp_path)
        plant = _plant(store)
        wrapped = f"https://x.example/conservatory/scan/{plant['id']}?utm=qr#top"
        assert store.resolve(wrapped)["id"] == plant["id"]

    def test_tolerates_surrounding_whitespace(self, tmp_path: Path):
        _, store = _client(tmp_path)
        plant = _plant(store)
        assert store.resolve(f"  {plant['id']}  ")["id"] == plant["id"]


class TestNeverResolvesToTheWrongPlant:
    def test_an_unknown_identifier_resolves_to_nothing(self, tmp_path: Path):
        client, store = _client(tmp_path)
        _plant(store)
        response = client.get("/api/conservatory/resolve/calyx:plant:not-a-real-id")
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "ACCESSION_NOT_RESOLVED"

    def test_a_truncated_identifier_does_not_prefix_match(self, tmp_path: Path):
        # The damaged-tag case. Half an id must not select the plant it is
        # half of — that is exactly how one plant inherits another's history.
        _, store = _client(tmp_path)
        plant = _plant(store)
        truncated = plant["id"][: len(plant["id"]) // 2]
        assert store.resolve(truncated) is None

    def test_a_neighbouring_accession_number_is_not_matched(self, tmp_path: Path):
        _, store = _client(tmp_path)
        first = _plant(store, "First")
        second = _plant(store, "Second")
        assert first["accession_number"] != second["accession_number"]
        # Each resolves to itself and never to its neighbour.
        assert store.resolve(first["accession_number"])["id"] == first["id"]
        assert store.resolve(second["accession_number"])["id"] == second["id"]

    def test_empty_and_junk_identifiers_resolve_to_nothing(self, tmp_path: Path):
        _, store = _client(tmp_path)
        _plant(store)
        for junk in ["", "   ", "https://", "calyx:plant:", "x" * 500, "/", "?"]:
            assert store.resolve(junk) is None, junk

    def test_a_blank_scan_cannot_match_a_malformed_row(self, tmp_path: Path):
        """A failed scan yields an empty string. A damaged record can hold an
        empty field. If both are compared as equals, an unreadable tag silently
        opens whichever record happens to be broken — the two most degraded
        things in the system finding each other."""
        import json

        store = ConservatoryStore(tmp_path)
        good = store.create(display_name="Healthy record")
        rows = json.loads((tmp_path / "plants.json").read_text(encoding="utf-8"))
        rows.append(
            {
                "id": "",
                "accession_number": "",
                "display_name": "Damaged record",
                "accepted_scientific_name": None,
                "location": None,
                "notes": None,
                "qr_identifier": "",
                "created_at": good["created_at"],
                "updated_at": good["updated_at"],
            }
        )
        (tmp_path / "plants.json").write_text(json.dumps(rows), encoding="utf-8")

        blanks = [
            "",
            "   ",
            "\t",
            "https://x.example/conservatory/scan/",
            # The subtle one: a scan URL whose final segment percent-decodes to
            # whitespace. It survives the early blank check as a non-empty
            # string and only collapses to nothing after unwrapping, so it
            # exercises a different guard than a plainly empty scan does.
            "https://x.example/conservatory/scan/%20",
            "https://x.example/conservatory/scan/%09",
        ]
        for blank in blanks:
            assert store.resolve(blank) is None, blank

    def test_resolution_is_scoped_to_this_collection(self, tmp_path: Path):
        # An identifier valid in someone else's store means nothing in ours.
        _, store_a = _client(tmp_path / "a")
        _, store_b = _client(tmp_path / "b")
        theirs = _plant(store_a)
        assert store_b.resolve(theirs["qr_identifier"]) is None


class TestScanningIsNotAuthorisation:
    def test_resolve_requires_an_owner(self, tmp_path: Path):
        # A QR code on a plant is visible to anyone walking past it. If this
        # route were open, the tag would publish a private collection to any
        # visitor with a phone.
        store = ConservatoryStore(tmp_path)
        plant = store.create(display_name="Private plant")

        def deny() -> None:
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="owner required")

        app = FastAPI()
        app.include_router(
            create_conservatory_router(get_store=lambda: store, require_owner=deny)
        )
        client = TestClient(app)
        response = client.get(f"/api/conservatory/resolve/{plant['qr_identifier']}")
        assert response.status_code == 401
        assert plant["display_name"] not in response.text


class TestTagsSayWhetherTheyScan:
    def test_without_a_configured_base_the_tag_carries_the_urn_and_says_so(
        self, tmp_path: Path, monkeypatch
    ):
        # Better an honestly unscannable tag than one pointing at a hostname
        # this service invented.
        monkeypatch.delenv("CONSERVATORY_SCAN_BASE_URL", raising=False)
        client, store = _client(tmp_path)
        plant = _plant(store)
        response = client.get(f"/api/conservatory/plants/{plant['id']}/qr.svg")
        assert response.status_code == 200
        assert response.headers["X-Conservatory-Qr-Scannable"] == "false"

        manifest = client.post("/api/conservatory/labels/manifest", json={}).json()
        assert manifest["qr_scannable"] is False
        assert manifest["labels"][0]["qr_target"] == plant["qr_identifier"]

    def test_with_a_configured_base_the_tag_carries_a_followable_url(
        self, tmp_path: Path, monkeypatch
    ):
        monkeypatch.setenv("CONSERVATORY_SCAN_BASE_URL", "https://continuum.example.org/")
        client, store = _client(tmp_path)
        plant = _plant(store)
        response = client.get(f"/api/conservatory/plants/{plant['id']}/qr.svg")
        assert response.headers["X-Conservatory-Qr-Scannable"] == "true"

        manifest = client.post("/api/conservatory/labels/manifest", json={}).json()
        label = manifest["labels"][0]
        assert manifest["qr_scannable"] is True
        assert label["qr_target"].startswith("https://continuum.example.org/conservatory/scan/")
        assert label["qr_scannable"] is True
        # And the round trip closes: what the tag carries resolves back.
        assert store.resolve(label["qr_target"])["id"] == plant["id"]

    def test_the_durable_identity_itself_never_changes(self, tmp_path: Path, monkeypatch):
        # Configuring, changing or removing a scan host must not rewrite the
        # identity on plants already tagged.
        monkeypatch.setenv("CONSERVATORY_SCAN_BASE_URL", "https://one.example")
        _, store = _client(tmp_path)
        plant = _plant(store)
        before = plant["qr_identifier"]
        monkeypatch.setenv("CONSERVATORY_SCAN_BASE_URL", "https://two.example")
        assert store.get(plant["id"])["qr_identifier"] == before
        monkeypatch.delenv("CONSERVATORY_SCAN_BASE_URL")
        assert store.get(plant["id"])["qr_identifier"] == before
