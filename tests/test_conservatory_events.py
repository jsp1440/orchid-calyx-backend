"""What happened to a plant, and when anybody wrote it down.

Three properties carry the weight:

  two clocks       a grower noticing on Sunday that a plant spiked last week
                   is recording one fact about biology and one about
                   bookkeeping. Storing one timestamp destroys the other.

  append-only      a correction is a new event naming the one it corrects, so
                   both the error and the repair survive. Editing in place
                   would rewrite history a grower may already have reasoned
                   from, with nothing marking that it happened.

  not evidence     everything here is what a grower said about their own
                   plant. Valuable, and not a scientific measurement.
"""

from pathlib import Path

import pytest

from runtime.conservatory_events import ConservatoryEventStore, PlantEventError

LAST_WEEK = "2026-08-16T09:00:00+00:00"
YESTERDAY = "2026-08-22T09:00:00+00:00"


def _store(tmp_path: Path) -> ConservatoryEventStore:
    return ConservatoryEventStore(tmp_path)


class TestTwoClocks:
    def test_when_it_happened_is_not_when_it_was_written_down(self, tmp_path: Path):
        event = _store(tmp_path).record(
            plant_id="p1", kind="spike_observed", occurred_at=LAST_WEEK
        )
        assert event["occurred_at"] == LAST_WEEK
        # recorded_at is stamped now, not copied from occurred_at.
        assert event["recorded_at"] != LAST_WEEK
        assert event["recorded_at"] > LAST_WEEK

    def test_the_ledger_is_ordered_by_when_things_happened(self, tmp_path: Path):
        # The timeline a grower reasons over is the plant's, not the typist's.
        store = _store(tmp_path)
        store.record(plant_id="p1", kind="watered", occurred_at=YESTERDAY)
        store.record(plant_id="p1", kind="spike_observed", occurred_at=LAST_WEEK)
        assert [row["occurred_at"] for row in store.events_for("p1")] == [
            LAST_WEEK,
            YESTERDAY,
        ]

    def test_entry_order_is_still_recoverable(self, tmp_path: Path):
        store = _store(tmp_path)
        late_entry = store.record(
            plant_id="p1", kind="spike_observed", occurred_at=LAST_WEEK
        )
        assert late_entry["recorded_at"] is not None

    def test_an_event_without_an_occurrence_time_is_refused(self, tmp_path: Path):
        with pytest.raises(PlantEventError, match="OCCURRED_AT_REQUIRED"):
            _store(tmp_path).record(plant_id="p1", kind="watered", occurred_at="")


class TestCorrectionsAreAppended:
    def test_a_correction_supersedes_without_deleting(self, tmp_path: Path):
        store = _store(tmp_path)
        wrong = store.record(
            plant_id="p1", kind="flowering_observed", occurred_at=LAST_WEEK
        )
        fix = store.record(
            plant_id="p1",
            kind="correction",
            occurred_at=YESTERDAY,
            supersedes_id=wrong["id"],
            note="It was a new leaf, not a flower",
        )
        everything = store.events_for("p1")
        assert len(everything) == 2
        superseded = next(row for row in everything if row["id"] == wrong["id"])
        assert superseded["superseded_by_id"] == fix["id"]

    def test_the_original_stays_readable(self, tmp_path: Path):
        # "I thought it flowered in March and I was wrong" is itself
        # information about the collection.
        store = _store(tmp_path)
        wrong = store.record(
            plant_id="p1", kind="flowering_observed", occurred_at=LAST_WEEK
        )
        store.record(
            plant_id="p1",
            kind="correction",
            occurred_at=YESTERDAY,
            supersedes_id=wrong["id"],
        )
        timeline = store.timeline("p1")
        assert any(row["id"] == wrong["id"] for row in timeline["corrected"])
        assert not any(row["id"] == wrong["id"] for row in timeline["standing"])

    def test_a_correction_must_say_what_it_corrects(self, tmp_path: Path):
        # Otherwise it is just another claim, and the contradiction it creates
        # cannot be resolved.
        with pytest.raises(PlantEventError, match="CORRECTION_REQUIRES_A_TARGET"):
            _store(tmp_path).record(
                plant_id="p1", kind="correction", occurred_at=YESTERDAY
            )

    def test_correcting_something_that_does_not_exist_is_refused(self, tmp_path: Path):
        with pytest.raises(PlantEventError, match="SUPERSEDED_EVENT_NOT_FOUND"):
            _store(tmp_path).record(
                plant_id="p1",
                kind="correction",
                occurred_at=YESTERDAY,
                supersedes_id="nope",
            )

    def test_a_correction_cannot_reach_into_another_plants_record(self, tmp_path: Path):
        # Moving a fact between plants with nothing marking that it happened.
        store = _store(tmp_path)
        theirs = store.record(plant_id="p2", kind="watered", occurred_at=LAST_WEEK)
        with pytest.raises(
            PlantEventError, match="SUPERSEDED_EVENT_BELONGS_TO_ANOTHER_PLANT"
        ):
            store.record(
                plant_id="p1",
                kind="correction",
                occurred_at=YESTERDAY,
                supersedes_id=theirs["id"],
            )

    def test_an_event_cannot_be_superseded_twice(self, tmp_path: Path):
        # Two corrections of one fact leave no way to say which stands.
        store = _store(tmp_path)
        original = store.record(plant_id="p1", kind="watered", occurred_at=LAST_WEEK)
        store.record(
            plant_id="p1",
            kind="correction",
            occurred_at=YESTERDAY,
            supersedes_id=original["id"],
        )
        with pytest.raises(PlantEventError, match="EVENT_ALREADY_SUPERSEDED"):
            store.record(
                plant_id="p1",
                kind="correction",
                occurred_at=YESTERDAY,
                supersedes_id=original["id"],
            )

    def test_superseded_events_can_be_excluded_when_asked_for(self, tmp_path: Path):
        store = _store(tmp_path)
        wrong = store.record(
            plant_id="p1", kind="flowering_observed", occurred_at=LAST_WEEK
        )
        store.record(
            plant_id="p1",
            kind="correction",
            occurred_at=YESTERDAY,
            supersedes_id=wrong["id"],
        )
        standing = store.events_for("p1", include_superseded=False)
        assert all(row["superseded_by_id"] is None for row in standing)


