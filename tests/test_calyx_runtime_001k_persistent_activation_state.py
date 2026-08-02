import pytest

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


def test_controller_fails_closed_without_state():
    controller = PersistentActivationController(MemoryStore())
    state = controller.load()
    assert state.authorized is False
    assert state.paused is True


def test_owner_approved_state_can_be_persisted_and_reloaded():
    store = MemoryStore()
    controller = PersistentActivationController(store)
    saved = controller.save(
        ActivationState(enabled=True, owner_approved=True, paused=False)
    )
    assert saved.authorized is True
    assert controller.load().authorized is True


def test_enabled_without_owner_approval_is_rejected():
    controller = PersistentActivationController(MemoryStore())
    with pytest.raises(PermissionError):
        controller.save(ActivationState(enabled=True, owner_approved=False))


def test_cycle_receipt_requires_authorized_runtime():
    controller = PersistentActivationController(MemoryStore())
    with pytest.raises(PermissionError):
        controller.record_cycle("no-op")


def test_authorized_cycle_records_last_result():
    store = MemoryStore()
    controller = PersistentActivationController(store)
    controller.save(ActivationState(enabled=True, owner_approved=True, paused=False))
    updated = controller.record_cycle(
        "draft-pr-created", occurred_at="2026-08-02T06:40:00Z"
    )
    assert updated.last_cycle_at == "2026-08-02T06:40:00Z"
    assert updated.last_result == "draft-pr-created"


def test_consequential_actions_remain_disabled():
    status = PersistentActivationController.safety_status()
    assert all(value is False for value in status.values())
