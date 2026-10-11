"""FIL-001B offline chain: Literature -> Taxonomy -> Evidence -> TraitBank -> Calyx."""

from __future__ import annotations

import copy
import json
import socket
from dataclasses import replace
from pathlib import Path

import jsonschema
import pytest

from app.evidence_aggregation import (
    CandidateInput,
    EvidenceAggregationService,
    MemoryAggregateRepository,
)
from app.functional_interaction.contracts import ContractError, TaxonResolutionPolicy
from app.functional_interaction.dry_run import HandlerResult, execute_dry_run
from app.functional_interaction.governance import evaluate_plan
from app.functional_interaction.literature_to_calyx import (
    build_handlers,
    chain_descriptors,
    chain_registry,
    load_manifest,
    plan_chain,
    run_chain,
    source_payload,
)
from app.functional_interaction.registry import FunctionalRegistry
from app.parallel_platform.reasoning_contract_bridge import (
    verification_packet_to_handoff_request,
)
from harvesters.execution import _validate_traitbank_record

ROOT = Path(__file__).resolve().parents[1]
RECEIPT_SCHEMA = json.loads(
    (ROOT / "contracts" / "oc-fil-execution-receipt.v1.json").read_text()
)
DESCRIPTOR_SCHEMA = json.loads(
    (ROOT / "contracts" / "oc-fil-capability-descriptor.v1.json").read_text()
)
EDGE_SCHEMA = json.loads(
    (ROOT / "contracts" / "oc-fil-functional-edge.v1.json").read_text()
)
CHAIN = [
    "fil.literature.paper-transducer",
    "fil.taxonomy.literature-name-adaptor",
    "fil.evidence.literature-claim-validator",
    "fil.traitbank.literature-record-buffer",
    "fil.calyx.verification-handoff",
]


@pytest.fixture(scope="module")
def report():
    return run_chain()


@pytest.fixture(scope="module")
def output(report):
    assert report.succeeded, [r.failure_reason for r in report.receipts]
    return report.final_output


def _by_candidate(output):
    return {h["candidate_id"]: h for h in output["handoffs"]}


def test_fixture_is_synthetic_and_declared_non_evidence():
    manifest = load_manifest()
    assert "not scientific evidence" in manifest["fixture_notice"]
    for paper in manifest["papers"]:
        text = (Path(manifest["_directory"]) / paper["file"]).read_text()
        assert "not scientific evidence" in text


def test_descriptors_validate_and_taxon_policies_are_declared():
    for descriptor in chain_descriptors():
        jsonschema.validate(descriptor.to_dict(), DESCRIPTOR_SCHEMA)
    policies = {d.capability_id: d.taxon_resolution for d in chain_descriptors()}
    assert policies["fil.taxonomy.literature-name-adaptor"].role == "provides"
    for consumer in (
        "fil.traitbank.literature-record-buffer",
        "fil.calyx.verification-handoff",
    ):
        assert policies[consumer].role == "requires"
        assert policies[consumer].admitted_statuses == ("accepted", "synonym")


def test_taxon_policy_contract_invariants():
    with pytest.raises(ContractError, match="FUZZY_TAXON_MATCHING_FORBIDDEN"):
        TaxonResolutionPolicy("provides", fuzzy_matching_allowed=True)
    with pytest.raises(ContractError, match="UNKNOWN_TAXON_LINK_STATUS"):
        TaxonResolutionPolicy("requires", admitted_statuses=("probable",))
    buffer = chain_registry().get("fil.traitbank.literature-record-buffer")
    with pytest.raises(
        ContractError, match="TAXON_POLICY_CONDITIONS_UNDECLARED:requires"
    ):
        replace(buffer, preconditions=("evidence_state_assigned",))


def test_planner_finds_the_chain_and_governance_admits_only_a_dry_run():
    plan = plan_chain()
    assert [step.capability_id for step in plan.steps] == CHAIN
    for edge in plan.edges:
        jsonschema.validate(edge.to_dict(), EDGE_SCHEMA)
    decision = evaluate_plan(plan)
    assert decision.action.value == "allow_dry_run"
    assert decision.to_dict()["scientific_publication_authorized"] is False


def test_requirer_without_a_taxon_provider_upstream_cannot_be_planned():
    descriptors = [
        d
        for d in chain_descriptors()
        if d.capability_id != "fil.taxonomy.literature-name-adaptor"
    ]
    plan = plan_chain(FunctionalRegistry(tuple(descriptors)))
    assert not plan.found


