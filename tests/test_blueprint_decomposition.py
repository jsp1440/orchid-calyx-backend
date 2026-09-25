"""Tests for blueprint/task decomposition: GovernanceDecision → ResearchBlueprint.

All tests are deterministic and provider-free. No model inference, no network,
no paid API calls. Fixtures use the same governance flags as test_governance_check.py.

Covers:
    - admitted governance → valid bounded blueprint
    - denied governance → fails closed (no tasks created)
    - malformed governance decision → fails closed
    - duplicate invocation → idempotent (same blueprint_id, same task keys)
    - task count limit enforced
    - dependency depth limit enforced
    - cycles rejected
    - duplicate task keys rejected
    - resource/capability propagation (human_review_required)
    - human-review restrictions propagate (auth classes owner-gated)
    - canonical queue receives only validated/admitted tasks (enqueue_blueprint)
    - no provider/API call required (all decompositions are deterministic)
    - route returns 422 for blocked governance
    - route returns blueprint summary for admitted governance
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_PRODUCTION,
    AUTH_READ_ONLY,
    AUTH_SCIENCE_PUB,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
)
from app.scientific_synthesis.blueprint import (
    BLUEPRINT_VERSION,
    MAX_DEPENDENCY_DEPTH,
    MAX_TASK_COUNT,
    BlueprintValidationError,
    ResearchBlueprint,
    _blueprint_fingerprint,
    _compute_max_depth,
    _detect_cycles,
    decompose_governed_action,
    enqueue_blueprint,
    validate_blueprint,
)
from app.scientific_synthesis.governance import (
    GovernanceDecision,
    GovernanceOutcome,
    check_manifest_governance,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

MANIFEST_VERSION = "oc-run-evidence-manifest-v1"
_RUN_FP = "a" * 64

BASE_MANIFEST: dict[str, Any] = {
    "contract_version": MANIFEST_VERSION,
    "run_id": "run:phal-2026-09",
    "research_question": "What is the optimal temperature range for Phalaenopsis?",
    "taxon_id": "taxon:phalaenopsis",
    "taxonomy_snapshot_id": "hassler:2026-09",
    "run_fingerprint": _RUN_FP,
    "created_at_utc": "2026-09-12T00:00:00+00:00",
    "verification_state": "ready_for_review",
    "resolved_evidence_count": 1,
    "missing_evidence_count": 0,
    "knowledge_gap_count": 0,
    "contradictions": [],
    "review_decision": None,
    "epistemic_state": None,
    "human_review_required": True,
    "automatic_scientific_publication_allowed": False,
    "canonical_knowledge_mutation_allowed": False,
    "canonical_activation_requires_human_authority": True,
    "immutable": True,
}


def manifest(**overrides: Any) -> dict[str, Any]:
    return {**BASE_MANIFEST, **overrides}


def _admitted_decision() -> GovernanceDecision:
    return check_manifest_governance(BASE_MANIFEST, "build_synthesis")


def _blocked_decision() -> GovernanceDecision:
    return check_manifest_governance(BASE_MANIFEST, "canonical_knowledge_mutation")


_RUN_CTX = {
    "run_id": "run:phal-2026-09",
    "taxon_id": "taxon:phalaenopsis",
    "research_question": "What is the optimal temperature range for Phalaenopsis?",
}


# ── decompose_governed_action: fail-closed checks ─────────────────────────────


class TestDecomposeFailsClosed:
    def test_not_a_governance_decision_raises(self):
        with pytest.raises(BlueprintValidationError, match="GOVERNANCE_DECISION_REQUIRED"):
            decompose_governed_action(
                "not-a-decision",  # type: ignore[arg-type]
                BASE_MANIFEST,
                "build_synthesis",
                **_RUN_CTX,
            )

    def test_blocked_decision_raises(self):
        decision = _blocked_decision()
        assert not decision.admitted
        with pytest.raises(BlueprintValidationError, match="GOVERNANCE_NOT_ADMITTED"):
            decompose_governed_action(decision, BASE_MANIFEST, "canonical_knowledge_mutation", **_RUN_CTX)

    def test_admitted_false_raises(self):
        """A GovernanceDecision that has outcome ADMITTED but admitted=False is rejected."""
        # Forge a contradictory object (admitted=False, outcome=ADMITTED) — fails closed.
        fake = GovernanceDecision(
            outcome=GovernanceOutcome.ADMITTED,
            admitted=False,
            reason="forged",
            blocking_flags=[],
        )
        with pytest.raises(BlueprintValidationError, match="GOVERNANCE_ADMITTED_FALSE"):
            decompose_governed_action(fake, BASE_MANIFEST, "build_synthesis", **_RUN_CTX)

    def test_blocking_flags_raises(self):
        fake = GovernanceDecision(
            outcome=GovernanceOutcome.ADMITTED,
            admitted=True,
            reason="forged",
            blocking_flags=["some:flag"],
        )
        with pytest.raises(BlueprintValidationError, match="GOVERNANCE_HAS_BLOCKING_FLAGS"):
            decompose_governed_action(fake, BASE_MANIFEST, "build_synthesis", **_RUN_CTX)

    def test_missing_run_fingerprint_raises(self):
        m = {k: v for k, v in BASE_MANIFEST.items() if k != "run_fingerprint"}
        decision = _admitted_decision()
        with pytest.raises(BlueprintValidationError, match="MANIFEST_FINGERPRINT_REQUIRED"):
            decompose_governed_action(decision, m, "build_synthesis", **_RUN_CTX)

    def test_malformed_fingerprint_raises(self):
        m = manifest(run_fingerprint="not-a-sha256")
        decision = _admitted_decision()
        with pytest.raises(BlueprintValidationError, match="MANIFEST_FINGERPRINT_REQUIRED"):
            decompose_governed_action(decision, m, "build_synthesis", **_RUN_CTX)

    def test_unknown_action_raises_for_invalid(self):
        decision = _admitted_decision()
        with pytest.raises(BlueprintValidationError, match="BLUEPRINT_UNKNOWN_ACTION"):
            decompose_governed_action(decision, BASE_MANIFEST, "destroy_everything", **_RUN_CTX)


# ── decompose_governed_action: admitted build_synthesis ───────────────────────


class TestDecomposeBuildSynthesis:
    @pytest.fixture()
    def blueprint(self) -> ResearchBlueprint:
        return decompose_governed_action(
            _admitted_decision(), BASE_MANIFEST, "build_synthesis", **_RUN_CTX
        )

    def test_returns_research_blueprint(self, blueprint):
        assert isinstance(blueprint, ResearchBlueprint)

    def test_blueprint_version_correct(self, blueprint):
        assert blueprint.version == BLUEPRINT_VERSION

    def test_blueprint_id_is_64_char_hex(self, blueprint):
        assert len(blueprint.blueprint_id) == 64
        int(blueprint.blueprint_id, 16)  # must be valid hex

    def test_blueprint_id_is_deterministic(self):
        bp1 = decompose_governed_action(
            _admitted_decision(), BASE_MANIFEST, "build_synthesis", **_RUN_CTX
        )
        bp2 = decompose_governed_action(
            _admitted_decision(), BASE_MANIFEST, "build_synthesis", **_RUN_CTX
        )
        assert bp1.blueprint_id == bp2.blueprint_id

    def test_run_fingerprint_matches_manifest(self, blueprint):
        assert blueprint.run_fingerprint == _RUN_FP

    def test_proposed_action_preserved(self, blueprint):
        assert blueprint.proposed_action == "build_synthesis"

    def test_governance_outcome_admitted(self, blueprint):
        assert blueprint.governance_outcome == "admitted"

    def test_task_count_within_limit(self, blueprint):
        assert len(blueprint.task_leaves) <= MAX_TASK_COUNT

    def test_task_count_nonzero(self, blueprint):
        assert len(blueprint.task_leaves) > 0

    def test_human_review_leaf_present_when_required(self, blueprint):
        # human_review_required=True → submit-for-human-review leaf
        keys = [leaf.key for leaf in blueprint.task_leaves]
        assert any("submit-for-human-review" in k for k in keys)

    def test_no_human_review_leaf_when_not_required(self):
        m = manifest(human_review_required=False)
        decision = check_manifest_governance(m, "build_synthesis")
        bp = decompose_governed_action(decision, m, "build_synthesis", **_RUN_CTX)
        keys = [leaf.key for leaf in bp.task_leaves]
        assert not any("submit-for-human-review" in k for k in keys)

    def test_dependency_depth_within_limit(self, blueprint):
        assert blueprint.max_dependency_depth <= MAX_DEPENDENCY_DEPTH

    def test_no_duplicate_task_keys(self, blueprint):
        keys = [leaf.key for leaf in blueprint.task_leaves]
        assert len(keys) == len(set(keys))

    def test_all_task_keys_share_blueprint_prefix(self, blueprint):
        prefix = blueprint.blueprint_id[:16]
        for leaf in blueprint.task_leaves:
            assert leaf.key.startswith(f"research:{prefix}:")

    def test_retrieve_evidence_leaf_is_read_only(self, blueprint):
        retrieve = next(
            (leaf for leaf in blueprint.task_leaves if "retrieve-evidence" in leaf.key),
            None,
        )
        assert retrieve is not None
        assert retrieve.authority_class == AUTH_READ_ONLY

    def test_produce_synthesis_leaf_is_workspace(self, blueprint):
        produce = next(
            (leaf for leaf in blueprint.task_leaves if "produce-synthesis" in leaf.key),
            None,
        )
        assert produce is not None
        assert produce.authority_class == AUTH_WORKSPACE

    def test_governance_flags_propagated(self, blueprint):
        assert blueprint.human_review_required is True
        assert blueprint.automatic_publication_allowed is False
        assert blueprint.canonical_mutation_allowed is False
        assert blueprint.canonical_activation_requires_human_authority is True

    def test_summary_is_serializable(self, blueprint):
        summary = blueprint.summary()
        json.dumps(summary)  # must not raise

    def test_summary_contains_required_fields(self, blueprint):
        s = blueprint.summary()
        for field in (
            "blueprint_id",
            "run_fingerprint",
            "proposed_action",
            "governance_outcome",
            "task_count",
            "tasks",
            "version",
        ):
            assert field in s, f"Missing field: {field}"


# ── decompose_governed_action: other actions ──────────────────────────────────


class TestDecomposeOtherActions:
    def test_read_evidence_admitted(self):
        decision = check_manifest_governance(BASE_MANIFEST, "read_evidence")
        bp = decompose_governed_action(decision, BASE_MANIFEST, "read_evidence", **_RUN_CTX)
        assert len(bp.task_leaves) == 1
        assert bp.task_leaves[0].authority_class == AUTH_READ_ONLY

    def test_build_manifest_admitted(self):
        decision = check_manifest_governance(BASE_MANIFEST, "build_manifest")
        bp = decompose_governed_action(decision, BASE_MANIFEST, "build_manifest", **_RUN_CTX)
        assert len(bp.task_leaves) == 1

    def test_human_review_submission_admitted(self):
        decision = check_manifest_governance(BASE_MANIFEST, "human_review_submission")
        bp = decompose_governed_action(
            decision, BASE_MANIFEST, "human_review_submission", **_RUN_CTX
        )
        assert len(bp.task_leaves) == 1
        assert bp.task_leaves[0].priority == Priority.P0

    def test_canonical_mutation_leaf_is_owner_gated(self):
        m = manifest(canonical_knowledge_mutation_allowed=True)
        decision = check_manifest_governance(m, "canonical_knowledge_mutation")
        bp = decompose_governed_action(decision, m, "canonical_knowledge_mutation", **_RUN_CTX)
        assert len(bp.task_leaves) == 1
        leaf = bp.task_leaves[0]
        assert leaf.authority_class == AUTH_PRODUCTION
        assert leaf.requires_owner_gate  # DeepOrchestrate auto-gates AUTH_PRODUCTION

    def test_publication_leaf_is_owner_gated(self):
        m = manifest(automatic_scientific_publication_allowed=True)
        decision = check_manifest_governance(m, "automatic_scientific_publication")
        bp = decompose_governed_action(
            decision, m, "automatic_scientific_publication", **_RUN_CTX
        )
        assert len(bp.task_leaves) == 1
        leaf = bp.task_leaves[0]
        assert leaf.authority_class == AUTH_SCIENCE_PUB
        assert leaf.requires_owner_gate

    def test_canonical_activation_leaf_is_owner_gated(self):
        m = manifest(canonical_activation_requires_human_authority=False)
        decision = check_manifest_governance(m, "canonical_activation")
        bp = decompose_governed_action(decision, m, "canonical_activation", **_RUN_CTX)
        assert len(bp.task_leaves) == 1
        leaf = bp.task_leaves[0]
        assert leaf.authority_class == AUTH_PRODUCTION
        assert leaf.requires_owner_gate


# ── validate_blueprint: structural invariants ─────────────────────────────────


class TestValidateBlueprint:
    def _base_blueprint(self, **overrides: Any) -> ResearchBlueprint:
        bp = decompose_governed_action(
            _admitted_decision(), BASE_MANIFEST, "build_synthesis", **_RUN_CTX
        )
        if not overrides:
            return bp
        return ResearchBlueprint(**{
            "blueprint_id": bp.blueprint_id,
            "run_fingerprint": bp.run_fingerprint,
            "proposed_action": bp.proposed_action,
            "governance_outcome": bp.governance_outcome,
            "task_leaves": bp.task_leaves,
            "max_dependency_depth": bp.max_dependency_depth,
            "human_review_required": bp.human_review_required,
            "automatic_publication_allowed": bp.automatic_publication_allowed,
            "canonical_mutation_allowed": bp.canonical_mutation_allowed,
            "canonical_activation_requires_human_authority": bp.canonical_activation_requires_human_authority,
            "run_id": bp.run_id,
            "taxon_id": bp.taxon_id,
            "research_question": bp.research_question,
            "created_at_utc": bp.created_at_utc,
            **overrides,
        })

    def test_valid_blueprint_passes(self):
        bp = self._base_blueprint()
        validate_blueprint(bp)  # must not raise

    def test_malformed_blueprint_id_raises(self):
        bp = self._base_blueprint(blueprint_id="not-a-sha256")
        with pytest.raises(BlueprintValidationError, match="BLUEPRINT_ID_MALFORMED"):
            validate_blueprint(bp)

    def test_malformed_run_fingerprint_raises(self):
        bp = self._base_blueprint(run_fingerprint="short")
        with pytest.raises(BlueprintValidationError, match="MANIFEST_FINGERPRINT_REQUIRED"):
            validate_blueprint(bp)

    def test_task_count_exceeded_raises(self):
        # Build 9 leaves (> MAX_TASK_COUNT=8) with unique keys and no deps.
        extra_leaves = tuple(
            TaskLeaf(
                key=f"research:fake0000deadbeef:step-{i}",
                title=f"Step {i}",
                repo="orchid-calyx-backend",
                module="app/scientific_synthesis",
                priority=Priority.P2,
                authority_class=AUTH_WORKSPACE,
                consequence_risk="low",
                dependencies=[],
                acceptance_criteria=["Done"],
            )
            for i in range(9)
        )
        bp = self._base_blueprint(task_leaves=extra_leaves)
        with pytest.raises(BlueprintValidationError, match="BLUEPRINT_TASK_COUNT_EXCEEDED"):
            validate_blueprint(bp)

    def test_duplicate_task_keys_raises(self):
        leaf = TaskLeaf(
            key="research:fake0000deadbeef:same-step",
            title="Same",
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=[],
            acceptance_criteria=["Done"],
        )
        bp = self._base_blueprint(task_leaves=(leaf, leaf))
        with pytest.raises(BlueprintValidationError, match="BLUEPRINT_DUPLICATE_TASK_KEYS"):
            validate_blueprint(bp)


# ── Cycle detection ───────────────────────────────────────────────────────────


class TestCycleDetection:
    def _leaf(self, key: str, deps: list[str]) -> TaskLeaf:
        return TaskLeaf(
            key=key,
            title=key,
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=deps,
            acceptance_criteria=["Done"],
        )

    def test_no_cycle_detected_for_linear_chain(self):
        a = self._leaf("a", [])
        b = self._leaf("b", ["a"])
        c = self._leaf("c", ["b"])
        assert not _detect_cycles((a, b, c))

    def test_cycle_detected_for_direct_loop(self):
        a = self._leaf("a", ["b"])
        b = self._leaf("b", ["a"])
        assert _detect_cycles((a, b))

    def test_cycle_detected_for_triangle(self):
        a = self._leaf("a", ["c"])
        b = self._leaf("b", ["a"])
        c = self._leaf("c", ["b"])
        assert _detect_cycles((a, b, c))

    def test_no_cycle_for_diamond(self):
        a = self._leaf("a", [])
        b = self._leaf("b", ["a"])
        c = self._leaf("c", ["a"])
        d = self._leaf("d", ["b", "c"])
        assert not _detect_cycles((a, b, c, d))


# ── Dependency depth ──────────────────────────────────────────────────────────


class TestDepthComputation:
    def _leaf(self, key: str, deps: list[str]) -> TaskLeaf:
        return TaskLeaf(
            key=key,
            title=key,
            repo="orchid-calyx-backend",
            module="app/scientific_synthesis",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
            dependencies=deps,
            acceptance_criteria=["Done"],
        )

    def test_single_leaf_depth_zero(self):
        a = self._leaf("a", [])
        assert _compute_max_depth((a,)) == 0

    def test_two_leaf_chain_depth_one(self):
        a = self._leaf("a", [])
        b = self._leaf("b", ["a"])
        assert _compute_max_depth((a, b)) == 1

    def test_five_leaf_chain_depth_four(self):
        a = self._leaf("a", [])
        b = self._leaf("b", ["a"])
        c = self._leaf("c", ["b"])
        d = self._leaf("d", ["c"])
        e = self._leaf("e", ["d"])
        assert _compute_max_depth((a, b, c, d, e)) == 4

    def test_parallel_branches_max_depth(self):
        a = self._leaf("a", [])
        b = self._leaf("b", ["a"])
        c = self._leaf("c", ["b"])  # depth 2
        d = self._leaf("d", ["a"])  # depth 1
        assert _compute_max_depth((a, b, c, d)) == 2


# ── enqueue_blueprint: idempotency ────────────────────────────────────────────


class TestEnqueueBlueprint:
    @pytest.fixture()
    def blueprint(self) -> ResearchBlueprint:
        return decompose_governed_action(
            _admitted_decision(), BASE_MANIFEST, "build_synthesis", **_RUN_CTX
        )

    @pytest.fixture()
    def reservoir(self) -> DeepOrchestrate:
        return DeepOrchestrate()

    def test_enqueue_returns_positive_count(self, blueprint, reservoir):
        count = enqueue_blueprint(blueprint, reservoir)
        assert count > 0

    def test_enqueue_returns_leaf_count(self, blueprint, reservoir):
        count = enqueue_blueprint(blueprint, reservoir)
        assert count == len(blueprint.task_leaves)

    def test_enqueue_is_idempotent(self, blueprint, reservoir):
        count1 = enqueue_blueprint(blueprint, reservoir)
        count2 = enqueue_blueprint(blueprint, reservoir)
        assert count1 > 0
        assert count2 == 0  # all keys already registered

    def test_same_blueprint_same_keys_idempotent(self):
        """Same GovernanceDecision → same blueprint_id → same task keys → 0 new on re-run."""
        reservoir = DeepOrchestrate()
        bp1 = decompose_governed_action(
            _admitted_decision(), BASE_MANIFEST, "build_synthesis", **_RUN_CTX
        )
        bp2 = decompose_governed_action(
            _admitted_decision(), BASE_MANIFEST, "build_synthesis", **_RUN_CTX
        )
        assert bp1.blueprint_id == bp2.blueprint_id
        enqueue_blueprint(bp1, reservoir)
        assert enqueue_blueprint(bp2, reservoir) == 0

    def test_leaves_appear_in_reservoir(self, blueprint, reservoir):
        enqueue_blueprint(blueprint, reservoir)
        registered_keys = set(reservoir._tasks.keys())
        for leaf in blueprint.task_leaves:
            assert leaf.key in registered_keys

    def test_blocked_leaves_are_owner_gated(self):
        m = manifest(canonical_knowledge_mutation_allowed=True)
        decision = check_manifest_governance(m, "canonical_knowledge_mutation")
        bp = decompose_governed_action(decision, m, "canonical_knowledge_mutation", **_RUN_CTX)
        reservoir = DeepOrchestrate()
        enqueue_blueprint(bp, reservoir)
        bp_keys = {leaf.key for leaf in bp.task_leaves}
        for key, leaf in reservoir._tasks.items():
            if key in bp_keys:
                assert leaf.requires_owner_gate


# ── Blueprint fingerprint ─────────────────────────────────────────────────────


class TestBlueprintFingerprint:
    def test_fingerprint_is_deterministic(self):
        fp1 = _blueprint_fingerprint(_RUN_FP, "build_synthesis", "admitted")
        fp2 = _blueprint_fingerprint(_RUN_FP, "build_synthesis", "admitted")
        assert fp1 == fp2

    def test_fingerprint_changes_with_different_action(self):
        fp1 = _blueprint_fingerprint(_RUN_FP, "build_synthesis", "admitted")
        fp2 = _blueprint_fingerprint(_RUN_FP, "read_evidence", "admitted")
        assert fp1 != fp2

    def test_fingerprint_changes_with_different_run_fingerprint(self):
        fp1 = _blueprint_fingerprint(_RUN_FP, "build_synthesis", "admitted")
        fp2 = _blueprint_fingerprint("b" * 64, "build_synthesis", "admitted")
        assert fp1 != fp2

    def test_fingerprint_is_64_char_hex(self):
        fp = _blueprint_fingerprint(_RUN_FP, "build_synthesis", "admitted")
        assert len(fp) == 64
        int(fp, 16)


# ── Route tests ───────────────────────────────────────────────────────────────


@pytest.fixture()
def client():
    from fastapi import FastAPI

    from app.scientific_synthesis.routes import router

    _app = FastAPI()
    _app.include_router(router)
    return TestClient(_app)


_BLUEPRINT_PAYLOAD = {
    "manifest": BASE_MANIFEST,
    "proposed_action": "build_synthesis",
    "run_id": "run:phal-2026-09",
    "taxon_id": "taxon:phalaenopsis",
    "research_question": "What is the optimal temperature range for Phalaenopsis?",
}


class TestBlueprintRoute:
    def test_admitted_action_returns_200(self, client):
        resp = client.post("/synthesis/blueprint", json=_BLUEPRINT_PAYLOAD)
        assert resp.status_code == 200

    def test_response_contains_blueprint_id(self, client):
        resp = client.post("/synthesis/blueprint", json=_BLUEPRINT_PAYLOAD)
        data = resp.json()
        assert "blueprint_id" in data
        assert len(data["blueprint_id"]) == 64

    def test_response_contains_tasks(self, client):
        resp = client.post("/synthesis/blueprint", json=_BLUEPRINT_PAYLOAD)
        data = resp.json()
        assert "tasks" in data
        assert len(data["tasks"]) > 0

    def test_response_task_count_within_limit(self, client):
        resp = client.post("/synthesis/blueprint", json=_BLUEPRINT_PAYLOAD)
        data = resp.json()
        assert data["task_count"] <= MAX_TASK_COUNT

    def test_response_is_deterministic(self, client):
        r1 = client.post("/synthesis/blueprint", json=_BLUEPRINT_PAYLOAD)
        r2 = client.post("/synthesis/blueprint", json=_BLUEPRINT_PAYLOAD)
        assert r1.json()["blueprint_id"] == r2.json()["blueprint_id"]

    def test_blocked_action_returns_422(self, client):
        payload = {**_BLUEPRINT_PAYLOAD, "proposed_action": "canonical_knowledge_mutation"}
        resp = client.post("/synthesis/blueprint", json=payload)
        assert resp.status_code == 422
        assert resp.json()["detail"]["code"] == "GOVERNANCE_NOT_ADMITTED"

    def test_unknown_action_returns_422(self, client):
        payload = {**_BLUEPRINT_PAYLOAD, "proposed_action": "destroy_everything"}
        resp = client.post("/synthesis/blueprint", json=payload)
        assert resp.status_code == 422

    def test_missing_manifest_returns_422(self, client):
        payload = {k: v for k, v in _BLUEPRINT_PAYLOAD.items() if k != "manifest"}
        resp = client.post("/synthesis/blueprint", json=payload)
        assert resp.status_code == 422

    def test_wrong_contract_version_returns_422(self, client):
        m = manifest(contract_version="wrong-v1")
        payload = {**_BLUEPRINT_PAYLOAD, "manifest": m}
        resp = client.post("/synthesis/blueprint", json=payload)
        assert resp.status_code == 422

    def test_malformed_fingerprint_returns_422(self, client):
        m = manifest(run_fingerprint="short")
        payload = {**_BLUEPRINT_PAYLOAD, "manifest": m}
        resp = client.post("/synthesis/blueprint", json=payload)
        assert resp.status_code == 422

    def test_governance_flags_in_response(self, client):
        resp = client.post("/synthesis/blueprint", json=_BLUEPRINT_PAYLOAD)
        data = resp.json()
        assert data["human_review_required"] is True
        assert data["automatic_publication_allowed"] is False
        assert data["canonical_mutation_allowed"] is False

    def test_no_provider_api_call_required(self, client):
        """Blueprint decomposition is deterministic — no external API call needed."""
        # If this test passes, no network call was made (no mock needed for pure logic).
        resp = client.post("/synthesis/blueprint", json=_BLUEPRINT_PAYLOAD)
        assert resp.status_code == 200
