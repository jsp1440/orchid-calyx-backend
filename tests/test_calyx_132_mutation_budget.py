from runtime.calyx_certification.mutation_budget import validate_mutation_budget


def test_zero_mutation_budget_passes():
    result = validate_mutation_budget(
        {"expected_mutations": 0, "observed_mutations": 0, "maximum_mutations": 0}
    )
    assert result["within_budget"] is True


def test_unexpected_mutation_blocks():
    result = validate_mutation_budget(
        {"expected_mutations": 0, "observed_mutations": 1, "maximum_mutations": 0}
    )
    assert "unexpected_mutation_count" in result["blockers"]
    assert "mutation_budget_exceeded" in result["blockers"]
