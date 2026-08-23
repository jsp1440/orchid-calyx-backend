"""Comparing where a plant is against what its taxon is known to need.

The outcome that matters most is `unassessable`. A bench with no thermometer
and a taxon nobody has studied produces no assessment at all, and saying
"within" there — the natural default for a comparison that finds nothing to
complain about — would tell a grower their plant is fine on the strength of two
absences.
"""

from runtime.conservatory_suitability import (
    ASSESSMENT_OUTCOMES,
    assess_placement_suitability,
)


def condition(value=12.0, known=True, origin="measured", **extra):
    """A condition in the shape the ENVELOPE produces, not the environment
    store's. They differ: the envelope wraps each value as a claim with a
    claim_class and no `known` flag, and a fixture using the store's shape
    would test this module against input it never actually receives."""
    if not known:
        return {
            "value": None,
            "claim_class": "absent",
            "unit": "degrees Celsius",
            "reason": "NO_READING_RECORDED",
            **extra,
        }
    base = {
        "value": value,
        "claim_class": "measured_evidence"
        if origin == "measured"
        else "manual_observation",
        "unit": "degrees Celsius",
        "origin": origin,
    }
    base.update(extra)
    return base


def bound(value, strength="verified"):
    return {"value": value, "evidence_strength": strength, "source_anchor_ids": [401]}


def envelope(conditions=None, requirement_bounds=None, taxon_known=True):
    requirements = (
        {
            "value": {
                "temperature_c": {
                    "unit": "degrees Celsius",
                    "bounds": requirement_bounds,
                }
            }
        }
        if taxon_known and requirement_bounds is not None
        else {"value": None, "claim_class": "absent"}
    )
    return {
        "plant": {"plant_id": {"value": "p1"}},
        "conditions": conditions or {},
        "taxon_requirements": requirements,
    }


def only(result):
    return result["assessments"][0]


class TestAbsenceIsNeverFine:
    def test_no_condition_and_no_requirement_assesses_nothing(self):
        result = assess_placement_suitability(envelope())
        assert result["assessments"] == []
        assert result["anything_assessed"] is False

    def test_a_bench_with_no_reading_is_unassessable_not_within(self):
        # The dangerous default: nothing to complain about is not "fine".
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(known=False)},
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        assert only(result)["outcome"] == "unassessable"
        assert only(result)["reason"] == "NO_CONDITION_RECORDED"
        assert result["anything_assessed"] is False

    def test_a_taxon_nobody_studied_is_unassessable(self):
        result = assess_placement_suitability(
            envelope(conditions={"temperature_c": condition(12.0)}, taxon_known=False)
        )
        assert only(result)["outcome"] == "unassessable"
        assert only(result)["reason"] == "NO_REQUIREMENT_EVIDENCE"

    def test_both_missing_says_so_specifically(self):
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(known=False)}, taxon_known=False
            )
        )
        assert only(result)["reason"] == "NO_CONDITION_AND_NO_REQUIREMENT"

    def test_a_claim_marked_absent_is_not_compared_even_if_it_carries_a_value(self):
        """claim_class is authoritative over value. A condition the envelope
        marked absent must not be compared because a number happens to be
        sitting in it — otherwise a placeholder or a stale field silently
        becomes a measurement the comparison acts on."""
        result = assess_placement_suitability(
            envelope(
                conditions={
                    "temperature_c": {
                        "value": 0.0,
                        "claim_class": "absent",
                        "unit": "degrees Celsius",
                        "reason": "NO_READING_RECORDED",
                    }
                },
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        assert only(result)["outcome"] == "unassessable"
        assert result["anything_assessed"] is False

    def test_a_non_numeric_condition_is_unassessable(self):
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(value="cold")},
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        assert only(result)["outcome"] == "unassessable"


class TestRealComparisons:
    def test_a_value_inside_the_bound_is_within(self):
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(20.0)},
                requirement_bounds={"minimum": [bound(15.0)], "maximum": [bound(28.0)]},
            )
        )
        assert only(result)["outcome"] == "within"
        assert result["anything_assessed"] is True

    def test_a_value_below_the_minimum_is_outside(self):
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(10.0)},
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        assessment = only(result)
        assert assessment["outcome"] == "outside"
        assert assessment["breached"] == [{"bound": "minimum", "limit": 15.0}]

    def test_a_value_above_the_maximum_is_outside(self):
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(35.0)},
                requirement_bounds={"maximum": [bound(28.0)]},
            )
        )
        assert only(result)["breached"] == [{"bound": "maximum", "limit": 28.0}]

    def test_a_value_exactly_on_the_bound_is_within(self):
        # A minimum is a floor the plant may sit on, not one it must clear.
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(15.0)},
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        assert only(result)["outcome"] == "within"

    def test_only_the_bound_that_exists_is_checked(self):
        # A taxon with a known minimum and no known maximum is not unbounded
        # above; it is unstudied above, and a low reading still fails the floor.
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(200.0)},
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        assert only(result)["outcome"] == "within"


