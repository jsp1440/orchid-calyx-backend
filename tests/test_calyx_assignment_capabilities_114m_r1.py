import pytest

from app.calyx_orchestrator.assignment_factory import (
    SAFE_ASSIGNMENT_CAPABILITIES,
    assignment_capabilities_for_role,
)
from app.calyx_orchestrator.isolated_patch_executor import ISOLATED_PATCH_ROLE


def test_workspace_write_requires_patch_role_and_explicit_mutating_intent() -> None:
    patch_capabilities = assignment_capabilities_for_role(
        ISOLATED_PATCH_ROLE,
        mutating_intent=True,
    )
    ordinary_capabilities = assignment_capabilities_for_role(
        "brain_engineer",
        mutating_intent=False,
    )

    assert "workspace_write" in patch_capabilities
    assert "workspace_write" not in ordinary_capabilities
    assert ordinary_capabilities == SAFE_ASSIGNMENT_CAPABILITIES
    assert set(patch_capabilities) == {*SAFE_ASSIGNMENT_CAPABILITIES, "workspace_write"}


def test_isolated_patch_role_without_mutating_intent_fails_closed() -> None:
    with pytest.raises(PermissionError, match="ISOLATED_PATCH_MUTATING_JOB_REQUIRED"):
        assignment_capabilities_for_role(
            ISOLATED_PATCH_ROLE,
            mutating_intent=False,
        )
