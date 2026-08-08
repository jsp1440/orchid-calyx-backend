from runtime.australian_diurideae_propagation_bridge import (
    bridge_matrix,
    diuris_observations,
    diuris_source,
    non_destructive_bridge_assessment,
    phylogenetic_bridge,
)


def test_diuris_source_is_proximal_australian_tuberous_comparator():
    source = diuris_source()
    assert source.taxon == "Diuris longifolia"
    assert source.tribe == "Diurideae"
    assert source.subtribe == "Diuridinae"
    assert "tuberous" in source.growth_form
    assert source.doi == "10.1071/EA9920131"


def test_diuris_preserves_two_non_destructive_plb_entry_explants():
    observations = diuris_observations()
    plb = [item for item in observations if item.response == "protocorm-like bodies formed"]
    assert len(plb) == 2
    assert {item.explant for item in plb} == {
        "basal section of unopened flower bud",
        "axillary node from inflorescence",
    }
    assert all(item.response_time_days == 49.0 for item in plb)
    assert all(item.destructive_parent_sampling_required is False for item in plb)


def test_phylogenetic_bridge_is_proximity_not_same_subtribe_or_transfer_proof():
    bridge = phylogenetic_bridge()
    assert bridge["focal_subtribe"] == "Thelymitrinae"
    assert bridge["comparator_subtribe"] == "Diuridinae"
    assert bridge["same_subtribe"] is False
    assert bridge["direct_thelymitra_evidence"] is False
    assert bridge["method_transfer_validated"] is False
    assert bridge["success_probability_generated"] is False


def test_non_destructive_bridge_does_not_select_thelymitra_explant():
    assessment = non_destructive_bridge_assessment()
    assert assessment["answer_state"] == "documented_in_diuris_longifolia"
    assert len(assessment["supporting_observation_ids"]) == 2
    assert assessment["recommended_thelymitra_explant"] is None
    assert assessment["direct_thelymitra_evidence"] is False
    assert assessment["publication_authority"] is False


def test_bridge_matrix_preserves_source_and_observation_provenance():
    rows = bridge_matrix()
    assert len(rows) == 3
    assert all(row["source"]["doi"] == "10.1071/EA9920131" for row in rows)
    assert all(len(row["source"]["source_sha256"]) == 64 for row in rows)
    assert all(len(row["observation_sha256"]) == 64 for row in rows)
