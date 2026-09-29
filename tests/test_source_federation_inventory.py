from dataclasses import replace

from app.source_federation import (
    AccessState,
    CandidateDisposition,
    FederationCandidate,
    RightsState,
    build_default_candidate_inventory,
    deduplicate_candidates,
)


def _candidate(**overrides: object) -> FederationCandidate:
    base = FederationCandidate(
        source_owner="Example",
        source_name="Dataset",
        identity="doi:10.0000/example",
        access=AccessState.REPOSITORY,
        rights=RightsState.OPEN,
        domains=("traits",),
        identifiers=("10.0000/example",),
        overlap="none",
        incremental_value="bounded fixture",
        taxonomy_reconciliation="retain source string and reconcile separately",
        provenance_contract="preserve source identity and hash",
        locality_risk="low",
        implementation_cost="low",
        requested_disposition=CandidateDisposition.ADD,
        license_identifier="CC-BY-4.0",
        source_url="https://example.org/dataset",
        update_cadence="annual",
        metadata_evidence=("https://example.org/metadata",),
    )
    return replace(base, **overrides)


def test_unknown_rights_fail_closed_to_defer() -> None:
    candidate = _candidate(rights=RightsState.UNKNOWN)
    assert candidate.disposition is CandidateDisposition.DEFER


def test_unknown_access_fail_closed_to_defer() -> None:
    candidate = _candidate(access=AccessState.UNKNOWN)
    assert candidate.disposition is CandidateDisposition.DEFER


def test_restricted_rights_reject_even_if_add_was_requested() -> None:
    candidate = _candidate(rights=RightsState.RESTRICTED)
    assert candidate.disposition is CandidateDisposition.REJECT


def test_add_without_explicit_license_identifier_fails_closed() -> None:
    candidate = _candidate(license_identifier=None)

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "license_identifier_missing" in candidate.admission_blockers


def test_add_without_provenance_contract_fails_closed() -> None:
    candidate = _candidate(provenance_contract="")

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "provenance_contract_missing" in candidate.admission_blockers


def test_add_without_stable_source_identifier_fails_closed() -> None:
    candidate = _candidate(identifiers=())

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "source_identifier_missing" in candidate.admission_blockers


def test_add_without_primary_metadata_evidence_fails_closed() -> None:
    candidate = _candidate(metadata_evidence=())

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "metadata_evidence_missing" in candidate.admission_blockers


def test_add_without_source_url_fails_closed() -> None:
    candidate = _candidate(source_url=None)

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "source_url_missing" in candidate.admission_blockers


def test_add_without_known_update_cadence_fails_closed() -> None:
    candidate = _candidate(update_cadence="unknown")

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "update_cadence_unknown" in candidate.admission_blockers


def test_high_locality_risk_requires_declared_controls() -> None:
    candidate = _candidate(locality_risk="high: precise specimen coordinates")

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "locality_controls_missing" in candidate.admission_blockers


def test_high_locality_risk_can_advance_only_with_declared_controls() -> None:
    candidate = _candidate(
        locality_risk="high: precise specimen coordinates",
        locality_controls=("strip_precise_coordinates", "respect_source_obscuring"),
    )

    assert candidate.disposition is CandidateDisposition.ADD
    assert candidate.admission_blockers == ()


def test_unclassified_locality_risk_fails_closed() -> None:
    candidate = _candidate(locality_risk="review later")

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "locality_risk_unclassified" in candidate.admission_blockers


def test_unknown_locality_risk_cannot_be_overridden_by_generic_controls() -> None:
    candidate = _candidate(
        locality_risk="unknown",
        locality_controls=("strip_precise_coordinates",),
    )

    assert candidate.disposition is CandidateDisposition.DEFER
    assert "locality_risk_unknown" in candidate.admission_blockers


def test_deduplication_is_stable_and_source_identity_based() -> None:
    first = _candidate()
    duplicate = replace(first, incremental_value="same source, changed commentary")
    distinct = replace(first, identity="doi:10.0000/other")

    assert deduplicate_candidates((first, duplicate, distinct)) == (first, distinct)


def test_default_inventory_covers_major_first_slice_families() -> None:
    inventory = build_default_candidate_inventory()
    domains = {domain for candidate in inventory for domain in candidate.domains}

    assert {
        "pollination",
        "mycorrhiza",
        "molecular",
        "occurrence",
        "media",
        "conservation",
    } <= domains
    assert len({candidate.fingerprint for candidate in inventory}) == len(inventory)


def test_pollination_candidate_records_evidence_but_remains_deferred() -> None:
    candidate = build_default_candidate_inventory()[0]

    assert candidate.source_owner == "Ackerman et al."
    assert candidate.identifiers[:2] == (
        "10.5281/zenodo.14601785",
        "10.5281/zenodo.7263689",
    )
    assert candidate.source_url == "https://zenodo.org/records/14601785"
    assert candidate.update_cadence.startswith("irregular depositor-driven")
    assert len(candidate.metadata_evidence) == 3
    assert candidate.locality_risk.startswith("high:")
    assert "strip_precise_coordinates" in candidate.locality_controls
    assert candidate.rights is RightsState.UNKNOWN
    assert candidate.license_identifier is None
    assert candidate.disposition is CandidateDisposition.DEFER
    assert "rights remain UNKNOWN and DEFER" in candidate.verification_note


def test_default_inventory_never_auto_adds_unknown_rights() -> None:
    inventory = build_default_candidate_inventory()

    assert all(
        candidate.disposition is not CandidateDisposition.ADD
        for candidate in inventory
        if candidate.rights is RightsState.UNKNOWN
        or candidate.access is AccessState.UNKNOWN
    )
