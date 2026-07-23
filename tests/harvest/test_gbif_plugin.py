from __future__ import annotations

from app.harvest.checkpoints import InMemoryCheckpointStore
from app.harvest.metrics import HarvestMetrics
from app.harvest.persistence import InMemoryHarvestPersistence
from app.harvest.plugins.gbif.plugin import GBIFHarvester


def _harvester() -> GBIFHarvester:
    return GBIFHarvester(
        persistence=InMemoryHarvestPersistence(),
        checkpoints=InMemoryCheckpointStore(),
        metrics=HarvestMetrics(),
    )


def test_normalize_gbif_occurrence_with_media() -> None:
    harvester = _harvester()
    record = {
        "key": 123,
        "scientificName": "Dendrobium kingianum Bidwill ex Lindl.",
        "acceptedScientificName": "Thelychiton kingianus (Bidwill ex Lindl.) M.A.Clem. & D.L.Jones",
        "taxonKey": 2812463,
        "occurrenceID": "urn:catalog:test:123",
        "basisOfRecord": "HUMAN_OBSERVATION",
        "decimalLatitude": -33.9,
        "decimalLongitude": 151.2,
        "countryCode": "AU",
        "eventDate": "2024-09-01T00:00:00Z",
        "media": [
            {
                "identifier": "https://example.org/image.jpg",
                "type": "StillImage",
                "license": "CC_BY_4_0",
            }
        ],
    }

    normalized = harvester.normalize(record)

    assert normalized["source_record_id"] == "123"
    assert normalized["scientific_name"].startswith("Dendrobium kingianum")
    assert normalized["latitude"] == -33.9
    assert len(normalized["images"]) == 1
    assert normalized["images"][0]["url"] == "https://example.org/image.jpg"
    assert harvester.validate(normalized) is True


def test_invalid_coordinates_do_not_break_normalization() -> None:
    harvester = _harvester()
    normalized = harvester.normalize(
        {
            "key": 9,
            "scientificName": "Orchis testii",
            "decimalLatitude": "not-a-number",
        }
    )
    assert normalized["latitude"] is None
