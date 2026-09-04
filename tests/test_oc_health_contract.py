from scripts.oc_health_contract import evaluate


def issue(number, *labels, **extra):
    return {"number": number, "labels": list(labels), **extra}


def test_healthy_queued_issue():
    report = evaluate({"issues": [issue(1, "oc-queued")]})
    assert report["healthy"] is True
    assert report["counts"]["queued"] == 1
    assert report["violations"] == []


def test_queued_backoff_is_contract_violation():
    report = evaluate({"issues": [issue(308, "oc-queued", "oc-runtime-backoff", "oc-repair-backoff")]})
    assert report["healthy"] is False
    assert any(v["type"] == "executable_parked_conflict" and v["issue"] == 308 for v in report["violations"])


def test_multiple_executable_states_are_rejected():
    report = evaluate({"issues": [issue(2, "oc-queued", "oc-running")]})
    assert report["healthy"] is False
    assert any(v["type"] == "multiple_executable_states" for v in report["violations"])


def test_running_requires_exactly_one_active_lease():
    no_lease = evaluate({"issues": [issue(3, "oc-running")]})
    assert any(v["type"] == "running_lease_cardinality" and v["active_leases"] == 0 for v in no_lease["violations"])

    two_leases = evaluate({
        "issues": [issue(3, "oc-running")],
        "leases": [
            {"id": "a", "issue": 3, "active": True},
            {"id": "b", "issue": 3, "active": True},
        ],
    })
    assert any(v["type"] == "running_lease_cardinality" and v["active_leases"] == 2 for v in two_leases["violations"])


def test_single_running_lease_is_healthy():
    report = evaluate({
        "issues": [issue(4, "oc-running")],
        "leases": [{"id": "lease-4", "issue": 4, "active": True}],
    })
    assert report["healthy"] is True


def test_orphan_and_stale_leases_fail_closed():
    report = evaluate({
        "issues": [issue(5, "oc-queued")],
        "leases": [{"id": "old", "issue": 5, "active": True, "stale": True}],
    })
    kinds = {v["type"] for v in report["violations"]}
    assert "orphan_active_lease" in kinds
    assert "stale_lease" in kinds


def test_duplicate_dispatch_fingerprint_is_rejected():
    report = evaluate({
        "issues": [],
        "dispatch_fingerprints": ["301:abc", "301:abc"],
    })
    assert report["healthy"] is False
    assert report["violations"] == [
        {"type": "duplicate_dispatch_fingerprint", "fingerprint": "301:abc"}
    ]


def test_validating_requires_exact_head():
    bad = evaluate({"issues": [issue(6, "oc-validating", pr=77)]})
    assert any(v["type"] == "validating_without_exact_head" for v in bad["violations"])

    good = evaluate({
        "issues": [issue(6, "oc-validating", validation_target={"pr": 77, "head_sha": "deadbeef"})]
    })
    assert good["healthy"] is True
    assert good["validating_targets"] == [{"issue": 6, "pr": 77, "head_sha": "deadbeef"}]


def test_provider_and_exception_fields_are_preserved_without_changing_queue_health():
    report = evaluate({
        "issues": [issue(7, "oc-queued")],
        "provider": {"anthropic": "degraded", "openai": "available"},
        "exceptions": [{"type": "spending", "owner_required": True}],
    })
    assert report["healthy"] is True
    assert report["provider"]["anthropic"] == "degraded"
    assert report["exceptions"][0]["type"] == "spending"
