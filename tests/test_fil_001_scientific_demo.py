"""FIL-001 fixture demonstration: discovery -> plan -> governance -> dry run -> downstream."""

from __future__ import annotations

import copy
import json
import socket
from pathlib import Path

import jsonschema
import pytest

from app.evidence_aggregation import (
    CandidateInput,
    EvidenceAggregationService,
    MemoryAggregateRepository,
)
from app.functional_interaction.dry_run import HandlerResult, execute_dry_run
from app.functional_interaction.governance import (
    GovernanceAction,
    GovernanceDecision,
    evaluate_plan,
)
from app.functional_interaction.planner import plan_workflow
from app.functional_interaction.scientific_demo import (
    SOURCE,
    build_handlers,
    demo_registry,
    load_fixture,
    run_demonstration,
    run_dry_run,
    source_payload,
)

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA = json.loads(
    (ROOT / "contracts" / "oc-fil-execution-receipt.v1.json").read_text()
)
EDGE_SCHEMA = json.loads(
    (ROOT / "contracts" / "oc-fil-functional-edge.v1.json").read_text()
)
DESCRIPTOR_SCHEMA = json.loads(
    (ROOT / "contracts" / "oc-fil-capability-descriptor.v1.json").read_text()
)


@pytest.fixture()
def fixture():
    return load_fixture()


def _plan_and_decision():
    plan = plan_workflow(demo_registry(), source=SOURCE, goal_type="oc:ReasoningDraft")
    return plan, evaluate_plan(plan)


def test_fixture_declares_itself_non_evidence(fixture):
    assert "not scientific evidence" in fixture["fixture_notice"]
    assert all(
        p["subject"].startswith(("Fixtureia", "Imaginaria"))
        for p in fixture["passages"]
    )


def test_demonstration_discovers_plans_admits_and_delivers(fixture):
    record = run_demonstration(fixture)
    expected = fixture["expected"]
    json.dumps(record)  # fully serializable

    for item in record["discovery"]["registry"]["capabilities"]:
        jsonschema.validate(
            {k: v for k, v in item.items() if k != "brain_eligibility"},
            DESCRIPTOR_SCHEMA,
        )
    assert record["discovery"]["producers_of_reasoning_drafts"] == [
        "fil.reasoning.ledger-integrator"
    ]
    for edge in (
        record["compatibility"]["chain_edges"]
        + record["compatibility"]["counter_examples"]
    ):
        jsonschema.validate(edge, EDGE_SCHEMA)
    assert all(edge["compatible"] for edge in record["compatibility"]["chain_edges"])
    assert not any(
        edge["compatible"] for edge in record["compatibility"]["counter_examples"]
    )

    assert [step["capability_id"] for step in record["plan"]["steps"]] == expected[
        "plan_steps"
    ]
    assert record["governance"]["action"] == "allow_dry_run"
    assert record["dry_run"]["succeeded"] is True
    for receipt in record["dry_run"]["receipts"]:
        jsonschema.validate(receipt, RECEIPT_SCHEMA)
        assert receipt["state"] == "delivered"
        assert receipt["provenance"], receipt["capability_id"]

    assert record["provider_goal"]["plan"]["found"] is False
    assert record["provider_goal"]["governance"]["dry_run_authorized"] is False


def test_dry_run_is_deterministic(fixture):
    assert (
        run_dry_run(fixture).run_digest
        == run_dry_run(copy.deepcopy(fixture)).run_digest
    )
    assert run_demonstration(fixture) == run_demonstration(copy.deepcopy(fixture))


