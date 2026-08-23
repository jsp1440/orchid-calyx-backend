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
        location = _store(tmp_path).create_location(
            name="Under the stairs", kind="custom"
        )
        assert location["kind"] == "custom"

    def test_the_same_bench_cannot_become_three_through_capitalisation(
        self, tmp_path: Path
    ):
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
            name="Shade house",
            kind="shade_house",
            described_conditions="Bright shade, cool nights",
        )
        assert location["described_by"] == "grower_description"
        assert location["described_conditions"] == "Bright shade, cool nights"

    def test_an_absent_description_is_absent_not_empty(self, tmp_path: Path):
        assert _bench(_store(tmp_path))["described_conditions"] is None


class TestPlacementIsAHistory:
    def test_records_an_initial_placement(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store)
        event = store.record_placement(
            plant_id="p1", location_id=bench["id"], reason="initial"
        )
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
        benches = [
            store.create_location(name=f"Bench {i}", kind="greenhouse")
            for i in range(4)
        ]
        for bench in benches:
            store.record_placement(
                plant_id="p1", location_id=bench["id"], reason="move"
            )
        assert len(store.placement_history("p1")) == 4

    def test_a_correction_is_not_a_move(self, tmp_path: Path):
        # Both change where the record says the plant is; only one means the
        # plant physically went somewhere.
        store = _store(tmp_path)
        wrong = store.create_location(name="Wrong bench", kind="greenhouse")
        right = store.create_location(name="Right bench", kind="greenhouse")
        store.record_placement(plant_id="p1", location_id=wrong["id"], reason="initial")
        store.record_placement(
            plant_id="p1", location_id=right["id"], reason="correction"
        )

        history = store.placement_history("p1")
        assert history[-1]["reason"] == "correction"
        assert [row["reason"] for row in history] == ["initial", "correction"]

    def test_rejects_an_unrecognised_reason(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store)
        with pytest.raises(LocationError, match="PLACEMENT_REASON_UNRECOGNISED"):
            store.record_placement(
                plant_id="p1", location_id=bench["id"], reason="teleported"
            )

    def test_a_plant_cannot_be_placed_somewhere_that_does_not_exist(
        self, tmp_path: Path
    ):
        # A history pointing at nothing reads as data loss later.
        with pytest.raises(LocationError, match="LOCATION_NOT_FOUND"):
            _store(tmp_path).record_placement(
                plant_id="p1", location_id="no-such-place"
            )

    def test_never_placed_and_removed_are_different_answers(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store)
        assert store.current_placement("never-placed") is None
        assert store.placement_history("never-placed") == []

        store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")
        store.record_placement(
            plant_id="p1", location_id=None, reason="removed", note="Sold"
        )
        # Not anywhere now — but it was, and that record survives.
        assert store.current_placement("p1") is None
        assert len(store.placement_history("p1")) == 2

    def test_removal_is_the_only_reason_allowed_without_a_location(
        self, tmp_path: Path
    ):
        with pytest.raises(LocationError, match="LOCATION_REQUIRED"):
            _store(tmp_path).record_placement(
                plant_id="p1", location_id=None, reason="move"
            )

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

    def test_a_plant_removed_from_a_named_bench_no_longer_occupies_it(
        self, tmp_path: Path
    ):
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
            json={
                "name": "Warm bench",
                "kind": "greenhouse",
                "described_conditions": "Warm days",
            },
        )
        assert warm.status_code == 201
        cool = client.post(
            "/api/conservatory/locations",
            json={"name": "Cool bench", "kind": "greenhouse"},
        )
        plant = plants.create(display_name="Cattleya skinneri")

        placed = client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": warm.json()["id"], "reason": "initial"},
        )
        assert placed.status_code == 201
        client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={
                "location_id": cool.json()["id"],
                "reason": "move",
                "note": "Not flowering",
            },
        )

        placement = client.get(
            f"/api/conservatory/plants/{plant['id']}/placement"
        ).json()
        assert placement["current"]["location_id"] == cool.json()["id"]
        assert len(placement["history"]) == 2
        # The earlier bench survives the move.
        assert placement["history"][0]["location_id"] == warm.json()["id"]

    def test_a_growers_description_arrives_labelled_as_a_description(
        self, tmp_path: Path
    ):
        client, _ = self._client(tmp_path)
        created = client.post(
            "/api/conservatory/locations",
            json={
                "name": "Shade house",
                "kind": "shade_house",
                "described_conditions": "Bright shade",
            },
        ).json()
        assert created["described_by"] == "grower_description"

    def test_placement_is_refused_for_a_plant_that_does_not_exist(self, tmp_path: Path):
        # Otherwise the log accumulates history for plants nobody owns.
        client, _ = self._client(tmp_path)
        location = client.post(
            "/api/conservatory/locations",
            json={"name": "A bench", "kind": "greenhouse"},
        ).json()
        response = client.post(
            "/api/conservatory/plants/no-such-plant/placement",
            json={"location_id": location["id"]},
        )
        assert response.status_code == 404

    def test_a_duplicate_bench_name_is_a_conflict_not_a_malformed_request(
        self, tmp_path: Path
    ):
        # "You already have this bench" and "that is not a kind of place" are
        # different problems and a grower fixes them differently.
        client, _ = self._client(tmp_path)
        client.post(
            "/api/conservatory/locations",
            json={"name": "Bench one", "kind": "greenhouse"},
        )
        duplicate = client.post(
            "/api/conservatory/locations",
            json={"name": "bench one", "kind": "greenhouse"},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "LOCATION_NAME_ALREADY_USED"

        bad_kind = client.post(
            "/api/conservatory/locations",
            json={"name": "Somewhere else", "kind": "orbital"},
        )
        assert bad_kind.status_code == 422
        assert bad_kind.json()["detail"]["code"] == "LOCATION_KIND_UNRECOGNISED"

    def test_occupancy_lists_every_location_including_empty_ones(self, tmp_path: Path):
        client, plants = self._client(tmp_path)
        used = client.post(
            "/api/conservatory/locations",
            json={"name": "Used bench", "kind": "greenhouse"},
        ).json()
        empty = client.post(
            "/api/conservatory/locations",
            json={"name": "Empty bench", "kind": "greenhouse"},
        ).json()
        plant = plants.create(display_name="Dendrobium")
        client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": used["id"], "reason": "initial"},
        )
        occupancy = client.get("/api/conservatory/locations/occupancy").json()[
            "occupancy"
        ]
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
        assert (
            client.post(
                "/api/conservatory/locations",
                json={"name": "X bench", "kind": "greenhouse"},
            ).status_code
            == 401
        )


