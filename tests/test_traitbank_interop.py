"""TRAITBANK-002: identifiers and shapes shared with #901 (KG) and #1819 (GGR).

Offline. Where the other lane's module exists on the base, the comparison runs
against it directly; until then it is skipped with the reason, and the pinned
copies below are the contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.literature_extraction.models import PaperKnowledge
from app.parallel_platform.matrix_adapters import MATRIX_DIMENSIONS
from app.traitbank import interop
from app.traitbank.adapters import (
    TraitIndex,
    from_paper_knowledge,
    from_traitbank_harvester,
)
from app.traitbank.cli import load_definition_file
from app.traitbank.matrix_adapter import compare_assertions
from app.traitbank.models import AssertionIn
from harvesters.traitbank import TraitBankHarvester

FIXTURES = Path(__file__).parent / "fixtures" / "traitbank"
ANGRAECUM, STANHOPEA = "990000002", "990000012"


def _traits() -> TraitIndex:
    return TraitIndex({d.trait_id: d for d in load_definition_file()})


def _paper() -> PaperKnowledge:
    return PaperKnowledge.model_validate_json(
        (FIXTURES / "darwin_1862_paper_knowledge.json").read_text()
    )


def _assertion(
    assertion_id: str,
    taxon: str,
    level: str,
    value: dict,
    *,
    confidence=None,
    **subject,
) -> AssertionIn:
    scope = "source_reported" if level == "taxon" else "direct"
    return AssertionIn.model_validate(
        {
            "assertion_id": assertion_id,
            "trait_id": "oc:trait:spur_presence"
            if value["kind"] == "categorical"
            else "oc:trait:spur_length",
            "level": level,
            "scope_basis": scope,
            "subject": {"taxon_id": taxon, "verbatim_taxon_name": "x", **subject},
            "value": value,
            "confidence": confidence,
            "provenance": {
                "source_id": f"doi:10.1000/{assertion_id}",
                "source_kind": "publication",
                "original_record_id": assertion_id,
                "citation": "CI interop source.",
                "license": "CC BY 4.0",
                "evidence_type": "literature_reported",
                "original_text": "verbatim excerpt",
            },
        }
    )


# -- crosswalk with #901's canonical keys ---------------------------------------------------


def test_literature_assertions_carry_the_kg_key_901_would_give_the_same_record():
    result = from_paper_knowledge(_paper(), _traits(), lambda name: ANGRAECUM)
    entry = result.crosswalk[
        "tb:lit:darwin-1862-fertilisation-of-orchids:m-nectary-length"
    ]
    assert entry == {
        "source_record_kind": "measurement",
        "kg_object_key": "measurement:darwin-1862-fertilisation-of-orchids:m-nectary-length",
        "source_document_id": "paper:darwin-1862-fertilisation-of-orchids",
    }


def test_claim_keys_follow_the_claim_type_node_mapping():
    assert interop.kg_claim_key("p", "c1", "observation") == "observation:p:c1"
    assert interop.kg_claim_key("p", "c1", "interpretation") == "assertion:p:c1"
    assert interop.kg_claim_key("p", "c1", "unknown_type") is None  # never guessed


def test_eol_records_have_no_kg_key_to_invent():
    harvester = TraitBankHarvester()
    record = harvester._normalize(
        {
            "eol_pk": "R1",
            "resource_id": "694",
            "scientific_name": "Angraecum sesquipedale",
            "predicate": "nectar spur length",
            "value": "30",
            "units": "cm",
        },
        source_path="local.tsv",
    )
    result = from_traitbank_harvester(
        [record],
        _traits(),
        lambda name: ANGRAECUM,
        dataset_citation="c.",
        dataset_license="l",
    )
    assert result.crosswalk == {
        "tb:eol:R1": {
            "source_record_kind": "dataset_record",
            "kg_object_key": None,
            "source_document_id": "eol-traitbank:resource:694",
        }
    }


def test_claim_node_mapping_matches_901_when_present():
    vocab = pytest.importorskip(
        "runtime.knowledge_graph.scientific_method_vocabulary",
        reason="#901 scientific_method_vocabulary is not on this base yet",
    )
    assert dict(vocab.CLAIM_TYPE_TO_NODE_TYPE) == interop.KG_CLAIM_NODE_TYPES


# -- #1819 evidence-packet compatibility -----------------------------------------------------


def test_graph_payload_uses_exactly_the_keys_1819_reads():
    a = _assertion(
        "sp1",
        ANGRAECUM,
        "specimen",
        {"kind": "quantitative", "numeric": 292.1, "unit": "mm"},
        specimen_id="S1",
    )
    payload = interop.graph_edge_payload(
        a, source_document_id="paper:x", conflicting=["b", "a"]
    )
    assert set(payload) == interop.GGR_PAYLOAD_KEYS
    assert payload["conflicting_assertion_ids"] == ["a", "b"]
    assert (
        payload["qualifier"]
        == "assertion_level=specimen;scope_basis=direct;confidence_state=unknown"
    )


def test_evidence_item_matches_1819_shape_and_keeps_level():
    a = _assertion(
        "sp1",
        ANGRAECUM,
        "specimen",
        {"kind": "quantitative", "numeric": 292.1, "unit": "mm"},
        specimen_id="S1",
    )
    item = interop.evidence_item(
        a,
        subject="Angraecum sesquipedale",
        object_label="Spur length: 292.1 mm",
        source_document_id="paper:x",
        conflicting=[],
    )
    assert set(item) == interop.GGR_EVIDENCE_ITEM_KEYS
    assert (
        item["domain"] == "traits"
        and item["edge_type"] == "has_trait_evidence_from_individuals"
    )
    assert (
        item["anchor_state"] == "ANCHORED"
        and item["citation"]["excerpt"] == "verbatim excerpt"
    )
    assert "assertion_level=specimen" in item["qualifier"]


def test_shapes_match_1819_when_present():
    contracts = pytest.importorskip(
        "app.graph_grounded_reasoning.contracts",
        reason="#1819 graph_grounded_reasoning is not on this base yet",
    )
    assert frozenset(contracts.PAYLOAD_ALLOWLIST) == interop.GGR_PAYLOAD_KEYS
    sample = contracts.EvidenceItem(
        ref="r",
        domain="traits",
        edge_type="has_trait",
        subject="s",
        object_label="o",
        polarity=1,
        evidence_class=None,
        review_state=None,
        verification_state=None,
        source_table=None,
        source_pk=None,
        source_document_id=None,
        assertion_id=None,
        conflicting_assertion_ids=(),
        qualifier=None,
        anchor_state=contracts.AnchorState.ANCHORED,
    )
    assert set(sample.to_dict()) == interop.GGR_EVIDENCE_ITEM_KEYS
    assert {s.value for s in contracts.AnchorState} >= {"ANCHORED", "SOURCE_UNDECLARED"}


# -- Matrix pairwise: species compared only on taxon-level evidence ---------------------------


def _taxon_presence(aid: str, taxon: str, state: str, confidence=None) -> AssertionIn:
    return _assertion(
        aid,
        taxon,
        "taxon",
        {"kind": "categorical", "state_id": state},
        confidence=confidence,
    )


def test_pairwise_uses_taxon_level_only_and_reports_individuals():
    specimen = _assertion(
        "sp1",
        ANGRAECUM,
        "specimen",
        {"kind": "quantitative", "numeric": 292.1, "unit": "mm"},
        specimen_id="S1",
    )
    ev = compare_assertions(
        ANGRAECUM,
        STANHOPEA,
        [
            _taxon_presence("a", ANGRAECUM, "present", 0.9),
            _taxon_presence("b", STANHOPEA, "present", 0.8),
            specimen,
        ],
    )
    assert ev.dimension == "morphology" and ev.dimension in MATRIX_DIMENSIONS
    assert (ev.availability, ev.score, ev.confidence) == ("available", 1.0, 0.8)
    assert ev.evidence == ("oc:trait:spur_presence",) and "sp1" not in ev.provenance
    assert any("not used to compare species" in lim for lim in ev.limitations)


def test_pairwise_never_invents_confidence_or_scores_contested_traits():
    unknown = compare_assertions(
        ANGRAECUM,
        STANHOPEA,
        [
            _taxon_presence("a", ANGRAECUM, "present", 0.9),
            _taxon_presence("b", STANHOPEA, "absent"),
        ],
    )
    assert unknown.score == 0.0 and unknown.confidence is None
    contested = compare_assertions(
        ANGRAECUM,
        STANHOPEA,
        [
            _taxon_presence("a", ANGRAECUM, "present"),
            _taxon_presence("b", STANHOPEA, "present"),
            _taxon_presence("c", STANHOPEA, "absent"),
        ],
    )
    assert contested.availability == "unavailable" and contested.score is None
    individuals_only = compare_assertions(
        ANGRAECUM,
        STANHOPEA,
        [
            _assertion(
                "s1",
                ANGRAECUM,
                "specimen",
                {"kind": "categorical", "state_id": "present"},
                specimen_id="1",
            ),
            _assertion(
                "s2",
                STANHOPEA,
                "specimen",
                {"kind": "categorical", "state_id": "present"},
                specimen_id="2",
            ),
        ],
    )
    assert (
        individuals_only.availability == "unavailable"
        and individuals_only.score is None
    )


# -- EOL TraitBank's own value columns (EOL/publishing doc/trait-schema.md) ----------------


def _eol(raw: dict) -> dict:
    return TraitBankHarvester()._normalize(
        {
            "eol_pk": raw.pop("eol_pk", "R1"),
            "resource_id": "694",
            "scientific_name": "Angraecum sesquipedale",
            **raw,
        },
        source_path="local.csv",
    )


def _eol_result(*rows: dict):
    return from_traitbank_harvester(
        [_eol(dict(r)) for r in rows],
        _traits(),
        lambda name: ANGRAECUM,
        dataset_citation="EOL.",
        dataset_license="see resource",
    )


def test_eol_measurement_columns_are_read_not_recorded_as_missing():
    # The harvester only reads value/measurementValue/object; an EOL export
    # carries the value in ``measurement``. Before TRAITBANK-002 this row was
    # stored as "missing: not_reported".
    result = _eol_result(
        {
            "predicate": "nectar spur length",
            "measurement": "29.2",
            "units_term": "http://purl.obolibrary.org/obo/UO_0000015",
        }
    )
    (a,) = result.batch.assertions
    assert a.value.kind == "quantitative" and a.value.numeric == 292.0
    assert a.value.verbatim == "29.2 http://purl.obolibrary.org/obo/UO_0000015"


def test_eol_normal_pair_is_used_with_its_own_unit_and_never_mixed():
    result = _eol_result(
        {
            "predicate": "nectar spur length",
            "normal_measurement": "0.292",
            "normal_units": "m",
            "units": "cm",
        }
    )
    assert result.batch.assertions[0].value.numeric == 292.0


def test_eol_categorical_literal_and_unknown_term_fail_closed():
    ok = _eol_result({"predicate": "Spur presence", "literal": "present"})
    assert ok.batch.assertions[0].value.state_id == "present"
    unknown = _eol_result(
        {"predicate": "Spur presence", "value_uri": "http://example.invalid/term/1"}
    )
    assert (
        unknown.batch is None
        and unknown.unmapped[0]["reason"] == "state_not_registered"
    )


def test_eol_unmapped_statistical_method_is_refused_not_read_as_single():
    result = _eol_result(
        {
            "predicate": "nectar spur length",
            "measurement": "30",
            "units": "cm",
            "statistical_method": "http://semanticscience.org/resource/SIO_001114",
        }
    )
    assert result.batch is None
    assert result.unmapped[0]["reason"] == "statistical_method_not_mapped"


def test_eol_row_with_no_value_column_is_missing_not_zero():
    (a,) = _eol_result({"predicate": "nectar spur length"}).batch.assertions
    assert a.value.kind == "missing" and a.evidence_state == "UNKNOWN"
