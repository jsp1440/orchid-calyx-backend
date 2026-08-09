from app.calyx_orchestrator.assignment_factory import (
    SAFE_ASSIGNMENT_CAPABILITIES,
    assignment_capabilities_for_role,
)
from app.calyx_orchestrator.isolated_patch_executor import ISOLATED_PATCH_ROLE


def test_workspace_write_is_scoped_only_to_isolated_patch_role() -> None:
    patch_capabilities = assignment_capabilities_for_role(ISOLATED_PATCH_ROLE)
    ordinary_capabilities = assignment_capabilities_for_role("brain_engineer")

    assert "workspace_write" in patch_capabilities
    assert "workspace_write" not in ordinary_capabilities
    assert ordinary_capabilities == SAFE_ASSIGNMENT_CAPABILITIES
    assert set(patch_capabilities) == {*SAFE_ASSIGNMENT_CAPABILITIES, "workspace_write"}
