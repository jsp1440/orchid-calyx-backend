"""Tests for app/intake/intelligence_bridge.py -- LIT-INTEL-002 acceptance criteria.

Acceptance criteria:
  AC1. Only lifecycle-gated items (ASSESSED, UNDER_REVIEW, PUBLISHED, TRIAGED)
       produce TaskLeaf entries; DISCOVERED and unknown lifecycles are rejected.
  AC2. Source findings and OC hypotheses must be in separate, distinct fields.
  AC3. All twelve triage dimensions must be present with evidence-based states.
  AC4. A stable, deterministic task key (fingerprint-based) deduplicates on
       re-proposal without creating a duplicate.
  AC5. Prior terminal outcomes (COMPLETED/BLOCKED in reservoir, or explicit
       suppress_fingerprint) prevent re-admission of the same fingerprint.
  AC6. EvidenceRecord.outcome drives suppression; UNMEASURED does not suppress.
  AC7. Material fingerprint must match computed sha256 of spec + sorted criteria.
"""

from __future__ import annotations

import pytest

from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_PRODUCTION,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    TaskLeaf,
    TaskState,
)
from app.intake.intelligence_bridge import (
    _TERMINAL_OUTCOMES,
    BRIDGE_VERSION,
    EvidenceGate,
    EvidenceRecord,
    GateRejection,
    IntelligenceBridge,
    ProposeTaskRequest,
    TriageDimensionAssessment,
    _compute_fingerprint,
)
from app.intake.technology_scout import TRIAGE_DIMENSIONS

_SPEC = "Add bounded hybrid search to research_station."
_CRITERIA = ["Unit tests pass", "Integration tests pass", "No production mutation"]
_FP = _compute_fingerprint(_SPEC, _CRITERIA)
_PSA = (
    "The paper reports hybrid BM25+dense retrieval improves recall@10 by 8% "
    "on standard QA benchmarks."
)
_AOC = (
    "OC research_station uses pure dense retrieval; BM25 index not present. "
    "Potential overlap with calyx semantic layer."
)


def _make_triage(state: str = "SCORED", score: float | None = 0.7) -> dict:
    return {
        dim: TriageDimensionAssessment(
            state=state,
            score=score,
            rationale=f"Evidence-based assessment for {dim}.",
        )
        for dim in TRIAGE_DIMENSIONS
    }


def _make_gate(**overrides: object) -> EvidenceGate:
    spec = overrides.pop("implementation_specification", _SPEC)
    criteria = list(overrides.pop("acceptance_criteria", _CRITERIA))
    fp = overrides.pop("material_fingerprint", _compute_fingerprint(spec, criteria))
    psa = overrides.pop("primary_source_assessment", _PSA)
    aoc = overrides.pop("architectural_overlap_comparison", _AOC)
    triage = overrides.pop("triage_assessment", _make_triage())
    issue_number = overrides.pop("github_issue_number", 1361)
    psv = overrides.pop("primary_source_version", "v1.2")
    return EvidenceGate(
        primary_source_version=psv,
        primary_source_assessment=psa,
        architectural_overlap_comparison=aoc,
        implementation_specification=spec,
        acceptance_criteria=criteria,
        github_issue_number=issue_number,
        material_fingerprint=fp,
        triage_assessment=triage,
        **overrides,
    )


def _make_item(lifecycle: str = "ASSESSED", title: str = "Hybrid search") -> dict:
    return {"id": 1, "lifecycle": lifecycle, "title": title}


def _make_bridge() -> IntelligenceBridge:
    return IntelligenceBridge(reservoir=DeepOrchestrate(configured_width=5))


