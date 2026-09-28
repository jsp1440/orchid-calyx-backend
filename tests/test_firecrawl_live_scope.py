"""A one-task live authorization never enables the remaining provider queue."""

from types import SimpleNamespace

import pytest

from app.literature_extraction import firecrawl_runtime as runtime
from app.literature_extraction.firecrawl_provider import (
    AcquisitionBlocked,
    FirecrawlConfig,
)


def request():
    return runtime.AcquisitionRequest(
        issue_number=123, run_id=77, run_attempt=1, comment_id=100
    )


@pytest.mark.parametrize("scope", ["", "124"])
def test_live_pilot_requires_exact_issue_scope_before_any_spend(monkeypatch, scope):
    monkeypatch.setenv("FIRECRAWL_PILOT_ISSUE_NUMBER", scope)
    events = []
    monkeypatch.setattr(
        runtime,
        "reserve_live_pilot_attempt",
        lambda request: events.append("reservation"),
    )
    provider = SimpleNamespace(_gate=lambda: events.append("provider-authority"))
    # This is the exact helper invoked only after successful production corpus audit.
    with pytest.raises(AcquisitionBlocked, match="LIVE_PILOT_ISSUE_SCOPE_REQUIRED"):
        runtime.authorize_external_acquisition(
            request(),
            FirecrawlConfig(dry_run=False),
            provider,
            ("leaf_width",),
            verify_lease=lambda: events.append("lease"),
        )
    assert (
        events == []
    )  # neither provider authority nor a durable reservation was reached


def test_missing_evidence_scope_never_reserves_a_live_pilot(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_PILOT_ISSUE_NUMBER", "123")
    events = []
    monkeypatch.setattr(
        runtime,
        "reserve_live_pilot_attempt",
        lambda request: events.append("reservation"),
    )
    with pytest.raises(AcquisitionBlocked, match="EXPLICIT_PREDICATE_SCOPE_REQUIRED"):
        runtime.authorize_external_acquisition(
            request(),
            FirecrawlConfig(dry_run=False),
            SimpleNamespace(_gate=lambda: events.append("provider-authority")),
            (),
            verify_lease=lambda: events.append("lease"),
        )
    assert events == []


def test_authorized_pilot_rechecks_lease_before_durable_reservation(monkeypatch):
    monkeypatch.setenv("FIRECRAWL_PILOT_ISSUE_NUMBER", "123")
    events = []
    monkeypatch.setattr(
        runtime,
        "reserve_live_pilot_attempt",
        lambda request: events.append("reservation"),
    )
    runtime.authorize_external_acquisition(
        request(),
        FirecrawlConfig(dry_run=False),
        SimpleNamespace(_gate=lambda: events.append("provider-authority")),
        ("leaf_width",),
        verify_lease=lambda: events.append("lease"),
    )
    assert events == ["provider-authority", "lease", "reservation"]
