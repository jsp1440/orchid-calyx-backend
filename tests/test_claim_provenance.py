from hashlib import sha256

import pytest

from app.graph_grounded_reasoning import (
    Facet,
    GraphGroundedReasoner,
    ResultState,
    ScientificQuestion,
)
from app.graph_grounded_reasoning.benchmark import (
    build_environment,
    fixture_taxon_node_key,
    load_json,
)
from app.literature_extraction.models import Claim, Evidence, Provenance, SourceSpan
from runtime.knowledge_graph.claim_provenance import (
    CONTRACT_VERSION,
    EXTRACTION_METHODS,
    PAYLOAD_KEY,
    REVIEW_STATUSES,
    ClaimProvenance,
    SourceAnchor,
    TaxonBinding,
    coverage,
    from_literature_claim,
    parse_claim_provenance,
)
from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.repository import InMemoryGraphRepository

TAXON = TaxonBinding("Exemplaria aurea", "accepted", "fixture-release", "taxon:1")


def record(**overrides):
    values = {
        "source_document_id": "doc-1",
        "source_revision_id": "doc-1@r1",
        "content_hash": "a" * 64,
        "anchors": (SourceAnchor(page_start=3, page_end=3, char_start=10, char_end=80),),
        "taxon": TAXON,
        "extraction_method": "model_extracted",
        "review_status": "unreviewed",
        "assertion_id": "claim-1",
        "confidence": 0.62,
    }
    values.update(overrides)
    return ClaimProvenance(**values)


def payload(**overrides):
    return {PAYLOAD_KEY: record(**overrides).to_payload()}


def test_vocabularies_are_the_literature_extraction_vocabularies():
    assert EXTRACTION_METHODS == (
        "source_reported", "rule_extracted", "model_extracted", "human_annotated", "inferred", "imported",
    )
    assert REVIEW_STATUSES == ("unreviewed", "accepted", "corrected", "rejected")


def test_round_trip_preserves_every_field():
    original = record(
        uncertainty=("sample size 3",),
        qualifiers=("greenhouse",),
        conflicting_assertion_ids=("claim-2",),
        interpretation_ids=("int-1",),
        evidence_packet_ids=("pkt-1",),
        normalized_record_ids=("nr-1",),
        extractor="calyx-extractor",
        extractor_version="2",
    )
    parsed, violations = parse_claim_provenance({PAYLOAD_KEY: original.to_payload()})
    assert violations == ()
    assert parsed == original
    assert parsed.to_payload()["contract_version"] == CONTRACT_VERSION
    assert parsed.to_payload()["confidence_is_probability"] is False


@pytest.mark.parametrize(
    "mutate,violation",
    [
        (lambda p: p.pop(PAYLOAD_KEY), "CLAIM_PROVENANCE_ABSENT"),
        (lambda p: p[PAYLOAD_KEY].update(contract_version="v0"), "CONTRACT_VERSION_UNSUPPORTED"),
        (lambda p: p[PAYLOAD_KEY]["source"].update(document_id=""), "SOURCE_DOCUMENT_UNDECLARED"),
        (lambda p: p[PAYLOAD_KEY].update(anchors=[{"section_id": "s1"}]), "EXACT_ANCHOR_MISSING"),
        (lambda p: p[PAYLOAD_KEY].update(anchors=[{"page_start": 5, "page_end": 2}]), "ANCHOR_PAGE_RANGE_INVALID"),
        (lambda p: p[PAYLOAD_KEY]["taxon"].update(canonical_name=""), "TAXON_UNBOUND"),
        (lambda p: p[PAYLOAD_KEY]["taxon"].update(link_status="ambiguous"), "TAXON_LINK_NOT_VERIFIED"),
        (lambda p: p[PAYLOAD_KEY]["taxon"].update(authority="gbif"), "TAXON_AUTHORITY_NOT_WORLD_PLANTS"),
        (lambda p: p[PAYLOAD_KEY]["extraction"].update(method="vibes"), "EXTRACTION_METHOD_UNKNOWN"),
        (lambda p: p[PAYLOAD_KEY].update(review_status="rejected"), "CLAIM_REJECTED_IN_REVIEW"),
        (lambda p: p[PAYLOAD_KEY].update(confidence=1.4), "CONFIDENCE_OUT_OF_RANGE"),
        (lambda p: p[PAYLOAD_KEY].update(confidence=None, uncertainty=[]), "CONFIDENCE_AND_UNCERTAINTY_BOTH_MISSING"),
        (lambda p: p[PAYLOAD_KEY].update(confidence_is_probability=True), "CONFIDENCE_IS_NOT_A_PROBABILITY"),
        (lambda p: p[PAYLOAD_KEY].update(assertion_id=""), "ASSERTION_ID_MISSING"),
        (lambda p: p[PAYLOAD_KEY]["anchors"][0].update(locator={"latitude": 1.0}), "FORBIDDEN_LOCALITY_KEYS:latitude"),
    ],
)
def test_validation_fails_closed_and_names_the_violation(mutate, violation):
    raw = payload()
    mutate(raw)
    parsed, violations = parse_claim_provenance(raw)
    assert parsed is None
    assert violation in violations


def test_uncertainty_may_stand_in_for_a_missing_confidence():
    parsed, violations = parse_claim_provenance(payload(confidence=None, uncertainty=("single observer",)))
    assert violations == () and parsed.confidence is None