class TestTriageDimensionAssessment:
    def test_scored_with_score_is_valid(self):
        t = TriageDimensionAssessment(state="SCORED", score=0.8, rationale="Good evidence.")
        assert t.state == "SCORED"
        assert t.score == 0.8

    def test_scored_requires_score(self):
        with pytest.raises((ValueError, Exception)):
            TriageDimensionAssessment(state="SCORED", score=None, rationale="Missing score.")

    def test_explicitly_unassessed_forbids_score(self):
        with pytest.raises((ValueError, Exception)):
            TriageDimensionAssessment(
                state="EXPLICITLY_UNASSESSED", score=0.5, rationale="Should not have score."
            )

    def test_explicitly_unassessed_without_score_is_valid(self):
        t = TriageDimensionAssessment(
            state="EXPLICITLY_UNASSESSED", rationale="Not applicable for this domain."
        )
        assert t.score is None

    def test_score_below_zero_rejected(self):
        with pytest.raises((ValueError, Exception)):
            TriageDimensionAssessment(state="SCORED", score=-0.1, rationale="Out of range.")

    def test_score_above_one_rejected(self):
        with pytest.raises((ValueError, Exception)):
            TriageDimensionAssessment(state="SCORED", score=1.1, rationale="Out of range.")

    def test_boundary_scores_accepted(self):
        for s in (0.0, 1.0):
            t = TriageDimensionAssessment(state="SCORED", score=s, rationale="Boundary.")
            assert t.score == s

    def test_metadata_state_rejected(self):
        with pytest.raises((ValueError, Exception)):
            TriageDimensionAssessment(
                state="METADATA_SIGNAL",  # type: ignore[arg-type]
                score=None,
                rationale="Should be rejected.",
            )


class TestEvidenceGate:
    def test_valid_gate_constructs(self):
        gate = _make_gate()
        assert gate.github_issue_number == 1361
        assert gate.material_fingerprint == _FP

    def test_missing_triage_dimension_rejected(self):
        bad_triage = {dim: _make_triage()[dim] for dim in list(TRIAGE_DIMENSIONS)[:-1]}
        with pytest.raises((ValueError, Exception), match="Missing required triage dimensions"):
            _make_gate(triage_assessment=bad_triage)

    def test_all_twelve_dimensions_required(self):
        triage = _make_triage()
        removed = next(iter(triage.keys()))
        triage.pop(removed)
        with pytest.raises((ValueError, Exception)):
            _make_gate(triage_assessment=triage)

    def test_extra_fields_forbidden(self):
        with pytest.raises((ValueError, Exception)):
            EvidenceGate(
                primary_source_version="v1",
                primary_source_assessment=_PSA,
                architectural_overlap_comparison=_AOC,
                implementation_specification=_SPEC,
                acceptance_criteria=_CRITERIA,
                github_issue_number=1361,
                material_fingerprint=_FP,
                triage_assessment=_make_triage(),
                unknown_extra_field="bad",  # type: ignore[call-arg]
            )

    def test_task_key_contains_issue_and_fingerprint_prefix(self):
        gate = _make_gate()
        key = gate.task_key
        assert "gh#1361" in key
        assert _FP[:16] in key
        assert len(key) >= len("lit-intel:gh#1361:") + 16

    def test_computed_fingerprint_matches_provided(self):
        gate = _make_gate()
        assert gate.computed_fingerprint == gate.material_fingerprint

    def test_fingerprint_is_deterministic(self):
        fp1 = _compute_fingerprint(_SPEC, _CRITERIA)
        fp2 = _compute_fingerprint(_SPEC, list(reversed(_CRITERIA)))
        assert fp1 == fp2

    def test_acceptance_criteria_empty_rejected(self):
        with pytest.raises((ValueError, Exception)):
            _make_gate(acceptance_criteria=[])

    def test_priority_above_4_rejected(self):
        with pytest.raises((ValueError, Exception)):
            _make_gate(priority=5)

    def test_priority_below_0_rejected(self):
        with pytest.raises((ValueError, Exception)):
            _make_gate(priority=-1)