def test_dry_run_opens_no_network_connection(fixture, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("FIL-001 dry run attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    assert run_dry_run(fixture).succeeded


def test_validation_withholds_unresolved_taxa_and_never_verifies(fixture):
    report = run_dry_run(fixture)
    downstream = report.final_output
    expected = fixture["expected"]
    assert len(downstream["evidence_gaps"]) == 2
    withheld = {
        gap["claim_id"]: gap["reasons"]
        for gap in downstream["evidence_gaps"]
        if gap["kind"] == "CLAIM_WITHHELD"
    }
    assert withheld == {
        claim: [reason] for claim, reason in expected["withheld_claims"].items()
    }
    gap_docs = [
        gap["source_document_id"]
        for gap in downstream["evidence_gaps"]
        if gap["kind"] == "PASSAGE_WITHOUT_EXTRACTABLE_CLAIM"
    ]
    assert gap_docs == expected["passages_without_claims"]
    for receipt in report.receipts:
        assert "VERIFIED" not in receipt.evidence_states


def test_synonym_resolution_exposes_contradiction_instead_of_hiding_it(fixture):
    entries = run_dry_run(fixture).final_output["entries"]
    conflicts = [
        [e["subject"], e["predicate"]]
        for e in entries
        if e["evidence_state"] == "CONTRADICTORY"
    ]
    assert conflicts == fixture["expected"]["contradictory_groups"]
    conflict = next(e for e in entries if e["evidence_state"] == "CONTRADICTORY")
    assert conflict["kind"] == "conflict"
    assert conflict["source_document_ids"] == ["fixture-doc-001", "fixture-doc-002"]
    assert conflict["values"] == ["summer", "winter"]


def test_outputs_remain_review_required_and_unpublished(fixture):
    output = run_dry_run(fixture).final_output
    assert output["human_review_required"] is True
    assert output["publication_authority"] is False
    assert output["ledger_appended"] is False


def test_trait_candidates_are_available_to_the_existing_aggregation_service(fixture):
    plan, _ = _plan_and_decision()
    handlers = build_handlers(fixture)
    payload = source_payload(fixture)
    for step in plan.steps[:4]:
        payload = handlers[step.capability_id](payload).output
    assert len(payload["candidates"]) == fixture["expected"]["trait_candidates"]
    for row in payload["traitbank_rows"]:
        assert row["taxonomy_id"], (
            "TraitBank candidate must carry a resolved backbone id, never 0"
        )
        assert row["reference_raw"].startswith("fixture://")
        assert row["review_state"] == "REQUIRED"

    candidates = [
        CandidateInput(
            **{
                **item,
                "source_anchor_ids": tuple(item["source_anchor_ids"]),
                "citation_lineage": tuple(item["citation_lineage"]),
                "taxon_links": tuple(item["taxon_links"]),
            }
        )
        for item in payload["candidates"]
    ]
    service = EvidenceAggregationService(MemoryAggregateRepository())
    run = service.preview(candidates)
    service.execute(run["aggregate_run_id"])
    aggregates = service.repo.aggregates
    assert len(aggregates) == 2
    assert all(
        a["review_state"] == "REQUIRED" and a["published"] is False for a in aggregates
    )
    phenology = next(a for a in aggregates if a["normalized_predicate"] == "phenology")
    assert phenology["normalized_object"] == "MULTIPLE_VALUES"


def test_handler_failure_yields_explicit_receipt_and_blocks_downstream(fixture):
    plan, decision = _plan_and_decision()
    handlers = build_handlers(fixture)

    def explode(payload):
        raise ValueError("CANONICAL_BACKBONE_UNAVAILABLE")

    handlers["fil.taxonomy.backbone-adaptor"] = explode
    report = execute_dry_run(plan, decision, handlers, source_payload(fixture))
    states = [(r.execution.state.value, r.failure_reason) for r in report.receipts]
    assert states == [
        ("delivered", None),
        ("blocked", "HANDLER_ERROR:ValueError:CANONICAL_BACKBONE_UNAVAILABLE"),
        ("blocked", "UPSTREAM_BLOCKED:1"),
        ("blocked", "UPSTREAM_BLOCKED:1"),
        ("blocked", "UPSTREAM_BLOCKED:1"),
    ]
    assert report.succeeded is False
    assert report.final_output is None
    for receipt in report.to_dict()["receipts"]:
        jsonschema.validate(receipt, RECEIPT_SCHEMA)


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (
            HandlerResult(
                output={},
                established=(),
                evidence_states=("UNKNOWN",),
                provenance=("x",),
            ),
            "EFFECT_NOT_ESTABLISHED:taxon_resolution_recorded",
        ),
        (
            HandlerResult(
                output={},
                established=("taxon_resolution_recorded",),
                evidence_states=("VERIFIED",),
                provenance=("x",),
            ),
            "UNDECLARED_EVIDENCE_STATE:VERIFIED",
        ),
        (
            HandlerResult(
                output={},
                established=("taxon_resolution_recorded",),
                events=("graph.write.accepted",),
                provenance=("x",),
            ),
            "UNDECLARED_EVENT:graph.write.accepted",
        ),
        (
            HandlerResult(output={}, established=("taxon_resolution_recorded",)),
            "PROVENANCE_CHAIN_DROPPED",
        ),
    ],
)
def test_postconditions_are_checked_not_trusted(fixture, result, reason):
    plan, decision = _plan_and_decision()
    handlers = build_handlers(fixture)
    handlers["fil.taxonomy.backbone-adaptor"] = lambda payload: result
    report = execute_dry_run(plan, decision, handlers, source_payload(fixture))
    assert report.receipts[1].failure_reason == reason
    assert report.receipts[1].to_dict()["would_emit"] == []


