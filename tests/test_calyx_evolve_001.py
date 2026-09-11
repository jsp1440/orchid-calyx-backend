"""CALYX-EVOLVE-001 acceptance tests.

Each of the fifteen deterministic tests required by issue #1190 is present and
named after the requirement it discharges.  Nothing here monkeypatches around a
guard: every safety assertion runs the real loop and inspects the real durable
record.
"""

from __future__ import annotations

import pytest

from runtime.calyx_evolve import analysis as analysis_module
from runtime.calyx_evolve import campaign as campaign_module
from runtime.calyx_evolve import governance as governance_module
from runtime.calyx_evolve.analysis import (
    FINDING_COUNTEREVIDENCE,
    FINDING_FAILURE,
    FINDING_MISSING_EVIDENCE,
    FINDING_SUCCESS,
    FINDING_UNCERTAINTY,
)
from runtime.calyx_evolve.campaign import (
    TERMINAL_COMPLETED,
    TERMINAL_INELIGIBLE,
    TERMINAL_REJECTED_UNSAFE,
    CampaignRunner,
)
from runtime.calyx_evolve.candidates import (
    BASELINE_CONFIG,
    GENERATOR_MUTATION,
    Candidate,
    CandidateError,
    ReconciliationConfig,
)
from runtime.calyx_evolve.cognition import (
    KIND_EXPERT_RULE,
    CognitionItem,
    MissingProvenance,
    MissingRequiredCognition,
    load_cognition,
)
from runtime.calyx_evolve.defaults import (
    CANDIDATE_AUTHORSHIP_BLIND,
    CANDIDATE_BASELINE,
    CANDIDATE_FUZZY_GUARDED,
    CANDIDATE_FUZZY_UNGUARDED,
    DEFAULT_CAMPAIGN_ID,
    default_campaign,
    default_candidates,
    default_cognition,
)
from runtime.calyx_evolve.fixture import locked_fixture
from runtime.calyx_evolve.governance import (
    PROMOTION_BLOCKED,
    PROMOTION_REVIEW_PENDING,
    PROMOTION_STATES,
)
from runtime.calyx_evolve.memory import InMemoryExperimentMemory, replay_key
from runtime.calyx_evolve.metrics import (
    METRIC_ACCURACY,
    METRIC_COST,
    METRIC_FALSE_MERGE_COUNT,
    METRIC_PROVENANCE,
    METRIC_REPLAY,
    METRIC_RUNTIME,
    STATE_UNAVAILABLE,
)
from runtime.calyx_evolve.redaction import RedactionViolation
from runtime.calyx_evolve.safety import (
    CODE_MISSING_PROVENANCE,
    CODE_PRODUCTION_MUTATION,
    CODE_PROTECTED_LOCALITY,
)
from runtime.calyx_evolve.selection import (
    POLICY_BASELINE,
    POLICY_BEST_ELIGIBLE,
    POLICY_SEEDED_RANDOM,
    ScoredCandidate,
    SelectionError,
    build_selector,
)
from runtime.calyx_evolve.status import campaign_status

# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def fresh_runner() -> tuple[CampaignRunner, InMemoryExperimentMemory]:
    memory = InMemoryExperimentMemory()
    return CampaignRunner(memory=memory), memory


def probe_candidate(
    candidate_id: str, config: ReconciliationConfig, **kwargs
) -> Candidate:
    return Candidate(
        candidate_id=candidate_id,
        campaign_id=DEFAULT_CAMPAIGN_ID,
        label=candidate_id,
        hypothesis="probe candidate registered by the acceptance tests",
        config=config,
        generator=GENERATOR_MUTATION,
        parent_ids=(CANDIDATE_BASELINE,),
        **kwargs,
    )


def run_probe(
    runner: CampaignRunner, candidate: Candidate
) -> campaign_module.RunResult:
    campaign = default_campaign()
    runner.learn(campaign, default_cognition())
    baseline = default_candidates()[0]
    runner.design(campaign, [baseline])
    baseline_result = runner.experiment(campaign, baseline)
    runner.design(campaign, [candidate])
    return runner.experiment(
        campaign,
        candidate,
        baseline_metrics=baseline_result.metrics,
        baseline_score=baseline_result.score,
    )


def find_run(report: campaign_module.CycleReport, candidate_id: str):
    for result in report.results:
        if result.run["candidate_id"] == candidate_id:
            return result
    raise AssertionError(f"no run for {candidate_id}")


# --------------------------------------------------------------------------
# 1. complete learn-design-experiment-analyze-remember cycle
# --------------------------------------------------------------------------