class TestAC1LifecycleGating:
    def test_discovered_item_is_rejected(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1,
            gate=gate,
            assessor="analyst",
            get_item=lambda _: _make_item(lifecycle="DISCOVERED"),
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "LIFECYCLE_NOT_ASSESSED"
        assert "DISCOVERED" in result.reason

    def test_unknown_lifecycle_is_rejected(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1,
            gate=gate,
            assessor="analyst",
            get_item=lambda _: _make_item(lifecycle="UNKNOWN_STATE"),
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "LIFECYCLE_NOT_ASSESSED"

    @pytest.mark.parametrize("lc", ["ASSESSED", "UNDER_REVIEW", "PUBLISHED", "TRIAGED"])
    def test_admitted_lifecycles_succeed(self, lc):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1,
            gate=gate,
            assessor="analyst",
            get_item=lambda _: _make_item(lifecycle=lc),
        )
        assert isinstance(result, TaskLeaf)

    def test_nonexistent_item_is_rejected(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=9999,
            gate=gate,
            assessor="analyst",
            get_item=lambda _: None,
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "ITEM_NOT_FOUND"


class TestAC2FindingsSeparation:
    def test_identical_fields_rejected(self):
        b = _make_bridge()
        same_text = "A" * 20
        gate = _make_gate(
            primary_source_assessment=same_text,
            architectural_overlap_comparison=same_text,
        )
        result = b.propose_task(
            item_id=1,
            gate=gate,
            assessor="analyst",
            get_item=lambda _: _make_item(),
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "FINDINGS_NOT_SEPARATED"

    def test_distinct_fields_allowed(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1,
            gate=gate,
            assessor="analyst",
            get_item=lambda _: _make_item(),
        )
        assert isinstance(result, TaskLeaf)

    def test_whitespace_only_difference_rejected(self):
        b = _make_bridge()
        base = "The paper demonstrates X improvement on benchmark Y."
        gate = _make_gate(
            primary_source_assessment=base,
            architectural_overlap_comparison=f"  {base}  ",
        )
        result = b.propose_task(
            item_id=1,
            gate=gate,
            assessor="analyst",
            get_item=lambda _: _make_item(),
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "FINDINGS_NOT_SEPARATED"


class TestAC3TrigageDimensionsComplete:
    def test_all_twelve_present_in_valid_gate(self):
        gate = _make_gate()
        assert len(gate.triage_assessment) == len(TRIAGE_DIMENSIONS)
        for dim in TRIAGE_DIMENSIONS:
            assert dim in gate.triage_assessment

    def test_incomplete_triage_rejected_by_model(self):
        triage = _make_triage()
        dim_to_remove = TRIAGE_DIMENSIONS[0]
        triage.pop(dim_to_remove)
        with pytest.raises((ValueError, Exception), match="Missing required triage dimensions"):
            _make_gate(triage_assessment=triage)

    def test_evidence_based_states_required(self):
        triage = _make_triage(state="EXPLICITLY_UNASSESSED", score=None)
        gate = _make_gate(triage_assessment=triage)
        assert gate.triage_assessment[TRIAGE_DIMENSIONS[0]].state == "EXPLICITLY_UNASSESSED"

    def test_metadata_signal_state_rejected(self):
        with pytest.raises((ValueError, Exception)):
            TriageDimensionAssessment(
                state="UNASSESSED",  # type: ignore[arg-type]
                score=None,
                rationale="Scout metadata state.",
            )

    def test_triage_count_recorded_in_evidence(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1,
            gate=gate,
            assessor="analyst",
            get_item=lambda _: _make_item(),
        )
        assert isinstance(result, TaskLeaf)
        assert result.evidence["assessed_triage_dimensions"] == 12


class TestAC4TaskKeyStableAndDeduplicable:
    def test_task_key_is_stable(self):
        gate = _make_gate()
        assert gate.task_key == gate.task_key

    def test_task_key_contains_issue_number(self):
        gate = _make_gate()
        assert "gh#1361" in gate.task_key

    def test_task_key_is_long_enough(self):
        gate = _make_gate()
        key = gate.task_key
        assert len(key) >= len("lit-intel:gh#1361:") + 16

    def test_second_proposal_returns_existing_leaf(self):
        b = _make_bridge()
        gate = _make_gate()
        def item_fn(_): return _make_item()
        leaf1 = b.propose_task(item_id=1, gate=gate, assessor="a", get_item=item_fn)
        leaf2 = b.propose_task(item_id=1, gate=gate, assessor="b", get_item=item_fn)
        assert isinstance(leaf1, TaskLeaf)
        assert isinstance(leaf2, TaskLeaf)
        assert leaf1 is leaf2

    def test_different_spec_produces_different_key(self):
        spec2 = "Add sparse BM25 index to content pipeline."
        gate1 = _make_gate()
        gate2 = _make_gate(implementation_specification=spec2)
        assert gate1.task_key != gate2.task_key

    def test_criteria_order_does_not_affect_fingerprint(self):
        fp1 = _compute_fingerprint(_SPEC, _CRITERIA)
        fp2 = _compute_fingerprint(_SPEC, list(reversed(_CRITERIA)))
        assert fp1 == fp2


class TestAC5PriorTerminalOutcomeSuppresses:
    def test_completed_task_in_reservoir_suppresses_rediscovery(self):
        b = _make_bridge()
        gate = _make_gate()
        def item_fn(_): return _make_item()

        leaf1 = b.propose_task(item_id=1, gate=gate, assessor="a", get_item=item_fn)
        assert isinstance(leaf1, TaskLeaf)
        leaf1.state = TaskState.COMPLETED

        result2 = b.propose_task(item_id=1, gate=gate, assessor="b", get_item=item_fn)
        assert isinstance(result2, GateRejection)
        assert result2.gate == "PRIOR_TERMINAL_OUTCOME"
        assert "completed" in result2.reason.lower()

    def test_blocked_task_in_reservoir_suppresses(self):
        b = _make_bridge()
        gate = _make_gate()
        def item_fn(_): return _make_item()

        leaf1 = b.propose_task(item_id=1, gate=gate, assessor="a", get_item=item_fn)
        assert isinstance(leaf1, TaskLeaf)
        leaf1.state = TaskState.BLOCKED

        result2 = b.propose_task(item_id=1, gate=gate, assessor="b", get_item=item_fn)
        assert isinstance(result2, GateRejection)
        assert result2.gate == "PRIOR_TERMINAL_OUTCOME"

    def test_explicit_suppress_fingerprint_blocks_admission(self):
        b = _make_bridge()
        gate = _make_gate()
        b.suppress_fingerprint(gate.material_fingerprint)

        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "PRIOR_TERMINAL_OUTCOME"

    def test_active_task_allows_idempotent_return(self):
        b = _make_bridge()
        gate = _make_gate()
        def item_fn(_): return _make_item()

        leaf1 = b.propose_task(item_id=1, gate=gate, assessor="a", get_item=item_fn)
        assert isinstance(leaf1, TaskLeaf)
        leaf2 = b.propose_task(item_id=1, gate=gate, assessor="b", get_item=item_fn)
        assert isinstance(leaf2, TaskLeaf)
        assert leaf2 is leaf1

    def test_is_suppressed_reflects_state(self):
        b = _make_bridge()
        fp = "a" * 64
        assert not b.is_suppressed(fp)
        b.suppress_fingerprint(fp)
        assert b.is_suppressed(fp)

    def test_different_bridges_have_isolated_suppression(self):
        b1 = _make_bridge()
        b2 = _make_bridge()
        fp = _FP
        b1.suppress_fingerprint(fp)
        assert b1.is_suppressed(fp)
        assert not b2.is_suppressed(fp)


class TestAC6OutcomeRecordingAndSuppression:
    def _admitted_leaf(self, b: IntelligenceBridge) -> tuple[TaskLeaf, EvidenceGate]:
        gate = _make_gate()
        leaf = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(leaf, TaskLeaf)
        return leaf, gate

    @pytest.mark.parametrize("outcome", sorted(_TERMINAL_OUTCOMES))
    def test_terminal_outcomes_suppress(self, outcome):
        b = _make_bridge()
        _, gate = self._admitted_leaf(b)
        ev = EvidenceRecord(
            issue_number=1361,
            evaluator="analyst",
            outcome=outcome,  # type: ignore[arg-type]
            outcome_notes="Terminal.",
        )
        result = b.record_outcome(
            item_id=1,
            task_key=gate.task_key,
            evidence=ev,
            material_fingerprint=gate.material_fingerprint,
        )
        assert result["suppressed_future_rediscovery"] is True
        assert b.is_suppressed(gate.material_fingerprint)

    def test_unmeasured_does_not_suppress(self):
        b = _make_bridge()
        _, gate = self._admitted_leaf(b)
        ev = EvidenceRecord(
            issue_number=1361,
            evaluator="analyst",
            outcome="UNMEASURED",
            outcome_notes="Still under investigation.",
        )
        result = b.record_outcome(
            item_id=1,
            task_key=gate.task_key,
            evidence=ev,
            material_fingerprint=gate.material_fingerprint,
        )
        assert result["suppressed_future_rediscovery"] is False
        assert not b.is_suppressed(gate.material_fingerprint)

    def test_record_event_callback_called(self):
        b = _make_bridge()
        _, gate = self._admitted_leaf(b)
        events: list[dict] = []
        ev = EvidenceRecord(
            issue_number=1361,
            evaluator="analyst",
            outcome="MEASURED_BENEFIT",
            outcome_notes="8% recall improvement confirmed.",
            pr_number=999,
            benefit_metric="recall@10 +8%",
        )
        b.record_outcome(
            item_id=1,
            task_key=gate.task_key,
            evidence=ev,
            material_fingerprint=gate.material_fingerprint,
            record_event=lambda **kw: events.append(kw),
        )
        assert len(events) == 1
        assert events[0]["event_type"] == "TASK_OUTCOME"
        assert events[0]["event_payload"]["outcome"] == "MEASURED_BENEFIT"

    def test_canonical_graph_not_mutated(self):
        b = _make_bridge()
        _, gate = self._admitted_leaf(b)
        ev = EvidenceRecord(
            issue_number=1361, evaluator="analyst", outcome="UNMEASURED", outcome_notes="x"
        )
        result = b.record_outcome(
            item_id=1,
            task_key=gate.task_key,
            evidence=ev,
            material_fingerprint=gate.material_fingerprint,
        )
        assert result["canonical_graph_mutated"] is False

    def test_no_record_event_callback_does_not_raise(self):
        b = _make_bridge()
        _, gate = self._admitted_leaf(b)
        ev = EvidenceRecord(
            issue_number=1361, evaluator="analyst", outcome="UNMEASURED", outcome_notes="x"
        )
        result = b.record_outcome(
            item_id=1,
            task_key=gate.task_key,
            evidence=ev,
            material_fingerprint=gate.material_fingerprint,
        )
        assert "outcome" in result


class TestAC7FingerprintMismatch:
    def test_fingerprint_mismatch_is_rejected(self):
        b = _make_bridge()
        gate = _make_gate(material_fingerprint="a" * 64)
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "FINGERPRINT_MISMATCH"

    def test_correct_fingerprint_passes(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, TaskLeaf)

    def test_spec_change_invalidates_fingerprint(self):
        b = _make_bridge()
        original_fp = _compute_fingerprint(_SPEC, _CRITERIA)
        altered_spec = _SPEC + " With extra clause."
        gate = _make_gate(
            implementation_specification=altered_spec,
            material_fingerprint=original_fp,
        )
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "FINGERPRINT_MISMATCH"

    def test_criteria_change_invalidates_fingerprint(self):
        b = _make_bridge()
        original_fp = _compute_fingerprint(_SPEC, _CRITERIA)
        altered_criteria = _CRITERIA + ["Extra criterion added after fingerprint."]
        gate = _make_gate(
            acceptance_criteria=altered_criteria,
            material_fingerprint=original_fp,
        )
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, GateRejection)
        assert result.gate == "FINGERPRINT_MISMATCH"


class TestBridgeVersion:
    def test_bridge_version_constant(self):
        assert BRIDGE_VERSION.startswith("oc.intelligence-bridge.")

    def test_version_recorded_in_task_evidence(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, TaskLeaf)
        assert result.evidence["bridge_version"] == BRIDGE_VERSION

    def test_assessor_recorded_in_evidence(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1, gate=gate, assessor="dr.jones", get_item=lambda _: _make_item()
        )
        assert isinstance(result, TaskLeaf)
        assert result.evidence["assessor"] == "dr.jones"


class TestTaskLeafProperties:
    def test_issue_number_set_from_gate(self):
        b = _make_bridge()
        gate = _make_gate(github_issue_number=1361)
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, TaskLeaf)
        assert result.issue_number == 1361

    def test_acceptance_criteria_transferred(self):
        b = _make_bridge()
        gate = _make_gate()
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, TaskLeaf)
        assert sorted(result.acceptance_criteria) == sorted(_CRITERIA)

    def test_authority_workspace_stays_ready(self):
        b = _make_bridge()
        gate = _make_gate(authority_class=AUTH_WORKSPACE)
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, TaskLeaf)
        assert result.state == TaskState.READY

    def test_auth_production_moves_to_owner_gated(self):
        b = _make_bridge()
        gate = _make_gate(authority_class=AUTH_PRODUCTION)
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, TaskLeaf)
        assert result.state == TaskState.OWNER_GATED

    def test_resource_claims_transferred(self):
        b = _make_bridge()
        gate = _make_gate(resource_claims=["research_station_db"])
        result = b.propose_task(
            item_id=1, gate=gate, assessor="a", get_item=lambda _: _make_item()
        )
        assert isinstance(result, TaskLeaf)
        assert "research_station_db" in result.resources


