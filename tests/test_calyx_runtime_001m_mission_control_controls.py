import pytest

from runtime.governed_worker_loop import GovernedWorkerLoop
from runtime.persistent_activation_state import PersistentActivationController
from runtime.runtime_operator_controls import RuntimeOperatorControls


class MemoryStore:
    def __init__(self):
        self.payload = None

    def load(self):
        return self.payload

    def save(self, payload):
        self.payload = dict(payload)


def build_controls(result: str = "draft-pr-created") -> RuntimeOperatorControls:
    controller = PersistentActivationController(MemoryStore())
    worker = GovernedWorkerLoop(controller, lambda: result)
    return RuntimeOperatorControls(controller, worker)


def test_controls_fail_closed_without_owner_approval():
    controls = build_controls()
    with pytest.raises(PermissionError):
        controls.resume(owner_approved=False)
    with pytest.raises(PermissionError):
        controls.pause(owner_approved=False)
    with pytest.raises(PermissionError):
        controls.run_once(owner_approved=False)


def test_resume_run_once_and_pause_cycle():
    controls = build_controls()
    resumed = controls.resume(owner_approved=True)
    assert resumed["authorized"] is True
    result = controls.run_once(owner_approved=True)
    assert result["executed"] is True
    paused = controls.pause(owner_approved=True)
    assert paused["authorized"] is False
    assert paused["paused"] is True


def test_status_preserves_consequential_action_boundaries():
    status = build_controls().status()
    assert all(value is False for value in status["safety"].values())


def test_configuration_is_bounded():
    controls = build_controls()
    configured = controls.configure(
        owner_approved=True,
        interval_minutes=120,
        max_draft_prs_per_cycle=2,
    )
    assert configured["interval_minutes"] == 120
    assert configured["max_draft_prs_per_cycle"] == 2