class TestARenameIsNotAMove:
    """Four things change what a grower sees beside a plant, and only one of
    them is husbandry:

      the plant moved            it physically went somewhere
      the record was corrected   it never went anywhere; the record was wrong
      the location was renamed   nothing about any plant changed at all
      the location was retired   the place is gone; the history is not

    Collapsing any of these into "move" invents husbandry that later reads as a
    cause of whatever the plant did next.
    """

    def test_renaming_keeps_the_identity_so_history_still_points_here(
        self, tmp_path: Path
    ):
        store = _store(tmp_path)
        bench = _bench(store, "Bench two")
        store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")

        renamed = store.rename_location(bench["id"], name="The cool bench")
        assert renamed["id"] == bench["id"]
        assert renamed["name"] == "The cool bench"
        # The placement recorded before the rename still resolves here.
        assert store.current_placement("p1")["location_id"] == bench["id"]

    def test_renaming_appends_nothing_to_any_plants_placement_history(
        self, tmp_path: Path
    ):
        # The invariant this class exists for.
        store = _store(tmp_path)
        bench = _bench(store, "Bench two")
        store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")
        before = store.placement_history("p1")

        store.rename_location(bench["id"], name="The cool bench")

        assert store.placement_history("p1") == before

    def test_a_rename_is_recorded_in_the_locations_own_history(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store, "Bench two")
        store.rename_location(bench["id"], name="The cool bench", note="Clearer name")

        history = store.location_history(bench["id"])
        assert [row["change"] for row in history] == ["created", "renamed"]
        assert history[-1]["previous_name"] == "Bench two"
        assert history[-1]["new_name"] == "The cool bench"

    def test_renaming_to_a_name_another_location_holds_is_refused(self, tmp_path: Path):
        store = _store(tmp_path)
        _bench(store, "Warm bench")
        cool = store.create_location(name="Cool bench", kind="greenhouse_bench")
        with pytest.raises(LocationError, match="LOCATION_NAME_ALREADY_USED"):
            store.rename_location(cool["id"], name="warm bench")

    def test_renaming_a_location_to_its_own_name_records_nothing(self, tmp_path: Path):
        # A change that did not happen must not appear in the log.
        store = _store(tmp_path)
        bench = _bench(store, "Bench two")
        store.rename_location(bench["id"], name="Bench two")
        assert [row["change"] for row in store.location_history(bench["id"])] == [
            "created"
        ]

    def test_renaming_something_that_does_not_exist_is_refused(self, tmp_path: Path):
        with pytest.raises(LocationError, match="LOCATION_NOT_FOUND"):
            _store(tmp_path).rename_location("no-such-place", name="Anything")


