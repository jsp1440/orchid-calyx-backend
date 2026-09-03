"""Photographs, and the coordinates that must not travel with them.

A phone photograph of an orchid on a windowsill routinely carries GPS in its
EXIF, and those coordinates are the grower's home address. This collection is
private and a dossier can be shared, printed or served behind a QR route, so
the property under test throughout is that no original container ever reaches
disk — including when the tool that strips it is missing.
"""

from io import BytesIO
from pathlib import Path

import pytest

from runtime.conservatory_photographs import (
    MAX_PHOTOGRAPH_BYTES,
    ConservatoryPhotographStore,
    PhotographError,
)

PIL = pytest.importorskip("PIL", reason="the imaging library is what is under test")


def jpeg_with_exif(*, gps=True, taken="2024:03:17 14:05:00", size=(48, 32)) -> bytes:
    """A JPEG carrying the metadata a phone would attach."""
    from PIL import Image

    image = Image.new("RGB", size, (90, 140, 90))
    exif = image.getexif()
    exif[36867] = taken  # DateTimeOriginal
    exif[271] = "ACME"  # Make
    exif[272] = "Phone 12"  # Model
    exif[42033] = "SERIAL-0001"  # BodySerialNumber
    if gps:
        # 34.05 N, 118.24 W — a home address, written the way a camera writes
        # it: into the GPS IFD, as rationals.
        from PIL.TiffImagePlugin import IFDRational

        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1] = "N"
        gps_ifd[2] = (IFDRational(34, 1), IFDRational(3, 1), IFDRational(0, 1))
        gps_ifd[3] = "W"
        gps_ifd[4] = (IFDRational(118, 1), IFDRational(14, 1), IFDRational(0, 1))
    buffer = BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    return buffer.getvalue()


