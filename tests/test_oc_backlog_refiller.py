from scripts.oc_backlog_refiller import plan_refill


def issue(number, *labels, **extra):
    return {"number": number, "labels": list(labels), **extra}


def snapshot(*issues, leases=None, fingerprints=None, **extra):
    return {
        "issues": list(issues),
        "leases": list(leases or []),
        "dispatch_fingerprints": list(fingerprints or []),
        **extra,
    }


def candidate(ref, fingerprint, **extra):
    return {
        "source_kind": "issue",
        "source_ref": ref,
        "title": f"Work {ref}",
        "material_fingerprint": fingerprint,
        "priority": 1,
        **extra,
    }


def test_refills_only_to_configured_reserve_depth():
    state = snapshot(issue(1, "oc-queued"))
    result = plan_refill(
        state,
        [
            candidate("#2", "fp-2"),
            candidate("#3", "fp-3"),
            candidate("#4", "fp-4"),
        ],
        reserve_depth=3,
    )
    assert result["status"] == "refill_planned"
    assert result["deficit"] == 2
    assert [proposal["source_ref"] for proposal in result["proposals"]] == [
        "#2",
        "#3",
    ]


def test_duplicate_fingerprint_and_semantic_duplicate_are_suppressed():
    state = snapshot(
        issue(
            10,
            "oc-running",
            material_fingerprint="same",
            semantic_key="health-monitor",
        ),
        leases=[
            {
                "issue": 10,
                "id": "lease-10",
                "owner": "test-worker",
                "material_fingerprint": "same",
                "active": True,
            }
        ],
    )
    result = plan_refill(
        state,
        [
            candidate("#11", "same", semantic_key="other"),
            candidate("#12", "new", semantic_key="health-monitor"),
        ],
        reserve_depth=1,
    )
    assert result["status"] == "queue_empty_all_candidates_rejected"
    assert {item["reason"] for item in result["rejections"]} == {
        "duplicate_fingerprint",
        "semantic_duplicate",
    }


def test_dependency_gating_requires_completed_dependency():
    blocked = candidate("#20", "fp-20", dependencies=["contract-v1"])
    first = plan_refill(snapshot(), [blocked], reserve_depth=1)
    assert first["status"] == "queue_empty_all_candidates_rejected"
    assert first["rejections"] == [
        {"source_ref": "#20", "reason": "dependency_blocked"}
    ]

    second = plan_refill(
        snapshot(completed_dependencies=["contract-v1"]),
        [blocked],
        reserve_depth=1,
    )
    assert second["status"] == "refill_planned"
    assert second["proposals"][0]["dependencies"] == ["contract-v1"]


def test_protected_boundary_exhaustion_parks_truthfully():
    result = plan_refill(
        snapshot(),
        [candidate("#30", "fp-30", protected_boundaries=["production"])],
        reserve_depth=2,
    )
    assert result["status"] == "queue_empty_all_candidates_rejected"
    assert result["proposals"] == []
    assert result["rejections"] == [
        {"source_ref": "#30", "reason": "protected_boundary"}
    ]


def test_planner_failure_is_distinct_from_healthy_empty_queue():
    result = plan_refill(
        snapshot(),
        [],
        reserve_depth=1,
        planner_ok=False,
    )
    assert result["status"] == "queue_empty_planner_failed"
    assert result["rejections"] == [{"reason": "planner_unavailable"}]


def test_unhealthy_health_snapshot_fails_closed_without_proposals():
    # Two executable states on one issue is not an isolatable conflict.
    result = plan_refill(
        snapshot(issue(40, "oc-queued", "oc-validating", head_sha="a" * 40)),
        [candidate("#41", "fp-41")],
        reserve_depth=2,
    )
    assert result["status"] == "planner_failed"
    assert result["proposals"] == []
    assert result["rejections"][0]["reason"] == "health_contract_violation"
    assert "conflicts" not in result


def test_one_executable_parked_conflict_is_skipped_and_others_are_proposed():
    # Real shape from the scheduled run: #238 carried both oc-queued and a
    # backoff label, and that single issue failed the whole planner.
    state = snapshot(
        issue(238, "oc-queued", "oc-runtime-backoff"),
        issue(1, "oc-queued"),
    )
    result = plan_refill(
        state,
        [
            candidate("#238", "fp-238"),
            candidate("#2", "fp-2"),
            candidate("#3", "fp-3"),
        ],
        reserve_depth=3,
    )
    assert result["status"] == "refill_planned"
    # The contradictory issue is not counted as executable reserve.
    assert result["queued_count"] == 1
    assert result["deficit"] == 2
    assert [p["source_ref"] for p in result["proposals"]] == ["#2", "#3"]
    assert {"source_ref": "#238", "reason": "executable_parked_conflict"} in result[
        "rejections"
    ]
    [finding] = result["conflicts"]
    assert {
        key: finding[key]
        for key in ("type", "issue", "executable", "parked", "action", "counted_as_reserve")
    } == {
        "type": "executable_parked_conflict",
        "issue": 238,
        "executable": ["oc-queued"],
        "parked": ["oc-runtime-backoff"],
        "action": "issue_skipped",
        "counted_as_reserve": False,
    }
    # The actionable fix: drop the executable label, keep the parked one.
    assert finding["relabel"] == {"remove": ["oc-queued"], "add": []}
    assert finding["relabel_command"] == [
        "gh", "issue", "edit", "238", "--remove-label", "oc-queued",
    ]
    [follow_up] = result["conflict_follow_ups"]
    assert follow_up["issue"] == 238
    assert follow_up["kind"] == "issue_comment"
    assert follow_up["marker"] in follow_up["body"]
    assert "gh issue edit 238 --remove-label oc-queued" in follow_up["body"]


