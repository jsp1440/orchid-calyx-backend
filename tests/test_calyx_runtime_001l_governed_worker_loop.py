from runtime.governed_worker_loop import GovernedWorkerLoop
from runtime.persistent_activation_state import (
    ActivationState,
    PersistentActivationController,
)


class MemoryStore:
    def __init__(self):
        self.payload = None

    def load(self):
        return self.payload

    def save(self, payload):
        self.payload = dict(payload)


def build_controller(state: ActivationState) -> PersistentActivationController:
    controller = PersistentActivationController(MemoryStore())
    controller.save(state)
    return controller


def test_worker_fails_closed_when_paused():
    calls = []
    worker = GovernedWorkerLoop(
        build_controller(
            ActivationState(enabled=True, owner_approved=True, paused=True)
        ),
        lambda: calls.append("cycle") or "complete",
    )
    result = worker.tick()
    assert result.executed is False
    assert result.reason == "paused"
    assert calls == []


def test_worker_runs_one_authorized_cycle_and_records_result():
    controller = build_controller(
        ActivationState(enabled=True, owner_approved=True, paused=False)
    )
    worker = GovernedWorkerLoop(controller, lambda: "draft-pr-created")
    result = worker.tick()
    assert result.executed is True
    assert result.cycle_result == "draft-pr-created"
    assert controller.load().last_result == "draft-pr-created"


def test_worker_rejects_enabled_state_without_owner_approval():
    controller = PersistentActivationController(MemoryStore())
    worker = GovernedWorkerLoop(controller, lambda: "should-not-run")
    result = worker.tick()
    assert result.executed is False
    assert result.reason == "paused"


def test_consequential_actions_remain_disabled():
    assert all(value is False for value in GovernedWorkerLoop.safety_status().values())