def test_01_complete_cycle_executes_and_persists_every_stage():
    runner, memory = fresh_runner()
    campaign = default_campaign()

    report = runner.cycle(campaign, default_cognition(), default_candidates())

    # LEARN
    stored_campaign = memory.get_campaign(DEFAULT_CAMPAIGN_ID)
    assert stored_campaign is not None
    assert stored_campaign["governance_state"] == "DRAFT"
    assert stored_campaign["execution_scope"] == "STAGING_ONLY"
    assert stored_campaign["cognition_bundle_hash"] == report.cognition_bundle_hash
    cognition = memory.list_cognition(DEFAULT_CAMPAIGN_ID)
    assert len(cognition) == len(default_cognition())
    assert all(item["content_hash"].startswith("sha256:") for item in cognition)

    # DESIGN
    assert len(memory.list_candidates(DEFAULT_CAMPAIGN_ID)) == len(default_candidates())

    # EXPERIMENT
    assert len(report.results) == len(default_candidates())
    assert all(result.terminal_state == TERMINAL_COMPLETED for result in report.results)

    # ANALYZE
    for result in report.results:
        assert result.findings, f"{result.run['candidate_id']} produced no findings"
        assert memory.list_metrics(result.run_id)

    # REMEMBER
    assert len(memory.list_runs(DEFAULT_CAMPAIGN_ID)) == len(default_candidates())
    assert report.selected_candidate_id == CANDIDATE_FUZZY_GUARDED


# --------------------------------------------------------------------------
# 2. same replay key produces no duplicate run
# --------------------------------------------------------------------------


def test_02_same_replay_key_reuses_the_stored_run():
    runner, memory = fresh_runner()
    campaign = default_campaign()

    first = runner.cycle(campaign, default_cognition(), default_candidates())
    assert all(not result.reused for result in first.results)
    stored_after_first = {run["run_id"]: run for run in memory.list_runs(DEFAULT_CAMPAIGN_ID)}

    second = runner.cycle(campaign, default_cognition(), default_candidates())
    assert all(result.reused for result in second.results)

    stored_after_second = {run["run_id"]: run for run in memory.list_runs(DEFAULT_CAMPAIGN_ID)}
    assert stored_after_first.keys() == stored_after_second.keys()
    assert len(stored_after_second) == len(default_candidates())
    for run_id, run in stored_after_second.items():
        assert run["record_hash"] == stored_after_first[run_id]["record_hash"]

    # The key itself is a pure function of the campaign, config, fixture and versions.
    any_run = stored_after_first[next(iter(stored_after_first))]
    key = replay_key(
        campaign_id=DEFAULT_CAMPAIGN_ID,
        config_hash=BASELINE_CONFIG.config_hash,
        fixture_hash=locked_fixture().fixture_hash,
        evaluator_version=any_run["evaluator_version"],
        scoring_version=any_run["scoring_version"],
        baseline_candidate_id=CANDIDATE_BASELINE,
    )
    assert any(run["replay_key"] == key for run in stored_after_second.values())


def test_02b_a_changed_configuration_gets_a_different_replay_key():
    base = {
        "campaign_id": DEFAULT_CAMPAIGN_ID,
        "fixture_hash": locked_fixture().fixture_hash,
        "evaluator_version": "v1",
        "scoring_version": "s1",
        "baseline_candidate_id": CANDIDATE_BASELINE,
    }
    left = replay_key(config_hash=BASELINE_CONFIG.config_hash, **base)
    right = replay_key(
        config_hash=BASELINE_CONFIG.mutate(fuzzy_max_distance=1).config_hash, **base
    )
    assert left != right


# --------------------------------------------------------------------------
# 3. candidate lineage is retained
# --------------------------------------------------------------------------


def test_03_candidate_lineage_is_retained_through_memory():
    runner, memory = fresh_runner()
    runner.cycle(default_campaign(), default_cognition(), default_candidates())

    status = campaign_status(memory, DEFAULT_CAMPAIGN_ID)
    lineage = {row["candidate_id"]: row["lineage"] for row in status["runs"]}

    assert lineage[CANDIDATE_BASELINE] == []
    assert lineage[CANDIDATE_FUZZY_GUARDED] == [CANDIDATE_BASELINE]
    # Two generations deep: unguarded came from the guarded variant.
    assert lineage[CANDIDATE_FUZZY_UNGUARDED] == [
        CANDIDATE_FUZZY_GUARDED,
        CANDIDATE_BASELINE,
    ]

    stored = memory.get_candidate(CANDIDATE_FUZZY_UNGUARDED)
    assert stored["parent_ids"] == [CANDIDATE_FUZZY_GUARDED]


