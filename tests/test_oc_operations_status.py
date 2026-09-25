from __future__ import annotations

import io
import json
import sys

from scripts.oc_operations_status import build_operations_status, main


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


def test_operations_status_projects_canonical_health_and_exception_fields():
    value = snapshot(
        issues=[
            issue(10, "oc-queued"),
            issue(
                11,
                "oc-running",
                lease={
                    "owner": "lane-1",
                    "material_fingerprint": "lease-11",
                    "age_seconds": 42,
                    "stale": False,
                },
            ),
            issue(
                12,
                "oc-validating",
                validation_target={"pr": 88, "head_sha": "abc123"},
            ),
            issue(13, "oc-runtime-backoff"),
        ],
        autonomous_prs=[
            {
                "number": 88,
                "head_sha": "abc123",
                "ci_state": "success",
                "mergeable": True,
            }
        ],
        provider={"status": "degraded", "degraded": True, "reason_code": "capacity"},
        integration={
            "ready": True,
            "target": "oc-autonomous-integration",
            "head_sha": "def456",
            "ahead_by": 3,
        },
    )
    status = build_operations_status(value)

    assert status["healthy"] is True
    assert status["counts"]["queued"] == 1
    assert status["lanes"] == [
        {"issue": 11, "lane": "lane-1", "age_seconds": 42, "stale": False}
    ]
    assert status["exception_class"] == "none"
    assert status["should_interrupt_owner"] is False


def test_operations_status_surfaces_invariants_as_engineering_exceptions():
    value = snapshot(
        issues=[
            issue(
                21,
                "oc-running",
                lease={
                    "owner": "lane-a",
                    "material_fingerprint": "lease-21",
                    "stale": True,
                },
            ),
            issue(22, "oc-validating", validation_target={"pr": 99}),
        ],
        dispatch_fingerprints=["same", "same"],
    )
    status = build_operations_status(value)
    violation_types = {item["type"] for item in status["violations"]}

    assert {"stale_lease", "duplicate_dispatch_fingerprint"} <= violation_types
    assert "validating_without_exact_head" in violation_types
    assert status["exception_class"] == "engineering_exception"
    assert status["autonomous_repair_available"] is True
    assert status["should_interrupt_owner"] is False


def test_operations_status_exposes_owner_exception_only_at_real_boundary():
    context = {
        "anomaly": "provider_disabled",
        "protected_boundary": "paid_provider_restoration",
    }
    status = build_operations_status(
        snapshot(provider={"status": "disabled"}, exception_context=context)
    )
    assert status["exception_class"] == "owner_exception"
    assert status["owner_exception_category"] == "spending_provider_restoration"
    assert status["should_interrupt_owner"] is True

    continuing = build_operations_status(
        snapshot(
            provider={"status": "disabled"},
            deterministic_work_available=True,
            exception_context=context,
        )
    )
    assert continuing["exception_class"] == "engineering_exception"
    assert continuing["should_interrupt_owner"] is False


def test_operations_status_redacts_unapproved_fields():
    value = snapshot(
        issues=[issue(31, "oc-queued")],
        provider={
            "status": "ok",
            "api_key": "secret-provider-key",
            "endpoint": "private-endpoint",
        },
        integration={
            "ready": False,
            "target": "oc-autonomous-integration",
            "private_provenance": "do-not-expose",
        },
        autonomous_prs=[
            {
                "number": 101,
                "head_sha": "head101",
                "ci_state": "pending",
                "mergeable": None,
                "token": "secret-token",
            }
        ],
        exception_context={
            "anomaly": "lane_blocked",
            "detail": "internal vulnerability detail",
            "coordinates": [-1.0, 2.0],
        },
        credentials={"token": "secret"},
    )
    rendered = repr(build_operations_status(value))
    for secret in (
        "secret-provider-key",
        "private-endpoint",
        "do-not-expose",
        "secret-token",
        "internal vulnerability detail",
        "coordinates",
        "credentials",
    ):
        assert secret not in rendered


def test_main_fails_closed_for_unhealthy_or_malformed_input(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({})))
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["healthy"] is False

    monkeypatch.setattr(sys, "stdin", io.StringIO("[]"))
    assert main() == 2
    assert json.loads(capsys.readouterr().out)["error"] == "invalid_snapshot"
