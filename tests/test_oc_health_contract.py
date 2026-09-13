from __future__ import annotations

import io
import json
import sys

from scripts.oc_health_contract import evaluate, main


def issue(number, *labels, **extra):
    return {"number": number, "labels": list(labels), **extra}


def snapshot(*, issues=None, leases=None, dispatch_fingerprints=None, **extra):
    return {
        "issues": [] if issues is None else issues,
        "leases": [] if leases is None else leases,
        "dispatch_fingerprints": (
            [] if dispatch_fingerprints is None else dispatch_fingerprints
        ),
        **extra,
    }


def lease(issue_number, *, lease_id="lease", owner="lane", fingerprint="fp", **extra):
    return {
        "id": lease_id,
        "issue": issue_number,
        "owner": owner,
        "material_fingerprint": fingerprint,
        "active": True,
        **extra,
    }


def test_healthy_queued_issue():
    report = evaluate(snapshot(issues=[issue(1, "oc-queued")]))
    assert report["healthy"] is True
    assert report["counts"]["queued"] == 1
    assert report["violations"] == []


def test_missing_or_invalid_required_evidence_fails_closed():
    missing = evaluate({})
    assert missing["healthy"] is False
    assert {v["field"] for v in missing["violations"]} == {
        "issues",
        "leases",
        "dispatch_fingerprints",
    }

    invalid = evaluate(
        {
            "issues": {},
            "leases": "unknown",
            "dispatch_fingerprints": None,
        }
    )
    assert invalid["healthy"] is False
    assert all(v["type"] == "invalid_snapshot_field" for v in invalid["violations"])


def test_queued_backoff_is_contract_violation():
    report = evaluate(
        snapshot(
            issues=[
                issue(
                    308,
                    "oc-queued",
                    "oc-runtime-backoff",
                    "oc-repair-backoff",
                )
            ]
        )
    )
    assert report["healthy"] is False
    assert any(
        v["type"] == "executable_parked_conflict" and v["issue"] == 308
        for v in report["violations"]
    )


def test_multiple_executable_states_are_rejected():
    report = evaluate(snapshot(issues=[issue(2, "oc-queued", "oc-running")]))
    assert report["healthy"] is False
    assert any(v["type"] == "multiple_executable_states" for v in report["violations"])


def test_running_requires_exactly_one_complete_active_lease():
    no_lease = evaluate(snapshot(issues=[issue(3, "oc-running")]))
    assert any(
        v["type"] == "running_lease_cardinality" and v["active_leases"] == 0
        for v in no_lease["violations"]
    )

    two_leases = evaluate(
        snapshot(
            issues=[issue(3, "oc-running")],
            leases=[
                lease(3, lease_id="a", fingerprint="a"),
                lease(3, lease_id="b", fingerprint="b"),
            ],
        )
    )
    assert any(
        v["type"] == "running_lease_cardinality" and v["active_leases"] == 2
        for v in two_leases["violations"]
    )

    incomplete = evaluate(
        snapshot(
            issues=[issue(3, "oc-running")],
            leases=[{"id": "a", "issue": 3, "active": True}],
        )
    )
    kinds = {v["type"] for v in incomplete["violations"]}
    assert "lease_without_owner" in kinds
    assert "lease_without_material_fingerprint" in kinds


def test_single_running_lease_is_healthy():
    report = evaluate(
        snapshot(issues=[issue(4, "oc-running")], leases=[lease(4)])
    )
    assert report["healthy"] is True


def test_inline_running_lease_is_healthy():
    report = evaluate(
        snapshot(
            issues=[
                issue(
                    8,
                    "oc-running",
                    lease={
                        "id": "lease-8",
                        "owner": "lane-8",
                        "fingerprint": "8:head",
                    },
                )
            ]
        )
    )
    assert report["healthy"] is True


def test_orphan_and_stale_leases_fail_closed():
    report = evaluate(
        snapshot(
            issues=[issue(5, "oc-queued")],
            leases=[lease(5, lease_id="old", stale=True)],
        )
    )
    kinds = {v["type"] for v in report["violations"]}
    assert "orphan_active_lease" in kinds
    assert "stale_lease" in kinds


