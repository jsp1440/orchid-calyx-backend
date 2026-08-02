from runtime.world_plants_delta import CrosswalkCandidate
from runtime.world_plants_impact import (
    audit_downstream_impact,
    read_only_query_contract,
)


def candidate(classification: str, row: int = 2) -> CrosswalkCandidate:
    return CrosswalkCandidate(
        previous_row=row,
        current_row=3,
        previous_name="Old name",
        current_name="New name",
        classification=classification,
        confidence="authority_exact",
        evidence=("world_plants_number",),
        automatic_acceptance=False,
    )


def test_unchanged_low_volume_mapping_is_low_risk():
    audit = audit_downstream_impact(
        [candidate("unchanged")],
        {2: {"images": 50, "occurrences": 10}},
    )
    assert audit.taxa[0].risk_level == "low"
    assert audit.promotion_blocked is False
    assert audit.domain_totals["images"] == 50


def test_ambiguous_mapping_blocks_promotion():
    audit = audit_downstream_impact(
        [candidate("ambiguous")],
        {2: {"images": 5}},
    )
    assert audit.taxa[0].risk_level == "high"
    assert "unresolved_ambiguous_mapping" in audit.taxa[0].blockers
    assert audit.promotion_blocked is True


def test_large_fanout_is_critical():
    audit = audit_downstream_impact(
        [candidate("genus_transfer")],
        {2: {"images": 100000}},
    )
    assert audit.taxa[0].risk_level == "critical"
    assert "very_large_downstream_fanout" in audit.taxa[0].blockers


def test_negative_counts_are_clamped_to_zero():
    audit = audit_downstream_impact(
        [candidate("unchanged")],
        {2: {"images": -4}},
    )
    assert audit.taxa[0].domain_counts["images"] == 0


def test_query_contract_is_select_only():
    contract = read_only_query_contract()
    assert contract["mutation_policy"].startswith("SELECT-only")