def test_03b_duplicate_novelty_keys_are_recorded_not_rerun():
    runner, memory = fresh_runner()
    campaign = default_campaign()
    runner.learn(campaign, default_cognition())

    original = default_candidates()[1]
    twin = Candidate(
        candidate_id="fuzzy-d1-renamed",
        campaign_id=DEFAULT_CAMPAIGN_ID,
        label="same strategy under a different name",
        hypothesis="a renamed duplicate must not be re-run",
        config=original.config,
        generator=GENERATOR_MUTATION,
        parent_ids=(CANDIDATE_BASELINE,),
    )
    assert twin.novelty_key == original.novelty_key

    registered, duplicates = runner.design(campaign, [original, twin])
    assert [c.candidate_id for c in registered] == [original.candidate_id]
    assert [c.candidate_id for c in duplicates] == ["fuzzy-d1-renamed"]
    assert memory.get_candidate("fuzzy-d1-renamed") is None


# --------------------------------------------------------------------------
# 4. objective metrics match locked expected outcomes
# --------------------------------------------------------------------------


def test_04_metrics_match_the_locked_fixture_expectations():
    runner, _ = fresh_runner()
    report = runner.cycle(default_campaign(), default_cognition(), default_candidates())

    expected = {
        # candidate: (accuracy numerator, false merges, abstentions)
        CANDIDATE_BASELINE: (10, 0, 4),
        CANDIDATE_FUZZY_GUARDED: (12, 0, 2),
        CANDIDATE_FUZZY_UNGUARDED: (11, 1, 1),
        CANDIDATE_AUTHORSHIP_BLIND: (7, 0, 7),
    }
    total = len(locked_fixture().records)

    for candidate_id, (correct, false_merges, abstentions) in expected.items():
        metrics = find_run(report, candidate_id).metrics.as_mapping()
        assert metrics[METRIC_ACCURACY].value == pytest.approx(correct / total)
        assert metrics[METRIC_FALSE_MERGE_COUNT].value == false_merges
        assert metrics["unresolved_abstention_count"].value == abstentions
        assert metrics[METRIC_PROVENANCE].value == 1.0
        assert metrics[METRIC_REPLAY].value == 1.0


# --------------------------------------------------------------------------
# 5. false merge remains visible even if the aggregate score improves
# --------------------------------------------------------------------------


def test_05_false_merge_survives_an_improving_aggregate_score():
    runner, memory = fresh_runner()
    report = runner.cycle(default_campaign(), default_cognition(), default_candidates())

    baseline = find_run(report, CANDIDATE_BASELINE)
    offender = find_run(report, CANDIDATE_FUZZY_UNGUARDED)

    # The aggregate genuinely improves: this is exactly the concealment risk.
    assert offender.score.value > baseline.score.value

    metrics = offender.metrics.as_mapping()
    assert metrics[METRIC_FALSE_MERGE_COUNT].value == 1
    assert offender.metrics.false_merge_records == ("rec-09",)

    counterevidence = [
        f for f in offender.findings if f.finding_type == FINDING_COUNTEREVIDENCE
    ]
    assert len(counterevidence) == 1
    assert counterevidence[0].code == "FALSE_MERGE_PRESENT"
    assert counterevidence[0].evidence["aggregate_improved"] is True
    assert counterevidence[0].evidence["false_merge_records"] == ["rec-09"]

    assert offender.run["promotable"] is False
    assert offender.proposal.state == PROMOTION_BLOCKED

    # The count is stored as its own durable metric row, not folded into the score.
    stored = {row["key"]: row for row in memory.list_metrics(offender.run_id)}
    assert stored[METRIC_FALSE_MERGE_COUNT]["value"] == 1
    status_row = next(
        row
        for row in campaign_status(memory, DEFAULT_CAMPAIGN_ID)["runs"]
        if row["candidate_id"] == CANDIDATE_FUZZY_UNGUARDED
    )
    assert status_row["false_merge_count"] == 1
    assert status_row["counterevidence"]


# --------------------------------------------------------------------------
# 6. missing provenance fails closed
# --------------------------------------------------------------------------


def test_06a_cognition_without_provenance_is_rejected():
    with pytest.raises(MissingProvenance):
        CognitionItem(
            item_id="rule-without-origin",
            kind=KIND_EXPERT_RULE,
            version="1.0.0",
            summary="a rule with no recorded origin",
            provenance={"reference": "somewhere", "recorded_at": "2026-08-26T00:00:00+00:00"},
        )


