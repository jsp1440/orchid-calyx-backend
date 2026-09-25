"""The oc-done false-completion rule fails closed."""

from __future__ import annotations

import json

from runtime.oc_done_guard import (
    Decision,
    Observation,
    Receipt,
    decide,
    parse_receipt_comment,
    transitions,
)

SHA_ON_MAIN = "bcf6bcb1e873bc5fe05b7c339cb30a74bbc55fd3"
SHA_ELSEWHERE = "4ea032b7cacab6e1a9312e2d5b2111212c40b843"


def on_main(sha: str) -> bool:
    return sha == SHA_ON_MAIN


def receipt(sha=SHA_ON_MAIN, changed=0, disposition="done", mode="validate"):
    return Receipt(
        sha=sha,
        changed_file_count=changed,
        disposition=disposition,
        mode=mode,
        schema="oc.swarm-provider-free-result.v1",
    )


def observe(state="closed", labels=("oc-done",), receipts=(), merged=()):
    return Observation(1592, state, tuple(labels), tuple(receipts), tuple(merged))


def test_open_issue_can_never_be_done():
    decision = decide(
        observe(state="open", receipts=[receipt(changed=5)], merged=[SHA_ON_MAIN]),
        on_main,
    )
    assert decision == Decision(1592, False, "issue_open")


def test_issue_without_the_claim_is_left_alone():
    assert decide(observe(labels=("oc-queued",)), on_main).reason == "not_claimed"


def test_closed_without_a_receipt_fails_closed():
    assert decide(observe(), on_main).reason == "no_receipt_with_full_sha"


def test_receipt_without_a_full_sha_does_not_count():
    assert (
        decide(observe(receipts=[receipt(sha=None, changed=3)]), on_main).reason
        == "no_receipt_with_full_sha"
    )


def test_blocked_receipt_is_not_completion():
    assert decide(
        observe(receipts=[receipt(disposition="blocked", changed=3)]), on_main
    ).reason == ("no_receipt_with_full_sha")


def test_receipt_sha_off_the_target_branch_fails_closed():
    decision = decide(
        observe(receipts=[receipt(sha=SHA_ELSEWHERE, changed=3)]), on_main
    )
    assert decision.reason == "receipt_sha_not_on_target_branch"
    assert decision.evidence == {"shas": [SHA_ELSEWHERE]}


def test_validate_only_receipt_with_zero_changed_files_is_the_flagged_false_completion():
    """Backend #1592: closed-or-not, a validate-mode receipt with changed_file_count 0
    and no merged PR is not evidence that the requested change happened."""
    decision = decide(observe(receipts=[receipt(changed=0)]), on_main)
    assert decision.reason == "no_change_evidence"
    assert decision.evidence == {"sha": SHA_ON_MAIN, "changed_file_count": 0}


def test_changed_files_on_main_is_admissible():
    decision = decide(observe(receipts=[receipt(changed=4, mode="implement")]), on_main)
    assert decision.allowed and decision.reason == "changed_files_receipt"


def test_merged_pull_request_is_admissible():
    decision = decide(
        observe(receipts=[receipt(changed=0)], merged=[SHA_ON_MAIN]), on_main
    )
    assert decision.allowed and decision.reason == "merged_pull_request"


def test_validation_only_issue_is_exempt_from_the_change_requirement():
    decision = decide(
        observe(
            labels=("oc-done", "oc-validation-only"), receipts=[receipt(changed=0)]
        ),
        on_main,
    )
    assert decision.allowed and decision.reason == "validation_only_issue"


def test_transitions_only_touch_refused_claims():
    decisions = [
        decide(observe(state="open"), on_main),
        decide(observe(receipts=[receipt(changed=4)]), on_main),
    ]
    assert transitions(decisions) == [
        {
            "number": 1592,
            "remove": ["oc-done"],
            "add": ["oc-validating"],
            "reason": "issue_open",
            "evidence": {},
        }
    ]


def test_parse_the_real_swarm_receipt_comment():
    payload = {
        "schema": "oc.swarm-provider-free-result.v1",
        "disposition": "done",
        "integration_sha": SHA_ELSEWHERE,
        "issue_number": 1592,
        "mode": "validate",
        "write_set": {
            "changed_file_count": 0,
            "schema": "oc.swarm-write-set-verification.v2",
        },
    }
    body = (
        "[OC-SWARM-V4] Provider-free worker completed, actual write set validated, and "
        f"lease released: `{json.dumps(payload)}`. Run: https://example.invalid/runs/1"
    )
    parsed = parse_receipt_comment(body)
    assert parsed == Receipt(
        SHA_ELSEWHERE, 0, "done", "validate", "oc.swarm-provider-free-result.v1"
    )


def test_parse_ignores_claims_and_malformed_json():
    claim = '[OC-SWARM-V4] Dependency/resource lease claimed: `{"schema":"oc.swarm-claim.v1","issue_number":1592}`.'
    assert parse_receipt_comment(claim) is None
    assert parse_receipt_comment("[OC-SWARM-V4] completed: `{not json}`") is None
    assert parse_receipt_comment("plain comment") is None
    abbreviated = '[OC-SWARM-V4] completed: `{"schema":"oc.swarm-provider-free-result.v1","disposition":"done","integration_sha":"4ea032b7"}`'
    assert parse_receipt_comment(abbreviated).sha is None
