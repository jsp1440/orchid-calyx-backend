"""The envelope Calyx receives, and the collapses it must never allow.

The envelope answers nothing. Its whole job is to hand over what is known
without handing over a false impression of how well it is known. Each test
below is one way a weak claim could acquire an authority it has not earned.
"""

from runtime.conservatory_calyx_context import CLAIM_CLASSES, build_cultivation_context

PLANT = {
    "id": "p1",
    "accession_number": "OC-2026-0001",
    "display_name": "Cattleya skinneri alba",
    "accepted_scientific_name": "Cattleya skinneri",
}
LOCATION = {
    "id": "loc-cool",
    "name": "Cool bench",
    "kind": "greenhouse_bench",
    "described_conditions": "Bright shade, cool nights",
}


def _context(**overrides):
    base = {
        "plant": PLANT,
        "placement_current": {"location_id": "loc-cool", "reason": "move"},
        "placement_history": [
            {
                "location_id": "loc-cool",
                "reason": "move",
                "recorded_at": "2026-02-01T00:00:00Z",
            }
        ],
        "location": LOCATION,
        "environment": None,
        "events": None,
        "trait_candidates": None,
    }
    base.update(overrides)
    return build_cultivation_context(**base)


def _env(origin: str, *, known: bool = True, value: float = 12.0, **extra):
    return {
        "variables": {
            "temperature_c": {
                "unit": "degrees Celsius",
                "known": known,
                "value": value,
                "origin": origin,
                "instrument": extra.get("instrument"),
                "observed_at": "2026-08-23T06:00:00Z",
                "is_summary": extra.get("is_summary", False),
                "summary_kind": extra.get("summary_kind"),
                "reason": extra.get("reason"),
            }
        }
    }


class TestClaimClassesNeverMerge:
    def test_a_measurement_is_measured_evidence(self):
        context = _context(environment=_env("measured", instrument="Probe A"))
        assert (
            context["conditions"]["temperature_c"]["claim_class"] == "measured_evidence"
        )

    def test_a_hand_entered_value_is_not_measured_evidence(self):
        # The collapse that would let a guess acquire instrument authority.
        context = _context(environment=_env("manual"))
        assert (
            context["conditions"]["temperature_c"]["claim_class"]
            == "manual_observation"
        )

    def test_an_inference_is_not_an_observation(self):
        context = _context(environment=_env("inferred"))
        assert (
            context["conditions"]["temperature_c"]["claim_class"] == "inferred_context"
        )

    def test_an_unrecorded_variable_is_absent_not_zero(self):
        context = _context(
            environment=_env("unknown", known=False, reason="NO_READING_RECORDED")
        )
        temperature = context["conditions"]["temperature_c"]
        assert temperature["claim_class"] == "absent"
        assert temperature["value"] is None
        assert temperature["reason"] == "NO_READING_RECORDED"

    def test_an_unmapped_origin_is_not_assumed_trustworthy(self):
        # A future origin must not inherit measured_evidence by default.
        context = _context(environment=_env("some_new_origin"))
        assert (
            context["conditions"]["temperature_c"]["claim_class"] != "measured_evidence"
        )

    def test_every_claim_carries_a_recognised_class(self):
        context = _context(environment=_env("measured", instrument="Probe A"))
        for claim in [
            context["current_location"],
            context["placement_history"],
            context["observations"],
        ]:
            assert claim["claim_class"] in CLAIM_CLASSES


class TestTheGrowersNameIsNotADetermination:
    def test_a_typed_scientific_name_is_a_collection_fact(self):
        # It is what the grower believes the plant is, which is not a
        # determination anybody has verified.
        name = _context()["plant"]["grower_stated_name"]
        assert name["claim_class"] == "collection_fact"
        assert name["claim_class"] != "identity"
        assert "not a verified taxonomic determination" in name["note"].lower()

    def test_an_absent_name_is_absent(self):
        context = _context(plant={**PLANT, "accepted_scientific_name": None})
        assert context["plant"]["grower_stated_name"]["claim_class"] == "absent"

    def test_the_accession_itself_is_identity(self):
        assert _context()["plant"]["accession_number"]["claim_class"] == "identity"


