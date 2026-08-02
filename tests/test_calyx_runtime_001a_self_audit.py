from runtime.self_audit import AuditSignal, SelfAuditEngine, build_operational_briefing


def test_healthy_signals_produce_no_findings():
    report = SelfAuditEngine().audit(
        [
            AuditSignal("backend", "health", "healthy"),
            AuditSignal("github", "ci", "passing"),
        ]
    )

    assert report.status == "healthy"
    assert report.findings == ()
    assert report.autonomous_changes == ()


def test_unhealthy_signals_are_prioritized_deterministically():
    report = SelfAuditEngine().audit(
        [
            AuditSignal("harvester", "queue", "stale", "medium", 0.8),
            AuditSignal("github", "required_checks", "failed", "critical", 1.0),
        ]
    )

    assert report.status == "attention_required"
    assert [finding.finding_key for finding in report.findings] == [
        "github:required_checks",
        "harvester:queue",
    ]
    assert report.findings[0].priority == 100
    assert report.autonomous_changes == ()


def test_consequential_recommendations_remain_human_gated():
    report = SelfAuditEngine().audit(
        [
            AuditSignal(
                "github",
                "release",
                "blocked",
                "high",
                1.0,
                {"recommended_action": "merge"},
            )
        ]
    )

    finding = report.findings[0]
    assert finding.recommended_action == "merge"
    assert finding.requires_human_approval is True

    briefing = build_operational_briefing(report)
    assert briefing["execution_policy"] == {
        "mode": "observe_and_prepare_only",
        "automatic_merge": False,
        "automatic_deploy": False,
        "automatic_scientific_publication": False,
        "external_communications": False,
    }


def test_unknown_severity_fails_closed():
    try:
        SelfAuditEngine().audit([AuditSignal("x", "y", "failed", "catastrophic")])
    except ValueError as exc:
        assert "unsupported severity" in str(exc)
    else:
        raise AssertionError("unknown severity must fail closed")
