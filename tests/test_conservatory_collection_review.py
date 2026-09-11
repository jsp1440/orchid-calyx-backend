"""Reviewing a whole collection without turning ignorance into reassurance.

A list is a more dangerous shape than a dossier. On one plant `unassessable` is
a paragraph a grower reads; in a list of two hundred it is a grey row they skip.
The property under test throughout is that a collection nobody can assess never
renders as a collection with nothing wrong.
"""

import pytest

from runtime.conservatory_collection_review import (
    REVIEW_GROUPS,
    build_collection_review,
)


def plant(plant_id="p1", **overrides):
    base = {
        "id": plant_id,
        "accession_number": f"OC-2026-{plant_id[-1]}",
        "display_name": "Cattleya",
        "accepted_scientific_name": "Cattleya skinneri",
    }
    base.update(overrides)
    return base


def assessment(counts=None, assessments=None, consulted=True):
    base = {"within": 0, "outside": 0, "unassessable": 0, "conflicting": 0}
    base.update(counts or {})
    return {
        "counts": base,
        "assessments": assessments or [],
        "requirement_source_consulted": consulted,
        "is_recommendation": False,
    }


class TestGrouping:
    def test_a_breach_puts_a_plant_in_outside(self):
        review = build_collection_review(
            [
                (
                    plant(),
                    assessment(
                        {"outside": 1},
                        [
                            {
                                "variable": "temperature_c",
                                "outcome": "outside",
                                "breached": [{"bound": "minimum", "limit": 15}],
                            }
                        ],
                    ),
                )
            ]
        )

        assert [row["plant_id"] for row in review["groups"]["outside"]] == ["p1"]
        assert review["groups"]["outside"][0]["breaches"] == [
            {
                "variable": "temperature_c",
                "breached": [{"bound": "minimum", "limit": 15}],
            }
        ]

    def test_a_breach_outranks_a_pile_of_unassessable_variables(self):
        # A plant with one established breach and four unknowns is a plant with
        # a breach. Filing it under `unassessed` would bury the one fact that
        # was established.
        review = build_collection_review(
            [(plant(), assessment({"outside": 1, "unassessable": 4}))]
        )

        assert review["counts"]["outside"] == 1
        assert review["counts"]["unassessed"] == 0

    def test_disagreeing_evidence_is_its_own_group_not_a_pass(self):
        review = build_collection_review(
            [(plant(), assessment({"conflicting": 1, "within": 2}))]
        )

        assert review["counts"]["conflicting"] == 1
        assert review["counts"]["within"] == 0

    def test_a_plant_with_nothing_comparable_is_unassessed_not_within(self):
        review = build_collection_review([(plant(), assessment({"unassessable": 3}))])

        assert review["counts"]["unassessed"] == 1
        assert review["counts"]["within"] == 0

    def test_every_plant_lands_in_exactly_one_group(self):
        review = build_collection_review(
            [
                (plant("p1"), assessment({"outside": 1})),
                (plant("p2"), assessment({"conflicting": 1})),
                (plant("p3"), assessment({"within": 2})),
                (plant("p4"), assessment({"unassessable": 1})),
            ]
        )

        seen = [
            row["plant_id"]
            for group in REVIEW_GROUPS
            for row in review["groups"][group]
        ]
        assert sorted(seen) == ["p1", "p2", "p3", "p4"]
        assert len(seen) == len(set(seen))
        assert review["plant_count"] == 4


class TestNotSayingEverythingIsFine:
    def test_a_collection_nobody_could_assess_says_so(self):
        review = build_collection_review(
            [
                (plant("p1"), assessment({"unassessable": 2})),
                (plant("p2"), assessment({"unassessable": 2})),
            ]
        )

        assert review["groups"]["outside"] == []
        # The assertion that matters: an empty breach list is not a clean bill.
        assert review["anything_assessed"] is False

    def test_one_comparison_anywhere_makes_the_collection_assessed(self):
        review = build_collection_review(
            [
                (plant("p1"), assessment({"within": 1})),
                (plant("p2"), assessment({"unassessable": 2})),
            ]
        )

        assert review["anything_assessed"] is True

    def test_an_empty_collection_is_not_a_healthy_one(self):
        review = build_collection_review([])

        assert review["plant_count"] == 0
        assert review["anything_assessed"] is False

    def test_it_counts_plants_assessed_against_an_unreadable_store(self):
        # Those plants are unassessed for a reason that says nothing about them
        # or their taxa, and a grower reading the group needs that separated.
        review = build_collection_review(
            [
                (plant("p1"), assessment({"unassessable": 2}, consulted=False)),
                (plant("p2"), assessment({"unassessable": 2})),
            ]
        )

        assert review["requirement_source_unread_for"] == 1
        by_id = {row["plant_id"]: row for row in review["groups"]["unassessed"]}
        assert by_id["p1"]["requirement_source_consulted"] is False
        assert by_id["p2"]["requirement_source_consulted"] is True

    def test_it_offers_no_advice_and_no_ranking(self):
        review = build_collection_review([(plant(), assessment({"outside": 1}))])

        assert review["is_recommendation"] is False
        assert review["is_scientific_evidence"] is False
        assert "priority" not in review
        assert "score" not in review