def test_06b_campaign_cannot_learn_without_a_release_and_evaluator():
    partial = [item for item in default_cognition() if item.kind == KIND_EXPERT_RULE]
    with pytest.raises(MissingRequiredCognition):
        load_cognition(partial)


def test_06c_incomplete_claim_provenance_blocks_promotion():
    runner, _memory = fresh_runner()
    candidate = probe_candidate(
        "no-provenance",
        BASELINE_CONFIG.mutate(fuzzy_max_distance=1, emit_provenance=False),
    )
    result = run_probe(runner, candidate)

    metrics = result.metrics.as_mapping()
    assert metrics[METRIC_ACCURACY].value == 1.0  # perfectly accurate...
    assert metrics[METRIC_PROVENANCE].value == 0.0  # ...and still unpromotable
    assert result.run["promotable"] is False
    assert CODE_MISSING_PROVENANCE in [
        v["code"] for v in result.run["safety_violations"]
    ]
    blocking = [
        f
        for f in result.findings
        if f.severity == analysis_module.SEVERITY_BLOCKING
        and f.code == "INCOMPLETE_PROVENANCE"
    ]
    assert blocking


# --------------------------------------------------------------------------
# 7. protected-locality signal makes a candidate ineligible
# --------------------------------------------------------------------------


def test_07_protected_locality_output_makes_the_candidate_ineligible():
    runner, memory = fresh_runner()
    candidate = probe_candidate(
        "locality-leaking", BASELINE_CONFIG.mutate(emit_protected_locality=True)
    )
    result = run_probe(runner, candidate)

    assert result.terminal_state == TERMINAL_INELIGIBLE
    assert result.run["eligible"] is False
    assert result.run["promotable"] is False
    codes = [v["code"] for v in result.run["safety_violations"]]
    assert CODE_PROTECTED_LOCALITY in codes
    assert result.proposal is None

    # The coordinates themselves never reach durable memory: the run record keeps
    # a resolution summary that carries no provenance block at all.
    serialised = repr(memory.runs) + repr(memory.findings) + repr(memory.metrics)
    assert "-43.1729" not in serialised
    assert "-22.9068" not in serialised

    # And nothing persisted carries a protected-locality *field*. The violation
    # evidence names the offending paths as text, which is the audit trail, not
    # an exposure.
    from runtime.calyx_evolve.redaction import find_violations

    assert find_violations(memory.runs) == ()
    assert find_violations(memory.findings) == ()
    assert find_violations(memory.metrics) == ()
    assert any(
        path.endswith("exact_latitude")
        for violation in result.run["safety_violations"]
        for path in violation["evidence"]
    )


def test_07b_an_ineligible_candidate_is_never_selected():
    scored = [
        ScoredCandidate("baseline", "run-b", True, True, 0.5),
        ScoredCandidate("leaky", "run-l", False, False, 0.99, ("PROTECTED_LOCALITY_EXPOSED",)),
    ]
    assert build_selector(POLICY_BEST_ELIGIBLE).select(scored).candidate_id == "baseline"
    assert build_selector(POLICY_SEEDED_RANDOM, seed=3).select(scored).candidate_id == "baseline"


# --------------------------------------------------------------------------
# 8. production-mutation request is rejected before execution
# --------------------------------------------------------------------------


def test_08_production_mutation_request_is_rejected_before_execution():
    runner, memory = fresh_runner()
    candidate = probe_candidate(
        "wants-production-write", BASELINE_CONFIG.mutate(request_production_write=True)
    )
    result = run_probe(runner, candidate)

    assert result.terminal_state == TERMINAL_REJECTED_UNSAFE
    assert result.run["executed"] is False
    assert result.run["artifact_digest"] is None
    assert result.run["resolutions"] == []
    assert result.run["metric_vector"] is None
    assert [v["code"] for v in result.run["safety_violations"]] == [
        CODE_PRODUCTION_MUTATION
    ]
    assert result.run["eligible"] is False
    assert result.proposal is None
    assert memory.list_proposals(DEFAULT_CAMPAIGN_ID) == []


def test_08b_the_sandbox_itself_refuses_forbidden_capabilities():
    from runtime.calyx_evolve.sandbox import ExperimentSandbox, SandboxViolation

    sandbox = ExperimentSandbox().start()
    for method in (
        sandbox.request_production_write,
        sandbox.request_taxonomy_activation,
        sandbox.request_knowledge_graph_publication,
        sandbox.request_external_publication,
    ):
        with pytest.raises(SandboxViolation):
            method()


# --------------------------------------------------------------------------
# 9. missing/unknown cost is unavailable, not numeric zero
# --------------------------------------------------------------------------