def test_chain_is_deterministic_and_offline(report, monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("FIL-001B attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    again = run_chain()
    assert again.run_digest == report.run_digest
    for receipt in again.to_dict()["receipts"]:
        jsonschema.validate(receipt, RECEIPT_SCHEMA)
        assert receipt["state"] == "delivered"
        assert receipt["provenance"]


def test_every_claim_keeps_its_exact_source_span(report):
    manifest = load_manifest()
    directory = Path(manifest["_directory"])
    texts = {}
    for paper in manifest["papers"]:
        texts[paper["source_object_id"]] = (directory / paper["file"]).read_text()
    handlers = build_handlers(manifest)
    claims = handlers[CHAIN[0]](source_payload(manifest)).output["claims"]
    assert len(claims) == 13
    for claim in claims:
        assert (
            texts[claim["source_object_id"]][claim["char_start"] : claim["char_end"]]
            == claim["statement"]
        )
        assert f"sha256:{claim['content_hash']}" in claim["provenance"]


def test_taxonomy_resolves_exactly_and_never_guesses(output):
    withheld = {
        g["claim_id"]: g
        for g in output["evidence_gaps"]
        if g["kind"] == "CLAIM_WITHHELD"
    }
    assert withheld["doi:10.5555/fil.001b.paper-c#claim-1"]["reasons"] == [
        "TAXON_UNRESOLVED"
    ]
    assert withheld["doi:10.5555/fil.001b.paper-a#claim-3"]["reasons"] == [
        "TAXON_AMBIGUOUS"
    ]
    for handoff in output["handoffs"]:
        link = handoff["taxon_link"]
        assert link["status"] in {"accepted", "synonym"}
        assert link["authority"] == "world_plants"
        assert link["automatic_fuzzy_matching"] is False
    synonym = [h for h in output["handoffs"] if h["taxon_link"]["status"] == "synonym"]
    assert {h["subject"] for h in synonym} == {"Fixtureia alpha"}
    assert all("Fixtureia beta" in h["taxon_link"]["submitted_names"] for h in synonym)


def test_contradictions_are_preserved_as_paired_candidates(output):
    handoffs = _by_candidate(output)
    summer = handoffs["fil001b:1:phenology:summer"]
    winter = handoffs["fil001b:1:phenology:winter"]
    assert summer["evidence_state"] == winter["evidence_state"] == "CONTRADICTORY"
    assert summer["contradicts"] == ["fil001b:1:phenology:winter"]
    assert winter["contradicts"] == ["fil001b:1:phenology:summer"]
    assert summer["sources"] != winter["sources"]
    packets = {
        p["reasoning"]["candidate_knowledge"]["candidate_id"]: p
        for p in output["packets"]
    }
    assert (
        packets["fil001b:1:phenology:summer"]["reasoning"]["candidate_knowledge"][
            "review_state"
        ]
        == "review_required"
    )
    assert (
        "resolve_conflicting_sources"
        in packets["fil001b:1:phenology:summer"]["reasoning"]["validation_pathways"]
    )


def test_differing_measurements_are_variation_not_conflict(output):
    assert output["variation"] == [
        {
            "taxon_id": 1,
            "predicate": "measurement",
            "values": ["12 mm", "15 mm"],
            "assessment": "VARIATION_AT_UNSTATED_LEVEL",
            "sources": ["doi:10.5555/fil.001b.paper-a", "doi:10.5555/fil.001b.paper-b"],
        }
    ]
    measured = [h for h in output["handoffs"] if h["predicate"] == "measurement"]
    assert {h["evidence_state"] for h in measured} == {"PROVISIONAL"}
    assert all(h["contradicts"] == [] for h in measured)
    packets = {
        p["reasoning"]["candidate_knowledge"]["candidate_id"]: p
        for p in output["packets"]
    }
    assert (
        "assertion_level_unstated"
        in packets["fil001b:1:measurement:12-mm"]["knowledge_gaps"]
    )


def test_hedged_interpretation_keeps_its_uncertainty(output):
    pollination = _by_candidate(output)[
        "fil001b:1:ecological_relationship:fixture-moths"
    ]
    assert pollination["uncertainty"] == [
        "HEDGED_SOURCE_LANGUAGE",
        "INTERPRETATION_NOT_OBSERVATION",
    ]
    packets = {
        p["reasoning"]["candidate_knowledge"]["candidate_id"]: p
        for p in output["packets"]
    }
    packet = packets["fil001b:1:ecological_relationship:fixture-moths"]
    assert (
        "expert_review_of_uncertain_claim" in packet["reasoning"]["validation_pathways"]
    )
    assert (
        "uncertainty:HEDGED_SOURCE_LANGUAGE"
        in packet["resolved_evidence"][0]["provenance"]
    )
    assert packet["missing_evidence"] == ["independent_corroboration"]


def test_calyx_admission_uses_the_existing_bridge_and_stays_review_gated(output):
    assert output["human_review_required"] is True
    assert output["publication_authority"] is False
    for handoff in output["handoffs"]:
        assert handoff["calyx_state"] == "COMPLETED"
        assert handoff["calyx_candidate_ids"]
        assert handoff["review_required"] is True
        assert handoff["published"] is False
        assert handoff["graph_mutation"] is False
    for packet in output["packets"]:
        request = verification_packet_to_handoff_request(
            packet,
            domain="trait",
            source_object_type="fil_001b_literature_claim",
            source_object_id=1,
            revision_id=1,
            extraction_run_id=1,
        )
        assert request.qualifiers["human_review_required"] is True
        assert request.source_anchors[0].logical_unit.startswith(
            "doi:10.5555/fil.001b.paper-"
        )


def test_traitbank_records_match_the_harvester_contract_and_feed_aggregation():
    manifest = load_manifest()
    handlers = build_handlers(manifest)
    payload = source_payload(manifest)
    for step in CHAIN[:4]:
        payload = handlers[step](payload).output
    records = payload["traitbank_records"]
    assert len(records) == 6
    for record in records:
        assert _validate_traitbank_record(record) == (True, None)
        assert record["raw"]["canonical_taxon_id"], (
            "a TraitBank record must carry a resolved backbone id"
        )
        assert (
            record["raw"]["record_id"]
            and record["raw"]["citation"]
            and record["raw"]["license"]
        )
        assert record["raw"]["assertion_level"] == "unstated"
    candidates = [
        CandidateInput(
            **{
                **item,
                "source_anchor_ids": tuple(item["source_anchor_ids"]),
                "citation_lineage": tuple(item["citation_lineage"]),
                "taxon_links": tuple(item["taxon_links"]),
            }
        )
        for item in payload["aggregation_candidates"]
    ]
    service = EvidenceAggregationService(MemoryAggregateRepository())
    run = service.preview(candidates)
    service.execute(run["aggregate_run_id"])
    assert all(
        a["review_state"] == "REQUIRED" and a["published"] is False
        for a in service.repo.aggregates
    )
    phenology = next(
        a for a in service.repo.aggregates if a["normalized_predicate"] == "phenology"
    )
    assert phenology["normalized_object"] == "MULTIPLE_VALUES"


def test_unresolved_name_reaching_traitbank_is_blocked_at_runtime():
    manifest = load_manifest()
    plan = plan_chain()
    handlers = build_handlers(manifest)
    original = handlers[CHAIN[3]]

    def leaky(payload):
        result = original(payload)
        bad = {**result.taxon_links[0], "status": "unresolved"}
        return replace(result, taxon_links=(bad, *result.taxon_links[1:]))

    handlers[CHAIN[3]] = leaky
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(manifest)
    )
    assert (
        report.receipts[3].failure_reason
        == "TAXON_RESOLUTION_VIOLATION:inadmissible_status:unresolved"
    )
    assert [r.failure_reason for r in report.receipts[4:]] == ["UPSTREAM_BLOCKED:3"]


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        (
            {"automatic_fuzzy_matching": True},
            "TAXON_RESOLUTION_VIOLATION:fuzzy_matching_not_excluded",
        ),
        ({"authority": "gbif"}, "TAXON_RESOLUTION_VIOLATION:authority:gbif"),
        ({"status": "probable"}, "TAXON_RESOLUTION_VIOLATION:unknown_status:probable"),
    ],
)
def test_taxon_provider_links_are_checked_not_trusted(mutation, reason):
    manifest = load_manifest()
    plan = plan_chain()
    handlers = build_handlers(manifest)
    original = handlers[CHAIN[1]]

    def tampered(payload):
        result = original(payload)
        return replace(
            result,
            taxon_links=tuple({**link, **mutation} for link in result.taxon_links),
        )

    handlers[CHAIN[1]] = tampered
    report = execute_dry_run(
        plan, evaluate_plan(plan), handlers, source_payload(manifest)
    )
    assert report.receipts[1].failure_reason == reason


def test_pipeline_failure_is_an_explicit_receipt(tmp_path):
    manifest = copy.deepcopy(load_manifest())
    manifest["_directory"] = str(tmp_path)
    report = run_chain(manifest)
    assert report.receipts[0].failure_reason.startswith(
        "HANDLER_ERROR:FileNotFoundError"
    )
    assert report.final_output is None
    assert not list(tmp_path.iterdir()), (
        "the chain must not write into the document directory"
    )


def test_handler_result_carries_taxon_links_field():
    assert HandlerResult(output={}).taxon_links == ()


def test_describing_and_planning_never_import_the_database_dependency_module():
    """``app.candidate_knowledge.dependencies`` builds a repository from
    DATABASE_URL at import. Describing and planning FIL must not reach it; only
    running the Calyx step does, exactly as the application itself does."""
    import os
    import subprocess
    import sys

    code = (
        "import sys\n"
        "import app.functional_interaction.literature_to_calyx as m\n"
        "m.plan_chain(); m.chain_registry().view()\n"
        "print('app.candidate_knowledge.dependencies' in sys.modules)\n"
    )
    env = {k: v for k, v in os.environ.items() if k != "DATABASE_URL"}
    result = subprocess.run(
        [sys.executable, "-B", "-c", code],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "False"
