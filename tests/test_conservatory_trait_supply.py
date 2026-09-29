"""Reading trait evidence out of the real candidate store, and surviving its absence.

The point of these tests is not that the adapter reshapes rows correctly —
test_conservatory_requirement_source.py covers that. It is that the route now
actually consults the store the Continuum keeps, and that a store which cannot
be read produces a different answer from a store that holds nothing.

Those two must stay distinguishable. A grower reading "no minimum temperature
is known for this taxon" is being told something about the literature. If an
outage can produce the same sentence, the sentence is worthless.
"""

import pytest

from runtime.conservatory_trait_supply import (
    TRAIT_SOURCE_UNAVAILABLE,
    TraitSupply,
    supply_from_repository,
)


class FakeRepository:
    """The two attributes and one method the supplier touches."""

    def __init__(self, candidates=None, evidence_links=None, refresh_raises=False):
        self.candidates = candidates or []
        self.evidence_links = evidence_links or []
        self._refresh_raises = refresh_raises
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1
        if self._refresh_raises:
            raise RuntimeError("database unreachable")


def trait_row(**overrides):
    base = {
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
    base.update(overrides)
    return base


def anchor_link(candidate_id=11, anchor_id=401, revision_id=41):
    return {
        "evidence_link_id": 1,
        "candidate_id": candidate_id,
        "revision_id": revision_id,
        "anchor": {"anchor_id": anchor_id, "ordered_span": 0},
    }


class TestReadingTheStore:
    def test_a_stored_trait_reaches_the_resolver_shape(self):
        supply = supply_from_repository(
            "Cattleya skinneri",
            FakeRepository([trait_row()], [anchor_link()]),
        )

        assert supply.available is True
        assert supply.unavailable_reason is None
        assert [row["numeric_value"] for row in supply.candidates] == [15.0]
        assert supply.candidates[0]["source_anchor_ids"] == [401]

    def test_the_store_is_refreshed_before_reading(self):
        # A long-lived worker holding a cached snapshot would serve whatever it
        # last saw, which can be hours behind the evidence a reviewer just
        # accepted.
        repository = FakeRepository([trait_row()], [anchor_link()])

        supply_from_repository("Cattleya skinneri", repository)

        assert repository.refreshed == 1

    def test_an_empty_store_is_available_and_empty(self):
        supply = supply_from_repository("Cattleya skinneri", FakeRepository())

        assert supply.available is True
        assert supply.candidates == []


class TestSurvivingItsAbsence:
    def test_no_repository_is_unavailable_not_empty(self):
        supply = supply_from_repository("Cattleya skinneri", None)

        assert supply.available is False
        assert supply.unavailable_reason == TRAIT_SOURCE_UNAVAILABLE
        assert supply.candidates == []

    def test_a_failing_refresh_is_unavailable(self):
        supply = supply_from_repository(
            "Cattleya skinneri",
            FakeRepository([trait_row()], [anchor_link()], refresh_raises=True),
        )

        assert supply.unavailable_reason == TRAIT_SOURCE_UNAVAILABLE

    def test_a_partial_read_is_discarded_rather_than_passed_forward(self):
        """A store that breaks mid-read yields an unknown fraction of itself.

        Keeping what arrived would let a plant assess `within` a maximum whose
        matching minimum had not loaded — a verdict built on the half of the
        evidence that happened to be fast.
        """

        class HalfBroken(FakeRepository):
            @property
            def evidence_links(self):
                raise RuntimeError("connection reset mid-read")

            @evidence_links.setter
            def evidence_links(self, value):
                pass

        supply = supply_from_repository(
            "Cattleya skinneri", HalfBroken([trait_row()], [])
        )

        assert supply.unavailable_reason == TRAIT_SOURCE_UNAVAILABLE
        assert supply.candidates == []

    def test_a_malformed_row_is_unavailable_rather_than_quietly_skipped(self):
        """A row the adapter cannot read means the store is not what we think.

        Skipping it would drop an unknown requirement without a trace, and the
        grower would be told the literature is silent about a bound that is
        sitting in the store in a shape we failed to parse.
        """
        supply = supply_from_repository(
            "Cattleya skinneri",
            FakeRepository(["not a candidate row"], [anchor_link()]),
        )

        assert supply.unavailable_reason == TRAIT_SOURCE_UNAVAILABLE
        assert supply.candidates == []

    def test_a_repository_of_the_wrong_shape_is_unavailable_not_a_crash(self):
        supply = supply_from_repository("Cattleya skinneri", object())

        assert supply.unavailable_reason == TRAIT_SOURCE_UNAVAILABLE


class TestThroughTheRoute:
    """The wiring itself: seed the store the deployment uses, ask the route."""

    @staticmethod
    def _client(tmp_path, repository, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import app.routers.conservatory as module
        from runtime.conservatory_environment import ConservatoryEnvironmentStore
        from runtime.conservatory_events import ConservatoryEventStore
        from runtime.conservatory_locations import ConservatoryLocationStore
        from runtime.conservatory_store import ConservatoryStore

        # Patched at the locator, not at the supplier: this exercises the real
        # _default_trait_evidence, which is the code the deployment runs.
        monkeypatch.setattr(module, "_candidate_repository", lambda: repository)

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
    def _cold_bench_plant(client, plants, locations):
        plant = plants.create(
            display_name="Cattleya", accepted_scientific_name="Cattleya skinneri"
        )
        bench = locations.create_location(name="Cold bench", kind="greenhouse_bench")
        client.post(
            f"/api/conservatory/plants/{plant['id']}/placement",
            json={"location_id": bench["id"], "reason": "initial"},
        )
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
        return plant

    def test_evidence_in_the_store_produces_a_verdict_through_the_default_path(
        self, tmp_path, monkeypatch
    ):
        repository = FakeRepository([trait_row()], [anchor_link()])
        client, plants, locations = self._client(tmp_path, repository, monkeypatch)
        plant = self._cold_bench_plant(client, plants, locations)

        result = client.get(
            f"/api/conservatory/plants/{plant['id']}/placement-assessment"
        ).json()

        temperature = next(
            row for row in result["assessments"] if row["variable"] == "temperature_c"
        )
        assert temperature["outcome"] == "outside"
        assert temperature["breached"] == [{"bound": "minimum", "limit": 15.0}]
        assert result["requirement_source_consulted"] is True

    def test_an_unreachable_store_says_so_rather_than_reporting_no_evidence(
        self, tmp_path, monkeypatch
    ):
        client, plants, locations = self._client(tmp_path, None, monkeypatch)
        plant = self._cold_bench_plant(client, plants, locations)

        result = client.get(
            f"/api/conservatory/plants/{plant['id']}/placement-assessment"
        ).json()

        temperature = next(
            row for row in result["assessments"] if row["variable"] == "temperature_c"
        )
        assert temperature["outcome"] == "unassessable"
        assert temperature["reason"] == "REQUIREMENT_SOURCE_UNAVAILABLE"
        assert result["requirement_source_consulted"] is False

    def test_an_unreachable_store_does_not_take_the_dossier_down_with_it(
        self, tmp_path, monkeypatch
    ):
        """Everything the grower recorded is theirs and stays available.

        The knowledge store is consulted, not depended on. A plant's placement,
        its bench, and its readings do not become unavailable because a
        literature store is.
        """
        client, plants, locations = self._client(tmp_path, None, monkeypatch)
        plant = self._cold_bench_plant(client, plants, locations)

        response = client.get(
            f"/api/conservatory/plants/{plant['id']}/cultivation-context"
        )

        assert response.status_code == 200
        context = response.json()
        assert context["conditions"]["temperature_c"]["value"] == 8.0
        requirements = context["taxon_requirements"]
        assert requirements["claim_class"] == "absent"
        assert requirements["reason"] == TRAIT_SOURCE_UNAVAILABLE
        assert requirements["source_consulted"] is False

    def test_an_unreachable_store_never_reports_an_evidence_backed_bound(
        self, tmp_path, monkeypatch
    ):
        """Candidates cannot sneak past an outage.

        If a partial read ever reached the resolver, this is the shape it would
        take: rows present, store broken. The verdict must still be that we did
        not look.
        """
        from runtime.conservatory_calyx_context import build_cultivation_context

        context = build_cultivation_context(
            plant={"accepted_scientific_name": "Cattleya skinneri"},
            placement_current=None,
            placement_history=[],
            location=None,
            environment=None,
            events=None,
            trait_candidates=[
                {
                    "predicate": "minimum_temperature",
                    "numeric_value": 15.0,
                    "unit": "degrees Celsius",
                    "source_anchor_ids": [401],
                    "status": "ACTIVE",
                }
            ],
            trait_source_unavailable=TRAIT_SOURCE_UNAVAILABLE,
        )

        requirements = context["taxon_requirements"]
        assert requirements["value"] is None
        assert requirements["claim_class"] == "absent"
        assert requirements["reason"] == TRAIT_SOURCE_UNAVAILABLE


class TestTheSupplyShapeItself:
    def test_a_reason_makes_it_unavailable(self):
        assert TraitSupply([], "SOMETHING").available is False

    def test_no_reason_makes_it_available(self):
        assert TraitSupply([]).available is True

    @pytest.mark.parametrize("taxon", [None, "", "   "])
    def test_no_taxon_yields_nothing_but_is_not_an_outage(self, taxon):
        supply = supply_from_repository(
            taxon, FakeRepository([trait_row()], [anchor_link()])
        )

        assert supply.candidates == []
        assert supply.available is True


class TestTheLocator:
    """`_candidate_repository` is the only place that knows where the store lives.

    Its two jobs: hand back the deployment's repository, and turn any failure
    reaching it — no database configured, a driver that is not installed, the
    503 the candidate package raises — into None rather than an exception that
    would take a plant's dossier down.
    """

    def test_it_returns_the_repository_the_candidate_package_provides(
        self, monkeypatch
    ):
        import sys
        import types

        import app.routers.conservatory as module

        repository = FakeRepository()
        fake = types.ModuleType("app.candidate_knowledge.dependencies")
        fake.get_candidate_components = lambda: (repository, object())
        monkeypatch.setitem(sys.modules, "app.candidate_knowledge.dependencies", fake)

        assert module._candidate_repository() is repository

    def test_an_unavailable_candidate_package_becomes_none_not_an_exception(
        self, monkeypatch
    ):
        import sys
        import types

        import app.routers.conservatory as module

        def unavailable():
            raise RuntimeError("CANDIDATE_DATABASE_UNAVAILABLE")

        fake = types.ModuleType("app.candidate_knowledge.dependencies")
        fake.get_candidate_components = unavailable
        monkeypatch.setitem(sys.modules, "app.candidate_knowledge.dependencies", fake)

        assert module._candidate_repository() is None