def test_09_unknown_cost_is_unavailable_never_zero():
    runner, memory = fresh_runner()
    report = runner.cycle(default_campaign(), default_cognition(), default_candidates())
    result = find_run(report, CANDIDATE_BASELINE)

    cost = result.metrics.as_mapping()[METRIC_COST]
    assert cost.state == STATE_UNAVAILABLE
    assert cost.value is None
    assert cost.value != 0

    stored = {row["key"]: row for row in memory.list_metrics(result.run_id)}
    assert stored[METRIC_COST]["state"] == STATE_UNAVAILABLE
    assert stored[METRIC_COST]["value"] is None

    missing = [
        f
        for f in result.findings
        if f.finding_type == FINDING_MISSING_EVIDENCE
        and f.code == f"UNAVAILABLE_{METRIC_COST.upper()}"
    ]
    assert missing


def test_09b_a_declared_cost_is_measured_and_requires_a_basis():
    runner, _ = fresh_runner()
    candidate = probe_candidate(
        "priced",
        BASELINE_CONFIG.mutate(fuzzy_max_distance=1),
        declared_cost_usd=0.0125,
        cost_basis="measured provider usage for this candidate",
    )
    result = run_probe(runner, candidate)
    cost = result.metrics.as_mapping()[METRIC_COST]
    assert cost.is_measured
    assert cost.value == pytest.approx(0.0125)

    with pytest.raises(CandidateError):
        probe_candidate("unbased", BASELINE_CONFIG, declared_cost_usd=1.0)


def test_09c_an_unavailable_weighted_metric_makes_the_score_unavailable():
    from runtime.calyx_evolve.metrics import MetricValue, MetricVector, aggregate_score

    vector = MetricVector(
        evaluator_version="v",
        scoring_version="s",
        fixture_hash="sha256:0",
        values=(
            MetricValue.unavailable(METRIC_ACCURACY, "not measured"),
            MetricValue.measured("false_merge_rate", 0.0, "none"),
            MetricValue.measured(METRIC_PROVENANCE, 1.0, "complete"),
        ),
        false_merge_records=(),
        missed_records=(),
    )
    score = aggregate_score(vector)
    assert score.state == STATE_UNAVAILABLE
    assert score.value is None


# --------------------------------------------------------------------------
# 10. analyzer distinguishes failure, counterevidence, uncertainty, missing evidence
# --------------------------------------------------------------------------


def test_10_analyzer_distinguishes_all_finding_types():
    runner, _ = fresh_runner()
    report = runner.cycle(default_campaign(), default_cognition(), default_candidates())

    by_type: dict[str, set[str]] = {}
    for result in report.results:
        for finding in result.findings:
            by_type.setdefault(finding.finding_type, set()).add(finding.code)

    assert FINDING_SUCCESS in by_type
    assert FINDING_FAILURE in by_type
    assert FINDING_COUNTEREVIDENCE in by_type
    assert FINDING_UNCERTAINTY in by_type
    assert FINDING_MISSING_EVIDENCE in by_type

    # The types are not synonyms for one another.
    assert "FALSE_MERGE_PRESENT" in by_type[FINDING_COUNTEREVIDENCE]
    assert "RECORDS_LEFT_UNRESOLVED" in by_type[FINDING_UNCERTAINTY]
    assert f"UNAVAILABLE_{METRIC_COST.upper()}" in by_type[FINDING_MISSING_EVIDENCE]
    assert any(code.startswith("REGRESSED_") for code in by_type[FINDING_FAILURE])
    assert any(code.startswith("IMPROVED_") for code in by_type[FINDING_SUCCESS])

    # A regression is reported for the authorship-blind candidate specifically.
    regressed = {
        f.code
        for f in find_run(report, CANDIDATE_AUTHORSHIP_BLIND).findings
        if f.finding_type == FINDING_FAILURE
    }
    assert f"REGRESSED_{METRIC_ACCURACY.upper()}" in regressed

    # Runtime is operational, not a scientific result, so it is never a failure.
    all_codes = {code for codes in by_type.values() for code in codes}
    assert f"REGRESSED_{METRIC_RUNTIME.upper()}" not in all_codes


# --------------------------------------------------------------------------
# 11. selector is deterministic under a seed
# --------------------------------------------------------------------------