def test_conflict_does_not_mask_a_planner_blocking_violation():
    state = snapshot(
        issue(238, "oc-queued", "oc-repair-backoff"),
        issue(50, "oc-running"),  # running without a lease
    )
    result = plan_refill(state, [candidate("#2", "fp-2")], reserve_depth=2)
    assert result["status"] == "queue_empty_planner_failed"
    assert result["proposals"] == []
    assert result["rejections"][0]["reason"] == "health_contract_violation"
    assert [c["issue"] for c in result["conflicts"]] == [238]


def test_running_parked_conflict_with_active_lease_fails_closed():
    state = snapshot(
        issue(238, "oc-running", "oc-runtime-backoff"),
        leases=[
            {
                "issue": 238,
                "id": "lease-238",
                "owner": "worker-1",
                "material_fingerprint": "fp-238",
                "active": True,
            }
        ],
    )
    result = plan_refill(state, [candidate("#2", "fp-2")], reserve_depth=1)

    assert result["status"] == "queue_empty_planner_failed"
    assert result["proposals"] == []
    assert result["rejections"][0]["reason"] == "health_contract_violation"
    assert "conflicts" not in result
    assert "conflict_follow_ups" not in result


def test_validating_parked_conflict_fails_closed():
    state = snapshot(
        issue(238, "oc-validating", "oc-blocked", head_sha="a" * 40),
    )
    result = plan_refill(state, [candidate("#2", "fp-2")], reserve_depth=1)

    assert result["status"] == "queue_empty_planner_failed"
    assert result["proposals"] == []
    assert result["rejections"][0]["reason"] == "health_contract_violation"
    assert "conflicts" not in result


def test_healthy_plan_keeps_its_wire_shape_without_a_conflicts_key():
    result = plan_refill(snapshot(), [candidate("#2", "fp-2")], reserve_depth=1)
    assert "conflicts" not in result
    assert result["status"] == "refill_planned"


def test_unauthorized_source_cannot_enter_reserve():
    result = plan_refill(
        snapshot(),
        [candidate("invented", "fp-x", source_kind="freeform")],
        reserve_depth=1,
    )
    assert result["status"] == "queue_empty_all_candidates_rejected"
    assert result["rejections"] == [
        {"source_ref": "invented", "reason": "unauthorized_source"}
    ]


def test_repeated_cycle_does_not_duplicate_unchanged_work():
    work = candidate("#50", "fp-50", semantic_key="durable-gap-50")
    first = plan_refill(snapshot(), [work], reserve_depth=1)
    assert first["status"] == "refill_planned"
    assert len(first["proposals"]) == 1

    proposed = first["proposals"][0]
    second_state = snapshot(
        issue(
            50,
            "oc-queued",
            material_fingerprint=proposed["material_fingerprint"],
            semantic_key=proposed["semantic_key"],
        ),
        fingerprints=[proposed["material_fingerprint"]],
    )
    second = plan_refill(second_state, [work], reserve_depth=1)
    assert second["status"] == "reserve_satisfied"
    assert second["proposals"] == []


def test_depleted_queue_refill_order_is_deterministic():
    candidates = [
        candidate("#later", "fp-later", priority=2, created_at="2026-09-01"),
        candidate("#b", "fp-b", priority=1, created_at="2026-09-02"),
        candidate("#a", "fp-a", priority=1, created_at="2026-09-02"),
    ]
    first = plan_refill(snapshot(), candidates, reserve_depth=2)
    second = plan_refill(snapshot(), list(reversed(candidates)), reserve_depth=2)

    assert first["proposals"] == second["proposals"]
    assert [item["source_ref"] for item in first["proposals"]] == ["#a", "#b"]


def knowledge_gap_payload(**overrides):
    return {
        "schema": "oc.knowledge-gap-reserve-source.v1",
        "taxon_id": "taxon-1",
        "taxon_name": "Orchidaceae example",
        "domain": "ecology",
        "research_question": "What evidence resolves the ecology gap for taxon-1?",
        "execution_mode": "bounded_research_mission",
        "review_required": True,
        "automatic_publication": False,
        "knowledge_graph_mutation": False,
        "taxonomy_mutation": False,
        "sensitive_locality_disclosure": False,
        **overrides,
    }


