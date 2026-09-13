"""Adapting stored trait candidates into the requirement resolver's shape.

The store and the resolver do not agree on how a claim looks, and the gap is
exactly where a defect hides: anchors live in a separate table, there is no
verification state at all, and supersession is an `active` flag. These tests
are written against the shape the store really produces, taken from
app/candidate_knowledge/service.py, not one that looks plausible.
"""

from runtime.conservatory_requirement_source import TRAIT_KIND, collect_trait_candidates
from runtime.conservatory_taxon_requirements import resolve_taxon_requirements
from runtime.conservatory_trait_supply import TraitSupply


def stored(**overrides):
    """A candidate in the shape candidate_knowledge/service.py actually writes."""
    base = {
        "candidate_id": 7,
        "kind": TRAIT_KIND,
        "normalized_subject": "Cattleya skinneri",
        "predicate": "minimum_temperature",
        "object_value": None,
        "numeric_value": 12.0,
        "unit": "degrees Celsius",
        "confidence": 0.7,
        "extraction_method": "DIRECT",
        "version": 1,
        "active": True,
        "review_state": "REQUIRED",
        "published": False,
    }
    base.update(overrides)
    return base


def link(candidate_id=7, anchor_id=401, revision_id=41):
    return {
        "candidate_id": candidate_id,
        "revision_id": revision_id,
        "anchor": {"anchor_id": anchor_id},
    }


class TestItReadsTheStoresRealShape:
    def test_anchors_come_from_the_evidence_links_table(self):
        # They are not on the candidate. Assuming they were would produce
        # anchorless claims the resolver then silently refuses.
        collected = collect_trait_candidates(
            "Cattleya skinneri", candidates=[stored()], evidence_links=[link()]
        )
        assert collected[0]["source_anchor_ids"] == [401]
        assert collected[0]["source_revision_id"] == 41

    def test_a_candidate_with_no_links_yields_no_anchors(self):
        # And the resolver then refuses it, which is correct: an untraceable
        # number is indistinguishable from an invented one.
        collected = collect_trait_candidates(
            "Cattleya skinneri", candidates=[stored()], evidence_links=[]
        )
        assert collected[0]["source_anchor_ids"] == []
        assert (
            resolve_taxon_requirements("Cattleya skinneri", collected)["known"] is False
        )

    def test_multiple_anchors_are_deduplicated_and_ordered(self):
        collected = collect_trait_candidates(
            "Cattleya skinneri",
            candidates=[stored()],
            evidence_links=[
                link(anchor_id=402),
                link(anchor_id=401),
                link(anchor_id=402),
            ],
        )
        assert collected[0]["source_anchor_ids"] == [401, 402]

    def test_no_verification_state_is_invented(self):
        # The store records none. Claiming one would manufacture the exact
        # assurance the resolver exists to report honestly.
        collected = collect_trait_candidates(
            "Cattleya skinneri", candidates=[stored()], evidence_links=[link()]
        )
        assert "verification_state" not in collected[0]
        resolved = resolve_taxon_requirements("Cattleya skinneri", collected)
        claim = resolved["requirements"]["temperature_c"]["bounds"]["minimum"][0]
        assert claim["evidence_strength"] == "unverified"

    def test_a_reviewed_candidate_reaches_the_resolver_as_reviewed(self):
        collected = collect_trait_candidates(
            "Cattleya skinneri",
            candidates=[stored(review_state="CLEAR")],
            evidence_links=[link()],
        )
        resolved = resolve_taxon_requirements("Cattleya skinneri", collected)
        claim = resolved["requirements"]["temperature_c"]["bounds"]["minimum"][0]
        assert claim["evidence_strength"] == "reviewed"