def png_bytes(size=(20, 20)) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, (200, 200, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


def exif_of(content: bytes) -> dict:
    from PIL import Image

    return dict(Image.open(BytesIO(content)).getexif() or {})


class TestStrippingWhatMustNotBeStored:
    def test_the_stored_file_carries_no_gps(self, tmp_path: Path):
        store = ConservatoryPhotographStore(tmp_path)
        original = jpeg_with_exif()
        assert 34853 in exif_of(original), "fixture must actually carry GPS"

        record = store.store(plant_id="p1", content=original, content_type="image/jpeg")

        stored = store.bytes_for(record["id"])
        assert 34853 not in exif_of(stored)

    def test_it_strips_everything_not_just_the_gps_block(self, tmp_path: Path):
        # An allowlist of "safe" tags goes stale the first time a vendor adds a
        # field. Nothing from the original container survives.
        store = ConservatoryPhotographStore(tmp_path)
        record = store.store(
            plant_id="p1", content=jpeg_with_exif(), content_type="image/jpeg"
        )

        assert exif_of(store.bytes_for(record["id"])) == {}

    def test_the_picture_itself_survives(self, tmp_path: Path):
        from PIL import Image

        store = ConservatoryPhotographStore(tmp_path)
        record = store.store(
            plant_id="p1",
            content=jpeg_with_exif(size=(48, 32)),
            content_type="image/jpeg",
        )

        stored = Image.open(BytesIO(store.bytes_for(record["id"])))
        assert stored.size == (48, 32)

    def test_a_png_is_stored_as_a_png(self, tmp_path: Path):
        from PIL import Image

        store = ConservatoryPhotographStore(tmp_path)
        record = store.store(
            plant_id="p1", content=png_bytes(), content_type="image/png"
        )

        assert record["content_type"] == "image/png"
        assert Image.open(BytesIO(store.bytes_for(record["id"]))).format == "PNG"


class TestRefusingRatherThanDegrading:
    def test_a_missing_imaging_library_refuses_the_upload(
        self, tmp_path: Path, monkeypatch
    ):
        """The whole reason this module can refuse at all.

        Storing the image unstripped would fail open on the one property this
        exists to guarantee, and fail silently: the photograph appears,
        everything looks fine, and the address is on disk.
        """
        import runtime.conservatory_photographs as module

        def unavailable():
            raise PhotographError("IMAGE_PROCESSING_UNAVAILABLE")

        monkeypatch.setattr(module, "_load_image_library", unavailable)
        store = ConservatoryPhotographStore(tmp_path)

        with pytest.raises(PhotographError) as raised:
            store.store(
                plant_id="p1", content=jpeg_with_exif(), content_type="image/jpeg"
            )

        assert str(raised.value) == "IMAGE_PROCESSING_UNAVAILABLE"
        # And nothing reached disk.
        assert list((tmp_path / "photographs").iterdir()) == []
        assert store.for_plant("p1") == []

    def test_a_genuinely_absent_library_refuses_too(self, tmp_path: Path, monkeypatch):
        """The import failure itself, not a stubbed loader.

        Stubbing `_load_image_library` proves the caller handles a refusal. It
        does not prove the loader raises one. With PIL hidden from the import
        machinery, an implementation that swallowed the ImportError would
        return None here and the upload would proceed unstripped.
        """
        import sys

        monkeypatch.setitem(sys.modules, "PIL", None)
        store = ConservatoryPhotographStore(tmp_path)

        with pytest.raises(PhotographError) as raised:
            store.store(plant_id="p1", content=b"anything", content_type="image/jpeg")

        assert str(raised.value) == "IMAGE_PROCESSING_UNAVAILABLE"
        assert list((tmp_path / "photographs").iterdir()) == []

    def test_an_unreadable_file_does_not_reach_disk(self, tmp_path: Path):
        # An unreadable image is not a safe image; it is one nobody has checked.
        store = ConservatoryPhotographStore(tmp_path)

        with pytest.raises(PhotographError) as raised:
            store.store(
                plant_id="p1", content=b"not an image at all", content_type="image/jpeg"
            )

        assert str(raised.value) == "PHOTOGRAPH_UNREADABLE"
        assert list((tmp_path / "photographs").iterdir()) == []

    def test_an_unaccepted_type_is_refused_rather_than_sniffed(self, tmp_path: Path):
        # Guessing a format from bytes is how a file that is not an image ends
        # up on disk under a name saying it is.
        store = ConservatoryPhotographStore(tmp_path)

        with pytest.raises(PhotographError) as raised:
            store.store(
                plant_id="p1", content=png_bytes(), content_type="image/svg+xml"
            )

        assert str(raised.value) == "CONTENT_TYPE_NOT_ACCEPTED"

    def test_an_oversized_upload_is_refused(self, tmp_path: Path):
        store = ConservatoryPhotographStore(tmp_path)

        with pytest.raises(PhotographError) as raised:
            store.store(
                plant_id="p1",
                content=b"x" * (MAX_PHOTOGRAPH_BYTES + 1),
                content_type="image/jpeg",
            )

        assert str(raised.value) == "PHOTOGRAPH_TOO_LARGE"

    def test_an_empty_upload_is_refused(self, tmp_path: Path):
        store = ConservatoryPhotographStore(tmp_path)

        with pytest.raises(PhotographError) as raised:
            store.store(plant_id="p1", content=b"", content_type="image/jpeg")

        assert str(raised.value) == "EMPTY_UPLOAD"


class TestTheTwoClocks:
    def test_when_it_was_taken_is_read_from_the_file(self, tmp_path: Path):
        store = ConservatoryPhotographStore(tmp_path)

        record = store.store(
            plant_id="p1",
            content=jpeg_with_exif(taken="2024:03:17 14:05:00"),
            content_type="image/jpeg",
        )

        assert record["taken_at"] == "2024-03-17T14:05:00"
        assert record["recorded_at"] != record["taken_at"]

    def test_a_file_with_no_capture_time_says_so_rather_than_borrowing_one(
        self, tmp_path: Path
    ):
        # A photograph from three years ago would otherwise claim to be from
        # today, and a chronology built on that is fiction.
        store = ConservatoryPhotographStore(tmp_path)

        record = store.store(
            plant_id="p1", content=png_bytes(), content_type="image/png"
        )

        assert record["taken_at"] is None
        assert record["recorded_at"]

    def test_an_unparseable_capture_time_is_dropped_not_guessed(self, tmp_path: Path):
        store = ConservatoryPhotographStore(tmp_path)

        record = store.store(
            plant_id="p1",
            content=jpeg_with_exif(taken="not a date"),
            content_type="image/jpeg",
        )

        assert record["taken_at"] is None


class TestTheChronology:
    def test_photographs_read_oldest_capture_first(self, tmp_path: Path):
        store = ConservatoryPhotographStore(tmp_path)
        later = store.store(
            plant_id="p1",
            content=jpeg_with_exif(taken="2025:06:01 09:00:00"),
            content_type="image/jpeg",
        )
        earlier = store.store(
            plant_id="p1",
            content=jpeg_with_exif(taken="2024:03:17 14:05:00"),
            content_type="image/jpeg",
        )

        assert [row["id"] for row in store.for_plant("p1")] == [
            earlier["id"],
            later["id"],
        ]

    def test_undated_photographs_sort_after_the_dated_ones(self, tmp_path: Path):
        """A position in a chronology is a claim about when something happened.

        The dated photograph here carries a capture time *later* than the
        moment both were uploaded — a camera with a wrong clock produces
        exactly this. It is the case that separates "undated goes last" from
        "undated is slotted in by its upload time": under the second rule the
        undated one would come first, which asserts a sequence nobody recorded.
        """
        store = ConservatoryPhotographStore(tmp_path)
        undated = store.store(
            plant_id="p1", content=png_bytes(), content_type="image/png"
        )
        dated = store.store(
            plant_id="p1",
            content=jpeg_with_exif(taken="2027:03:17 14:05:00"),
            content_type="image/jpeg",
        )

        assert [row["id"] for row in store.for_plant("p1")] == [
            dated["id"],
            undated["id"],
        ]

    def test_one_plants_photographs_do_not_appear_under_another(self, tmp_path: Path):
        store = ConservatoryPhotographStore(tmp_path)
        store.store(plant_id="p1", content=png_bytes(), content_type="image/png")

        assert store.for_plant("p2") == []

    def test_every_record_denies_being_evidence(self, tmp_path: Path):
        store = ConservatoryPhotographStore(tmp_path)

        record = store.store(
            plant_id="p1", content=png_bytes(), content_type="image/png"
        )

        assert record["is_scientific_evidence"] is False
        assert record["exif_stripped"] is True


class TestThroughTheApi:
    @staticmethod
    def _client(tmp_path: Path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_store import ConservatoryStore

        plants = ConservatoryStore(tmp_path)
        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: plants,
                require_owner=lambda: {"sub": "owner"},
                get_photographs=lambda: ConservatoryPhotographStore(tmp_path),
            )
        )
        return TestClient(app), plants

    def test_upload_then_read_back_a_stripped_image(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        plant = plants.create(display_name="Cattleya")

        created = client.post(
            f"/api/conservatory/plants/{plant['id']}/photographs",
            files={"file": ("orchid.jpg", jpeg_with_exif(), "image/jpeg")},
            data={"caption": "First flowering"},
        )

        assert created.status_code == 201
        record = created.json()
        assert record["caption"] == "First flowering"
        assert record["taken_at"] == "2024-03-17T14:05:00"

        image = client.get(f"/api/conservatory/photographs/{record['id']}")
        assert image.status_code == 200
        assert image.headers["content-type"].startswith("image/jpeg")
        assert exif_of(image.content) == {}

    def test_the_listing_reads_as_a_chronology_and_denies_being_evidence(
        self, tmp_path: Path
    ):
        client, plants = self._client(tmp_path)
        plant = plants.create(display_name="Cattleya")
        for taken in ("2025:06:01 09:00:00", "2024:03:17 14:05:00"):
            client.post(
                f"/api/conservatory/plants/{plant['id']}/photographs",
                files={"file": ("o.jpg", jpeg_with_exif(taken=taken), "image/jpeg")},
            )

        listing = client.get(
            f"/api/conservatory/plants/{plant['id']}/photographs"
        ).json()

        assert listing["count"] == 2
        assert [row["taken_at"] for row in listing["photographs"]] == [
            "2024-03-17T14:05:00",
            "2025-06-01T09:00:00",
        ]
        assert listing["is_scientific_evidence"] is False

    def test_a_refused_type_is_a_415(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        plant = plants.create(display_name="Cattleya")

        response = client.post(
            f"/api/conservatory/plants/{plant['id']}/photographs",
            files={"file": ("map.svg", b"<svg/>", "image/svg+xml")},
        )

        assert response.status_code == 415
        assert response.json()["detail"]["code"] == "CONTENT_TYPE_NOT_ACCEPTED"

    def test_an_unusable_imaging_library_is_a_503_not_a_silent_success(
        self, tmp_path: Path, monkeypatch
    ):
        import runtime.conservatory_photographs as module

        def unavailable():
            raise PhotographError("IMAGE_PROCESSING_UNAVAILABLE")

        monkeypatch.setattr(module, "_load_image_library", unavailable)
        client, plants = self._client(tmp_path)
        plant = plants.create(display_name="Cattleya")

        response = client.post(
            f"/api/conservatory/plants/{plant['id']}/photographs",
            files={"file": ("o.jpg", jpeg_with_exif(), "image/jpeg")},
        )

        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "IMAGE_PROCESSING_UNAVAILABLE"

    def test_photographs_cannot_be_attached_to_a_plant_that_does_not_exist(
        self, tmp_path: Path
    ):
        client, _ = self._client(tmp_path)

        response = client.post(
            "/api/conservatory/plants/no-such-plant/photographs",
            files={"file": ("o.jpg", jpeg_with_exif(), "image/jpeg")},
        )

        assert response.status_code == 404

    def test_the_image_route_is_owner_gated(self, tmp_path: Path):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_store import ConservatoryStore

        def refuse():
            raise HTTPException(status_code=401, detail="owner only")

        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: ConservatoryStore(tmp_path),
                require_owner=refuse,
                get_photographs=lambda: ConservatoryPhotographStore(tmp_path),
            )
        )
        client = TestClient(app)

        # A photograph of somebody's greenhouse is private whether or not the
        # identifier is guessable.
        assert client.get("/api/conservatory/photographs/anything").status_code == 401
        assert client.get("/api/conservatory/plants/p1/photographs").status_code == 401

    def test_an_index_entry_with_no_file_is_reported_not_hidden(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        plant = plants.create(display_name="Cattleya")
        record = client.post(
            f"/api/conservatory/plants/{plant['id']}/photographs",
            files={"file": ("o.jpg", jpeg_with_exif(), "image/jpeg")},
        ).json()
        for path in (tmp_path / "photographs").iterdir():
            path.unlink()

        response = client.get(f"/api/conservatory/photographs/{record['id']}")

        # A storage fault must not read as "no such photograph".
        assert response.status_code == 410
        assert response.json()["detail"]["code"] == "PHOTOGRAPH_FILE_MISSING"
