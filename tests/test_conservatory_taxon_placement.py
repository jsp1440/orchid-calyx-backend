"""Where a plant the grower does not own yet could go.

The buying question, answered from what the benches actually measure. The
pressure this code is under is the pull towards an answer it cannot support:
"yes, buy it, put it on bench 3". Whether a bench has room, whether its
readings are current, whether the grower can hold those conditions through a
season — none of that is here. So the tests are largely about what the search
refuses to say.
"""

from pathlib import Path

from runtime.conservatory_taxon_placement import build_taxon_placement_search


def requirements(minimum=15.0, *, known=True, reason=None, consulted=True):
    if not known:
        return {
            "value": None,
            "claim_class": "absent",
            "reason": reason or "NO_CULTIVATION_EVIDENCE_FOR_THIS_TAXON",
            "source_consulted": consulted,
        }
    return {
        "value": {
            "temperature_c": {
                "unit": "degrees Celsius",
                "bounds": {
                    "minimum": [{"value": minimum, "evidence_strength": "unverified"}]
                },
            }
        },
        "claim_class": "literature_derived",
    }


def location(location_id="loc-1", name="Cool bench", **overrides):
    base = {"id": location_id, "name": name, "kind": "greenhouse_bench"}
    base.update(overrides)
    return base


def environment(values):
    """A context_for stand-in: {location_id: {variable: (value, origin)}}."""

    def lookup(location_id):
        variables = {}
        for variable, pair in (values.get(location_id) or {}).items():
            value, origin = pair
            variables[variable] = {
                "unit": "degrees Celsius",
                "known": value is not None,
                "value": value,
                "origin": origin,
                "instrument": "Probe A" if origin == "measured" else None,
                "derived_from": None,
                "observed_at": "2026-08-22T12:00:00+00:00",
                "window_end": None,
                "is_summary": False,
                "summary_kind": None,
            }
        return {"location_id": location_id, "variables": variables}

    return lookup


class TestAnsweringTheQuestion:
    def test_a_warm_bench_meets_a_minimum_and_a_cold_one_does_not(self):
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(),
            locations=[location("warm", "Warm bench"), location("cold", "Cold bench")],
            environment_for=environment(
                {
                    "warm": {"temperature_c": (20.0, "measured")},
                    "cold": {"temperature_c": (8.0, "measured")},
                }
            ),
        )

        by_id = {row["location_id"]: row for row in result["locations"]}
        warm = next(
            a for a in by_id["warm"]["assessments"] if a["variable"] == "temperature_c"
        )
        cold = next(
            a for a in by_id["cold"]["assessments"] if a["variable"] == "temperature_c"
        )
        assert warm["outcome"] == "within"
        assert cold["outcome"] == "outside"
        assert result["anything_assessed"] is True

    def test_the_origin_of_a_reading_survives_into_the_comparison(self):
        # A bench whose temperature is somebody's estimate must not compare as
        # though it were instrumented.
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(),
            locations=[location()],
            environment_for=environment({"loc-1": {"temperature_c": (20.0, "manual")}}),
        )

        row = next(
            a
            for a in result["locations"][0]["assessments"]
            if a["variable"] == "temperature_c"
        )
        assert row["condition"]["origin"] == "manual"
        assert row["condition"]["claim_class"] == "manual_observation"

    def test_the_evidence_behind_the_bound_travels_with_the_answer(self):
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(),
            locations=[location()],
            environment_for=environment(
                {"loc-1": {"temperature_c": (8.0, "measured")}}
            ),
        )

        assert result["requirements"]["claim_class"] == "literature_derived"
        row = next(
            a
            for a in result["locations"][0]["assessments"]
            if a["variable"] == "temperature_c"
        )
        assert row["bounds"]["minimum"][0]["evidence_strength"] == "unverified"


