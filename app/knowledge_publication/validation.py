from typing import Any


def reject_caller_overrides(payload: dict[str, Any]) -> None:
    protected = {
        "assertion",
        "eligibility",
        "provenance",
        "policy_result",
        "reviewer_approval",
        "state",
        "audit_identity",
        "graph_version",
    }
    attempted = sorted(protected.intersection(payload))
    if attempted:
        raise ValueError("CALLER_OVERRIDE_PROHIBITED:" + ",".join(attempted))