class TestThroughTheApi:
    @staticmethod
    def _client(tmp_path, monkeypatch, trait_rows=None, links=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import app.routers.conservatory as module
        from runtime.conservatory_environment import ConservatoryEnvironmentStore
        from runtime.conservatory_events import ConservatoryEventStore
        from runtime.conservatory_locations import ConservatoryLocationStore
        from runtime.conservatory_store import ConservatoryStore

        class Store:
            def __init__(self):
                self.candidates = trait_rows or []
                self.evidence_links = links or []

        monkeypatch.setattr(module, "_candidate_repository", lambda: Store())
        plants = ConservatoryStore(tmp_path)
        locations = ConservatoryLocationStore(tmp_path)
        app = FastAPI()
        app.include_router(
            module.create_conservatory_router(
                get_store=lambda: plants,
                require_owner=lambda: {"sub": "owner"},
                get_locations=lambda: locations,
                get_environment=lambda: ConservatoryEnvironmentStore(tmp_path),
                get_events=lambda: ConservatoryEventStore(tmp_path),
            )
        )
        return TestClient(app), plants, locations

    @staticmethod
    def _trait_row():
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

    def test_a_cold_plant_and_a_warm_one_land_in_different_groups(
        self, tmp_path, monkeypatch
    ):
        client, plants, locations = self._client(
            tmp_path, monkeypatch, [self._trait_row()], [self._link()]
        )
        cold_bench = locations.create_location(
            name="Cold bench", kind="greenhouse_bench"
        )
        warm_bench = locations.create_location(
            name="Warm bench", kind="greenhouse_bench"
        )
        for bench, value in ((cold_bench, 8.0), (warm_bench, 20.0)):
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
        cold = plants.create(
            display_name="Cold one", accepted_scientific_name="Cattleya skinneri"
        )
        warm = plants.create(
            display_name="Warm one", accepted_scientific_name="Cattleya skinneri"
        )
        for row, bench in ((cold, cold_bench), (warm, warm_bench)):
            client.post(
                f"/api/conservatory/plants/{row['id']}/placement",
                json={"location_id": bench["id"], "reason": "initial"},
            )

        review = client.get("/api/conservatory/collection/review").json()

        assert [r["plant_id"] for r in review["groups"]["outside"]] == [cold["id"]]
        assert [r["plant_id"] for r in review["groups"]["within"]] == [warm["id"]]
        assert review["anything_assessed"] is True

    def test_the_collection_view_and_the_dossier_agree(self, tmp_path, monkeypatch):
        """Two comparison paths would disagree eventually. There is only one."""
        client, plants, locations = self._client(
            tmp_path, monkeypatch, [self._trait_row()], [self._link()]
        )
        bench = locations.create_location(name="Cold bench", kind="greenhouse_bench")
        client.post(
            f"/api/conservatory/locations/{bench['id']}/environment",
            json={
                "variable": "temperature_c",
                "value": 8.0,
                "origin": "measured",
                "instrument": "Probe A",
                "observed_at": "2026-08-23T06:00:00+00:00",
            },
        )
        row = plants.create(
            display_name="Cold one", accepted_scientific_name="Cattleya skinneri"
        )
        client.post(
            f"/api/conservatory/plants/{row['id']}/placement",
            json={"location_id": bench["id"], "reason": "initial"},
        )

        review = client.get("/api/conservatory/collection/review").json()
        dossier = client.get(
            f"/api/conservatory/plants/{row['id']}/placement-assessment"
        ).json()

        listed = review["groups"]["outside"][0]["breaches"]
        from_dossier = [
            {"variable": a["variable"], "breached": a["breached"]}
            for a in dossier["assessments"]
            if a["outcome"] == "outside"
        ]
        assert listed == from_dossier

    def test_an_unreadable_store_leaves_the_collection_unassessed_and_says_why(
        self, tmp_path, monkeypatch
    ):
        import app.routers.conservatory as module

        client, plants, locations = self._client(tmp_path, monkeypatch)
        monkeypatch.setattr(module, "_candidate_repository", lambda: None)
        bench = locations.create_location(name="Cold bench", kind="greenhouse_bench")
        client.post(
            f"/api/conservatory/locations/{bench['id']}/environment",
            json={
                "variable": "temperature_c",
                "value": 8.0,
                "origin": "measured",
                "instrument": "Probe A",
                "observed_at": "2026-08-23T06:00:00+00:00",
            },
        )
        row = plants.create(
            display_name="Cold one", accepted_scientific_name="Cattleya skinneri"
        )
        client.post(
            f"/api/conservatory/plants/{row['id']}/placement",
            json={"location_id": bench["id"], "reason": "initial"},
        )

        review = client.get("/api/conservatory/collection/review").json()

        assert review["groups"]["outside"] == []
        assert review["anything_assessed"] is False
        assert review["requirement_source_unread_for"] == 1

    def test_the_review_is_owner_gated(self, tmp_path):
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

        # The whole holding in one response is the most sensitive shape here.
        assert (
            TestClient(app).get("/api/conservatory/collection/review").status_code
            == 401
        )


@pytest.mark.parametrize("group", REVIEW_GROUPS)
def test_every_group_is_always_present_even_when_empty(group):
    # A missing key reads as zero to some callers and as an error to others.
    assert group in build_collection_review([])["groups"]


class TestHowOldTheNumbersWere:
    """A collection list is where a season-old reading passes as this morning's.

    The per-plant panel at least shows one reading a grower might recognise. A
    list of two hundred rows shows none of them, so if the age does not travel
    into the row it is gone entirely.
    """

    def test_each_row_carries_the_age_behind_its_verdict(self):
        review = build_collection_review(
            [
                (
                    plant("p1"),
                    {
                        **assessment({"outside": 1}),
                        "oldest_verdict_condition_age_days": 212.0,
                    },
                )
            ]
        )

        assert (
            review["groups"]["outside"][0]["oldest_verdict_condition_age_days"] == 212.0
        )

    def test_an_unknown_age_travels_as_unknown_not_as_zero(self):
        review = build_collection_review([(plant("p1"), assessment({"outside": 1}))])

        assert (
            review["groups"]["outside"][0]["oldest_verdict_condition_age_days"] is None
        )
