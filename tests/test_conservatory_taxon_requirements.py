"""What the Continuum knows about a taxon's cultivation requirements.

It would be easy, and wrong, to ship a table saying Cattleya wants 18-28C.
Numbers like that are claims about the world, and a claim with no source is
indistinguishable from an invention once it is in the record. These tests hold
the line that every requirement traces back to evidence, and that the absence
of evidence surfaces as absence rather than as a default a grower might act on.
"""

from runtime.conservatory_taxon_requirements import (
    REQUIREMENT_PREDICATES,
    EvidenceStrength,
    resolve_taxon_requirements,
)


def candidate(**overrides):
    base = {
        "predicate": "minimum_temperature",
        "numeric_value": 12.0,
        "unit": "degrees Celsius",
        "source_anchor_ids": [401],
        "source_revision_id": 41,
        "verification_state": "UNVERIFIED",
        "review_state": "REQUIRED",
        "status": "ACTIVE",
        "directness": "DIRECT",
        "confidence": 0.7,
    }
    base.update(overrides)
    return base


class TestNothingIsInvented:
    def test_a_taxon_with_no_evidence_is_unknown_not_defaulted(self):
        """The normal case for most taxa in most collections. A default range
        would be acted on, and a grower moving a plant because of a fabricated
        minimum has been actively misled."""
        result = resolve_taxon_requirements("Cattleya skinneri", [])
        assert result["known"] is False
        assert result["requirements"] == {}
        assert result["reason"] == "NO_CULTIVATION_EVIDENCE_FOR_THIS_TAXON"
        assert result["claim_class"] == "absent"

    def test_no_taxon_at_all_is_its_own_answer(self):
        # A plant whose name nobody has recorded is a different situation from
        # a named taxon nobody has studied.
        result = resolve_taxon_requirements(None, [candidate()])
        assert result["known"] is False
        assert result["reason"] == "NO_TAXON_SUPPLIED"

    def test_a_claim_without_source_anchors_is_not_usable(self):
        # Without anchors the number cannot be traced back to anything, which
        # is the same position as having invented it.
        result = resolve_taxon_requirements(
            "Cattleya", [candidate(source_anchor_ids=[])]
        )
        assert result["known"] is False

    def test_a_free_text_trait_is_not_turned_into_a_number(self):
        # "Cool growing" says something real and cannot be compared against a
        # thermometer; coercing it would invent precision.
        result = resolve_taxon_requirements(
            "Cattleya", [candidate(numeric_value=None, object_value="cool growing")]
        )
        assert result["known"] is False

    def test_a_withdrawn_or_superseded_claim_is_never_used(self):
        for status in ["WITHDRAWN", "SUPERSEDED", "REJECTED"]:
            result = resolve_taxon_requirements("Cattleya", [candidate(status=status)])
            assert result["known"] is False, status


class TestEvidenceStrengthSurvives:
    def test_an_unverified_claim_arrives_marked_unverified(self):
        # A grower acting on a range is entitled to know whether anybody
        # checked it.
        result = resolve_taxon_requirements("Cattleya", [candidate()])
        claim = result["requirements"]["temperature_c"]["bounds"]["minimum"][0]
        assert claim["evidence_strength"] == EvidenceStrength.UNVERIFIED

    def test_a_verified_claim_is_distinguishable(self):
        result = resolve_taxon_requirements(
            "Cattleya", [candidate(verification_state="VERIFIED")]
        )
        claim = result["requirements"]["temperature_c"]["bounds"]["minimum"][0]
        assert claim["evidence_strength"] == EvidenceStrength.VERIFIED

    def test_a_reviewed_claim_sits_between_the_two(self):
        result = resolve_taxon_requirements(
            "Cattleya", [candidate(review_state="CLEAR")]
        )
        claim = result["requirements"]["temperature_c"]["bounds"]["minimum"][0]
        assert claim["evidence_strength"] == EvidenceStrength.REVIEWED

    def test_the_source_travels_with_the_number(self):
        result = resolve_taxon_requirements("Cattleya", [candidate()])
        claim = result["requirements"]["temperature_c"]["bounds"]["minimum"][0]
        assert claim["source_anchor_ids"] == [401]
        assert claim["source_revision_id"] == 41
        assert claim["directness"] == "DIRECT"


class TestDisagreementIsNotAveraged:
    def test_two_sources_disagreeing_are_both_kept(self):
        """Two sources disagreeing about a minimum is information. Their mean
        is a number no source stated."""
        result = resolve_taxon_requirements(
            "Cattleya",
            [
                candidate(numeric_value=10.0),
                candidate(numeric_value=15.0, source_anchor_ids=[402]),
            ],
        )
        claims = result["requirements"]["temperature_c"]["bounds"]["minimum"]
        assert sorted(claim["value"] for claim in claims) == [10.0, 15.0]

    def test_minimum_and_maximum_are_separate_bounds(self):
        result = resolve_taxon_requirements(
            "Cattleya",
            [
                candidate(),
                candidate(predicate="maximum_temperature", numeric_value=30.0),
            ],
        )
        bounds = result["requirements"]["temperature_c"]["bounds"]
        assert bounds["minimum"][0]["value"] == 12.0
        assert bounds["maximum"][0]["value"] == 30.0


class TestUnitsMustMatch:
    def test_a_mismatched_unit_is_refused_not_converted(self):
        # A unit mismatch is not a weaker claim, it is a different
        # measurement. Accepting it silently would compare Fahrenheit against
        # Celsius.
        result = resolve_taxon_requirements(
            "Cattleya", [candidate(unit="degrees Fahrenheit")]
        )
        assert result["known"] is False

    def test_an_unstated_unit_is_accepted_against_the_predicates_own_unit(self):
        # The predicate itself fixes the unit; a candidate that simply did not
        # repeat it is not making a different claim.
        result = resolve_taxon_requirements("Cattleya", [candidate(unit=None)])
        assert result["known"] is True

    def test_every_predicate_declares_a_variable_and_a_unit(self):
        for predicate, mapping in REQUIREMENT_PREDICATES.items():
            assert mapping["variable"], predicate
            assert mapping["unit"], predicate
            assert mapping["bound"] in {"minimum", "maximum"}, predicate


class TestScopeAndSelfDescription:
    def test_a_predicate_that_is_not_a_requirement_is_ignored(self):
        result = resolve_taxon_requirements(
            "Cattleya", [candidate(predicate="flower_colour")]
        )
        assert result["known"] is False

    def test_the_result_says_it_is_not_scientific_evidence(self):
        # The derivation is not itself a published finding.
        known = resolve_taxon_requirements("Cattleya", [candidate()])
        assert known["is_scientific_evidence"] is False
        assert known["claim_class"] == "literature_derived_claim"
        assert (
            resolve_taxon_requirements("Cattleya", [])["is_scientific_evidence"]
            is False
        )

    def test_it_offers_no_verdict_about_any_plant(self):
        # The comparison belongs beyond this boundary; this module answers only
        # what is known about the taxon.
        result = resolve_taxon_requirements("Cattleya", [candidate()])
        for forbidden in [
            "suitable",
            "verdict",
            "recommendation",
            "should_move",
            "score",
        ]:
            assert forbidden not in result
