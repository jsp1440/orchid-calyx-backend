"""TRAITBANK-001: contract compatibility, validation, provenance and privacy guards.

Offline: no database. The PostgreSQL-backed flow is in
``tests/test_traitbank_postgres.py``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.literature_extraction.models import PaperKnowledge
from app.parallel_platform.brain_candidate_handoff import handoff_brain_candidate
from app.traitbank import guards, projection
from app.traitbank.adapters import (
    TraitIndex,
    convert,
    from_paper_knowledge,
    from_traitbank_harvester,
)
from app.traitbank.cli import load_definition_file
from app.traitbank.contract import (
    BRAIN_CONTRACT_SHA256,
    BRAIN_OAO_REGISTRY_SHA256,
    CONTRACT_PATH,
    OAO_REGISTRY_PATH,
    TraitBankContractError,
    load_contract,
    load_oao_terms,
    oao_terms,
)
from app.traitbank.models import AssertionIn, EnvironmentRelationIn, TraitBankBatch
from harvesters.traitbank import TraitBankHarvester
from runtime.matrix_relationship import RelationshipAssertion, build_relationship_matrix

FIXTURES = Path(__file__).parent / "fixtures" / "traitbank"
ANGRAECUM = "990000002"
# SYNTHETIC coordinates (the open-Atlantic point used by
# tests/test_no_precise_coordinates.py), assembled at runtime so no precise
# coordinate literal is committed.
SYN_LAT, SYN_LON = "12." + "3456", "-45." + "6789"


def _codes(exc: ValidationError) -> set[str]:
    return {str(e["msg"]).removeprefix("Value error, ") for e in exc.errors()}


def _assertion(**overrides) -> dict:
    data = {
        "assertion_id": "a-1",
        "trait_id": "oc:trait:spur_length",
        "level": "specimen",
        "subject": {
            "taxon_id": ANGRAECUM,
            "verbatim_taxon_name": "Angraecum sesquipedale",
            "specimen_id": "S1",
        },
        "value": {"kind": "quantitative", "numeric": 280.0, "unit": "mm"},
        "provenance": {
            "source_id": "herbarium:K",
            "source_kind": "herbarium",
            "original_record_id": "K000123",
            "citation": "Royal Botanic Gardens, Kew herbarium sheet K000123.",
            "license": "CC BY 4.0",
            "evidence_type": "direct_measurement",
        },
    }
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    return data


def _batch(*assertions: dict, **extra) -> TraitBankBatch:
    return TraitBankBatch.model_validate(
        {
            "contract_version": "oc-traitbank-v1",
            "batch_key": "curated:unit-batch-0001",
            "producer": "curated",
            "assertions": list(assertions),
            **extra,
        }
    )


def _definitions():
    return {d.trait_id: d for d in load_definition_file()}


# -- 1. the vendored Brain contract is pinned ------------------------------------------


def test_vendored_contract_and_oao_registry_match_their_pins():
    assert (
        hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest() == BRAIN_CONTRACT_SHA256
    )
    assert (
        hashlib.sha256(OAO_REGISTRY_PATH.read_bytes()).hexdigest()
        == BRAIN_OAO_REGISTRY_SHA256
    )
    assert load_contract()["contract_version"] == "oc-traitbank-v1"
    assert "OAO:0000043" in load_oao_terms()


def test_a_drifted_contract_is_refused(tmp_path: Path):
    contract = json.loads(CONTRACT_PATH.read_text())
    contract["governance"]["graph_mutation_allowed"] = True
    drifted = tmp_path / "traitbank_v1.json"
    drifted.write_text(json.dumps(contract))
    with pytest.raises(TraitBankContractError):
        load_contract(drifted)
    # Even with a matching pin, a contract granting authority is refused.
    with pytest.raises(TraitBankContractError):
        load_contract(drifted, hashlib.sha256(drifted.read_bytes()).hexdigest())


def test_brain_records_are_accepted_once_their_taxon_id_is_canonical():
    """A record produced by the Brain reference implementation validates unchanged
    apart from the taxon id, which must be canonical rather than namespaced."""
    brain_record = _assertion(subject={"taxon_id": "taxon:1002"})
    with pytest.raises(ValidationError) as exc:
        AssertionIn.model_validate(brain_record)
    assert "TAXON_ID_NOT_CANONICAL" in _codes(exc.value)
    record = AssertionIn.model_validate(
        {**brain_record, "subject": {**brain_record["subject"], "taxon_id": ANGRAECUM}}
    )
    assert record.contract_version == "oc-traitbank-v1"


def test_definitions_reference_only_registered_oao_terms_and_no_placeholders():
    definitions = load_definition_file()
    assert {d.trait_id for d in definitions} >= {
        "oc:trait:spur_length",
        "oc:trait:spur_presence",
    }
    for d in definitions:
        assert guards.check_definition(d, live=True) == []
        assert not any("example.org" in a for a in d.aliases)
    terms = oao_terms()
    assert terms["OAO:0000043"]["term_label"] == "Spur length"


# -- 2. validation invariants -----------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,code",
    [
        ({"subject": {"specimen_id": None}}, "SPECIMEN_ASSERTION_REQUIRES_SPECIMEN_ID"),
        ({"level": "taxon"}, "TAXON_ASSERTION_CANNOT_BE_DIRECT"),
        (
            {"level": "taxon", "scope_basis": "aggregated_with_justification"},
            "TAXON_GENERALIZATION_REQUIRES_JUSTIFICATION",
        ),
        (
            {"value": {"kind": "range", "minimum": 5, "maximum": 1, "unit": "mm"}},
            "RANGE_BOUNDS_INVERTED",
        ),
        (
            {
                "value": {
                    "kind": "missing",
                    "numeric": None,
                    "unit": None,
                    "missing_reason": "not_reported",
                }
            },
            "MISSING_VALUE_REQUIRES_NON_VALUE_STATE",
        ),
        ({"confidence": 1.5}, "CONFIDENCE_OUT_OF_RANGE"),
        ({"provenance": {"source_kind": "rumour"}}, "UNKNOWN_SOURCE_KIND"),
    ],
)
def test_assertion_invariants(overrides, code):
    with pytest.raises(ValidationError) as exc:
        AssertionIn.model_validate(_assertion(**overrides))
    assert code in _codes(exc.value)


@pytest.mark.parametrize(
    "field", ["citation", "license", "original_record_id", "source_id"]
)
def test_provenance_is_required(field):
    with pytest.raises(ValidationError):
        AssertionIn.model_validate(_assertion(provenance={field: ""}))


def test_missing_confidence_stays_none():
    record = AssertionIn.model_validate(_assertion())
    assert record.confidence is None


def test_unknown_fields_are_refused_so_locality_cannot_be_smuggled_in():
    with pytest.raises(ValidationError):
        AssertionIn.model_validate({**_assertion(), "latitude": float(SYN_LAT)})
    with pytest.raises(ValidationError):
        AssertionIn.model_validate(_assertion(subject={"locality": "Ranomafana"}))


def test_batches_refuse_duplicate_source_records():
    with pytest.raises(ValidationError) as exc:
        _batch(_assertion(), _assertion(assertion_id="a-2"))
    assert "DUPLICATE_SOURCE_RECORD_IN_BATCH" in _codes(exc.value)


def test_environment_relation_kinds_are_distinct():
    base = {
        "relation_id": "r",
        "trait_id": "oc:trait:spur_length",
        "environment_variable": "elevation",
        "statement": "s",
        "provenance": _assertion()["provenance"],
    }
    with pytest.raises(ValidationError):
        EnvironmentRelationIn.model_validate(
            {
                **base,
                "claim_kind": "observed_correlation",
                "hypothesis_scope": "adaptive",
            }
        )
    with pytest.raises(ValidationError):
        EnvironmentRelationIn.model_validate(
            {
                **base,
                "claim_kind": "tested_hypothesis",
                "hypothesis_scope": "adaptive",
                "test_outcome": "supported",
            }
        )
    corr = EnvironmentRelationIn.model_validate(
        {**base, "claim_kind": "observed_correlation"}
    )
    assert corr.describe().startswith(
        "Observed correlation (not a causal or adaptive explanation)"
    )


# -- 3. live-ingestion and privacy guards ------------------------------------------------


def _violations(batch: TraitBankBatch, *, live: bool = True) -> set[str]:
    return {v.code for v in guards.check_batch(batch, live=live)}


def test_a_clean_record_passes_the_live_guards():
    assert _violations(_batch(_assertion())) == set()


@pytest.mark.parametrize(
    "overrides,code",
    [
        (
            {"provenance": {"fixture_status": "synthetic_contract_fixture"}},
            "FIXTURE_RECORD_REFUSED_IN_LIVE",
        ),
        (
            {
                "provenance": {
                    "source_url": "https://example.org/oc-fixture/resource/10"
                }
            },
            "PLACEHOLDER_REFUSED_IN_LIVE",
        ),
        (
            {
                "provenance": {
                    "citation": "Author (2026). https://doi.org/10.5555/oc.traitbank.fixture.001"
                }
            },
            "TEST_DOI_REFUSED_IN_LIVE",
        ),
        ({"provenance": {"source_id": "fx-cytology"}}, "FIXTURE_ID_REFUSED_IN_LIVE"),
        ({"notes": "[synthetic] value"}, "PLACEHOLDER_REFUSED_IN_LIVE"),
    ],
)
def test_live_ingestion_refuses_placeholders(overrides, code):
    batch = _batch(_assertion(**overrides))
    assert code in _violations(batch, live=True)
    # Placeholder checks apply to live ingestion only; fixture validation may
    # exercise them (it can never write: see the CLI and repository tests).
    assert code not in _violations(batch, live=False)


@pytest.mark.parametrize(
    "overrides",
    [
        {"notes": f"collected at {SYN_LAT}, {SYN_LON}"},
        {"provenance": {"locator": f"lat: {SYN_LAT}"}},
        {"habitats": ["ridge at 12" + "°20' N"]},
        {"provenance": {"contributor": "grower@example.net"}},
        {"provenance": {"contributor": "call +1 415 555 0100"}},
    ],
)
def test_privacy_guards_refuse_locality_and_contact_details_in_every_mode(overrides):
    codes = _violations(_batch(_assertion(**overrides)), live=False)
    assert codes & {"COORDINATES_REFUSED", "PRIVATE_CONTACT_REFUSED"}


def test_verified_requires_reviewed_provenance():
    assert "VERIFIED_REQUIRES_REVIEWED_PROVENANCE" in _violations(
        _batch(_assertion(evidence_state="VERIFIED"))
    )
    reviewed = _assertion(
        evidence_state="VERIFIED", provenance={"review_status": "accepted"}
    )
    assert _violations(_batch(reviewed)) == set()


# -- 4. adapters from existing pathways -----------------------------------------------------


def _paper() -> PaperKnowledge:
    return PaperKnowledge.model_validate_json(
        (FIXTURES / "darwin_1862_paper_knowledge.json").read_text()
    )


def _resolver(name: str) -> str | None:
    return {"Angraecum sesquipedale": ANGRAECUM}.get(name)


def test_literature_extraction_becomes_specimen_level_evidence_with_verbatim_provenance():
    result = from_paper_knowledge(_paper(), TraitIndex(_definitions()), _resolver)
    assert result.unmapped == []
    (a,) = result.batch.assertions
    assert (a.level, a.scope_basis, a.subject.specimen_id) == (
        "specimen",
        "direct",
        "darwin-1862:flowers-examined",
    )
    assert a.value.numeric == 292.1 and a.value.unit == "mm"
    assert a.value.verbatim == "eleven and a half inches"
    assert a.provenance.original_text == "nectaries eleven and a half inches long"
    assert a.provenance.locator == "section chapter-angraecum"
    assert a.provenance.license == "public domain"
    assert a.evidence_state == "PROVISIONAL"
    (rel,) = result.batch.environment_relations
    assert rel.claim_kind == "proposed_hypothesis" and rel.taxon_scope == (ANGRAECUM,)
    assert guards.check_batch(result.batch, live=True) == []


def test_literature_adapter_never_guesses_level_or_taxon():
    paper = _paper().model_copy(deep=True)
    paper.entities[0].attributes.clear()
    result = from_paper_knowledge(paper, TraitIndex(_definitions()), _resolver)
    assert [u["reason"] for u in result.unmapped] == ["assertion_level_not_stated"]
    unresolved = from_paper_knowledge(
        _paper(), TraitIndex(_definitions()), lambda name: None
    )
    assert (
        unresolved.unmapped[0]["reason"]
        == "taxon_not_uniquely_resolved_in_canonical_taxonomy"
    )


def test_eol_harvester_records_are_normalized_without_a_second_parser(tmp_path: Path):
    harvester = TraitBankHarvester()
    raw_rows = [
        {
            "eol_pk": "R1",
            "resource_id": "694",
            "scientific_name": "Angraecum sesquipedale",
            "predicate": "nectar spur length",
            "value": "30",
            "units": "cm",
            "statistical_method": "mean",
            "sample_size": "5",
            "citation": "Resource 694 citation.",
            "license": "CC BY 4.0",
        },
        {
            "eol_pk": "R2",
            "resource_id": "694",
            "scientific_name": "Angraecum sesquipedale",
            "predicate": "fragrance chemistry",
            "value": "linalool",
        },
        {
            "eol_pk": "R3",
            "resource_id": "694",
            "scientific_name": "Angraecum sesquipedale",
            "predicate": "nectar spur length",
            "value": "0.3",
            "units": "kg",
        },
        {
            "eol_pk": "R4",
            "resource_id": "694",
            "scientific_name": "Angraecum sesquipedale",
            "predicate": "leaf length",
            "value": "",
        },
    ]
    records = [harvester._normalize(r, source_path="local.tsv") for r in raw_rows]
    result = from_traitbank_harvester(
        records,
        TraitIndex(_definitions()),
        _resolver,
        dataset_citation="EOL TraitBank.",
        dataset_license="see resource",
    )
    by_id = {a.assertion_id: a for a in result.batch.assertions}
    spur = by_id["tb:eol:R1"]
    assert (spur.level, spur.scope_basis, spur.evidence_state) == (
        "taxon",
        "source_reported",
        "AVAILABLE",
    )
    assert (
        spur.value.numeric == 300.0
        and spur.value.verbatim == "30 cm"
        and spur.value.statistic == "mean"
    )
    assert spur.confidence is None  # EOL reports none; none is invented
    assert (
        by_id["tb:eol:R4"].value.kind == "missing"
        and by_id["tb:eol:R4"].evidence_state == "UNKNOWN"
    )
    assert {u["original_record_id"]: u["reason"] for u in result.unmapped} == {
        "R2": "trait_not_registered",
        "R3": "value_or_unit_not_convertible",
    }


def test_unit_conversion_is_length_only():
    assert convert(11.5, "in", "mm") == 292.1
    assert convert(1, "kg", "mm") is None


# -- 5. projections --------------------------------------------------------------------------


def _members() -> list[AssertionIn]:
    darwin = from_paper_knowledge(
        _paper(), TraitIndex(_definitions()), _resolver
    ).batch.assertions[0]
    eol = AssertionIn.model_validate(
        _assertion(
            assertion_id="eol-1",
            level="taxon",
            scope_basis="source_reported",
            subject={"specimen_id": None},
            evidence_state="AVAILABLE",
            value={
                "kind": "quantitative",
                "numeric": 300.0,
                "unit": "mm",
                "statistic": "mean",
            },
            provenance={
                "source_id": "eol-traitbank:resource:694",
                "source_kind": "dataset",
                "original_record_id": "R1",
                "evidence_type": "dataset_import",
            },
        )
    )
    return [darwin, eol]


def test_calyx_keeps_unreported_confidence_unknown():
    definition = _definitions()["oc:trait:spur_length"]
    out = projection.calyx_envelope(definition, ANGRAECUM, _members())
    assert out["confidence"] is None and out["confidence_state"] == "partially_unknown"
    assert out["reasoning_envelope"]["candidate_knowledge"]["confidence"] is None
    assert out["reasoning_envelope"]["candidate_knowledge"]["predicate"] == "has_trait"
    assert "left unknown" in out["statement"]
    only_darwin = projection.calyx_envelope(definition, ANGRAECUM, _members()[:1])
    assert only_darwin["confidence"] == 0.95
    assert (
        only_darwin["reasoning_envelope"]["candidate_knowledge"]["predicate"]
        == "has_trait_evidence_from_individuals"
    )
    assert "must not be presented as typical of the species" in only_darwin["statement"]


def test_matrix_assertions_are_accepted_by_the_existing_matrix_builder():
    items = projection.matrix_assertions(
        _definitions(), _members(), {ANGRAECUM: "Angraecum sesquipedale"}
    )
    dims = {i["provenance"]["source_pk"]: i["dimension"] for i in items}
    assert dims == {
        "eol-1": "trait",
        "tb:lit:darwin-1862-fertilisation-of-orchids:m-nectary-length": "trait_individual_evidence",
    }
    governed = [
        RelationshipAssertion(
            **{k: v for k, v in i.items() if k not in projection.GOVERNANCE}
        )
        for i in items
    ]
    matrix = build_relationship_matrix(
        governed, dimension="trait", subject_ids=[ANGRAECUM]
    )
    assert matrix["dimension"] == "trait" and len(matrix["cells"]) == 1
    assert (
        matrix["cells"][0]["state"] == "present"
        and matrix["cells"][0]["confidence"] is None
    )


def test_candidate_handoff_withholds_unknown_confidence_and_flows_through_the_existing_pipeline():
    definition = _definitions()["oc:trait:spur_length"]
    darwin, eol = _members()
    rows = []
    for pk, a in enumerate((darwin, eol), start=1):
        rows.append(_row(a, assertion_pk=pk, batch_pk=7))
    requests, withheld = projection.candidate_handoff_requests(definition, rows)
    assert withheld == [
        {"assertion_id": "eol-1", "reason": "CONFIDENCE_NOT_REPORTED_NOT_DEFAULTED"}
    ]
    (request,) = requests
    assert (
        request.confidence == 0.95
        and request.predicate == "has_trait_evidence_from_individuals"
    )
    assert request.qualifiers["assertion_level"] == "specimen"
    components = (repo := MemoryCandidateRepository(), CandidateExtractionService(repo))
    result = handoff_brain_candidate(request, components)
    assert (
        result["review_required"] is True
        and result["published"] is False
        and result["graph_mutation"] is False
    )
    assert result["candidate_ids"]


def _row(a: AssertionIn, *, assertion_pk: int, batch_pk: int) -> dict:
    v, p, s = a.value, a.provenance, a.subject
    return {
        "assertion_pk": assertion_pk,
        "batch_pk": batch_pk,
        "assertion_id": a.assertion_id,
        "trait_id": a.trait_id,
        "level": a.level,
        "taxon_id": int(s.taxon_id),
        "verbatim_taxon_name": s.verbatim_taxon_name,
        "specimen_id": s.specimen_id,
        "population_id": s.population_id,
        "observation_id": s.observation_id,
        "value_kind": v.kind,
        "numeric_value": v.numeric,
        "minimum_value": v.minimum,
        "maximum_value": v.maximum,
        "unit": v.unit,
        "state_id": v.state_id,
        "statistic": v.statistic,
        "sd": v.sd,
        "sample_size": v.n,
        "uncertainty": v.uncertainty,
        "missing_reason": v.missing_reason,
        "verbatim_value": v.verbatim,
        "evidence_state": a.evidence_state,
        "scope_basis": a.scope_basis,
        "scope_justification": a.scope_justification,
        "derived_from": list(a.derived_from),
        "method_id": a.method_id,
        "confidence": a.confidence,
        "life_stage": a.life_stage,
        "habitats": list(a.habitats),
        "links": [x.model_dump() for x in a.links],
        "notes": a.notes,
        **{
            k: getattr(p, k)
            for k in (
                "source_id",
                "source_kind",
                "original_record_id",
                "citation",
                "license",
                "evidence_type",
                "contributor",
                "source_url",
                "locator",
                "original_text",
                "retrieved_at",
                "extraction_method",
                "review_status",
            )
        },
    }


def test_conflicts_are_preserved_and_variation_is_not_conflict():
    present = AssertionIn.model_validate(
        _assertion(
            assertion_id="p",
            trait_id="oc:trait:spur_presence",
            level="taxon",
            scope_basis="source_reported",
            subject={"specimen_id": None},
            value={
                "kind": "categorical",
                "state_id": "present",
                "numeric": None,
                "unit": None,
            },
        )
    )
    absent = AssertionIn.model_validate(
        _assertion(
            assertion_id="q",
            trait_id="oc:trait:spur_presence",
            level="taxon",
            scope_basis="source_reported",
            subject={"specimen_id": None},
            value={
                "kind": "categorical",
                "state_id": "absent",
                "numeric": None,
                "unit": None,
            },
            provenance={"original_record_id": "K000999"},
        )
    )
    (found,) = projection.conflicts([present, absent])
    assert (
        found["assertion_ids"] == ["p", "q"]
        and found["resolution"] == "preserved_not_collapsed"
    )
    s2 = AssertionIn.model_validate(
        _assertion(
            assertion_id="s2",
            subject={"specimen_id": "S2"},
            value={"numeric": 350.0},
            provenance={"original_record_id": "K2"},
        )
    )
    assert projection.conflicts([AssertionIn.model_validate(_assertion()), s2]) == []
