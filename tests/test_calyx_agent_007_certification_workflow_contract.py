"""The certification harness must stay a harness.

The whole value of AGENT-007 is that a governor repaired a real failure under
real authorization and then *stopped*. A harness that could merge, deploy, or
write to the repository would make that unprovable - you could no longer tell
which side of the boundary performed the action.

These assertions are cheap and the property they protect is not recoverable
after the fact, so they are checked structurally rather than trusted to review.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOW = Path(".github/workflows/calyx-agent-007-persisted-certification.yml")


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


@pytest.fixture(scope="module")
def steps(workflow) -> list[dict]:
    return workflow["jobs"]["certify"]["steps"]


def test_the_harness_is_owner_triggered_only(workflow):
    """No schedule, no push, no pull_request. Someone decides to run this."""
    # PyYAML parses a bare `on:` key as the boolean True.
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_dispatch"}, triggers


def test_the_harness_cannot_write_to_the_repository(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_the_harness_requires_an_explicit_confirmation_phrase(workflow, steps):
    inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
    assert inputs["confirmation"]["required"] is True
    guard = " ".join(s.get("run", "") for s in steps)
    assert "RUN AGENT-007 PERSISTED CERTIFICATION" in guard


def test_the_harness_refuses_a_target_that_is_not_a_draft(steps):
    """Guards against running a deliberate failing assertion at real work."""
    guard = " ".join(s.get("run", "") for s in steps)
    assert "isDraft" in guard
    assert "must be a draft PR" in guard


def _executable_text(steps: list[dict]) -> str:
    """Everything the runner would execute, minus the text it merely prints.

    Scanning the raw step body for a word like "deploy" flags the outcome
    message that exists to state no deploy happened. The property is about
    invocations, so strip the message text and match invocations.
    """
    lines: list[str] = []
    for step in steps:
        for line in str(step.get("run", "")).splitlines():
            stripped = line.strip()
            if stripped.startswith(("echo ", "#")) or "::notice::" in stripped or "::error::" in stripped:
                continue
            lines.append(stripped)
        lines.append(str(step.get("uses", "")))
    return "\n".join(lines)


def test_the_harness_never_merges_or_deploys(steps):
    body = _executable_text(steps)
    for forbidden in (
        "gh pr merge",
        "gh pr ready",
        "gh pr edit",
        "merge_pull_request",
        "--auto",
        "--squash",
        "--rebase",
        "deploy-hook",
        "deploys",
        "git push",
    ):
        assert forbidden not in body, f"certification harness must not invoke {forbidden!r}"


def test_the_guard_above_would_notice_a_merge_command(steps):
    """The guard must fail on a real merge, not just pass on prose."""
    tampered = list(steps) + [{"name": "sneak", "run": "gh pr merge 1043 --squash"}]
    assert "gh pr merge" in _executable_text(tampered)
    assert "gh pr merge" not in _executable_text(steps)


def test_the_harness_persists_evidence_even_when_the_governor_fails(steps):
    upload = [s for s in steps if "upload-artifact" in str(s.get("uses", ""))]
    assert upload, "certification evidence must be uploaded"
    assert upload[0].get("if") == "always()", (
        "a failed certification is exactly the run whose evidence is needed"
    )


def test_a_transport_failure_is_reported_as_distinct_from_a_governor_failure(steps):
    report = " ".join(s.get("run", "") for s in steps if "outcome" in str(s.get("name", "")).lower())
    assert "NOT a governor result" in report
    assert "stalled, not failed" in report


def test_the_harness_drives_the_persisted_script_not_the_direct_repair_cli(steps):
    body = " ".join(s.get("run", "") for s in steps)
    assert "calyx_agent_007_persisted_certify.py" in body
    assert "calyx_engineering_certify.py" not in body, (
        "the direct repair CLI proves the provider works, not the durable governor"
    )
