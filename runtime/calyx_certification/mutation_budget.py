from typing import Any


def validate_mutation_budget(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("expected_mutations", "observed_mutations", "maximum_mutations")
    blockers = [f"missing:{key}" for key in required if payload.get(key) is None]
    expected = payload.get("expected_mutations")
    observed = payload.get("observed_mutations")
    maximum = payload.get("maximum_mutations")
    if all(isinstance(value, int) for value in (expected, observed, maximum)):
        if observed != expected:
            blockers.append("unexpected_mutation_count")
        if observed > maximum:
            blockers.append("mutation_budget_exceeded")
    return {
        "within_budget": not blockers,
        "blockers": sorted(set(blockers)),
        "production_action_authorized": False,
    }