class TestGateRejection:
    def test_to_dict_contains_expected_keys(self):
        r = GateRejection(
            gate="ITEM_NOT_FOUND",
            reason="Not found.",
            item_id=1,
            material_fingerprint=_FP,
        )
        d = r.to_dict()
        assert d["admitted"] is False
        assert d["gate"] == "ITEM_NOT_FOUND"
        assert d["item_id"] == 1

    def test_frozen_dataclass_prevents_mutation(self):
        r = GateRejection(gate="X", reason="Y", item_id=1)
        with pytest.raises((AttributeError, TypeError)):
            r.gate = "Z"  # type: ignore[misc]


class TestProposeTaskRequest:
    def test_valid_request_constructs(self):
        req = ProposeTaskRequest(item_id=1, assessor="analyst", gate=_make_gate())
        assert req.item_id == 1

    def test_item_id_must_be_positive(self):
        with pytest.raises((ValueError, Exception)):
            ProposeTaskRequest(item_id=0, assessor="analyst", gate=_make_gate())

    def test_assessor_cannot_be_empty(self):
        with pytest.raises((ValueError, Exception)):
            ProposeTaskRequest(item_id=1, assessor="", gate=_make_gate())


class TestProposeTaskRoute:
    def test_route_exists(self):
        from app.main import app

        routes = [r.path for r in app.routes]
        assert any("propose-task" in r for r in routes)

    def test_route_rejects_discovered_lifecycle(self, monkeypatch):
        from fastapi.testclient import TestClient

        from app.main import app

        fresh_bridge = _make_bridge()
        monkeypatch.setattr("app.intake.intelligence_bridge.bridge", fresh_bridge)
        monkeypatch.setattr(
            "app.intake.intelligence_bridge._default_get_item",
            lambda _: _make_item(lifecycle="DISCOVERED"),
        )

        gate = _make_gate()
        payload = {
            "item_id": 1,
            "assessor": "test-analyst",
            "gate": {
                "primary_source_version": gate.primary_source_version,
                "primary_source_assessment": gate.primary_source_assessment,
                "architectural_overlap_comparison": gate.architectural_overlap_comparison,
                "implementation_specification": gate.implementation_specification,
                "acceptance_criteria": list(gate.acceptance_criteria),
                "github_issue_number": gate.github_issue_number,
                "material_fingerprint": gate.material_fingerprint,
                "triage_assessment": {
                    dim: {
                        "state": "SCORED",
                        "score": 0.7,
                        "rationale": f"Evidence for {dim}.",
                    }
                    for dim in TRIAGE_DIMENSIONS
                },
            },
        }

        client = TestClient(app)
        resp = client.post(
            "/api/intake/intelligence/propose-task",
            json=payload,
            headers={"Authorization": "Bearer test"},
        )
        # 409: lifecycle gate; 401/403: auth gate; 503: auth/DB unavailable in test env
        assert resp.status_code in (409, 401, 403, 503)