class TestOnlyLiveTraitClaimsForThisTaxon:
    def test_a_superseded_candidate_is_not_returned(self):
        """It describes what the Continuum used to think. Feeding it forward
        would let a corrected claim keep competing with its own correction."""
        collected = collect_trait_candidates(
            "Cattleya skinneri",
            candidates=[stored(active=False)],
            evidence_links=[link()],
        )
        assert collected == []

    def test_another_taxons_evidence_is_not_returned(self):
        collected = collect_trait_candidates(
            "Cattleya skinneri",
            candidates=[stored(normalized_subject="Phalaenopsis amabilis")],
            evidence_links=[link()],
        )
        assert collected == []

    def test_the_subject_matches_case_insensitively(self):
        # A collection recording one case should reach evidence filed under
        # another rather than silently missing it.
        collected = collect_trait_candidates(
            "cattleya skinneri", candidates=[stored()], evidence_links=[link()]
        )
        assert len(collected) == 1

    def test_a_non_trait_candidate_is_ignored(self):
        collected = collect_trait_candidates(
            "Cattleya skinneri",
            candidates=[stored(kind="TAXON")],
            evidence_links=[link()],
        )
        assert collected == []

    def test_a_predicate_that_is_not_a_requirement_is_ignored(self):
        collected = collect_trait_candidates(
            "Cattleya skinneri",
            candidates=[stored(predicate="flower_colour")],
            evidence_links=[link()],
        )
        assert collected == []

    def test_no_taxon_returns_nothing(self):
        assert (
            collect_trait_candidates(
                None, candidates=[stored()], evidence_links=[link()]
            )
            == []
        )
        assert (
            collect_trait_candidates(
                "  ", candidates=[stored()], evidence_links=[link()]
            )
            == []
        )


class TestEndToEndIntoARequirement:
    def test_a_stored_candidate_becomes_a_usable_requirement(self):
        collected = collect_trait_candidates(
            "Cattleya skinneri", candidates=[stored()], evidence_links=[link()]
        )
        resolved = resolve_taxon_requirements("Cattleya skinneri", collected)
        assert resolved["known"] is True
        claim = resolved["requirements"]["temperature_c"]["bounds"]["minimum"][0]
        assert claim["value"] == 12.0
        assert claim["source_anchor_ids"] == [401]

    def test_two_live_candidates_disagreeing_both_reach_the_resolver(self):
        collected = collect_trait_candidates(
            "Cattleya skinneri",
            candidates=[stored(), stored(candidate_id=8, numeric_value=15.0)],
            evidence_links=[link(), link(candidate_id=8, anchor_id=402)],
        )
        resolved = resolve_taxon_requirements("Cattleya skinneri", collected)
        claims = resolved["requirements"]["temperature_c"]["bounds"]["minimum"]
        assert sorted(claim["value"] for claim in claims) == [12.0, 15.0]

    def test_each_claim_carries_only_its_own_anchors(self):
        """Provenance must not cross-contaminate. If one claim inherits
        another's anchors, a reader tracing a number reaches a source that
        never made it — which is worse than no provenance, because it looks
        checked."""
        collected = collect_trait_candidates(
            "Cattleya skinneri",
            candidates=[stored(), stored(candidate_id=8, numeric_value=15.0)],
            evidence_links=[
                link(candidate_id=7, anchor_id=401, revision_id=41),
                link(candidate_id=8, anchor_id=402, revision_id=42),
            ],
        )
        by_value = {row["numeric_value"]: row for row in collected}
        assert by_value[12.0]["source_anchor_ids"] == [401]
        assert by_value[12.0]["source_revision_id"] == 41
        assert by_value[15.0]["source_anchor_ids"] == [402]
        assert by_value[15.0]["source_revision_id"] == 42


