"""Growing locations, and the history of where a plant has actually been.

The two properties worth defending:

  history is append-only     moving a plant is the most informative husbandry
                             act a grower performs. Overwriting a location
                             field destroys the record that explains what
                             happened next.

  a correction is not a move a plant wrongly entered on the wrong bench never
                             physically went anywhere. Recording that as a move
                             invents husbandry history, and a later reader
                             cannot tell invented history from real history.
"""

from pathlib import Path

import pytest

from runtime.conservatory_locations import ConservatoryLocationStore, LocationError


def _store(tmp_path: Path) -> ConservatoryLocationStore:
    return ConservatoryLocationStore(tmp_path)


def _bench(store: ConservatoryLocationStore, name: str = "Greenhouse bench 2") -> dict:
    return store.create_location(name=name, kind="greenhouse")


class TestALocationIsAThingNotASpelling:
    def test_creates_a_location_with_a_recognised_kind(self, tmp_path: Path):
        location = _bench(_store(tmp_path))
        assert location["kind"] == "greenhouse"
        assert location["name"] == "Greenhouse bench 2"

    def test_rejects_an_unrecognised_kind(self, tmp_path: Path):
        with pytest.raises(LocationError, match="LOCATION_KIND_UNRECOGNISED"):
            _store(tmp_path).create_location(name="Somewhere", kind="orbital_station")

    def test_allows_a_custom_kind_for_a_real_collection(self, tmp_path: Path):
        # The vocabulary must not block a grower whose setup we did not foresee.
        location = _store(tmp_path).create_location(name="Under the stairs", kind="custom")
        assert location["kind"] == "custom"

    def test_the_same_bench_cannot_become_three_through_capitalisation(self, tmp_path: Path):
        # Three spellings of one bench make every cross-location comparison
        # silently wrong, and nothing would report it.
        store = _store(tmp_path)
        store.create_location(name="Greenhouse bench 2", kind="greenhouse")
        for duplicate in ["greenhouse bench 2", "  GREENHOUSE BENCH 2  "]:
            with pytest.raises(LocationError, match="LOCATION_NAME_ALREADY_USED"):
                store.create_location(name=duplicate, kind="greenhouse")

    def test_rejects_a_name_too_short_to_mean_anything(self, tmp_path: Path):
        with pytest.raises(LocationError, match="LOCATION_NAME_TOO_SHORT"):
            _store(tmp_path).create_location(name="x", kind="greenhouse")


class TestDescribedConditionsAreNotMeasurements:
    def test_a_growers_description_is_labelled_as_one(self, tmp_path: Path):
        # "Bright shade, cool at night" is an assessment. If it can later be
        # read as though a sensor produced it, every comparison built on it
        # inherits a precision nobody ever measured.
        location = _store(tmp_path).create_location(
            name="Shade house", kind="shade_house", described_conditions="Bright shade, cool nights"
        )
        assert location["described_by"] == "grower_description"
        assert location["described_conditions"] == "Bright shade, cool nights"

    def test_an_absent_description_is_absent_not_empty(self, tmp_path: Path):
        assert _bench(_store(tmp_path))["described_conditions"] is None