class TestWhoSaidIt:
    def test_the_recorder_is_kept_on_every_event(self, tmp_path: Path):
        event = _store(tmp_path).record(
            plant_id="p1",
            kind="repotted",
            occurred_at=LAST_WEEK,
            recorder_kind="grower",
            recorder_ref="owner",
        )
        assert event["recorder_kind"] == "grower"
        assert event["recorder_ref"] == "owner"

    def test_an_import_is_distinguishable_from_a_person(self, tmp_path: Path):
        # A consumer weighing reliability needs to tell them apart.
        event = _store(tmp_path).record(
            plant_id="p1",
            kind="watered",
            occurred_at=LAST_WEEK,
            recorder_kind="import",
            recorder_ref="legacy-spreadsheet-2019",
        )
        assert event["recorder_kind"] == "import"

    def test_an_unrecognised_recorder_is_refused(self, tmp_path: Path):
        with pytest.raises(PlantEventError, match="RECORDER_KIND_UNRECOGNISED"):
            _store(tmp_path).record(
                plant_id="p1",
                kind="watered",
                occurred_at=LAST_WEEK,
                recorder_kind="anonymous",
            )


class TestObservationsAreNotEvidence:
    def test_the_timeline_says_what_this_is(self, tmp_path: Path):
        # A consumer must not be able to pick these up as scientific findings
        # without noticing what they are.
        store = _store(tmp_path)
        store.record(plant_id="p1", kind="flowering_observed", occurred_at=LAST_WEEK)
        timeline = store.timeline("p1")
        assert timeline["is_scientific_evidence"] is False
        assert timeline["provenance"] == "grower_recorded_collection_events"

    def test_an_empty_ledger_is_distinguishable_from_a_fully_corrected_one(
        self, tmp_path: Path
    ):
        store = _store(tmp_path)
        assert store.timeline("never-touched")["event_count"] == 0

        wrong = store.record(
            plant_id="p1", kind="flowering_observed", occurred_at=LAST_WEEK
        )
        store.record(
            plant_id="p1",
            kind="correction",
            occurred_at=YESTERDAY,
            supersedes_id=wrong["id"],
        )
        timeline = store.timeline("p1")
        # Nothing standing from the original claim, but the ledger is not empty.
        assert timeline["event_count"] == 2


