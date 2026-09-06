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


def test_deduplication_is_stable_and_source_identity_based() -> None:
    first = _candidate()
    duplicate = replace(first, incremental_value="same source, changed commentary")
    distinct = replace(first, identity="doi:10.0000/other")

    assert deduplicate_candidates((first, duplicate, distinct)) == (first, distinct)


def test_default_inventory_covers_major_first_slice_families() -> None:
    inventory = build_default_candidate_inventory()
    domains = {domain for candidate in inventory for domain in candidate.domains}

    assert {"pollination", "mycorrhiza", "molecular", "occurrence", "media", "conservation"} <= domains
    assert len({candidate.fingerprint for candidate in inventory}) == len(inventory)


def test_default_inventory_never_auto_adds_unknown_rights() -> None:
    inventory = build_default_candidate_inventory()

    assert all(
        candidate.disposition is not CandidateDisposition.ADD
        for candidate in inventory
        if candidate.rights is RightsState.UNKNOWN or candidate.access is AccessState.UNKNOWN
    )