def test_duplicate_dispatch_fingerprint_is_rejected():
    report = evaluate(
        snapshot(dispatch_fingerprints=["301:abc", "301:abc"])
    )
    assert report["healthy"] is False
    assert report["violations"] == [
        {"type": "duplicate_dispatch_fingerprint", "fingerprint": "301:abc"}
    ]


def test_validating_requires_exact_head():
    bad = evaluate(snapshot(issues=[issue(6, "oc-validating", pr=77)]))
    assert any(
        v["type"] == "validating_without_exact_head" for v in bad["violations"]
    )

    good = evaluate(
        snapshot(
            issues=[
                issue(
                    6,
                    "oc-validating",
                    validation_target={"pr": 77, "head_sha": "deadbeef"},
                )
            ]
        )
    )
    assert good["healthy"] is True
    assert good["validating_targets"] == [
        {"issue": 6, "pr": 77, "head_sha": "deadbeef"}
    ]


def test_provider_and_exception_fields_are_preserved():
    report = evaluate(
        snapshot(
            issues=[issue(7, "oc-queued")],
            provider={"anthropic": "degraded", "openai": "available"},
            exceptions=[{"type": "spending", "owner_required": True}],
        )
    )
    assert report["healthy"] is True
    assert report["provider"]["anthropic"] == "degraded"
    assert report["exceptions"][0]["type"] == "spending"


def test_non_object_json_returns_machine_readable_failure(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))

    assert main() == 2
    report = json.loads(capsys.readouterr().out)
    assert report["healthy"] is False
    assert report["violations"][0]["type"] == "invalid_snapshot"


def test_health_exposes_no_exception_for_a_valid_snapshot():
    report = evaluate(snapshot())
    assert report["exception_decision"]["exception_class"] == "none"
    assert report["exception_decision"]["should_interrupt_owner"] is False


def test_missing_evidence_is_an_engineering_exception():
    report = evaluate({})
    assert report["healthy"] is False
    assert report["exception_decision"]["exception_class"] == "engineering_exception"
    assert report["exception_decision"]["autonomous_repair_available"] is True
    assert report["exception_decision"]["should_interrupt_owner"] is False


def test_failed_autonomous_pr_is_exact_head_engineering_exception():
    report = evaluate(
        snapshot(
            autonomous_prs=[
                {"number": 77, "head_sha": "abc", "ci_state": "failure"}
            ]
        )
    )
    assert report["healthy"] is False
    assert {"exact_head_ci_failure"} == {
        item["type"] for item in report["violations"]
    }
    assert report["exception_decision"]["exception_class"] == "engineering_exception"


def test_provider_disabled_parks_without_interrupt_when_deterministic_work_remains():
    report = evaluate(
        snapshot(provider={"status": "no_api"}, deterministic_work_available=True)
    )
    decision = report["exception_decision"]
    assert report["healthy"] is True
    assert decision["exception_class"] == "engineering_exception"
    assert decision["action"] == "park_provider_and_continue_deterministic_work"
    assert decision["should_interrupt_owner"] is False


def test_protected_provider_restoration_interrupts_only_when_work_is_depleted():
    context = {
        "anomaly": "provider_disabled",
        "protected_boundary": "paid_provider_restoration",
    }
    blocked = evaluate(
        snapshot(provider={"status": "disabled"}, exception_context=context)
    )["exception_decision"]
    assert blocked["exception_class"] == "owner_exception"
    assert blocked["owner_exception_category"] == "spending_provider_restoration"
    assert blocked["should_interrupt_owner"] is True

    continuing = evaluate(
        snapshot(
            provider={"status": "disabled"},
            deterministic_work_available=True,
            exception_context=context,
        )
    )["exception_decision"]
    assert continuing["exception_class"] == "engineering_exception"
    assert continuing["should_interrupt_owner"] is False