class TestPlacementIsAHistory:
    def test_records_an_initial_placement(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store)
        event = store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")
        assert event["reason"] == "initial"
        assert store.current_placement("p1")["location_id"] == bench["id"]

    def test_moving_preserves_where_the_plant_was_before(self, tmp_path: Path):
        # The whole point. "It spiked six weeks after moving to the cooler
        # bench" is only recoverable if the earlier placement still exists.
        store = _store(tmp_path)
        warm = store.create_location(name="Warm bench", kind="greenhouse")
        cool = store.create_location(name="Cool bench", kind="greenhouse")
        store.record_placement(plant_id="p1", location_id=warm["id"], reason="initial")
        store.record_placement(plant_id="p1", location_id=cool["id"], reason="move")

        history = store.placement_history("p1")
        assert [row["location_id"] for row in history] == [warm["id"], cool["id"]]
        assert store.current_placement("p1")["location_id"] == cool["id"]

    def test_history_is_append_only_across_many_moves(self, tmp_path: Path):
        store = _store(tmp_path)
        benches = [store.create_location(name=f"Bench {i}", kind="greenhouse") for i in range(4)]
        for bench in benches:
            store.record_placement(plant_id="p1", location_id=bench["id"], reason="move")
        assert len(store.placement_history("p1")) == 4

    def test_a_correction_is_not_a_move(self, tmp_path: Path):
        # Both change where the record says the plant is; only one means the
        # plant physically went somewhere.
        store = _store(tmp_path)
        wrong = store.create_location(name="Wrong bench", kind="greenhouse")
        right = store.create_location(name="Right bench", kind="greenhouse")
        store.record_placement(plant_id="p1", location_id=wrong["id"], reason="initial")
        store.record_placement(plant_id="p1", location_id=right["id"], reason="correction")

        history = store.placement_history("p1")
        assert history[-1]["reason"] == "correction"
        assert [row["reason"] for row in history] == ["initial", "correction"]

    def test_rejects_an_unrecognised_reason(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store)
        with pytest.raises(LocationError, match="PLACEMENT_REASON_UNRECOGNISED"):
            store.record_placement(plant_id="p1", location_id=bench["id"], reason="teleported")

    def test_a_plant_cannot_be_placed_somewhere_that_does_not_exist(self, tmp_path: Path):
        # A history pointing at nothing reads as data loss later.
        with pytest.raises(LocationError, match="LOCATION_NOT_FOUND"):
            _store(tmp_path).record_placement(plant_id="p1", location_id="no-such-place")

    def test_never_placed_and_removed_are_different_answers(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store)
        assert store.current_placement("never-placed") is None
        assert store.placement_history("never-placed") == []

        store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")
        store.record_placement(plant_id="p1", location_id=None, reason="removed", note="Sold")
        # Not anywhere now — but it was, and that record survives.
        assert store.current_placement("p1") is None
        assert len(store.placement_history("p1")) == 2

    def test_removal_is_the_only_reason_allowed_without_a_location(self, tmp_path: Path):
        with pytest.raises(LocationError, match="LOCATION_REQUIRED"):
            _store(tmp_path).record_placement(plant_id="p1", location_id=None, reason="move")

    def test_current_placement_is_derived_not_stored(self, tmp_path: Path):
        # Re-reading from a fresh store instance must give the same answer:
        # nothing is cached beside the log that could disagree with it.
        store = _store(tmp_path)
        first = store.create_location(name="First", kind="greenhouse")
        second = store.create_location(name="Second", kind="windowsill")
        store.record_placement(plant_id="p1", location_id=first["id"], reason="initial")
        store.record_placement(plant_id="p1", location_id=second["id"], reason="move")

        reopened = ConservatoryLocationStore(tmp_path)
        assert reopened.current_placement("p1")["location_id"] == second["id"]
        assert len(reopened.placement_history("p1")) == 2


class TestHistorySurvivesTheStoreFile:
    def test_history_is_ordered_by_time_even_if_the_file_is_not(self, tmp_path: Path):
        """The log is read back from JSON that a restore, a merge or a hand
        edit can leave out of order. Insertion order is not a guarantee once
        the data has left this process, and a history read back in the wrong
        order reverses which move came first."""
        import json

        store = _store(tmp_path)
        first = store.create_location(name="First bench", kind="greenhouse")
        second = store.create_location(name="Second bench", kind="greenhouse")
        store.record_placement(plant_id="p1", location_id=first["id"], reason="initial")
        store.record_placement(plant_id="p1", location_id=second["id"], reason="move")

        payload = json.loads((tmp_path / "locations.json").read_text(encoding="utf-8"))
        payload["placements"] = list(reversed(payload["placements"]))
        (tmp_path / "locations.json").write_text(json.dumps(payload), encoding="utf-8")

        reopened = ConservatoryLocationStore(tmp_path)
        history = reopened.placement_history("p1")
        assert [row["location_id"] for row in history] == [first["id"], second["id"]]
        assert reopened.current_placement("p1")["location_id"] == second["id"]


class TestOccupancy:
    def test_reports_which_plants_are_where_now(self, tmp_path: Path):
        store = _store(tmp_path)
        warm = store.create_location(name="Warm", kind="greenhouse")
        cool = store.create_location(name="Cool", kind="greenhouse")
        store.record_placement(plant_id="p1", location_id=warm["id"], reason="initial")
        store.record_placement(plant_id="p2", location_id=warm["id"], reason="initial")
        store.record_placement(plant_id="p2", location_id=cool["id"], reason="move")

        occupancy = store.occupancy()
        assert occupancy[warm["id"]] == ["p1"]
        assert occupancy[cool["id"]] == ["p2"]

    def test_a_moved_plant_is_not_counted_in_both_places(self, tmp_path: Path):
        store = _store(tmp_path)
        a = store.create_location(name="A place", kind="greenhouse")
        b = store.create_location(name="B place", kind="greenhouse")
        store.record_placement(plant_id="p1", location_id=a["id"], reason="initial")
        store.record_placement(plant_id="p1", location_id=b["id"], reason="move")
        occupancy = store.occupancy()
        assert occupancy[a["id"]] == []
        assert occupancy[b["id"]] == ["p1"]

    def test_an_empty_location_is_listed_as_empty_not_missing(self, tmp_path: Path):
        # A location nobody has used yet still exists, and a grower comparing
        # candidate locations needs to see it.
        store = _store(tmp_path)
        bench = _bench(store)
        assert store.occupancy() == {bench["id"]: []}

    def test_a_plant_removed_from_a_named_bench_no_longer_occupies_it(self, tmp_path: Path):
        """Removal may name the place the plant left, which is the natural way
        to record it: "taken off the warm bench". If occupancy only checks for
        a missing location, that plant keeps occupying a bench it is no longer
        on, and every count and comparison built on occupancy is wrong."""
        store = _store(tmp_path)
        bench = _bench(store)
        store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")
        store.record_placement(
            plant_id="p1", location_id=bench["id"], reason="removed", note="Died back"
        )
        assert store.occupancy()[bench["id"]] == []
        assert store.current_placement("p1") is None

    def test_a_removed_plant_occupies_nothing(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store)
        store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")
        store.record_placement(plant_id="p1", location_id=None, reason="removed")
        assert store.occupancy()[bench["id"]] == []