class TestRetirementKeepsTheHistory:
    def test_a_retired_location_is_not_deleted(self, tmp_path: Path):
        # Deleting it would leave placement history pointing at nothing, which
        # a later reader cannot tell apart from data loss.
        store = _store(tmp_path)
        bench = _bench(store, "Old bench")
        store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")
        store.record_placement(plant_id="p1", location_id=None, reason="removed")

        retired = store.retire_location(bench["id"], reason="Dismantled")
        assert retired["retired_at"] is not None
        assert store.get_location(bench["id"]) is not None
        # The plant really was there, and still says so.
        assert store.placement_history("p1")[0]["location_id"] == bench["id"]

    def test_an_occupied_location_cannot_be_retired(self, tmp_path: Path):
        # Retiring it would strand the plant somewhere that accepts nothing,
        # and nothing would say where it actually is.
        store = _store(tmp_path)
        bench = _bench(store, "Busy bench")
        store.record_placement(plant_id="p1", location_id=bench["id"], reason="initial")
        with pytest.raises(LocationError, match="LOCATION_STILL_OCCUPIED"):
            store.retire_location(bench["id"])

    def test_a_retired_location_accepts_no_new_plants(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store, "Gone bench")
        store.retire_location(bench["id"])
        with pytest.raises(LocationError, match="LOCATION_RETIRED"):
            store.record_placement(
                plant_id="p1", location_id=bench["id"], reason="move"
            )

    def test_a_correction_may_still_name_a_retired_location(self, tmp_path: Path):
        # The plant really was on that bench before it was dismantled.
        # Refusing to record that would force a false history.
        store = _store(tmp_path)
        bench = _bench(store, "Gone bench")
        store.retire_location(bench["id"])
        event = store.record_placement(
            plant_id="p1",
            location_id=bench["id"],
            reason="correction",
            note="Was here all along",
        )
        assert event["reason"] == "correction"

    def test_retiring_twice_is_refused(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store, "Once bench")
        store.retire_location(bench["id"])
        with pytest.raises(LocationError, match="LOCATION_ALREADY_RETIRED"):
            store.retire_location(bench["id"])

    def test_retirement_is_recorded_in_the_locations_history(self, tmp_path: Path):
        store = _store(tmp_path)
        bench = _bench(store, "Old bench")
        store.retire_location(bench["id"], reason="Dismantled")
        assert [row["change"] for row in store.location_history(bench["id"])] == [
            "created",
            "retired",
        ]


class TestRealCultivationPositions:
    def test_a_bench_is_its_own_kind_of_place(self, tmp_path: Path):
        # Two benches in one greenhouse can differ more than two greenhouses
        # do, so recording only the building loses what a grower manages.
        store = _store(tmp_path)
        for kind in ["greenhouse_bench", "lath_house", "shelf", "zone"]:
            location = store.create_location(name=f"A {kind}", kind=kind)
            assert location["kind"] == kind


class TestLifecycleThroughTheApi:
    def test_rename_and_retire_round_trip(self, tmp_path: Path):
        client, plants = TestThroughTheApi._client(tmp_path)
        bench = client.post(
            "/api/conservatory/locations",
            json={"name": "Bench two", "kind": "greenhouse_bench"},
        ).json()
        plant = plants.create(display_name="Cattleya")
        client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": bench["id"], "reason": "initial"},
        )

        renamed = client.post(
            f"/api/conservatory/locations/{bench['id']}/rename",
            json={"name": "The cool bench"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["id"] == bench["id"]

        # The rename left the plant exactly where it was.
        placement = client.get(
            f"/api/conservatory/plants/{plant['id']}/placement"
        ).json()
        assert len(placement["history"]) == 1
        assert placement["current"]["location_id"] == bench["id"]

        # Occupied, so retirement is refused rather than stranding the plant.
        occupied = client.post(
            f"/api/conservatory/locations/{bench['id']}/retire", json={}
        )
        assert occupied.status_code == 409
        assert occupied.json()["detail"]["code"] == "LOCATION_STILL_OCCUPIED"

        client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": None, "reason": "removed"},
        )
        retired = client.post(
            f"/api/conservatory/locations/{bench['id']}/retire",
            json={"reason": "Dismantled"},
        )
        assert retired.status_code == 200
        assert retired.json()["retired_at"] is not None

    def test_the_location_history_reads_back_the_lifecycle(self, tmp_path: Path):
        client, _ = TestThroughTheApi._client(tmp_path)
        bench = client.post(
            "/api/conservatory/locations", json={"name": "Bench three", "kind": "shelf"}
        ).json()
        client.post(
            f"/api/conservatory/locations/{bench['id']}/rename",
            json={"name": "Top shelf"},
        )
        client.post(f"/api/conservatory/locations/{bench['id']}/retire", json={})

        history = client.get(
            f"/api/conservatory/locations/{bench['id']}/history"
        ).json()["history"]
        assert [row["change"] for row in history] == ["created", "renamed", "retired"]

    def test_history_of_an_unknown_location_is_a_404(self, tmp_path: Path):
        client, _ = TestThroughTheApi._client(tmp_path)
        assert client.get("/api/conservatory/locations/nope/history").status_code == 404

    def test_lifecycle_routes_require_an_owner(self, tmp_path: Path):
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
        assert (
            client.post(
                "/api/conservatory/locations/x/rename", json={"name": "Yy"}
            ).status_code
            == 401
        )
        assert (
            client.post("/api/conservatory/locations/x/retire", json={}).status_code
            == 401
        )
        assert client.get("/api/conservatory/locations/x/history").status_code == 401