def test_preserves_canonical_knowledge_gap_payload_in_proposal():
    payload = knowledge_gap_payload()
    result = plan_refill(
        snapshot(),
        [candidate("#gap", "fp-gap", source_kind="objective", source_payload=payload)],
        reserve_depth=1,
    )
    assert result["status"] == "refill_planned"
    assert result["proposals"][0]["source_payload"] == payload


def test_rejects_source_payload_authority_escalation():
    result = plan_refill(
        snapshot(),
        [candidate("#gap", "fp-gap", source_kind="objective", source_payload=knowledge_gap_payload(automatic_publication=True))],
        reserve_depth=1,
    )
    assert result["proposals"] == []
    assert result["rejections"] == [
        {"source_ref": "#gap", "reason": "authority_escalation"}
    ]


def test_rejects_malformed_or_oversized_source_payload():
    malformed = knowledge_gap_payload(unexpected_instruction="publish now")
    oversized = knowledge_gap_payload(research_question="x" * 5000)
    result = plan_refill(
        snapshot(),
        [
            candidate("#malformed", "fp-malformed", source_kind="objective", source_payload=malformed),
            candidate("#oversized", "fp-oversized", source_kind="objective", source_payload=oversized),
        ],
        reserve_depth=2,
    )
    assert result["proposals"] == []
    assert result["rejections"] == [
        {"source_ref": "#malformed", "reason": "invalid_source_payload"},
        {"source_ref": "#oversized", "reason": "source_payload_too_large"},
    ]


def test_preserves_valid_queue_source_identity_and_rejects_unknown_identity():
    result = plan_refill(
        snapshot(),
        [
            candidate(
                "#brain",
                "fp-brain",
                queue_source_kind="brain-knowledge-gap",
            ),
            candidate(
                "#invented",
                "fp-invented",
                queue_source_kind="invented-queue",
            ),
        ],
        reserve_depth=2,
    )

    assert result["proposals"][0]["queue_source_kind"] == "brain-knowledge-gap"
    assert result["rejections"] == [
        {"source_ref": "#invented", "reason": "unauthorized_queue_source"}
    ]


def test_a_queue_made_only_of_conflicts_is_blocked_not_healthy():
    # Five contradictory issues and nothing to propose used to report
    # queue_empty_healthy, a green run with no runnable work at all.
    parked = ["oc-runtime-backoff", "oc-repair-backoff", "oc-blocked"]
    state = snapshot(
        *[issue(300 + n, "oc-queued", parked[n % 3]) for n in range(5)]
    )
    result = plan_refill(state, [], reserve_depth=3)
    assert result["status"] == "queue_blocked_by_conflicts"
    assert result["queued_count"] == 0
    assert result["proposals"] == []
    assert [c["issue"] for c in result["conflicts"]] == [300, 301, 302, 303, 304]
    follow_ups = result["conflict_follow_ups"]
    assert [f["issue"] for f in follow_ups] == [300, 301, 302, 303, 304]
    assert len({f["idempotency_key"] for f in follow_ups}) == 5
    for finding in result["conflicts"]:
        assert finding["relabel"]["remove"] == ["oc-queued"]
        assert finding["parked"] and finding["parked"][0] in parked


def test_conflict_follow_ups_are_one_per_issue_and_idempotent():
    duplicate = issue(238, "oc-queued", "oc-runtime-backoff")
    state = snapshot(duplicate, dict(duplicate))
    first = plan_refill(state, [], reserve_depth=1)
    second = plan_refill(state, [], reserve_depth=1)
    assert [f["issue"] for f in first["conflict_follow_ups"]] == [238]
    assert first["conflict_follow_ups"] == second["conflict_follow_ups"]
    # A different conflict on the same issue is a different follow-up.
    changed = plan_refill(
        snapshot(issue(238, "oc-queued", "oc-blocked")), [], reserve_depth=1
    )
    assert (
        changed["conflict_follow_ups"][0]["idempotency_key"]
        != first["conflict_follow_ups"][0]["idempotency_key"]
    )


def test_conflicts_alongside_real_reserve_are_reported_without_blocking():
    state = snapshot(issue(1, "oc-queued"), issue(238, "oc-queued", "oc-blocked"))
    result = plan_refill(state, [], reserve_depth=2)
    assert result["status"] == "reserve_below_target_no_eligible_candidates"
    assert [c["issue"] for c in result["conflicts"]] == [238]


def test_queue_empty_healthy_is_reserved_for_a_genuinely_empty_candidate_set():
    """Rejected-only candidates are not healthy idle; no candidates at all is."""
    assert plan_refill(snapshot(), [], reserve_depth=2)["status"] == "queue_empty_healthy"

    rejected = plan_refill(
        snapshot(),
        [candidate("#90", "fp-90", dependencies=["never-done"])],
        reserve_depth=2,
    )
    assert rejected["status"] == "queue_empty_all_candidates_rejected"
    assert rejected["status"] != "queue_empty_healthy"
    assert rejected["proposals"] == []
    assert rejected["rejections"] == [
        {"source_ref": "#90", "reason": "dependency_blocked"}
    ]
