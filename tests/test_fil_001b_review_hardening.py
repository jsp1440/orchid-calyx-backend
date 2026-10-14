"""Regression tests for the independent checker's FIL-001B findings (head c9235e3)."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest

from app.functional_interaction.compatibility import check_edge
from app.functional_interaction.contracts import ContractError, TaxonResolutionPolicy
from app.functional_interaction.dry_run import HandlerResult, _taxon_violation
from app.functional_interaction.literature_to_calyx import (
    _candidate_ids,
    _value_key,
    build_handlers,
    chain_registry,
    load_manifest,
    run_chain,
)
from app.functional_interaction.value_semantics import value_key

ADAPTOR = "fil.taxonomy.literature-name-adaptor"
BUFFER = "fil.traitbank.literature-record-buffer"
HANDOFF = "fil.calyx.verification-handoff"


def _descriptor(capability_id):
    return chain_registry().get(capability_id)


# --- taxon policy cannot be bypassed --------------------------------------


def test_policy_less_function_cannot_declare_the_taxon_authority_condition():
    adaptor = _descriptor(ADAPTOR)
    with pytest.raises(ContractError, match="TAXON_CONDITION_WITHOUT_PROVIDER_POLICY"):
        replace(adaptor, taxon_resolution=None)


def test_policy_less_function_may_not_emit_taxon_links():
    transducer = _descriptor("fil.literature.paper-transducer")
    assert transducer.taxon_resolution is None
    result = HandlerResult(
        output={},
        taxon_links=(
            {
                "status": "fuzzy-guess",
                "authority": "gbif",
                "automatic_fuzzy_matching": True,
            },
        ),
    )
    assert (
        _taxon_violation(transducer, result)
        == "TAXON_RESOLUTION_VIOLATION:links_without_policy"
    )


def test_admitted_statuses_are_checked_when_the_edge_is_planned():
    adaptor, buffer = _descriptor(ADAPTOR), _descriptor(BUFFER)
    edge = check_edge(
        adaptor,
        adaptor.outputs[0].name,
        buffer,
        buffer.inputs[0].name,
        upstream_conditions=("claims_anchored", "source_content_addressed"),
    )
    assert "TAXON_STATUSES_FILTERED:ambiguous,unresolved" in edge.advisories

    other = TaxonResolutionPolicy(
        role="requires", authority="gbif", admitted_statuses=("accepted",)
    )
    foreign = replace(
        buffer,
        taxon_resolution=other,
        preconditions=(
            *[
                p
                for p in buffer.preconditions
                if p != "taxon_authority_fil_fixture_backbone"
            ],
            "taxon_authority_gbif",
        ),
    )
    edge = check_edge(adaptor, adaptor.outputs[0].name, foreign, foreign.inputs[0].name)
    assert "TAXON_AUTHORITY_MISMATCH:fil_fixture_backbone" in edge.blocking_reasons


# --- contradiction semantics and candidate identity -----------------------


def _traitbank_payload():
    report = run_chain(allow_import_time_database_contact=True)
    assert report.succeeded
    return copy.deepcopy(report.receipts[3].execution.output["artifact"])


def _clone(record, *, value, suffix, trait=None, units=None):
    clone = copy.deepcopy(record)
    clone["value_raw"] = value
    if trait is not None:
        clone["trait_raw"] = trait
    if units is not None:
        clone["units_raw"] = units
    clone["reference_raw"] = f"{record['reference_raw']}-{suffix}"
    clone["raw"]["record_id"] = f"{record['raw']['record_id']}-{suffix}"
    return clone


def _handoff(payload):
    handlers = build_handlers(load_manifest(), allow_import_time_database_contact=True)
    return handlers[HANDOFF](payload).output


def test_case_only_difference_supports_rather_than_contradicts():
    payload = _traitbank_payload()
    summer = next(r for r in payload["traitbank_records"] if r["value_raw"] == "summer")
    payload["traitbank_records"].append(_clone(summer, value="Summer", suffix="case"))
    output = _handoff(payload)
    ids = [h["candidate_id"] for h in output["handoffs"]]
    assert len(ids) == len(set(ids))
    by_id = {h["candidate_id"]: h for h in output["handoffs"]}
    summer_candidate = by_id["fil001b:1:phenology:summer"]
    assert len(summer_candidate["sources"]) == 2
    assert summer_candidate["contradicts"] == ["fil001b:1:phenology:winter"]
    assert sum(1 for h in output["handoffs"] if h["contradicts"]) == 2


def test_multi_valued_predicate_is_not_a_contradiction():
    payload = _traitbank_payload()
    moths = next(
        r
        for r in payload["traitbank_records"]
        if r["trait_raw"] == "ecological_relationship"
    )
    payload["traitbank_records"].append(_clone(moths, value="fixture bees", suffix="b"))
    output = _handoff(payload)
    related = [
        h for h in output["handoffs"] if h["predicate"] == "ecological_relationship"
    ]
    assert len(related) == 2
    assert all(h["contradicts"] == [] for h in related)
    assert all(h["evidence_state"] == "PROVISIONAL" for h in related)
    assert {v["assessment"] for v in output["variation"]} >= {
        "MULTIPLE_VALUES_PERMITTED"
    }


def test_unit_equivalent_measurements_agree():
    payload = _traitbank_payload()
    twelve = next(r for r in payload["traitbank_records"] if r["value_raw"] == 12.0)
    payload["traitbank_records"].append(
        _clone(twelve, value=1.2, units="cm", suffix="cm")
    )
    output = _handoff(payload)
    twelve_mm = next(h for h in output["handoffs"] if h["value"] == "12 mm")
    assert len(twelve_mm["sources"]) == 2


def test_mixed_measurement_and_category_is_incommensurable_not_contradictory():
    payload = _traitbank_payload()
    twelve = next(r for r in payload["traitbank_records"] if r["value_raw"] == 12.0)
    payload["traitbank_records"].append(
        _clone(twelve, value="long", units="", suffix="cat")
    )
    output = _handoff(payload)
    measured = [h for h in output["handoffs"] if h["predicate"] == "measurement"]
    assert all(h["contradicts"] == [] for h in measured)
    assert "INCOMMENSURABLE_VALUES" in {v["assessment"] for v in output["variation"]}


def test_candidate_ids_never_collide_when_slugs_coincide():
    keys = [
        value_key(object_value="pale/yellow", numeric_value=None, unit=None),
        value_key(object_value="pale yellow", numeric_value=None, unit=None),
        value_key(object_value="12 mm", numeric_value=None, unit=None),
        value_key(object_value=None, numeric_value=12, unit="mm"),
    ]
    ids = _candidate_ids(1, "color", keys)
    assert len(set(ids.values())) == 4
    assert ids[keys[0]].startswith("fil001b:1:color:pale-yellow-")


def test_value_key_normalizes_case_separators_and_length_units():
    def record(value, units=""):
        return {"value_raw": value, "units_raw": units}

    assert _value_key(record("White")) == _value_key(record("white"))
    assert _value_key(record("pale-yellow")) == _value_key(record("pale yellow"))
    assert _value_key(record(3.0, "cm")) == _value_key(record(30.0, "mm"))
    assert _value_key(record(12.0, "mm")) != _value_key(record(12.0, "cm"))


# --- Copilot review (#1810): requirer re-checks; fixture authority honesty --


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        (
            {"authority": "world_plants"},
            "TAXON_RESOLUTION_VIOLATION:authority:world_plants",
        ),
        (
            {"automatic_fuzzy_matching": True},
            "TAXON_RESOLUTION_VIOLATION:fuzzy_matching_not_excluded",
        ),
    ],
)
def test_requirer_rechecks_authority_and_fuzzy_matching(change, reason):
    buffer = _descriptor(BUFFER)
    link = {
        "status": "accepted",
        "authority": "fil_fixture_backbone",
        "automatic_fuzzy_matching": False,
    }
    assert (
        _taxon_violation(buffer, HandlerResult(output={}, taxon_links=(link,))) is None
    )
    corrupted = HandlerResult(output={}, taxon_links=({**link, **change},))
    assert _taxon_violation(buffer, corrupted) == reason


def test_fixture_chain_never_claims_world_plants_provenance():
    report = run_chain(allow_import_time_database_contact=True)
    assert report.succeeded
    text = json.dumps(report.to_dict())
    assert "world_plants" not in text
    for packet in report.final_output["packets"]:
        subject = packet["reasoning"]["candidate_knowledge"]["subject_id"]
        assert subject.startswith("taxon:fil_fixture_backbone:")


def test_manifest_must_declare_the_fixture_authority():
    manifest = load_manifest()
    manifest["taxonomy"] = {**manifest["taxonomy"], "authority": "world_plants"}
    with pytest.raises(ValueError, match="TAXONOMY_AUTHORITY_MISMATCH:world_plants"):
        build_handlers(manifest)


# --- second independent check (exact head 49bbc808) -------------------------


@pytest.mark.parametrize(
    ("first", "second", "assessment"),
    [
        ((123.4567, "mm"), (123.4568, "mm"), "VARIATION_AT_UNSTATED_LEVEL"),
        ((1234567.0, "mm"), (1234568.0, "mm"), "VARIATION_AT_UNSTATED_LEVEL"),
        (("12 mm", ""), (12.0, "mm"), "INCOMMENSURABLE_VALUES"),
    ],
)
def test_distinct_values_are_never_merged_into_false_corroboration(
    first, second, assessment
):
    payload = _traitbank_payload()
    records = [
        r for r in payload["traitbank_records"] if r["trait_raw"] == "measurement"
    ]
    for record, (value, units) in zip(records, (first, second), strict=True):
        record["value_raw"], record["units_raw"] = value, units
    output = _handoff(payload)
    measured = [h for h in output["handoffs"] if h["predicate"] == "measurement"]
    assert len(measured) == 2
    assert len({h["candidate_id"] for h in measured}) == 2
    assert all(len(h["sources"]) == 1 for h in measured)
    assert assessment in {v["assessment"] for v in output["variation"]}


def test_collision_is_refused_before_anything_is_admitted(monkeypatch):
    from app.candidate_knowledge.repository import MemoryCandidateRepository
    from app.candidate_knowledge.service import CandidateExtractionService
    from app.functional_interaction import literature_to_calyx as module

    payload = _traitbank_payload()
    repository = MemoryCandidateRepository()
    monkeypatch.setattr(
        module,
        "_candidate_ids",
        lambda taxon_id, predicate, keys: dict.fromkeys(keys, "fil001b:dup"),
    )
    handlers = build_handlers(
        load_manifest(),
        allow_import_time_database_contact=True,
        candidate_components=lambda: (
            repository,
            CandidateExtractionService(repository),
        ),
    )
    with pytest.raises(ValueError, match="CANDIDATE_ID_COLLISION"):
        handlers[HANDOFF](payload)
    assert list(repository.candidates) == []


def test_source_may_not_claim_the_reserved_taxon_condition():
    from app.functional_interaction.governance import GovernanceAction, evaluate_plan
    from app.functional_interaction.planner import SourceArtifact, plan_workflow

    buffer = _descriptor(BUFFER)
    port = buffer.inputs[0]
    source = SourceArtifact(
        port.semantic_type,
        port.evidence_states,
        tuple(sorted({*buffer.preconditions})),
    )
    plan = plan_workflow(
        chain_registry(), source=source, goal_type="oc:CalyxCandidateHandoffBatch"
    )
    assert plan.found  # the planner alone would accept the claim ...
    decision = evaluate_plan(plan)  # ... governance refuses it
    assert decision.action is GovernanceAction.REFUSE
    assert any(
        r.startswith("SOURCE_CLAIMS_RESERVED_TAXON_CONDITION:")
        for r in decision.reasons
    )