def test_11_selectors_are_deterministic():
    scored = [
        ScoredCandidate(f"cand-{index}", f"run-{index}", index == 0, True, 0.5 + index / 100)
        for index in range(6)
    ]

    assert build_selector(POLICY_BASELINE).select(scored).candidate_id == "cand-0"
    assert build_selector(POLICY_BEST_ELIGIBLE).select(scored).candidate_id == "cand-5"

    picks = {build_selector(POLICY_SEEDED_RANDOM, seed=42).select(scored).candidate_id for _ in range(25)}
    assert len(picks) == 1

    shuffled = list(reversed(scored))
    assert (
        build_selector(POLICY_SEEDED_RANDOM, seed=42).select(shuffled).candidate_id
        == picks.pop()
    )
    assert build_selector(POLICY_SEEDED_RANDOM, seed=7).select(scored) is not None

    with pytest.raises(SelectionError):
        build_selector(POLICY_SEEDED_RANDOM)
    with pytest.raises(SelectionError):
        build_selector("ucb1")


def test_11b_a_whole_cycle_replays_to_the_same_selection():
    first = CampaignRunner(memory=InMemoryExperimentMemory()).cycle(
        default_campaign(), default_cognition(), default_candidates()
    )
    second = CampaignRunner(memory=InMemoryExperimentMemory()).cycle(
        default_campaign(), default_cognition(), default_candidates()
    )
    assert first.selected_candidate_id == second.selected_candidate_id
    assert first.cognition_bundle_hash == second.cognition_bundle_hash
    assert [r.run["artifact_digest"] for r in first.results] == [
        r.run["artifact_digest"] for r in second.results
    ]


# --------------------------------------------------------------------------
# 12. experiment success yields only a review-pending promotion proposal
# --------------------------------------------------------------------------


def test_12_success_yields_only_a_review_pending_proposal():
    runner, memory = fresh_runner()
    report = runner.cycle(default_campaign(), default_cognition(), default_candidates())

    winner = find_run(report, CANDIDATE_FUZZY_GUARDED)
    assert winner.run["promotable"] is True
    assert winner.run["improved_over_baseline"] is True

    proposal = winner.proposal
    assert proposal is not None
    assert proposal.state == PROMOTION_REVIEW_PENDING
    assert proposal.blockers == ()
    assert proposal.requires_human_scientific_review is True
    assert proposal.taxonomy_activation_permitted is False
    assert proposal.knowledge_graph_publication_permitted is False
    assert proposal.external_publication_permitted is False

    stored = memory.list_proposals(DEFAULT_CAMPAIGN_ID)
    assert {row["state"] for row in stored} <= set(PROMOTION_STATES)
    assert all(row["requires_human_scientific_review"] for row in stored)

    # The baseline is never proposed, and a non-improving candidate is not either.
    assert find_run(report, CANDIDATE_BASELINE).proposal is None
    assert find_run(report, CANDIDATE_AUTHORSHIP_BLIND).proposal is None


def test_12b_promotion_states_cannot_be_widened():
    with pytest.raises(governance_module.GovernanceError):
        governance_module.PromotionProposal(
            campaign_id="c",
            run_id="r",
            candidate_id="x",
            state="approved",
            rationale="not a permitted state",
        )
    with pytest.raises(governance_module.GovernanceError):
        governance_module.PromotionProposal(
            campaign_id="c",
            run_id="r",
            candidate_id="x",
            state=PROMOTION_REVIEW_PENDING,
            rationale="review cannot be waived",
            requires_human_scientific_review=False,
        )
    with pytest.raises(governance_module.GovernanceError):
        governance_module.PromotionProposal(
            campaign_id="c",
            run_id="r",
            candidate_id="x",
            state=PROMOTION_REVIEW_PENDING,
            rationale="activation cannot be granted",
            taxonomy_activation_permitted=True,
        )


# --------------------------------------------------------------------------
# 13. no taxonomy activation / KG publication path is reachable
# --------------------------------------------------------------------------


def test_13_no_activation_or_publication_path_exists_in_the_package():
    import importlib
    import pathlib
    import pkgutil
    import re

    import runtime.calyx_evolve as package

    forbidden_imports = (
        "runtime.taxonomy_release_intake",
        "runtime.taxonomy_preflight_release_gate",
        "runtime.knowledge_graph",
        "app.publication",
        "runtime.publication",
        "app.reasoning_publication",
    )

    modules = [name for _, name, _ in pkgutil.iter_modules(package.__path__)]
    assert modules, "calyx_evolve exposes no modules"

    for name in modules:
        module = importlib.import_module(f"runtime.calyx_evolve.{name}")
        source = pathlib.Path(module.__file__).read_text()

        # Nothing in the package may reach an activation or publication surface.
        for target in forbidden_imports:
            assert f"import {target}" not in source, f"{name} imports {target}"
            assert f"from {target}" not in source, f"{name} imports from {target}"

        # Every schema-qualified table the package touches is its own ledger.
        for referenced in re.findall(r"oc_admin\.([a-z_]+)", source):
            assert referenced.startswith(
                "calyx_evolve_"
            ), f"{name} references oc_admin.{referenced}"

        # No public callable may be named for activation, publication or approval.
        for attribute in dir(module):
            if attribute.startswith("_"):
                continue
            lowered = attribute.lower()
            assert not lowered.startswith(
                ("activate", "publish", "approve")
            ), f"{name}.{attribute} looks like an activation or publication entry point"

    # The promotion vocabulary is exhaustive: there is no approved or activated state.
    assert governance_module.PROMOTION_STATES == ("review_pending", "blocked")
    assert governance_module.EXECUTION_SCOPES == ("STAGING_ONLY",)