def test_missing_handler_and_non_admitted_plan_never_execute(fixture):
    plan, decision = _plan_and_decision()
    handlers = build_handlers(fixture)
    del handlers["fil.reasoning.ledger-integrator"]
    report = execute_dry_run(plan, decision, handlers, source_payload(fixture))
    assert report.receipts[-1].failure_reason == "NO_DRY_RUN_HANDLER"

    calls = []
    spying = {
        key: (lambda payload, key=key: calls.append(key))
        for key in build_handlers(fixture)
    }
    gated = GovernanceDecision(
        plan.plan_id, "dry_run", GovernanceAction.OWNER_GATE, ("TEST",)
    )
    report = execute_dry_run(plan, gated, spying, source_payload(fixture))
    assert calls == []
    assert {r.failure_reason for r in report.receipts} == {"GOVERNANCE_OWNER_GATE"}

    with pytest.raises(ValueError, match="GOVERNANCE_DECISION_PLAN_MISMATCH"):
        execute_dry_run(
            plan,
            GovernanceDecision(
                "fil-plan-0000000000000000",
                "dry_run",
                GovernanceAction.ALLOW_DRY_RUN,
                (),
            ),
            spying,
            {},
        )


def test_all_unresolved_fixture_produces_no_candidates_and_records_every_gap(fixture):
    altered = copy.deepcopy(fixture)
    altered["taxonomy"]["load_rows"] = [
        {"name": "Otheria solo Fixt.", "taxon_code": "S"}
    ]
    altered["taxonomy"]["synonym_rows"] = []
    report = run_dry_run(altered)
    assert report.succeeded
    output = report.final_output
    assert output["entries"] == []
    assert (
        sum(1 for gap in output["evidence_gaps"] if gap["kind"] == "CLAIM_WITHHELD")
        == 4
    )


def test_fixture_demo_never_claims_world_plants_provenance():
    # The fixture backbone is invented; claiming the canonical authority would
    # fabricate taxonomy provenance for fictional taxa.
    record = run_demonstration()
    text = json.dumps(record, default=str)
    assert "world_plants" not in text
    taxonomy_step = run_dry_run(load_fixture()).receipts[1].execution.output["artifact"]
    authorities = {c["taxon_link"]["authority"] for c in taxonomy_step["claims"]}
    assert authorities == {"fil_fixture_backbone"}
