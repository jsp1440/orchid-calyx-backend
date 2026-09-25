"""Release-1 journey 19 — one evidence object, one provenance, across modules.

The same stored image row and the same persisted Knowledge Graph edge are read by the
homepage species exhibit and by the species dossier. This test feeds both from one fake
``public.orchid_images`` / ``oc_graph`` and proves the provenance they report is the same
record, the same license, the same attribution rule, the same confidence (the graph's own
score, never a verdict), and that the exhibit's advertised evidence link really answers
with those receipts. It also pins that a Field Journal photo keeps its provenance intact
through attach, list and reload.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.field_observation import service as observation_service
from app.field_observation.schemas import FieldObservationCreate, PhotoAttachRequest
from app.field_observation.service import FieldObservationService
from app.species_dossier.models import DossierEvidenceState
from app.species_dossier.repository import PostgresSpeciesRepository
from app.species_dossier.routes import get_service
from app.species_dossier.routes import router as dossier_router
from app.species_dossier.service import SpeciesDossierService
from app.species_exhibit import service as exhibit_service

TAXA = [
    {"id": 101, "scientific_name": "Phalaenopsis amabilis (L.) Blume", "genus": "Phalaenopsis"},
    {"id": 102, "scientific_name": "Phalaenopsis aphrodite Rchb.f.", "genus": "Phalaenopsis"},
]
IMAGE_9002 = {
    "id": 9002,
    "image_url": "https://images.example/2.jpg",
    "image_source": "Wikimedia Commons",
    "image_license": "CC-BY-SA-4.0",
    "image_rights_holder": None,
    "observer_name": "B. Photographer",
    "gbif_occurrence_key": None,
}
IMAGE_9001 = {
    "id": 9001,
    "image_url": "https://images.example/1.jpg",
    "image_source": "iNaturalist",
    "image_license": "CC-BY-NC-4.0",
    "image_rights_holder": "A. Grower",
    "observer_name": "someone else",
    "gbif_occurrence_key": None,
}
IMAGES = {101: [IMAGE_9001], 102: [IMAGE_9002]}
EDGE_5 = {
    "edge_type": "pollinated_by",
    "node_type": "pollinator",
    "canonical_key": "pollinator:moth",
    "display_label": "hawk moth",
    "evidence_class": "literature",
    "confidence_score": 0.7,
    "confidence_label": "moderate",
    "source_table": "oc_graph.kg_edges",
    "source_pk": 5,
}
GRAPH = {101: [EDGE_5]}


class SharedEvidenceCursor:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        compact = " ".join(sql.split())
        if "to_regclass('oc_graph.kg_nodes')" in compact:
            self._rows = [{"nodes_present": True, "edges_present": True}]
        elif "FROM public.orchid_taxonomy t LEFT JOIN public.orchid_images i" in compact:
            genus = params[0].lower()
            self._rows = [{**t, "image_count": len(IMAGES.get(t["id"], []))} for t in TAXA if t["genus"].lower() == genus]
        elif "FROM public.orchid_taxonomy WHERE id::text = %s" in compact:
            self._rows = [dict(t) for t in TAXA if str(t["id"]) == params[0]]
        elif "lower(scientific_name) = lower(%s)" in compact:
            self._rows = []
        elif "FROM public.orchid_images" in compact:
            self._rows = [dict(r) for r in IMAGES.get(int(params[0]), [])]
        elif "FROM oc_graph.kg_nodes t JOIN oc_graph.kg_edges e" in compact:
            # dossier only: compiled-specialist (federated) evidence nodes; this fixture has none
            assert "e.edge_type = 'supported_by_evidence'" in compact
            self._rows = []
        elif "FROM oc_graph.kg_nodes n1" in compact:
            self._rows = [dict(r) for r in GRAPH.get(int(params[0].split(":", 1)[1]), [])]
        elif "lower(genus) = lower(%s) AND id::text <> %s" in compact:
            self._rows = [dict(t) for t in TAXA if t["genus"].lower() == params[0].lower() and str(t["id"]) != params[1]]
        else:  # pragma: no cover
            raise AssertionError(f"unexpected SQL: {compact}")

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeConnection:
    def __init__(self, cursor) -> None:
        self._cursor = cursor

    def cursor(self):
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture()
def cursor() -> SharedEvidenceCursor:
    return SharedEvidenceCursor()


@pytest.fixture()
def repository(cursor) -> PostgresSpeciesRepository:
    return PostgresSpeciesRepository(lambda work: work(cursor))


@pytest.fixture()
def exhibit(cursor, monkeypatch) -> dict[str, Any]:
    @contextmanager
    def fake_connect(dsn, **kwargs):
        yield FakeConnection(cursor)

    monkeypatch.setattr(exhibit_service.psycopg, "connect", fake_connect)
    return exhibit_service.build_species_exhibit("postgresql://fake", "Phalaenopsis", limit=9)


def card(exhibit: dict[str, Any], taxon_id: str) -> dict[str, Any]:
    return next(item for item in exhibit["items"] if item["taxon_id"] == taxon_id)


# -- the same image row -------------------------------------------------------------------


def test_the_same_image_row_carries_the_same_record_license_and_source_in_both_modules(repository, exhibit):
    dossier = repository.get_dossier("102")
    receipt = dossier.living_media.receipts[0]
    anchor = next(a for a in card(exhibit, "102")["provenance"] if a["kind"] == "media")
    media = card(exhibit, "102")["evidence_states"]["media"]["value"]

    assert str(anchor["record_id"]) == receipt.record_id == "9002"
    assert anchor["license"] == receipt.license == media["license"] == "CC-BY-SA-4.0"
    assert anchor["source"] == receipt.source_name == media["source"] == "Wikimedia Commons"
    assert receipt.source_id == "public.orchid_images"
    assert media["url"] == dossier.living_media.items[0]["url"] == "https://images.example/2.jpg"


def test_attribution_follows_one_rule_rights_holder_first_then_observer(repository, exhibit):
    without_holder = repository.get_dossier("102").living_media.receipts[0]
    with_holder = repository.get_dossier("101").living_media.receipts[0]
    assert without_holder.attribution == "B. Photographer"
    assert with_holder.attribution == "A. Grower"
    exhibit_102 = card(exhibit, "102")["evidence_states"]["media"]["value"]
    exhibit_101 = card(exhibit, "101")["evidence_states"]["media"]["value"]
    assert (exhibit_102["rights_holder"], exhibit_102["observer_name"]) == (None, "B. Photographer")
    assert (exhibit_101["rights_holder"], exhibit_101["observer_name"]) == ("A. Grower", "someone else")
    # The dossier's single attribution string is exactly the exhibit's rights holder when present, else its observer.
    assert with_holder.attribution == exhibit_101["rights_holder"]
    assert without_holder.attribution == exhibit_102["observer_name"]


def test_neither_module_upgrades_a_source_image_to_a_verified_identification(repository, exhibit):
    dossier = repository.get_dossier("102")
    assert dossier.living_media.state is DossierEvidenceState.PROVISIONAL
    assert dossier.living_media.receipts[0].evidence_state is DossierEvidenceState.PROVISIONAL
    assert dossier.living_media.items[0]["identification_state"] == "source_record_not_independently_verified"
    assert card(exhibit, "102")["evidence_states"]["media"]["value"]["identification_state"] == "source_record_not_independently_verified"
    assert card(exhibit, "102")["evidence_state"] == "provisional"  # no graph edge for 102 -> provisional card


# -- the same graph edge ------------------------------------------------------------------


def test_the_same_graph_edge_is_cited_by_table_and_primary_key_in_both_modules(repository, exhibit):
    dossier = repository.get_dossier("101")
    receipt = dossier.knowledge_graph.receipts[0]
    anchor = next(a for a in card(exhibit, "101")["provenance"] if a["kind"] == "knowledge_graph")
    assert (anchor["source"], anchor["record_id"]) == (receipt.source_id, receipt.record_id) == ("oc_graph.kg_edges", "5")

    fact_provenance = card(exhibit, "101")["distinguishing_fact_provenance"]
    assert (fact_provenance["source_table"], str(fact_provenance["source_pk"])) == ("oc_graph.kg_edges", "5")
    assert fact_provenance["evidence_class"] == dossier.knowledge_graph.items[0]["evidence_class"] == "literature"


def test_confidence_is_the_graph_s_own_score_in_both_modules_never_a_verdict(repository, exhibit):
    dossier = repository.get_dossier("101")
    item = dossier.knowledge_graph.items[0]
    exhibit_confidence = card(exhibit, "101")["confidence"]
    assert item["confidence_score"] == exhibit_confidence["score"] == 0.7
    assert item["confidence_label"] == exhibit_confidence["label"] == "moderate"
    assert "not a verdict" in dossier.knowledge_graph.receipts[0].notes
    assert exhibit_confidence["basis"].startswith("Maximum explicit confidence score among returned persisted graph edges")


def test_exhibit_evidence_receipt_is_deterministic_and_content_free(exhibit):
    item = card(exhibit, "101")
    recomputed = exhibit_service._evidence_receipt(
        "101", item["evidence_states"]["media"]["value"], [EDGE_5]
    )
    assert item["evidence_receipt"] == recomputed
    assert item["evidence_receipt"]["contents_included"] is False
    assert len(item["evidence_receipt"]["digest"]) == 64


# -- the exhibit's advertised evidence link answers with the dossier's receipts -------------


def test_the_exhibit_s_evidence_link_serves_the_dossier_receipts_for_the_same_taxon(repository, exhibit, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test")
    app = FastAPI()
    app.include_router(dossier_router)
    app.dependency_overrides[get_service] = lambda: SpeciesDossierService(repository, public_base_url="https://oc.test")
    client = TestClient(app)

    item = card(exhibit, "101")
    assert item["links"]["evidence"] == "/api/platform/homepage/species/101/evidence"
    via_link = client.get(item["links"]["evidence"])
    assert via_link.status_code == 200, via_link.text[:300]
    via_species = client.get("/api/platform/species/101/dossier")
    assert via_species.status_code == 200

    linked, canonical = via_link.json(), via_species.json()

    def timeless(value: Any) -> Any:  # the two responses differ only by their retrieval clocks
        if isinstance(value, dict):
            return {k: timeless(v) for k, v in value.items() if k != "retrieved_at"}
        if isinstance(value, list):
            return [timeless(v) for v in value]
        return value

    for key in ("identity", "living_media", "knowledge_graph", "provenance", "related_species", "matrix_url"):
        assert timeless(linked[key]) == timeless(canonical[key]), key
    assert linked["identity"]["taxon_id"] == item["taxon_id"] == "101"
    taxonomy_anchor = next(a for a in item["provenance"] if a["kind"] == "taxonomy")
    assert [r["record_id"] for r in linked["provenance"] if r["source_id"] == taxonomy_anchor["source"]] == ["101"]
    assert client.get("/api/platform/homepage/species/999/evidence").status_code == 404


# -- a Field Journal photo keeps its provenance through attach, list and reload -------------


def test_a_field_journal_photo_keeps_its_provenance_across_attach_list_and_reload():
    store = observation_service.memory_store()
    service = FieldObservationService(store)
    observation, _ = service.create(
        "observer-1",
        FieldObservationCreate(
            observed_at=datetime(2026, 8, 2, 9, 0, tzinfo=timezone.utc),
            note="Two plants in flower; photographed the pollinator.",
            taxon_hint="Phalaenopsis amabilis",
            client_draft_id="draft-42",
        ),
    )
    attach = PhotoAttachRequest(
        storage_key="field-photos/2026/08/obs-42/1.jpg",
        content_hash="a" * 64,
        photographer_subject="observer-1",
        captured_at=datetime(2026, 8, 2, 9, 5, tzinfo=timezone.utc),
        license="CC-BY-NC-4.0",
        provenance={"device": "phone camera", "edited": False},
    )
    photo = service.attach_photo(observation.id, attach)
    listed = FieldObservationService(store).list_photos(observation.id)  # a fresh service over the same store
    assert [p.model_dump() for p in listed] == [photo.model_dump()]
    assert (photo.content_hash, photo.license, photo.photographer_subject) == ("a" * 64, "CC-BY-NC-4.0", "observer-1")
    assert photo.storage_key == "field-photos/2026/08/obs-42/1.jpg"
    reloaded = FieldObservationService(store).get(observation.id)
    assert reloaded.photo_count == 1
    assert reloaded.taxon_hint == "Phalaenopsis amabilis"  # attaching evidence never changes the observer's claim
    assert reloaded.scientific_status == "observer_report"
