from runtime.durable_task_reserve_bridge import plan_durable_task_refill


def snapshot(*issues, fingerprints=None):
    return {
        "issues": list(issues),
        "leases": [],
        "dispatch_fingerprints": list(fingerprints or []),
    }


def self_audit_task(**overrides):
    return {
        "task_key": "self-audit:finding-1",
        "task_type": "platform_self_audit_followup",
        "title": "Repair evidenced audit finding",
        "payload": {
            "execution_mode": "draft_only",
            "automatic_merge": False,
            "automatic_deploy": False,
            "automatic_publication": False,
            "finding": {"finding_key": "finding-1"},
        },
        "status": "pending",
        "priority": 80,
        "required_approval": False,
        **overrides,
    }


def connector_task(**overrides):
    return {
        "task_key": "source-federation:add:source-1",
        "task_type": "source_federation_adapter_evaluation",
        "title": "Evaluate admitted source adapter",
        "payload": {
            "schema": "oc.source-federation-task.v1",
            "execution_mode": "draft_only",
            "network_fetch_authorized": False,
            "scientific_publication_authorized": False,
            "knowledge_graph_mutation_authorized": False,
            "taxonomy_mutation_authorized": False,
            "automatic_merge": False,
            "automatic_deploy": False,
        },
        "status": "pending",
        "priority": 20,
        "required_approval": False,
        **overrides,
    }


def test_depleted_reserve_admits_safe_durable_sources_with_true_identity():
    result = plan_durable_task_refill(
        snapshot(),
        [connector_task(), self_audit_task()],
        reserve_depth=2,
    )

    assert result["status"] == "refill_planned"
    assert [item["queue_source_kind"] for item in result["proposals"]] == [
        "self-audit",
        "connector-queue",
    ]
    assert result["source_candidate_count"] == 2
    assert result["source_rejections"] == []
    assert result["provider_launch_authorized"] is False
    assert result["no_api_mode"] is True


def test_repeated_cycle_does_not_duplicate_unchanged_durable_task():
    first = plan_durable_task_refill(
        snapshot(),
        [self_audit_task()],
        reserve_depth=1,
    )
    proposal = first["proposals"][0]
    existing = {
        "number": 700,
        "labels": ["oc-queued"],
        "material_fingerprint": proposal["material_fingerprint"],
        "semantic_key": proposal["semantic_key"],
    }

    repeated = plan_durable_task_refill(
        snapshot(existing, fingerprints=[proposal["material_fingerprint"]]),
        [self_audit_task()],
        reserve_depth=2,
    )

    assert repeated["proposals"] == []
    assert repeated["status"] == "reserve_below_target_no_eligible_candidates"
    assert repeated["rejections"] == [
        {
            "source_ref": "self-audit:finding-1",
            "reason": "duplicate_fingerprint",
        }
    ]


def test_review_gated_completed_and_unsupported_tasks_fail_closed():
    result = plan_durable_task_refill(
        snapshot(),
        [
            self_audit_task(required_approval=True),
            self_audit_task(
                task_key="self-audit:completed",
                status="completed",
            ),
            self_audit_task(
                task_key="invented:1",
                task_type="invented_task_type",
            ),
        ],
        reserve_depth=3,
    )

    assert result["proposals"] == []
    assert [item["reason"] for item in result["source_rejections"]] == [
        "protected_task",
        "task_not_pending",
        "unsupported_task_type",
    ]


def test_authority_expansion_and_malformed_payloads_are_rejected():
    escalated = connector_task()
    escalated["payload"] = {
        **escalated["payload"],
        "network_fetch_authorized": True,
    }
    malformed = self_audit_task()
    malformed["payload"] = "not-an-object"

    result = plan_durable_task_refill(
        snapshot(),
        [escalated, malformed],
        reserve_depth=2,
    )

    assert result["proposals"] == []
    assert [item["reason"] for item in result["source_rejections"]] == [
        "authority_escalation",
        "invalid_task_contract",
    ]


def test_candidate_order_is_deterministic_and_priority_preserving():
    first = plan_durable_task_refill(
        snapshot(),
        [connector_task(), self_audit_task()],
        reserve_depth=2,
    )
    second = plan_durable_task_refill(
        snapshot(),
        [self_audit_task(), connector_task()],
        reserve_depth=2,
    )

    assert first["proposals"] == second["proposals"]
    assert first["proposals"][0]["source_ref"] == "self-audit:finding-1"


def test_planner_failure_is_distinct_from_healthy_empty_queue():
    result = plan_durable_task_refill(
        snapshot(),
        [self_audit_task()],
        reserve_depth=1,
        planner_ok=False,
    )

    assert result["status"] == "queue_empty_planner_failed"
    assert result["proposals"] == []
