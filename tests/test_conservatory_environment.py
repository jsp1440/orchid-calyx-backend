"""Environmental context, and where each number came from.

A number describing a plant's environment is only as trustworthy as its
origin, and the four are not interchangeable: a device reported it, a person
read a dial, this system derived it, or nobody has said. These tests exist to
stop the weaker three ever being read as the strongest.
"""

from pathlib import Path

import pytest

from runtime.conservatory_environment import (
    MEASURABLE_VARIABLES,
    ConservatoryEnvironmentStore,
    EnvironmentError_,
)

AT = "2026-08-23T06:00:00+00:00"
LATER = "2026-08-23T18:00:00+00:00"


def _store(tmp_path: Path) -> ConservatoryEnvironmentStore:
    return ConservatoryEnvironmentStore(tmp_path)


class TestMeasuredMeansAnInstrumentSaidSo:
    def test_a_measured_reading_records_its_instrument(self, tmp_path: Path):
        reading = _store(tmp_path).record(
            location_id="loc-1", variable="temperature_c", value=18.4,
            origin="measured", instrument="SensorPush HT.w #A31", observed_at=AT,
        )
        assert reading["origin"] == "measured"
        assert reading["instrument"] == "SensorPush HT.w #A31"
        assert reading["unit"] == "degrees Celsius"

    def test_measured_without_an_instrument_is_refused_not_downgraded(self, tmp_path: Path):
        """Silently demoting it to `manual` would hide a caller bug while
        leaving the caller believing a sensor is attached. Without an
        instrument, "measured" is an assertion wearing a sensor's authority."""
        with pytest.raises(EnvironmentError_, match="MEASURED_REQUIRES_INSTRUMENT"):
            _store(tmp_path).record(
                location_id="loc-1", variable="temperature_c", value=18.4,
                origin="measured", observed_at=AT,
            )

    def test_measured_without_a_value_is_refused(self, tmp_path: Path):
        with pytest.raises(EnvironmentError_, match="MEASURED_REQUIRES_VALUE"):
            _store(tmp_path).record(
                location_id="loc-1", variable="temperature_c", value=None,
                origin="measured", instrument="Probe 1", observed_at=AT,
            )

    def test_only_a_measured_reading_may_carry_an_instrument(self, tmp_path: Path):
        # Attaching a sensor name to a hand-entered number is exactly how a
        # guess acquires instrumented authority.
        for origin in ["manual", "inferred", "unknown"]:
            with pytest.raises(EnvironmentError_, match="ONLY_MEASURED_CARRIES_AN_INSTRUMENT"):
                _store(tmp_path).record(
                    location_id="loc-1", variable="temperature_c",
                    value=None if origin == "unknown" else 18.0,
                    origin=origin, instrument="Probe 1",
                    derived_from="x" if origin == "inferred" else None, observed_at=AT,
                )


class TestInferenceMustBeTraceable:
    def test_an_inferred_value_records_what_it_came_from(self, tmp_path: Path):
        reading = _store(tmp_path).record(
            location_id="loc-1", variable="daily_light_integral_mol_m2_d", value=8.1,
            origin="inferred", derived_from="PPFD readings 2026-08-22, 12h photoperiod",
            observed_at=AT,
        )
        assert reading["origin"] == "inferred"
        assert "PPFD readings" in reading["derived_from"]

    def test_an_untraceable_inference_is_refused(self, tmp_path: Path):
        # An inference nobody can trace is indistinguishable from a guess.
        with pytest.raises(EnvironmentError_, match="INFERRED_REQUIRES_DERIVATION"):
            _store(tmp_path).record(
                location_id="loc-1", variable="temperature_c", value=18.0,
                origin="inferred", observed_at=AT,
            )


class TestMissingIsNotZero:
    def test_unknown_cannot_carry_a_value(self, tmp_path: Path):
        with pytest.raises(EnvironmentError_, match="UNKNOWN_ORIGIN_CANNOT_CARRY_A_VALUE"):
            _store(tmp_path).record(
                location_id="loc-1", variable="relative_humidity_pct", value=0.0,
                origin="unknown", observed_at=AT,
            )

    def test_a_variable_nobody_recorded_reads_as_unknown_not_zero(self, tmp_path: Path):
        """A greenhouse with no humidity sensor has unknown humidity, not 0%.
        Defaulting would put a fabricated measurement in the record that later
        reasoning cannot distinguish from a real one."""
        context = _store(tmp_path).context_for("loc-1")["variables"]
        humidity = context["relative_humidity_pct"]
        assert humidity["known"] is False
        assert humidity["origin"] == "unknown"
        assert humidity["reason"] == "NO_READING_RECORDED"
        assert "value" not in humidity

    def test_every_variable_appears_even_when_nothing_is_known(self, tmp_path: Path):
        # An absent key reads as "nothing to consider here", which is exactly
        # the wrong conclusion for a comparison.
        context = _store(tmp_path).context_for("loc-1")["variables"]
        assert set(context) == set(MEASURABLE_VARIABLES)

    def test_a_genuine_zero_survives(self, tmp_path: Path):
        # 0 PPFD at night is a real measurement, not a missing one.
        store = _store(tmp_path)
        store.record(
            location_id="loc-1", variable="light_ppfd_umol_m2_s", value=0.0,
            origin="measured", instrument="Quantum sensor", observed_at=AT,
        )
        light = store.context_for("loc-1")["variables"]["light_ppfd_umol_m2_s"]
        assert light["known"] is True
        assert light["value"] == 0.0