class TestThroughTheApi:
    """The store is only useful if a grower can reach it."""

    @staticmethod
    def _client(tmp_path: Path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_store import ConservatoryStore

        plants = ConservatoryStore(tmp_path)
        locations = ConservatoryLocationStore(tmp_path)
        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: plants,
                require_owner=lambda: {"sub": "owner"},
                get_locations=lambda: locations,
            )
        )
        return TestClient(app), plants

    def test_create_a_location_then_place_and_move_a_plant(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        warm = client.post(
            "/api/conservatory/locations",
            json={"name": "Warm bench", "kind": "greenhouse", "described_conditions": "Warm days"},
        )
        assert warm.status_code == 201
        cool = client.post("/api/conservatory/locations", json={"name": "Cool bench", "kind": "greenhouse"})
        plant = plants.create(display_name="Cattleya skinneri")

        placed = client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": warm.json()["id"], "reason": "initial"},
        )
        assert placed.status_code == 201
        client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": cool.json()["id"], "reason": "move", "note": "Not flowering"},
        )

        placement = client.get(f"/api/conservatory/plants/{plant['id']}/placement").json()
        assert placement["current"]["location_id"] == cool.json()["id"]
        assert len(placement["history"]) == 2
        # The earlier bench survives the move.
        assert placement["history"][0]["location_id"] == warm.json()["id"]

    def test_a_growers_description_arrives_labelled_as_a_description(self, tmp_path: Path):
        client, _ = self._client(tmp_path)
        created = client.post(
            "/api/conservatory/locations",
            json={"name": "Shade house", "kind": "shade_house", "described_conditions": "Bright shade"},
        ).json()
        assert created["described_by"] == "grower_description"

    def test_placement_is_refused_for_a_plant_that_does_not_exist(self, tmp_path: Path):
        # Otherwise the log accumulates history for plants nobody owns.
        client, _ = self._client(tmp_path)
        location = client.post(
            "/api/conservatory/locations", json={"name": "A bench", "kind": "greenhouse"}
        ).json()
        response = client.post(
            "/api/conservatory/plants/no-such-plant/placement",
            json={"location_id": location["id"]},
        )
        assert response.status_code == 404

    def test_a_duplicate_bench_name_is_a_conflict_not_a_malformed_request(self, tmp_path: Path):
        # "You already have this bench" and "that is not a kind of place" are
        # different problems and a grower fixes them differently.
        client, _ = self._client(tmp_path)
        client.post("/api/conservatory/locations", json={"name": "Bench one", "kind": "greenhouse"})
        duplicate = client.post(
            "/api/conservatory/locations", json={"name": "bench one", "kind": "greenhouse"}
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "LOCATION_NAME_ALREADY_USED"

        bad_kind = client.post(
            "/api/conservatory/locations", json={"name": "Somewhere else", "kind": "orbital"}
        )
        assert bad_kind.status_code == 422
        assert bad_kind.json()["detail"]["code"] == "LOCATION_KIND_UNRECOGNISED"

    def test_occupancy_lists_every_location_including_empty_ones(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        used = client.post("/api/conservatory/locations", json={"name": "Used bench", "kind": "greenhouse"}).json()
        empty = client.post("/api/conservatory/locations", json={"name": "Empty bench", "kind": "greenhouse"}).json()
        plant = plants.create(display_name="Dendrobium")
        client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": used["id"], "reason": "initial"},
        )
        occupancy = client.get("/api/conservatory/locations/occupancy").json()["occupancy"]
        assert occupancy[used["id"]] == [plant["id"]]
        assert occupancy[empty["id"]] == []

    def test_locations_require_an_owner(self, tmp_path: Path):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_store import ConservatoryStore

        def deny() -> None:
            raise HTTPException(status_code=401, detail="owner required")

        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: ConservatoryStore(tmp_path),
                require_owner=deny,
                get_locations=lambda: ConservatoryLocationStore(tmp_path),
            )
        )
        client = TestClient(app)
        assert client.get("/api/conservatory/locations").status_code == 401
        assert client.post("/api/conservatory/locations", json={"name": "X bench", "kind": "greenhouse"}).status_code == 401
