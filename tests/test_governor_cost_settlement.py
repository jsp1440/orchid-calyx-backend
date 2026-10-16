"""A checker reservation is settled with its real cost, never double counted.

The hosted checker writes its ledger receipt before credentials exist, so the
receipt can only carry the $0.08 reservation (every window-3 checker receipt on
#1330 reads actual_usd=unknown). After the call, one settle line per run and
provider replaces that reservation in the totals.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from scripts import oc_hosted_completion as hosted
from scripts import swarm_governor_github_ledger as ledger

TODAY = ledger.datetime.now(ledger.timezone.utc).strftime("%Y-%m-%d")


def _receipt(
    run="38862098700", provider="anthropic-checker", reserved="0.08", actual="unknown"
):
    return (
        f"[OC-GOVERNOR-COST] run_id={run} issue=1915 provider={provider} "
        f"reserved_usd={reserved} actual_usd={actual} date={TODAY} month={TODAY[:7]}"
    )


def _settle(run="38862098700", provider="anthropic-checker", actual="0.0123"):
    return f"[OC-GOVERNOR-COST-SETTLE] run_id={run} provider={provider} actual_usd={actual}"


BOT = "github-actions"


def _snapshot(monkeypatch, lines, author=BOT):
    """Rows as the snapshot's jq emits them; ``author`` may vary per line."""
    rows = []
    for line in lines:
        who, body = line if isinstance(line, tuple) else (author, line)
        rows.append(json.dumps({"a": who, "b": body}))
    monkeypatch.setattr(ledger, "_gh", lambda *args: "\n".join(rows))
    return ledger.snapshot("o/r", 1330)


def test_a_settle_line_replaces_the_reservation_of_its_run(monkeypatch):
    daily, monthly = _snapshot(monkeypatch, [_receipt(), _settle()])
    assert daily == monthly == Decimal("0.0123")


def test_a_settle_line_alone_is_never_counted(monkeypatch):
    assert _snapshot(monkeypatch, [_settle()]) == (Decimal(0), Decimal(0))


def test_settlement_is_bound_to_run_and_provider(monkeypatch):
    lines = [
        _receipt(),
        _receipt(run="1", provider="anthropic", reserved="0.50"),
        _settle(run="1", provider="anthropic-checker"),
        _settle(run="38862098700", provider="anthropic"),
    ]
    daily, _ = _snapshot(monkeypatch, lines)
    assert daily == Decimal("0.58")  # neither settle line matches its receipt


@pytest.mark.parametrize(
    "author", ["jsp1440", "drive-by", "copilot-swe-agent[bot]", None]
)
def test_a_settle_line_from_anyone_but_the_workflow_bot_is_ignored(monkeypatch, author):
    """#1330 is a public, unlocked issue: anyone could post a settle line."""
    daily, _ = _snapshot(monkeypatch, [_receipt(), (author, _settle(actual="0"))])
    assert daily == Decimal("0.08")


def test_a_forged_settle_posted_first_cannot_beat_the_bot(monkeypatch):
    lines = [
        _receipt(),
        ("attacker", _settle(actual="0.0000")),
        _settle(actual="0.0500"),
    ]
    assert _snapshot(monkeypatch, lines)[0] == Decimal("0.0500")


def test_only_checker_reservations_can_be_settled(monkeypatch):
    lines = [
        _receipt(run="7", provider="anthropic", reserved="0.50"),
        _settle(run="7", provider="anthropic", actual="0"),
    ]
    assert _snapshot(monkeypatch, lines)[0] == Decimal("0.50")


def test_receipts_from_any_author_still_count(monkeypatch):
    """Extra receipts can only raise spend, which fails closed."""
    lines = [_receipt(), ("someone", _receipt(run="9"))]
    assert _snapshot(monkeypatch, lines)[0] == Decimal("0.16")


def test_plain_body_lines_without_author_count_receipts_but_never_settle(monkeypatch):
    plain = f"{_receipt()}\n{_settle()}"
    monkeypatch.setattr(ledger, "_gh", lambda *args: plain)
    assert ledger.snapshot("o/r", 1330)[0] == Decimal("0.08")


def test_a_settle_line_inside_a_multi_line_bot_comment_is_read(monkeypatch):
    body = "note\n" + _settle(actual="0.0100")
    assert _snapshot(monkeypatch, [_receipt(), body])[0] == Decimal("0.0100")


def test_an_actual_on_the_receipt_wins_over_a_settle_line(monkeypatch):
    daily, _ = _snapshot(monkeypatch, [_receipt(actual="0.0400"), _settle()])
    assert daily == Decimal("0.0400")


@pytest.mark.parametrize("actual", ["unknown", "-1", "1e3", "NaN", "0.01;x"])
def test_an_invalid_settle_amount_leaves_the_reservation(monkeypatch, actual):
    daily, _ = _snapshot(monkeypatch, [_receipt(), _settle(actual=actual)])
    assert daily == Decimal("0.08")


def test_the_first_valid_settle_line_wins(monkeypatch):
    lines = [_receipt(), _settle(actual="0.0100"), _settle(actual="0.0001")]
    assert _snapshot(monkeypatch, lines)[0] == Decimal("0.0100")


def test_append_settlement_writes_only_valid_lines(monkeypatch):
    calls = []
    monkeypatch.setattr(ledger, "_gh", lambda *args: calls.append(args) or "")
    assert ledger.append_settlement(
        "o/r", 1330, run_id="12", provider="anthropic-checker", actual_usd="0.0123"
    )
    assert calls[-1][-1] == _settle(run="12", actual="0.0123")
    assert not ledger.append_settlement(
        "o/r", 1330, run_id="12", provider="x", actual_usd="unknown"
    )
    assert not ledger.append_settlement(
        "o/r", 1330, run_id="12;x", provider="x", actual_usd="0.01"
    )
    assert not ledger.append_settlement(
        "o/r", 1330, run_id="12", provider="a b", actual_usd="0.01"
    )
    assert len(calls) == 1


def test_the_checker_settles_its_real_cost(monkeypatch):
    written = []
    monkeypatch.setattr(ledger, "_gh", lambda *args: written.append(args[-1]) or "")
    context = {"repository": "o/r", "completion_run": 38862098700}
    usage = {
        "model": hosted.MODEL,
        "usage": {"input_tokens": 10000, "output_tokens": 400},
    }
    # 10000 * $1.00/MTok + 400 * $5.00/MTok = $0.0120
    assert hosted.settle_checker_cost(context, usage) == "0.0120"
    assert written == [_settle(actual="0.0120")]


@pytest.mark.parametrize(
    "usage",
    [None, {}, {"usage": {}}, {"usage": {"input_tokens": -1, "output_tokens": 2}}],
)
def test_unusable_usage_writes_nothing(monkeypatch, usage):
    written = []
    monkeypatch.setattr(ledger, "_gh", lambda *args: written.append(args) or "")
    assert (
        hosted.settle_checker_cost({"repository": "o/r", "completion_run": 1}, usage)
        is None
    )
    assert written == []


def test_a_ledger_failure_never_fails_the_record_phase(monkeypatch):
    def broken(*args):
        raise RuntimeError("gh failed")

    monkeypatch.setattr(ledger, "_gh", broken)
    usage = {"usage": {"input_tokens": 10, "output_tokens": 2}}
    assert (
        hosted.settle_checker_cost({"repository": "o/r", "completion_run": 1}, usage)
        is None
    )