class TestOriginSurvivesIntoTheContext:
    def test_the_context_says_how_each_number_was_obtained(self, tmp_path: Path):
        # A consumer must be able to weight a hand-entered value differently
        # from an instrumented one. Flattening the origin away removes the only
        # basis for doing so.
        store = _store(tmp_path)
        store.record(location_id="loc-1", variable="temperature_c", value=18.0,
                     origin="manual", observed_at=AT, note="Read off the wall dial")
        temperature = store.context_for("loc-1")["variables"]["temperature_c"]
        assert temperature["origin"] == "manual"
        assert temperature["instrument"] is None

    def test_a_later_manual_reading_does_not_inherit_an_earlier_instrument(self, tmp_path: Path):
        store = _store(tmp_path)
        store.record(location_id="loc-1", variable="temperature_c", value=18.0,
                     origin="measured", instrument="Probe 1", observed_at=AT)
        store.record(location_id="loc-1", variable="temperature_c", value=21.0,
                     origin="manual", observed_at=LATER)
        temperature = store.context_for("loc-1")["variables"]["temperature_c"]
        assert temperature["value"] == 21.0
        assert temperature["origin"] == "manual"
        assert temperature["instrument"] is None


class TestAReadingHasATime:
    def test_a_summary_must_state_its_window(self, tmp_path: Path):
        # Without an end it is being passed off as a spot reading at its start.
        with pytest.raises(EnvironmentError_, match="SUMMARY_REQUIRES_A_WINDOW"):
            _store(tmp_path).record(
                location_id="loc-1", variable="temperature_c", value=12.0,
                origin="measured", instrument="Probe 1", observed_at=AT, summary_kind="min",
            )

    def test_a_nightly_minimum_is_marked_as_a_summary(self, tmp_path: Path):
        reading = _store(tmp_path).record(
            location_id="loc-1", variable="temperature_c", value=12.0,
            origin="measured", instrument="Probe 1", observed_at=AT,
            window_end=LATER, summary_kind="min",
        )
        assert reading["is_summary"] is True
        assert reading["summary_kind"] == "min"

    def test_a_spot_reading_is_not_marked_as_a_summary(self, tmp_path: Path):
        reading = _store(tmp_path).record(
            location_id="loc-1", variable="temperature_c", value=18.0,
            origin="measured", instrument="Probe 1", observed_at=AT,
        )
        assert reading["is_summary"] is False

    def test_a_window_ending_before_it_starts_is_refused(self, tmp_path: Path):
        with pytest.raises(EnvironmentError_, match="WINDOW_ENDS_BEFORE_IT_STARTS"):
            _store(tmp_path).record(
                location_id="loc-1", variable="temperature_c", value=12.0,
                origin="measured", instrument="Probe 1", observed_at=LATER,
                window_end=AT, summary_kind="min",
            )

    def test_an_unrecognised_summary_kind_is_refused(self, tmp_path: Path):
        with pytest.raises(EnvironmentError_, match="SUMMARY_KIND_UNRECOGNISED"):
            _store(tmp_path).record(
                location_id="loc-1", variable="temperature_c", value=12.0,
                origin="measured", instrument="Probe 1", observed_at=AT,
                window_end=LATER, summary_kind="vibes",
            )


class TestVocabulary:
    def test_an_unrecognised_variable_is_refused(self, tmp_path: Path):
        # Two growers recording different things under one name is worse than
        # not recording it.
        with pytest.raises(EnvironmentError_, match="VARIABLE_UNRECOGNISED"):
            _store(tmp_path).record(
                location_id="loc-1", variable="vibes", value=1.0,
                origin="manual", observed_at=AT,
            )

    def test_an_unrecognised_origin_is_refused(self, tmp_path: Path):
        with pytest.raises(EnvironmentError_, match="ORIGIN_UNRECOGNISED"):
            _store(tmp_path).record(
                location_id="loc-1", variable="temperature_c", value=1.0,
                origin="recommended", observed_at=AT,
            )

    def test_every_variable_has_a_stated_unit(self, tmp_path: Path):
        assert all(unit for unit in MEASURABLE_VARIABLES.values())


