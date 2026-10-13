"""Regression tests for the independent checker's FIL-001B findings (head c9235e3)."""

from __future__ import annotations

import copy
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
            *[p for p in buffer.preconditions if p != "taxon_authority_world_plants"],
            "taxon_authority_gbif",
        ),
    )
    edge = check_edge(adaptor, adaptor.outputs[0].name, foreign, foreign.inputs[0].name)
    assert "TAXON_AUTHORITY_MISMATCH:world_plants" in edge.blocking_reasons


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
    keys = {
        "pale/yellow": value_key(
            object_value="pale/yellow", numeric_value=None, unit=None
        ),
        "pale yellow": value_key(
            object_value="pale yellow", numeric_value=None, unit=None
        ),
    }
    ids = _candidate_ids(1, "color", keys)
    assert len(set(ids.values())) == 2
    assert all(i.startswith("fil001b:1:color:pale-yellow-") for i in ids.values())


def test_value_key_normalizes_case_separators_and_length_units():
    def record(value, units=""):
        return {"value_raw": value, "units_raw": units}

    assert _value_key(record("White")) == _value_key(record("white"))
    assert _value_key(record("pale-yellow")) == _value_key(record("pale yellow"))
    assert _value_key(record(3.0, "cm")) == _value_key(record(30.0, "mm"))
    assert _value_key(record(12.0, "mm")) != _value_key(record(12.0, "cm"))