class TestVocabularyAndScope:
    def test_an_unrecognised_kind_is_refused(self, tmp_path: Path):
        # A generic note pile is what this ledger exists to avoid.
        with pytest.raises(PlantEventError, match="EVENT_KIND_UNRECOGNISED"):
            _store(tmp_path).record(
                plant_id="p1", kind="thought_about_it", occurred_at=LAST_WEEK
            )

    def test_events_are_scoped_to_their_plant(self, tmp_path: Path):
        store = _store(tmp_path)
        store.record(plant_id="p1", kind="watered", occurred_at=LAST_WEEK)
        assert store.events_for("p2") == []

    def test_structured_detail_is_kept_out_of_prose(self, tmp_path: Path):
        event = _store(tmp_path).record(
            plant_id="p1",
            kind="repotted",
            occurred_at=LAST_WEEK,
            detail={"medium": "sphagnum", "pot_size_cm": 12},
        )
        assert event["detail"]["medium"] == "sphagnum"

    def test_the_ledger_survives_an_out_of_order_store_file(self, tmp_path: Path):
        import json

        store = _store(tmp_path)
        store.record(plant_id="p1", kind="spike_observed", occurred_at=LAST_WEEK)
        store.record(plant_id="p1", kind="watered", occurred_at=YESTERDAY)
        rows = json.loads((tmp_path / "plant_events.json").read_text(encoding="utf-8"))
        (tmp_path / "plant_events.json").write_text(
            json.dumps(list(reversed(rows))), encoding="utf-8"
        )

        reopened = ConservatoryEventStore(tmp_path)
        assert [row["occurred_at"] for row in reopened.events_for("p1")] == [
            LAST_WEEK,
            YESTERDAY,
        ]


class TestThroughTheApi:
    @staticmethod
    def _client(tmp_path: Path, *, deny: bool = False):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_store import ConservatoryStore

        plants = ConservatoryStore(tmp_path)

        def refuse() -> None:
            raise HTTPException(status_code=401, detail="owner required")

        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: plants,
                require_owner=refuse if deny else (lambda: {"sub": "owner"}),
                get_events=lambda: ConservatoryEventStore(tmp_path),
            )
        )
        return TestClient(app), plants

    def test_record_and_read_back_a_plants_timeline(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        plant = plants.create(display_name="Cattleya skinneri")

        created = client.post(
            f"/api/conservatory/plants/{plant['id']}/events",
            json={
                "kind": "repotted",
                "occurred_at": LAST_WEEK,
                "detail": {"medium": "bark"},
                "note": "Roots were tight",
            },
        )
        assert created.status_code == 201

        timeline = client.get(f"/api/conservatory/plants/{plant['id']}/events").json()
        assert timeline["event_count"] == 1
        assert timeline["standing"][0]["kind"] == "repotted"
        # The timeline says what it is, so nothing can pick it up as a finding.
        assert timeline["is_scientific_evidence"] is False

    def test_a_correction_through_the_api_keeps_both_records(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        plant = plants.create(display_name="Dendrobium")
        wrong = client.post(
            f"/api/conservatory/plants/{plant['id']}/events",
            json={"kind": "flowering_observed", "occurred_at": LAST_WEEK},
        ).json()
        client.post(
            f"/api/conservatory/plants/{plant['id']}/events",
            json={
                "kind": "correction",
                "occurred_at": YESTERDAY,
                "supersedes_id": wrong["id"],
            },
        )
        timeline = client.get(f"/api/conservatory/plants/{plant['id']}/events").json()
        assert timeline["event_count"] == 2
        assert len(timeline["corrected"]) == 1
        assert timeline["corrected"][0]["id"] == wrong["id"]

    def test_correcting_an_already_corrected_event_is_a_conflict(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        plant = plants.create(display_name="Phalaenopsis")
        original = client.post(
            f"/api/conservatory/plants/{plant['id']}/events",
            json={"kind": "watered", "occurred_at": LAST_WEEK},
        ).json()
        body = {
            "kind": "correction",
            "occurred_at": YESTERDAY,
            "supersedes_id": original["id"],
        }
        client.post(f"/api/conservatory/plants/{plant['id']}/events", json=body)
        again = client.post(f"/api/conservatory/plants/{plant['id']}/events", json=body)
        assert again.status_code == 409
        assert again.json()["detail"]["code"] == "EVENT_ALREADY_SUPERSEDED"

    def test_events_cannot_be_attached_to_a_plant_that_does_not_exist(
        self, tmp_path: Path
    ):
        client, _ = self._client(tmp_path)
        response = client.post(
            "/api/conservatory/plants/no-such-plant/events",
            json={"kind": "watered", "occurred_at": LAST_WEEK},
        )
        assert response.status_code == 404

    def test_event_routes_require_an_owner(self, tmp_path: Path):
        client, _ = self._client(tmp_path, deny=True)
        assert client.get("/api/conservatory/plants/x/events").status_code == 401
        assert (
            client.post(
                "/api/conservatory/plants/x/events",
                json={"kind": "watered", "occurred_at": LAST_WEEK},
            ).status_code
            == 401
        )