def test_13b_the_operator_router_exposes_no_activation_route():
    from app.routers.calyx_evolve import router

    paths = {(route.path, tuple(sorted(route.methods))) for route in router.routes}
    for path, methods in paths:
        assert "activate" not in path
        assert "publish" not in path
        assert "approve" not in path
        assert set(methods) <= {"GET", "POST", "HEAD"}
    # Exactly one non-read route, and it creates a staging experiment.
    writes = [path for path, methods in paths if "POST" in methods]
    assert writes == ["/api/calyx-evolve/campaigns/{campaign_id}/experiments"]


# --------------------------------------------------------------------------
# 14. concise records carry no chain-of-thought, transcripts or secrets
# --------------------------------------------------------------------------


def test_14_durable_records_reject_transcripts_and_secrets():
    runner, memory = fresh_runner()
    runner.cycle(default_campaign(), default_cognition(), default_candidates())

    from runtime.calyx_evolve.redaction import find_violations

    everything = {
        "campaigns": memory.campaigns,
        "cognition": memory.cognition,
        "candidates": memory.candidates,
        "runs": memory.runs,
        "metrics": memory.metrics,
        "findings": memory.findings,
        "proposals": memory.proposals,
    }
    # Structural, not substring: a hypothesis may legitimately contain the word
    # "transcription", but no record may carry a transcript, credential or
    # locality *field*, or a secret-shaped value.
    assert find_violations(everything) == ()

    def keys(payload):
        if isinstance(payload, dict):
            for key, value in payload.items():
                yield str(key).lower()
                yield from keys(value)
        elif isinstance(payload, (list, tuple)):
            for value in payload:
                yield from keys(value)

    present = set(keys(everything))
    for forbidden in (
        "chain_of_thought",
        "reasoning_trace",
        "scratchpad",
        "transcript",
        "messages",
        "system_prompt",
        "api_key",
        "database_url",
        "authorization",
        "exact_latitude",
    ):
        assert forbidden not in present


def test_14b_an_unsafe_record_cannot_be_written_at_all():
    memory = InMemoryExperimentMemory()
    with pytest.raises(RedactionViolation):
        memory.upsert_campaign(
            {"campaign_id": "c", "chain_of_thought": "first I considered..."}
        )
    with pytest.raises(RedactionViolation):
        memory.save_run(
            {
                "run_id": "r",
                "campaign_id": "c",
                "candidate_id": "x",
                "replay_key": "k",
                "terminal_state": "completed",
                "notes": "connect with sk-abcdefghijklmnopqrstuvwx",
            }
        )
    assert memory.campaigns == {}
    assert memory.runs == {}


def test_14c_findings_and_hypotheses_are_length_bounded():
    with pytest.raises(analysis_module.FindingError):
        analysis_module.Finding(
            run_id="r",
            finding_type=FINDING_SUCCESS,
            code="TOO_LONG",
            summary="x" * (analysis_module.SUMMARY_MAX_CHARS + 1),
        )
    with pytest.raises(CandidateError):
        probe_candidate("verbose", BASELINE_CONFIG).__class__(
            candidate_id="verbose",
            campaign_id=DEFAULT_CAMPAIGN_ID,
            label="verbose",
            hypothesis="y" * 401,
            config=BASELINE_CONFIG,
        )


# --------------------------------------------------------------------------
# 15. focused API tests over the read-only operator surface
# --------------------------------------------------------------------------