class TestWhatItRefusesToSay:
    def test_a_taxon_with_no_evidence_compares_nowhere(self):
        # The common case. A location that cannot be compared must not read as
        # a location that will do.
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(known=False),
            locations=[location()],
            environment_for=environment(
                {"loc-1": {"temperature_c": (20.0, "measured")}}
            ),
        )

        row = next(
            a
            for a in result["locations"][0]["assessments"]
            if a["variable"] == "temperature_c"
        )
        assert row["outcome"] == "unassessable"
        assert row["reason"] == "NO_REQUIREMENT_EVIDENCE"
        assert result["anything_assessed"] is False

    def test_an_unreadable_store_is_not_reported_as_an_unstudied_taxon(self):
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(
                known=False, reason="TRAIT_SOURCE_UNAVAILABLE", consulted=False
            ),
            locations=[location()],
            environment_for=environment(
                {"loc-1": {"temperature_c": (20.0, "measured")}}
            ),
        )

        row = next(
            a
            for a in result["locations"][0]["assessments"]
            if a["variable"] == "temperature_c"
        )
        assert row["reason"] == "REQUIREMENT_SOURCE_UNAVAILABLE"

    def test_it_offers_no_ranking_and_no_purchase_verdict(self):
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(),
            # The breaching bench is listed first deliberately: if anything
            # sorted by fit, the passing one would jump ahead of it and this
            # assertion would notice.
            locations=[location("cold", "Cold bench"), location("warm", "Warm bench")],
            environment_for=environment(
                {
                    "warm": {"temperature_c": (20.0, "measured")},
                    "cold": {"temperature_c": (8.0, "measured")},
                }
            ),
        )

        assert result["is_recommendation"] is False
        assert result["is_scientific_evidence"] is False
        for key in ("best_location", "recommended", "score", "rank"):
            assert key not in result
        # Locations come back in the order they were given, not sorted by fit.
        assert [row["location_id"] for row in result["locations"]] == ["cold", "warm"]

    def test_a_retired_bench_is_not_offered(self):
        # A place the grower has dismantled cannot house a plant they have not
        # bought yet.
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(),
            locations=[
                location("gone", "Old bench", retired_at="2026-02-01T00:00:00+00:00"),
                location("here", "Warm bench"),
            ],
            environment_for=environment(
                {
                    "gone": {"temperature_c": (20.0, "measured")},
                    "here": {"temperature_c": (20.0, "measured")},
                }
            ),
        )

        assert [row["location_id"] for row in result["locations"]] == ["here"]

    def test_no_taxon_is_a_refusal_not_an_empty_result(self):
        for value in (None, "", "   "):
            result = build_taxon_placement_search(
                taxon=value,
                requirements_claim=requirements(),
                locations=[location()],
                environment_for=environment(
                    {"loc-1": {"temperature_c": (20.0, "measured")}}
                ),
            )
            assert result["locations"] == []
            assert result["reason"] == "NO_TAXON_SUPPLIED"
            assert result["anything_assessed"] is False

    def test_a_bench_with_no_readings_is_unassessable_not_suitable(self):
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(),
            locations=[location()],
            environment_for=environment({"loc-1": {}}),
        )

        assert result["locations"][0]["anything_assessed"] is False
        assert result["anything_assessed"] is False

    def test_a_variable_nobody_recorded_carries_no_value(self):
        """An unrecorded reading must arrive as absent, not as a number.

        A zero would compare: below every minimum, inside nothing, and
        indistinguishable from a genuinely freezing bench. The store reports
        the variable with known=False precisely so it can be carried as
        missing rather than dropped or defaulted.
        """
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(),
            locations=[location()],
            environment_for=environment(
                {"loc-1": {"temperature_c": (None, "unknown")}}
            ),
        )

        row = next(
            a
            for a in result["locations"][0]["assessments"]
            if a["variable"] == "temperature_c"
        )
        assert row["outcome"] == "unassessable"
        assert row["reason"] == "NO_CONDITION_RECORDED"
        assert result["anything_assessed"] is False

    def test_each_location_states_its_own_assessed_flag(self):
        # A reader scanning one row must not have to trust that a heading
        # somewhere above still applies to it.
        result = build_taxon_placement_search(
            taxon="Cattleya skinneri",
            requirements_claim=requirements(),
            locations=[
                location("measured", "Warm bench"),
                location("blank", "New bench"),
            ],
            environment_for=environment(
                {"measured": {"temperature_c": (20.0, "measured")}}
            ),
        )

        by_id = {row["location_id"]: row for row in result["locations"]}
        assert by_id["measured"]["anything_assessed"] is True
        assert by_id["blank"]["anything_assessed"] is False
        assert result["anything_assessed"] is True


