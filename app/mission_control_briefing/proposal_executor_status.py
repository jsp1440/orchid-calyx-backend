from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.calyx_orchestrator.github_proposal_executor_policy import (
    github_proposal_executor_status,
)

_TRUST_CHAIN = (
    ("reviewed_proposal_plan", "BUILD-BRAIN-114R", True),
    ("owner_authorization", "BUILD-BRAIN-114N/114O/114Q", True),
    ("bounded_mutation_executor", "BUILD-BRAIN-114S", True),
    ("durable_mutation_journal", "BUILD-BRAIN-114T", True),
    ("verified_github_adapter", "BUILD-BRAIN-114U-C", True),
    ("disabled_by_default_policy", "BUILD-BRAIN-114U-D", True),
    ("live_credential_registration", "owner-governed activation", False),
)


def proposal_executor_mission_control_status(
    environ: Mapping[str, str] | None = None,
    *,
    credential_ready: bool = False,
) -> dict[str, Any]:
    """Return a non-secret, read-only Mission Control autonomy status snapshot."""

    policy = github_proposal_executor_status(
        environ,
        credential_ready=credential_ready,
    )
    trust_chain = [
        {"layer": layer, "contract": contract, "implemented": implemented}
        for layer, contract, implemented in _TRUST_CHAIN
    ]
    return {
        "schema": "calyx-mission-control-proposal-executor-status-v1",
        "status": "ready" if policy["ready_for_owner_authorized_draft_pr"] else "blocked",
        "policy": policy,
        "trust_chain": trust_chain,
        "evidence_chain_complete_through_policy": all(
            item["implemented"] for item in trust_chain[:-1]
        ),
        "live_credential_registration_active": False,
        "read_only": True,
        "secret_material_exposed": False,
        "mutation_performed": False,
        "authority": {
            "draft_pull_request_only": True,
            "merge_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "taxonomy_activation_authorized": False,
            "production_database_mutation_authorized": False,
            "production_graph_mutation_authorized": False,
            "credential_disclosure_authorized": False,
            "spending_authorized": False,
        },
    }