def api_client(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.routers import calyx_evolve as evolve_router

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CALYX_API_KEY", "test-api-key")
    monkeypatch.setattr(evolve_router, "_FALLBACK_MEMORY", InMemoryExperimentMemory())

    app = FastAPI()
    app.include_router(evolve_router.router)
    return TestClient(app)


def test_15_operator_surface_requires_authentication(monkeypatch):
    client = api_client(monkeypatch)
    assert client.get("/api/calyx-evolve/campaigns").status_code == 401
    assert (
        client.post(
            f"/api/calyx-evolve/campaigns/{DEFAULT_CAMPAIGN_ID}/experiments", json={}
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/calyx-evolve/campaigns", headers={"X-API-Key": "wrong"}
        ).status_code
        == 401
    )


def test_15b_operator_surface_exposes_the_full_experiment_record(monkeypatch):
    client = api_client(monkeypatch)
    headers = {"X-API-Key": "test-api-key"}

    contract = client.get("/api/calyx-evolve/contract", headers=headers)
    assert contract.status_code == 200
    body = contract.json()
    assert body["governance"]["taxonomy_activation_permitted"] is False
    assert body["governance"]["execution_scope"] == "STAGING_ONLY"
    assert {row["key"] for row in body["metric_catalogue"]} >= {
        METRIC_ACCURACY,
        METRIC_FALSE_MERGE_COUNT,
        METRIC_PROVENANCE,
        METRIC_COST,
    }

    created = client.post(
        f"/api/calyx-evolve/campaigns/{DEFAULT_CAMPAIGN_ID}/experiments",
        json={},
        headers=headers,
    )
    assert created.status_code == 200
    report = created.json()["report"]
    assert report["selected_candidate_id"] == CANDIDATE_FUZZY_GUARDED
    assert all(row["reused"] is False for row in report["runs"])

    replayed = client.post(
        f"/api/calyx-evolve/campaigns/{DEFAULT_CAMPAIGN_ID}/experiments",
        json={},
        headers=headers,
    )
    assert replayed.status_code == 200
    assert all(row["reused"] is True for row in replayed.json()["report"]["runs"])

    status = client.get(
        f"/api/calyx-evolve/campaigns/{DEFAULT_CAMPAIGN_ID}", headers=headers
    )
    assert status.status_code == 200
    payload = status.json()
    assert payload["governance"]["requires_human_scientific_review"] is True
    assert len(payload["runs"]) == len(default_candidates())
    offender = next(
        row for row in payload["runs"] if row["candidate_id"] == CANDIDATE_FUZZY_UNGUARDED
    )
    assert offender["false_merge_count"] == 1
    assert offender["counterevidence"]
    assert offender["replay_deterministic"] is True
    assert offender["promotion"]["state"] == PROMOTION_BLOCKED
    assert offender["lineage"] == [CANDIDATE_FUZZY_GUARDED, CANDIDATE_BASELINE]

    comparison = client.get(
        f"/api/calyx-evolve/campaigns/{DEFAULT_CAMPAIGN_ID}/candidates/{CANDIDATE_FUZZY_GUARDED}",
        headers=headers,
    )
    assert comparison.status_code == 200
    compared = comparison.json()
    assert compared["baseline"]["candidate_id"] == CANDIDATE_BASELINE
    assert compared["candidate"]["score_delta_vs_baseline"] > 0

    index = client.get("/api/calyx-evolve/campaigns", headers=headers).json()
    assert index["campaigns"][0]["run_count"] == len(default_candidates())

    assert (
        client.get("/api/calyx-evolve/campaigns/unknown-campaign", headers=headers).status_code
        == 404
    )
    assert (
        client.post(
            "/api/calyx-evolve/campaigns/unknown-campaign/experiments",
            json={},
            headers=headers,
        ).status_code
        == 404
    )
    assert (
        client.post(
            f"/api/calyx-evolve/campaigns/{DEFAULT_CAMPAIGN_ID}/experiments",
            json={"candidate_ids": ["not-a-candidate"]},
            headers=headers,
        ).status_code
        == 400
    )


def test_15c_the_request_body_cannot_smuggle_an_unsafe_configuration(monkeypatch):
    client = api_client(monkeypatch)
    headers = {"X-API-Key": "test-api-key"}
    response = client.post(
        f"/api/calyx-evolve/campaigns/{DEFAULT_CAMPAIGN_ID}/experiments",
        json={
            "candidate_ids": [CANDIDATE_FUZZY_GUARDED],
            "config": {"request_production_write": True},
            "execution_scope": "PRODUCTION",
            "governance_state": "APPROVED",
        },
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["governance"]["execution_scope"] == "STAGING_ONLY"
    assert body["governance"]["production_mutation_permitted"] is False
    # Only the requested candidate plus the always-included baseline ran.
    assert {row["candidate_id"] for row in body["report"]["runs"]} == {
        CANDIDATE_BASELINE,
        CANDIDATE_FUZZY_GUARDED,
    }