class TestThroughTheApi:
    @staticmethod
    def _client(tmp_path: Path, monkeypatch, rows=None, links=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import app.routers.conservatory as module
        from runtime.conservatory_environment import ConservatoryEnvironmentStore
        from runtime.conservatory_locations import ConservatoryLocationStore
        from runtime.conservatory_store import ConservatoryStore

        class Store:
            def __init__(self):
                self.candidates = rows or []
                self.evidence_links = links or []

        monkeypatch.setattr(module, "_candidate_repository", lambda: Store())
        locations = ConservatoryLocationStore(tmp_path)
        app = FastAPI()
        app.include_router(
            module.create_conservatory_router(
                get_store=lambda: ConservatoryStore(tmp_path),
                require_owner=lambda: {"sub": "owner"},
                get_locations=lambda: locations,
                get_environment=lambda: ConservatoryEnvironmentStore(tmp_path),
            )
        )
        return TestClient(app), locations

    @staticmethod
    def _trait():
        return {
            "candidate_id": 11,
            "kind": "TRAIT",
            "normalized_subject": "Cattleya skinneri",
            "predicate": "minimum_temperature",
            "numeric_value": 15.0,
            "unit": "degrees Celsius",
            "active": True,
            "review_state": "REQUIRED",
            "extraction_method": "DETERMINISTIC_RULE",
            "confidence": 0.8,
        }

    @staticmethod
    def _link():
        return {
            "evidence_link_id": 1,
            "candidate_id": 11,
            "revision_id": 41,
            "anchor": {"anchor_id": 401, "ordered_span": 0},
        }

    def test_the_search_reaches_real_readings_and_real_evidence(
        self, tmp_path: Path, monkeypatch
    ):
        client, locations = self._client(
            tmp_path, monkeypatch, [self._trait()], [self._link()]
        )
        cold = locations.create_location(name="Cold bench", kind="greenhouse_bench")
        warm = locations.create_location(name="Warm bench", kind="greenhouse_bench")
        for bench, value in ((cold, 8.0), (warm, 20.0)):
            client.post(
                f"/api/conservatory/locations/{bench['id']}/environment",
                json={
                    "variable": "temperature_c",
                    "value": value,
                    "origin": "measured",
                    "instrument": "Probe A",
                    "observed_at": "2026-08-23T06:00:00+00:00",
                },
            )

        result = client.get(
            "/api/conservatory/locations/suitability",
            params={"taxon": "Cattleya skinneri"},
        ).json()

        by_id = {row["location_id"]: row for row in result["locations"]}
        assert by_id[cold["id"]]["counts"]["outside"] == 1
        assert by_id[warm["id"]]["counts"]["within"] == 1
        assert result["anything_assessed"] is True

    def test_a_taxon_the_store_knows_nothing_about_compares_nowhere(
        self, tmp_path: Path, monkeypatch
    ):
        client, locations = self._client(tmp_path, monkeypatch)
        bench = locations.create_location(name="Warm bench", kind="greenhouse_bench")
        client.post(
            f"/api/conservatory/locations/{bench['id']}/environment",
            json={
                "variable": "temperature_c",
                "value": 20.0,
                "origin": "measured",
                "instrument": "Probe A",
                "observed_at": "2026-08-23T06:00:00+00:00",
            },
        )

        result = client.get(
            "/api/conservatory/locations/suitability",
            params={"taxon": "Phalaenopsis amabilis"},
        ).json()

        assert result["anything_assessed"] is False
        assert result["requirements"]["claim_class"] == "absent"

    def test_an_unreadable_store_is_not_reported_as_an_unstudied_taxon(
        self, tmp_path: Path, monkeypatch
    ):
        """The route must carry the outage through, not flatten it.

        Reported as "no evidence for this taxon", an outage becomes a claim
        about the literature — and a grower deciding whether to buy a plant
        would take it as one.
        """
        import app.routers.conservatory as module

        client, locations = self._client(tmp_path, monkeypatch)
        monkeypatch.setattr(module, "_candidate_repository", lambda: None)
        bench = locations.create_location(name="Warm bench", kind="greenhouse_bench")
        client.post(
            f"/api/conservatory/locations/{bench['id']}/environment",
            json={
                "variable": "temperature_c",
                "value": 20.0,
                "origin": "measured",
                "instrument": "Probe A",
                "observed_at": "2026-08-23T06:00:00+00:00",
            },
        )

        result = client.get(
            "/api/conservatory/locations/suitability",
            params={"taxon": "Cattleya skinneri"},
        ).json()

        assert result["requirements"]["reason"] == "TRAIT_SOURCE_UNAVAILABLE"
        assert result["requirements"]["source_consulted"] is False
        row = next(
            a
            for a in result["locations"][0]["assessments"]
            if a["variable"] == "temperature_c"
        )
        assert row["reason"] == "REQUIREMENT_SOURCE_UNAVAILABLE"

    def test_an_over_long_taxon_is_refused_by_the_route(
        self, tmp_path: Path, monkeypatch
    ):
        # It arrives from a query string; nothing downstream should be asked to
        # hold a document.
        client, _ = self._client(tmp_path, monkeypatch)

        response = client.get(
            "/api/conservatory/locations/suitability", params={"taxon": "C" * 5000}
        )

        assert response.status_code == 422

    def test_the_search_is_owner_gated(self, tmp_path: Path):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_locations import ConservatoryLocationStore
        from runtime.conservatory_store import ConservatoryStore

        def refuse():
            raise HTTPException(status_code=401, detail="owner only")

        app = FastAPI()
        app.include_router(
            create_conservatory_router(
                get_store=lambda: ConservatoryStore(tmp_path),
                require_owner=refuse,
                get_locations=lambda: ConservatoryLocationStore(tmp_path),
            )
        )

        # The response names every location in the collection, which is private
        # whether or not a plant is standing in it.
        assert (
            TestClient(app)
            .get(
                "/api/conservatory/locations/suitability", params={"taxon": "Cattleya"}
            )
            .status_code
            == 401
        )