class TestThroughTheRouter:
    """Supplying trait evidence must actually change what the assessment says.

    Until now every variable resolved to unassessable because nothing fed the
    resolver. This is the test that proves the wiring carries evidence all the
    way to a verdict — and that the default supplier still yields nothing.
    """

    @staticmethod
    def _client(tmp_path, trait_supplier=None):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from app.routers.conservatory import create_conservatory_router
        from runtime.conservatory_environment import ConservatoryEnvironmentStore
        from runtime.conservatory_events import ConservatoryEventStore
        from runtime.conservatory_locations import ConservatoryLocationStore
        from runtime.conservatory_store import ConservatoryStore

        plants = ConservatoryStore(tmp_path)
        locations = ConservatoryLocationStore(tmp_path)
        kwargs = {
            "get_store": lambda: plants,
            "require_owner": lambda: {"sub": "owner"},
            "get_locations": lambda: locations,
            "get_environment": lambda: ConservatoryEnvironmentStore(tmp_path),
            "get_events": lambda: ConservatoryEventStore(tmp_path),
        }
        if trait_supplier is not None:
            kwargs["get_trait_evidence"] = trait_supplier
        app = FastAPI()
        app.include_router(create_conservatory_router(**kwargs))
        return TestClient(app), plants, locations

    @staticmethod
    def _plant_on_a_cold_bench(client, plants, locations):
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

    def test_supplied_evidence_turns_unassessable_into_a_real_verdict(self, tmp_path):
        def supplier(taxon):
            return TraitSupply(
                collect_trait_candidates(
                    taxon,
                    candidates=[stored(numeric_value=15.0)],
                    evidence_links=[link()],
                )
            )

        client, plants, locations = self._client(tmp_path, supplier)
        plant = self._plant_on_a_cold_bench(client, plants, locations)

        result = client.get(
            f"/api/conservatory/plants/{plant['id']}/placement-assessment"
        ).json()
        temperature = next(
            row for row in result["assessments"] if row["variable"] == "temperature_c"
        )
        assert temperature["outcome"] == "outside"
        assert temperature["breached"] == [{"bound": "minimum", "limit": 15.0}]
        assert result["anything_assessed"] is True
        # Still not advice, however clear the breach.
        assert result["is_recommendation"] is False

    def test_the_envelope_carries_the_same_evidence(self, tmp_path):
        def supplier(taxon):
            return TraitSupply(
                collect_trait_candidates(
                    taxon, candidates=[stored()], evidence_links=[link()]
                )
            )

        client, plants, locations = self._client(tmp_path, supplier)
        plant = self._plant_on_a_cold_bench(client, plants, locations)

        context = client.get(
            f"/api/conservatory/plants/{plant['id']}/cultivation-context"
        ).json()
        requirements = context["taxon_requirements"]
        assert requirements["claim_class"] == "literature_derived"
        assert (
            requirements["value"]["temperature_c"]["bounds"]["minimum"][0]["value"]
            == 12.0
        )

    def test_an_empty_store_still_yields_no_evidence(self, tmp_path, monkeypatch):
        # The default supplier now consults the real candidate store. With
        # nothing in it the answer is still "no evidence" — but it is a read
        # that returned nothing, not a refusal to look.
        #
        # The store is stubbed rather than left to the ambient default so this
        # asserts the empty-store path in every environment, including ones
        # where the database driver is not installed and the real default would
        # instead report unavailability.
        import app.routers.conservatory as module

        class EmptyStore:
            def __init__(self):
                self.candidates = []
                self.evidence_links = []

        monkeypatch.setattr(module, "_candidate_repository", lambda: EmptyStore())
        client, plants, locations = self._client(tmp_path)
        plant = self._plant_on_a_cold_bench(client, plants, locations)

        result = client.get(
            f"/api/conservatory/plants/{plant['id']}/placement-assessment"
        ).json()
        temperature = next(
            row for row in result["assessments"] if row["variable"] == "temperature_c"
        )
        assert temperature["outcome"] == "unassessable"
        assert temperature["reason"] == "NO_REQUIREMENT_EVIDENCE"
        assert result["anything_assessed"] is False
        assert result["requirement_source_consulted"] is True