def test_producer_helper_builds_from_real_literature_models():
    span = SourceSpan(page_start=4, page_end=4, char_start=100, char_end=180)
    evidence = [
        Evidence(evidence_id="ev-1", excerpt="visited by bees", span=span, evidence_type="text"),
        Evidence(evidence_id="ev-2", excerpt="unrelated", span=SourceSpan(page_start=9), evidence_type="text"),
    ]
    claim = Claim(
        claim_id="claim-7",
        statement="Exemplaria aurea is visited by bees.",
        claim_type="observation",
        subject_ids=["taxon-1"],
        predicate="visited_by",
        object_ids=["bee-1"],
        evidence_ids=["ev-1"],
        polarity="positive",
        provenance=Provenance(method="model_extracted", confidence=0.7, extractor="x", extractor_version="1"),
    )
    built = from_literature_claim(
        claim.model_dump(),
        [e.model_dump() for e in evidence],
        source_document_id="paper-9",
        source_revision_id="paper-9@r2",
        content_hash="b" * 64,
        taxon=TAXON,
    )
    assert [a.page_start for a in built.anchors] == [4]  # only the cited evidence
    assert built.anchors[0].anchor_id == "ev-1"
    assert built.extraction_method == "model_extracted" and built.review_status == "unreviewed"
    parsed, violations = parse_claim_provenance({PAYLOAD_KEY: built.to_payload()})
    assert violations == () and parsed.assertion_id == "claim-7"


def test_coverage_counts_valid_records_and_violations():
    report = coverage([payload(), {}, {PAYLOAD_KEY: {"contract_version": CONTRACT_VERSION}}, None])
    assert report.total == 4 and report.valid == 1
    assert report.violations["CLAIM_PROVENANCE_ABSENT"] == 2
    assert report.violations["SOURCE_DOCUMENT_UNDECLARED"] == 1


# --- the pilot reads the contract and cross-checks it against the index ------


def pilot_with_edge(edge_payload):
    fixture = load_json("fixture.json")
    registry, _, engine = build_environment(fixture)
    text = next(d["text"] for d in fixture["documents"] if d["id"] == "doc-pol-1")
    nodes = [Node(1, "taxon", "taxon:1", "Exemplaria aurea"), Node(50, "pollinator", "pollinator:x", "Fictibombus alpha")]
    edges = [Edge(900, "associated_with_pollinator", 1, 50, payload=edge_payload)]
    reasoner = GraphGroundedReasoner(
        registry, InMemoryGraphRepository(nodes, edges), fixture_taxon_node_key(fixture, registry), search=engine.search
    )
    result = reasoner.answer(ScientificQuestion("Which pollinators visit Exemplaria aurea?", Facet.POLLINATION))
    return result, sha256(text.encode()).hexdigest()


def anchored_payload(**overrides):
    text_hash = sha256(
        next(d["text"] for d in load_json("fixture.json")["documents"] if d["id"] == "doc-pol-1").encode()
    ).hexdigest()
    values = {
        "source_document_id": "doc-pol-1",
        "source_revision_id": "doc-pol-1@r1",
        "content_hash": text_hash,
        "review_status": "accepted",
    }
    values.update(overrides)
    return payload(**values)


def test_valid_provenance_is_cited_with_method_confidence_and_taxon():
    result, _ = pilot_with_edge(anchored_payload())
    assert result["state"] == ResultState.CANDIDATE
    [item] = result["evidence_packet"]["items"]
    assert item["anchor_state"] == "ANCHORED"
    assert item["extraction_method"] == "model_extracted"
    assert item["confidence"] == 0.62 and item["confidence_is_probability"] is False
    assert item["taxon_binding"]["canonical_name"] == "Exemplaria aurea"
    assert "MODEL_EXTRACTED_ASSERTIONS:1" in result["uncertainty"]


@pytest.mark.parametrize(
    "overrides,state",
    [
        ({"source_revision_id": "doc-pol-1@r0"}, "SOURCE_REVISION_MISMATCH"),
        ({"content_hash": "f" * 64}, "SOURCE_REVISION_MISMATCH"),
        ({"taxon": TaxonBinding("Exemplaria rubra", "accepted", "fixture-release", None)}, "TAXON_BINDING_MISMATCH"),
        ({"taxon": TaxonBinding("Exemplaria aurea", "accepted", "fixture-release", "taxon:2")}, "TAXON_BINDING_MISMATCH"),
    ],
)
def test_claims_that_disagree_with_the_index_or_the_taxon_are_never_cited(overrides, state):
    result, _ = pilot_with_edge(anchored_payload(**overrides))
    [item] = result["evidence_packet"]["items"]
    assert item["anchor_state"] == state
    assert result["claims"] == [] and result["state"] == ResultState.INSUFFICIENT_EVIDENCE


def test_invalid_provenance_is_reported_with_its_violations_and_not_cited():
    raw = anchored_payload()
    raw[PAYLOAD_KEY]["extraction"]["method"] = "vibes"
    result, _ = pilot_with_edge(raw)
    [item] = result["evidence_packet"]["items"]
    assert item["anchor_state"] == "PROVENANCE_INVALID"
    assert "EXTRACTION_METHOD_UNKNOWN" in item["provenance_violations"]
    assert result["claims"] == []


def test_flat_legacy_payload_keys_are_ignored():
    result, _ = pilot_with_edge({"source_document_id": "doc-pol-1", "assertion_id": "x", "review_state": "APPROVED"})
    [item] = result["evidence_packet"]["items"]
    assert item["anchor_state"] == "SOURCE_UNDECLARED"
    assert item["provenance_violations"] == ["CLAIM_PROVENANCE_ABSENT"]