class TestDisagreementIsNotResolvedHere:
    def test_two_sources_giving_different_minima_conflict(self):
        """Picking the stricter would invent a precautionary policy nobody
        agreed to; picking the mean would state a number no source gave."""
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(12.0)},
                requirement_bounds={"minimum": [bound(10.0), bound(15.0)]},
            )
        )
        assessment = only(result)
        assert assessment["outcome"] == "conflicting"
        assert assessment["reason"] == "SOURCES_DISAGREE_ABOUT_THE_BOUND"

    def test_two_sources_agreeing_do_not_conflict(self):
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(20.0)},
                requirement_bounds={"minimum": [bound(15.0), bound(15.0)]},
            )
        )
        assert only(result)["outcome"] == "within"

    def test_a_conflict_is_not_counted_as_assessed(self):
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(12.0)},
                requirement_bounds={"minimum": [bound(10.0), bound(15.0)]},
            )
        )
        assert result["anything_assessed"] is False


class TestProvenanceTravels:
    def test_both_sides_arrive_with_their_own_provenance(self):
        # A reader needs to know it compared a hand-entered number against an
        # unverified claim, if that is what happened.
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(10.0, origin="manual")},
                requirement_bounds={"minimum": [bound(15.0, strength="unverified")]},
            )
        )
        assessment = only(result)
        assert assessment["condition"]["origin"] == "manual"
        assert assessment["bounds"]["minimum"][0]["evidence_strength"] == "unverified"

    def test_no_confidence_score_is_invented(self):
        # Multiplying an instrument reading by an unverified literature claim
        # produces a number that describes nothing.
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(20.0)},
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        for forbidden in ["score", "confidence", "certainty", "rating"]:
            assert forbidden not in result
            assert forbidden not in only(result)


class TestItOffersNoAdvice:
    def test_it_does_not_say_whether_to_move_the_plant(self):
        """That depends on what else is on the bench, what the grower can do,
        and the season — none of which are in this data."""
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(5.0)},
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        assert result["is_recommendation"] is False
        for forbidden in [
            "recommendation",
            "should_move",
            "advice",
            "action",
            "verdict",
        ]:
            assert forbidden not in result

    def test_it_denies_being_scientific_evidence(self):
        assert (
            assess_placement_suitability(envelope())["is_scientific_evidence"] is False
        )

    def test_every_outcome_is_in_the_declared_vocabulary(self):
        result = assess_placement_suitability(
            envelope(
                conditions={"temperature_c": condition(5.0)},
                requirement_bounds={"minimum": [bound(15.0)]},
            )
        )
        assert set(result["counts"]) == set(ASSESSMENT_OUTCOMES)
        assert all(a["outcome"] in ASSESSMENT_OUTCOMES for a in result["assessments"])


class TestThroughTheApi:
    """The whole chain assembled: plant, bench, reading, and the comparison."""

    @staticmethod
    def _client(tmp_path):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_environment import ConservatoryEnvironmentStore
        from runtime.conservatory_events import ConservatoryEventStore
        from runtime.conservatory_locations import ConservatoryLocationStore
        from runtime.conservatory_store import ConservatoryStore

        plants = ConservatoryStore(tmp_path)
        locations = ConservatoryLocationStore(tmp_path)
        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: plants,
                require_owner=lambda: {"sub": "owner"},
                get_locations=lambda: locations,
                get_environment=lambda: ConservatoryEnvironmentStore(tmp_path),
                get_events=lambda: ConservatoryEventStore(tmp_path),
            )
        )
        return TestClient(app), plants, locations

    def test_a_real_plant_with_a_reading_and_no_taxon_evidence_is_unassessable(
        self, tmp_path, monkeypatch
    ):
        # The honest common case: the Continuum knows the bench is 12C and
        # knows nothing about what this taxon needs.
        #
        # The candidate store is stubbed empty rather than left ambient so
        # this asserts "read it, found nothing" in every environment. Left
        # ambient it would assert whatever the environment's database driver
        # happens to make possible, and an unreachable store is a different
        # answer with a different reason.
        import app.routers.conservatory as module

        class EmptyStore:
            def __init__(self):
                self.candidates = []
                self.evidence_links = []

        monkeypatch.setattr(module, "_candidate_repository", lambda: EmptyStore())
        client, plants, locations = self._client(tmp_path)
        plant = plants.create(
            display_name="Cattleya", accepted_scientific_name="Cattleya skinneri"
        )
        bench = locations.create_location(name="Cool bench", kind="greenhouse_bench")
        client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": bench["id"], "reason": "initial"},
        )
        client.post(
            f"/api/conservatory/locations/{bench['id']}/environment",
            json={
                "variable": "temperature_c",
                "value": 12.0,
                "origin": "measured",
                "instrument": "Probe A",
                "observed_at": "2026-08-23T06:00:00+00:00",
            },
        )

        result = client.get(
            f"/api/conservatory/plants/{plant['id']}/placement-assessment"
        ).json()
        assert result["anything_assessed"] is False
        temperature = next(
            a for a in result["assessments"] if a["variable"] == "temperature_c"
        )
        assert temperature["outcome"] == "unassessable"
        assert temperature["reason"] == "NO_REQUIREMENT_EVIDENCE"
        assert result["is_recommendation"] is False

    def test_it_requires_an_owner(self, tmp_path):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_store import ConservatoryStore

        def deny() -> None:
            raise HTTPException(status_code=401, detail="owner required")

        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: ConservatoryStore(tmp_path), require_owner=deny
            )
        )
        assert (
            TestClient(app)
            .get("/api/conservatory/plants/x/placement-assessment")
            .status_code
            == 401
        )

    def test_an_unknown_plant_has_no_assessment(self, tmp_path):
        client, _, _ = self._client(tmp_path)
        assert (
            client.get("/api/conservatory/plants/nope/placement-assessment").status_code
            == 404
        )