class TestTheGrowersDescriptionIsNotAMeasurement:
    def test_described_conditions_are_marked_as_an_observation(self):
        # "Bright shade, cool nights" must not sit beside instrument data as
        # an equal.
        where = _context()["current_location"]
        assert where["claim_class"] == "collection_fact"
        assert where["described_conditions_class"] == "manual_observation"

    def test_a_location_without_a_description_says_so(self):
        context = _context(location={**LOCATION, "described_conditions": None})
        assert context["current_location"]["described_conditions_class"] == "absent"


class TestAbsenceIsRepresentedNotDropped:
    def test_a_plant_in_no_location_says_why(self):
        context = _context(placement_current=None, location=None)
        assert context["current_location"]["claim_class"] == "absent"
        assert context["current_location"]["reason"] == "NO_CURRENT_PLACEMENT"

    def test_literature_evidence_is_named_as_absent(self):
        # A consumer must see the gap rather than mistake collection data for
        # the whole picture.
        literature = _context()["literature_evidence"]
        assert literature["claim_class"] == "absent"
        assert literature["value"] is None

    def test_taxon_requirements_are_absent_when_no_evidence_exists(self):
        """Now that the requirement contract exists, absence means the
        Continuum holds no cultivation evidence for this taxon — the normal
        case — rather than that no contract was available. A default range
        would be acted on by a grower."""
        requirements = _context()["taxon_requirements"]
        assert requirements["claim_class"] == "absent"
        assert requirements["reason"] == "NO_CULTIVATION_EVIDENCE_FOR_THIS_TAXON"
        assert requirements["value"] is None

    def test_an_empty_history_is_absent_rather_than_an_empty_fact(self):
        context = _context(placement_history=[])
        assert context["placement_history"]["claim_class"] == "absent"

    def test_no_observations_is_absent(self):
        assert _context()["observations"]["claim_class"] == "absent"


class TestRequirementsArriveAsLiteratureNotMeasurement:
    def test_evidence_backed_requirements_appear_in_their_own_class(self):
        """A published range and a thermometer reading are not the same kind of
        thing, and collapsing them would let one stand in for the other."""
        context = _context(
            trait_candidates=[
                {
                    "predicate": "minimum_temperature",
                    "numeric_value": 12.0,
                    "unit": "degrees Celsius",
                    "source_anchor_ids": [401],
                    "source_revision_id": 41,
                    "verification_state": "VERIFIED",
                    "status": "ACTIVE",
                }
            ]
        )
        requirements = context["taxon_requirements"]
        assert requirements["claim_class"] == "literature_derived"
        assert requirements["claim_class"] != "measured_evidence"
        bound = requirements["value"]["temperature_c"]["bounds"]["minimum"][0]
        assert bound["value"] == 12.0
        assert bound["evidence_strength"] == "verified"

    def test_the_envelope_still_denies_being_evidence(self):
        # Requirements are the strongest thing in here and the envelope is
        # still not a finding.
        context = _context(
            trait_candidates=[
                {
                    "predicate": "minimum_temperature",
                    "numeric_value": 12.0,
                    "unit": "degrees Celsius",
                    "source_anchor_ids": [401],
                    "source_revision_id": 41,
                    "status": "ACTIVE",
                }
            ]
        )
        assert context["is_scientific_evidence"] is False
        assert context["may_be_promoted_to_evidence"] is False


class TestObservationsStayObservations:
    def test_grower_events_are_manual_observations(self):
        context = _context(
            events={
                "standing": [
                    {
                        "kind": "flowering_observed",
                        "occurred_at": "2026-08-16T00:00:00Z",
                        "recorded_at": "2026-08-22T00:00:00Z",
                        "recorder_kind": "grower",
                        "note": None,
                    },
                ]
            }
        )
        assert context["observations"]["claim_class"] == "manual_observation"
        assert context["observations"]["value"][0]["kind"] == "flowering_observed"

    def test_both_clocks_survive_into_the_envelope(self):
        # An event recorded six days late is a weaker claim about timing, and
        # Calyx cannot weigh that if only one timestamp arrives.
        context = _context(
            events={
                "standing": [
                    {
                        "kind": "spike_observed",
                        "occurred_at": "2026-08-16T00:00:00Z",
                        "recorded_at": "2026-08-22T00:00:00Z",
                        "recorder_kind": "grower",
                        "note": None,
                    },
                ]
            }
        )
        observation = context["observations"]["value"][0]
        assert observation["occurred_at"] != observation["recorded_at"]

    def test_superseded_events_do_not_reach_calyx_as_standing_facts(self):
        # Only what currently stands is handed over; corrections already
        # removed it from `standing`.
        context = _context(
            events={"standing": [], "corrected": [{"kind": "flowering_observed"}]}
        )
        assert context["observations"]["claim_class"] == "absent"