class TestReadingsSurviveTheStoreFile:
    def test_readings_are_ordered_by_observation_time(self, tmp_path: Path):
        import json

        store = _store(tmp_path)
        store.record(location_id="loc-1", variable="temperature_c", value=12.0,
                     origin="manual", observed_at=AT)
        store.record(location_id="loc-1", variable="temperature_c", value=21.0,
                     origin="manual", observed_at=LATER)
        rows = json.loads((tmp_path / "environment.json").read_text(encoding="utf-8"))
        (tmp_path / "environment.json").write_text(json.dumps(list(reversed(rows))), encoding="utf-8")

        reopened = ConservatoryEnvironmentStore(tmp_path)
        observed = [row["observed_at"] for row in reopened.readings_for("loc-1")]
        assert observed == [AT, LATER]
        assert reopened.context_for("loc-1")["variables"]["temperature_c"]["value"] == 21.0

    def test_readings_are_scoped_to_their_location(self, tmp_path: Path):
        store = _store(tmp_path)
        store.record(location_id="loc-1", variable="temperature_c", value=18.0,
                     origin="manual", observed_at=AT)
        assert store.readings_for("loc-2") == []
        assert store.context_for("loc-2")["variables"]["temperature_c"]["known"] is False


class TestThroughTheApi:
    @staticmethod
    def _client(tmp_path: Path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_locations import ConservatoryLocationStore
        from runtime.conservatory_store import ConservatoryStore

        locations = ConservatoryLocationStore(tmp_path)
        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: ConservatoryStore(tmp_path),
                require_owner=lambda: {"sub": "owner"},
                get_locations=lambda: locations,
                get_environment=lambda: ConservatoryEnvironmentStore(tmp_path),
            )
        )
        return TestClient(app), locations

    def test_record_and_read_back_context_for_a_location(self, tmp_path: Path):
        client, locations = self._client(tmp_path)
        bench = locations.create_location(name="Cool bench", kind="greenhouse_bench")

        created = client.post(
            f"/api/conservatory/locations/{bench['id']}/environment",
            json={
                "variable": "temperature_c", "value": 12.5, "origin": "measured",
                "instrument": "Probe A", "observed_at": AT, "window_end": LATER,
                "summary_kind": "min",
            },
        )
        assert created.status_code == 201

        context = client.get(f"/api/conservatory/locations/{bench['id']}/environment").json()
        temperature = context["variables"]["temperature_c"]
        assert temperature["known"] is True
        assert temperature["origin"] == "measured"
        assert temperature["is_summary"] is True
        # Humidity was never recorded, and says so rather than reading as zero.
        assert context["variables"]["relative_humidity_pct"]["known"] is False
        # The raw readings are returned alongside, so the summary can be checked.
        assert len(context["readings"]) == 1

    def test_a_measurement_without_an_instrument_is_rejected_by_the_api(self, tmp_path: Path):
        client, locations = self._client(tmp_path)
        bench = locations.create_location(name="Warm bench", kind="greenhouse_bench")
        response = client.post(
            f"/api/conservatory/locations/{bench['id']}/environment",
            json={"variable": "temperature_c", "value": 20.0, "origin": "measured", "observed_at": AT},
        )
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "MEASURED_REQUIRES_INSTRUMENT"

    def test_environment_cannot_be_attached_to_a_location_that_does_not_exist(self, tmp_path: Path):
        # Otherwise readings accumulate against places nobody has.
        client, _ = self._client(tmp_path)
        response = client.post(
            "/api/conservatory/locations/no-such-place/environment",
            json={"variable": "temperature_c", "value": 20.0, "origin": "manual", "observed_at": AT},
        )
        assert response.status_code == 404

    def test_environment_routes_require_an_owner(self, tmp_path: Path):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_locations import ConservatoryLocationStore
        from runtime.conservatory_store import ConservatoryStore

        def deny() -> None:
            raise HTTPException(status_code=401, detail="owner required")

        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: ConservatoryStore(tmp_path),
                require_owner=deny,
                get_locations=lambda: ConservatoryLocationStore(tmp_path),
                get_environment=lambda: ConservatoryEnvironmentStore(tmp_path),
            )
        )
        client = TestClient(app)
        assert client.get("/api/conservatory/locations/x/environment").status_code == 401
        assert client.post(
            "/api/conservatory/locations/x/environment",
            json={"variable": "temperature_c", "value": 1.0, "origin": "manual", "observed_at": AT},
        ).status_code == 401
