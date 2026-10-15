from decimal import Decimal
from pathlib import Path

import pytest

from scripts import swarm_governor_github_ledger as ledger

LANE = Path(".github/workflows/orchid-completion-lane.yml")


def _line(reserved="0.50", actual="unknown", date="2026-10-15"):
    return (
        "[OC-GOVERNOR-COST] run_id=1 issue=1861 provider=anthropic "
        f"reserved_usd={reserved} actual_usd={actual} date={date} month={date[:7]}"
    )


@pytest.mark.parametrize(
    ("actual", "counted"),
    [
        ("0.1234", Decimal("0.1234")),  # real cost below the reservation
        ("0.5900", Decimal("0.5900")),  # and above it
        ("unknown", Decimal("0.50")),  # no actual cost: reservation stands
        ("-1", Decimal("0.50")),
        ("1e3", Decimal("0.50")),
        ("NaN", Decimal("0.50")),
    ],
)
def test_the_budget_counts_actual_cost_when_recorded(actual, counted):
    assert ledger.receipt_spend(_line(actual=actual))[0] == counted


def test_receipts_without_an_actual_field_still_count_the_reservation():
    old = (
        "[OC-GOVERNOR-COST] run_id=1 issue=1 provider=anthropic-checker "
        "reserved_usd=0.08 date=2026-10-15 month=2026-10"
    )
    assert ledger.receipt_spend(old) == (Decimal("0.08"), "2026-10-15", "2026-10")
    assert ledger.receipt_spend("unrelated comment") is None


def test_snapshot_sums_actual_or_reserved_per_receipt(monkeypatch):
    today = ledger.datetime.now(ledger.timezone.utc).strftime("%Y-%m-%d")
    lines = [
        _line(actual="0.1200", date=today),
        _line(actual="unknown", date=today),
        _line(actual="0.3000", date="2000-01-01"),
    ]
    monkeypatch.setattr(ledger, "_gh", lambda *args: "\n".join(lines))
    daily, monthly = ledger.snapshot("o/r", 1330)
    assert daily == Decimal("0.6200")
    assert monthly == Decimal("0.6200")


@pytest.mark.parametrize(
    ("given", "written"),
    [("0.1234", "0.1234"), ("", "unknown"), ("12; rm -rf", "unknown")],
)
def test_append_writes_only_a_plain_decimal_actual(monkeypatch, given, written):
    calls = []
    monkeypatch.setattr(ledger, "_gh", lambda *args: calls.append(args) or "")
    ledger.append_receipt(
        "o/r",
        1330,
        run_id="9",
        issue_number="1861",
        provider="anthropic",
        reserved_usd=Decimal("0.50"),
        actual_usd=given,
    )
    body = calls[0][calls[0].index("--body") + 1]
    assert f"actual_usd={written} " in body
    assert ledger.receipt_spend(body)[0] == (
        Decimal(written) if written != "unknown" else Decimal("0.50")
    )


def test_the_completion_lane_passes_the_executor_cost_to_the_ledger():
    text = LANE.read_text()
    assert ".total_cost_usd // empty" in text
    assert '--actual-usd "$actual"' in text