class TestTheEnvelopeDeclaresItself:
    def test_it_says_it_is_not_scientific_evidence(self):
        context = _context()
        assert context["is_scientific_evidence"] is False
        assert context["may_be_promoted_to_evidence"] is False

    def test_it_says_so_in_prose_too(self):
        note = _context()["envelope_note"].lower()
        assert "nothing here is a verified scientific finding" in note
        assert "no value may be promoted into evidence" in note

    def test_it_publishes_the_class_vocabulary(self):
        # A consumer can check it understands every class before reasoning.
        assert set(_context()["claim_classes"]) == set(CLAIM_CLASSES)

    def test_it_contains_no_recommendation_or_conclusion(self):
        # The envelope answers nothing; reasoning happens beyond this boundary.
        context = _context(environment=_env("measured", instrument="Probe A"))
        for forbidden in ["recommendation", "conclusion", "verdict", "score", "advice"]:
            assert forbidden not in context


class TestTheWholeChainThroughTheApi:
    """QR identity -> plant -> location -> conditions -> observations, composed
    into one envelope with every claim still labelled."""

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

    def test_the_full_chain_composes_with_classes_intact(self, tmp_path):
        client, plants, locations = self._client(tmp_path)
        plant = plants.create(
            display_name="Cattleya skinneri alba",
            accepted_scientific_name="Cattleya skinneri",
        )
        bench = locations.create_location(
            name="Cool bench",
            kind="greenhouse_bench",
            described_conditions="Cool nights",
        )
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
        client.post(
            f"/api/conservatory/locations/{bench['id']}/environment",
            json={
                "variable": "relative_humidity_pct",
                "value": 60.0,
                "origin": "manual",
                "observed_at": "2026-08-23T06:00:00+00:00",
            },
        )
        client.post(
            f"/api/conservatory/plants/{plant['id']}/events",
            json={"kind": "spike_observed", "occurred_at": "2026-08-16T09:00:00+00:00"},
        )

        context = client.get(
            f"/api/conservatory/plants/{plant['id']}/cultivation-context"
        ).json()

        assert context["plant"]["accession_number"]["claim_class"] == "identity"
        # The grower typed the name; it is not a determination.
        assert (
            context["plant"]["grower_stated_name"]["claim_class"] == "collection_fact"
        )
        assert context["current_location"]["value"]["name"] == "Cool bench"
        # The instrument reading and the hand-entered one arrive in different
        # classes, which is the entire point of the envelope.
        assert (
            context["conditions"]["temperature_c"]["claim_class"] == "measured_evidence"
        )
        assert (
            context["conditions"]["relative_humidity_pct"]["claim_class"]
            == "manual_observation"
        )
        # A variable with no sensor is present and absent, not missing.
        assert context["conditions"]["light_ppfd_umol_m2_s"]["claim_class"] == "absent"
        assert context["observations"]["claim_class"] == "manual_observation"
        assert context["literature_evidence"]["claim_class"] == "absent"
        assert context["is_scientific_evidence"] is False

    def test_the_envelope_requires_an_owner(self, tmp_path):
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
            .get("/api/conservatory/plants/x/cultivation-context")
            .status_code
            == 401
        )

    def test_a_plant_that_does_not_exist_has_no_envelope(self, tmp_path):
        client, _, _ = self._client(tmp_path)
        assert (
            client.get("/api/conservatory/plants/nope/cultivation-context").status_code
            == 404
        )
