from __future__ import annotations

import json

import pytest

from app.calyx_orchestrator.auto_mission import GovernanceAwarePrioritySelector
from app.calyx_orchestrator.executor_registry import AUTONOMY_PROBE_ROLE
from app.calyx_orchestrator.program_models import CalyxProgramJob


def job_with_inputs(inputs: dict) -> CalyxProgramJob:
    return CalyxProgramJob(
        program_job_id="alias-fixture",
        program_id="program-fixture",
        job_key="alias-fixture",
        role_key=AUTONOMY_PROBE_ROLE,
        title="alias fixture",
        repository="jsp1440/orchid-calyx-backend",
        branch=None,
        mutating=False,
        input_json=json.dumps(inputs),
        status="queued",
        attempt_count=0,
        max_attempts=3,
    )


@pytest.mark.parametrize(
    ("inputs", "expected_code"),
    [
        ({"action": "force-push"}, "OWNER_ONLY_ACTION:force_push"),
        ({"action": "branch deletion"}, "OWNER_ONLY_ACTION:branch_delete"),
        ({"requested_action": "Production Database Mutation"}, "OWNER_ONLY_ACTION:production_database_mutation"),
        ({"actions": ["taxonomy-activation"]}, "OWNER_ONLY_ACTION:taxonomy_activation"),
        ({"workflow": {"production-migration": True}}, "REVIEW_REQUIRED_ACTION:production_migration"),
        ({"workflow": {"schema activation": "enabled"}}, "REVIEW_REQUIRED_ACTION:schema_activation"),
        ({"governance": {"class": "owner-only"}}, "EXPLICIT_OWNER_ONLY"),
        ({"governance": {"class": "review required"}}, "EXPLICIT_REVIEW_REQUIRED"),
    ],
)
def test_equivalent_action_spellings_fail_closed(inputs, expected_code):
    decision = GovernanceAwarePrioritySelector().decision(job_with_inputs(inputs))
    assert decision.automatically_executable is False
    assert decision.code == expected_code


def test_metadata_mapping_is_not_promoted_to_action_request():
    decision = GovernanceAwarePrioritySelector().decision(
        job_with_inputs(
            {
                "publication": {"doi": "10.0000/example"},
                "force-push": False,
                "production migration": "disabled",
            }
        )
    )
    assert decision.automatically_executable is True
    assert decision.code == "AUTOMATICALLY_ADMISSIBLE"
