"""Dispatch-only entrypoints must not contend with execution for a queue slot."""

from pathlib import Path

import pytest
import yaml


WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


@pytest.mark.parametrize(
    "entrypoint",
    [
        "orchid-continuous-completion.yml",
        "orchid-continuous-pulse.yml",
        "oc-integration-handoff.yml",
    ],
)
def test_dispatch_entrypoints_do_not_evict_pending_controller(entrypoint):
    controller = yaml.safe_load(
        (WORKFLOWS / "orchid-swarm-controller.yml").read_text()
    )
    dispatcher = yaml.safe_load((WORKFLOWS / entrypoint).read_text())
    controller_group = controller["concurrency"]["group"]
    dispatcher_group = dispatcher.get("concurrency", {}).get("group")
    # GitHub permits only one pending run in a concurrency group, even with
    # cancel-in-progress=false. A redirect arriving behind an active controller
    # must not replace that controller's pending autonomous refill.
    assert dispatcher_group != controller_group


def test_controller_still_serializes_execution_without_cancelling_active_work():
    controller = yaml.safe_load(
        (WORKFLOWS / "orchid-swarm-controller.yml").read_text()
    )
    assert controller["concurrency"] == {
        "group": "orchid-swarm-controller-${{ github.repository }}",
        "cancel-in-progress": False,
    }
