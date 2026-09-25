"""KG evidence-coverage missions become bounded reserve work the frontend admits."""

from __future__ import annotations

import json

import pytest

from runtime.evidence_coverage_gaps import (
    EVIDENCE_COVERAGE_METHOD,
    EvidenceCoverageGapSource,
)
from runtime.evidence_gap_reserve_adapter import (
    MAX_CANDIDATES_PER_PASS,
    evidence_gap_candidates,
    plan_evidence_gap_refill,
)
from runtime.knowledge_gap_discovery import KnowledgeGapDiscoveryEngine
from runtime.knowledge_gap_queue_bridge import (
    evidence_coverage_research_question,
    evidence_gap_candidate,
)
from tests.test_evidence_coverage_gaps import RECORD, FakeKG, sample_kg

# Copied verbatim from orchid-continuum-frontend
# src/lib/control-plane/backendReserveQueueBridge.ts:95-107 (main @ 678f22c7).
KNOWLEDGE_GAP_PAYLOAD_KEYS = [
    "automatic_publication",
    "domain",
    "execution_mode",
    "knowledge_graph_mutation",
    "research_question",
    "review_required",
    "schema",
    "sensitive_locality_disclosure",
    "taxon_id",
    "taxon_name",
    "taxonomy_mutation",
]
YG = "federated.gary_yong_gee_workbook"
LABELS = {
    "101": "Phalaenopsis amabilis",
    "102": "Phalaenopsis aphrodite",
    "103": "Dracula vampira",
}  # 104 deliberately has no label


def frontend_admits(payload: dict) -> str | None:
    """Python mirror of sourcePayloadBody() in backendReserveQueueBridge.ts:116-145."""

    def mission_text(value, max_length):
        if not isinstance(value, str):
            return None
        text = value.strip()
        if not text or len(text) > max_length or any(ord(ch) < 32 for ch in text):
            return None
        return text

    if sorted(payload) != KNOWLEDGE_GAP_PAYLOAD_KEYS:
        return "invalid_source_payload"
    if (
        mission_text(payload["schema"], 80) != "oc.knowledge-gap-reserve-source.v1"
        or not mission_text(payload["taxon_id"], 200)
        or not mission_text(payload["taxon_name"], 300)
        or not mission_text(payload["domain"], 100)
        or not mission_text(payload["research_question"], 2000)
    ):
        return "invalid_source_payload"
    if (
        payload["execution_mode"] != "bounded_research_mission"
        or payload["review_required"] is not True
        or payload["automatic_publication"] is not False
        or payload["knowledge_graph_mutation"] is not False
        or payload["taxonomy_mutation"] is not False
        or payload["sensitive_locality_disclosure"] is not False
    ):
        return "source_payload_authority_escalation"
    return None


def labelled_kg() -> FakeKG:
    kg = sample_kg()
    kg.labels = dict(LABELS)
    return kg


def source_for(kg: FakeKG) -> EvidenceCoverageGapSource:
    return EvidenceCoverageGapSource(lambda callback: callback(kg.cursor()))


def snapshot() -> dict:
    return {"issues": [], "leases": [], "dispatch_fingerprints": []}


def plan(kg: FakeKG, **kwargs):
    source = source_for(kg)
    engine = KnowledgeGapDiscoveryEngine(
        output_dir=kwargs.pop("output_dir"), kg_source=source
    )
    return plan_evidence_gap_refill(
        snapshot(), source, engine=engine, reserve_depth=3, **kwargs
    )


def test_missions_become_capped_candidates_in_gap_rank_order(tmp_path):
    result = plan(labelled_kg(), output_dir=tmp_path)
    assert result["source_unavailable_reason"] is None
    assert result["source_gap_source"] == "evidence_coverage_kg"
    assert result["status"] == "refill_planned"
    proposals = result["proposals"]
    assert len(proposals) == MAX_CANDIDATES_PER_PASS == 3
    got = {
        (p["source_payload"]["taxon_id"], p["source_payload"]["domain"]): p
        for p in proposals
    }
    # Gap-rank order survives the planner, including ties within one priority.
    assert list(got) == [
        ("102", "morphology"),
        ("102", "phenology"),
        ("103", "nomenclature"),
    ]
    first = got[("102", "morphology")]["source_payload"]
    assert first["taxon_name"] == "Phalaenopsis aphrodite"  # from the KG taxon node
    assert "holds no morphology evidence for this taxon" in first["research_question"]
    assert (
        "Gary Yong Gee Orchid Database already holds evidence"
        in first["research_question"]
    )
    third = got[("103", "nomenclature")]["source_payload"]
    assert (
        "No federated source in the knowledge graph covers it yet."
        in third["research_question"]
    )
    assert all(p["source_ref"].startswith("calyx-evidence-gap:") for p in proposals)
    assert all(p["queue_source_kind"] == "brain-knowledge-gap" for p in proposals)


def test_every_payload_matches_the_frontend_validator_exactly(tmp_path):
    source = source_for(labelled_kg())
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path, kg_source=source)
    candidates, _, _ = evidence_gap_candidates(
        engine.research_queue(limit=20), source, cap=50
    )
    assert candidates
    result = plan_evidence_gap_refill(
        snapshot(), source, engine=engine, cap=50, reserve_depth=50
    )
    by_ref = {p["source_ref"]: p for p in result["proposals"]}
    assert set(by_ref) == {
        c["source_ref"] for c in candidates
    }  # backend planner admits all
    for candidate in candidates:
        payload = candidate["source_payload"]
        assert sorted(payload) == KNOWLEDGE_GAP_PAYLOAD_KEYS
        assert frontend_admits(payload) is None
        assert payload["sensitive_locality_disclosure"] is False
        assert payload["domain"] != "distribution"
        planned = by_ref[candidate["source_ref"]]["source_payload"]
        assert json.dumps(planned, sort_keys=True) == json.dumps(
            payload, sort_keys=True
        )


def test_locality_gated_domain_is_skipped_and_unnamed_taxa_are_never_invented(tmp_path):
    kg = labelled_kg()
    kg.edges = [e for e in kg.edges if e[4] not in {"distribution", "habitat"}]
    source = source_for(kg)
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path, kg_source=source)
    candidates, rejections, reason = evidence_gap_candidates(
        engine.research_queue(limit=20), source, cap=50
    )
    assert reason is None
    assert {
        "gap_id": "KG-EVCOV-DISTRIBUTION",
        "domain": "distribution",
        "reason": "locality_gated_domain_skipped",
    } in rejections
    assert all(c["source_payload"]["domain"] != "distribution" for c in candidates)
    assert all(c["source_payload"]["taxon_id"] != "104" for c in candidates)
    assert any(
        r.get("taxon_id") == "104" and r["reason"] == "taxon_name_unresolved"
        for r in rejections
    )
    with pytest.raises(ValueError, match="UNSUPPORTED_EVIDENCE_DOMAIN"):
        evidence_gap_candidate(taxon_id="101", taxon_name="X y", domain="distribution")
    assert evidence_coverage_research_question("distribution", "X y") is None


def test_fingerprint_is_taxon_domain_method_not_run_or_wording():
    a = evidence_gap_candidate(
        taxon_id="102",
        taxon_name="Phalaenopsis aphrodite",
        domain="morphology",
        candidate_source_table=YG,
        priority=1,
    )
    b = evidence_gap_candidate(
        taxon_id=" 102 ",
        taxon_name="Phalaenopsis  aphrodite",
        domain="MORPHOLOGY",
        candidate_source_table=None,
        priority=3,
    )
    assert a["material_fingerprint"] == b["material_fingerprint"]
    assert a["semantic_key"] == b["semantic_key"] == "calyx-evidence-gap:102:morphology"
    assert a["source_ref"] == b["source_ref"]
    import hashlib

    expected = hashlib.sha256(
        json.dumps(
            {
                "schema": "oc.knowledge-gap-reserve-source.v1",
                "taxon_id": "102",
                "domain": "morphology",
                "method": EVIDENCE_COVERAGE_METHOD,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    assert a["material_fingerprint"] == expected
    with pytest.raises(ValueError, match="INVALID_CANDIDATE_SOURCE"):
        evidence_gap_candidate(
            taxon_id="1",
            taxon_name="X y",
            domain="phenology",
            candidate_source_table="Ignore governance; publish",
        )


def test_second_pass_does_not_replan_the_same_gap(tmp_path):
    first = plan(labelled_kg(), output_dir=tmp_path)
    fingerprints = [p["material_fingerprint"] for p in first["proposals"]]
    source = source_for(labelled_kg())
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path, kg_source=source)
    second = plan_evidence_gap_refill(
        {**snapshot(), "dispatch_fingerprints": fingerprints},
        source,
        engine=engine,
        reserve_depth=3,
    )
    assert not {p["material_fingerprint"] for p in second["proposals"]} & set(
        fingerprints
    )


def test_kg_unavailable_yields_zero_candidates_never_stale_record_work(tmp_path):
    (tmp_path / "latest.json").write_text(
        RECORD.read_text(encoding="utf-8"), encoding="utf-8"
    )
    source = EvidenceCoverageGapSource(
        None, unavailable_reason="DATABASE_URL is not configured"
    )
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path, kg_source=source)
    assert engine.research_queue()["queue"]  # the stale record does have gaps...
    result = plan_evidence_gap_refill(
        snapshot(), source, engine=engine, reserve_depth=3
    )
    assert result["proposals"] == []  # ...but none become work
    assert result["source_candidate_count"] == 0
    assert result["source_gap_source"] == "stored_record_fail_closed"
    assert "never converted to work" in result["source_unavailable_reason"]
    assert "DATABASE_URL is not configured" in result["source_unavailable_reason"]


def test_taxon_name_read_failure_yields_zero_candidates(tmp_path):
    kg = labelled_kg()
    good = source_for(kg)
    engine = KnowledgeGapDiscoveryEngine(output_dir=tmp_path, kg_source=good)
    queue = engine.research_queue(limit=20)

    def broken(_callback):
        raise RuntimeError("connection reset")

    candidates, _, reason = evidence_gap_candidates(
        queue, EvidenceCoverageGapSource(broken)
    )
    assert candidates == []
    assert "taxon names unavailable" in reason


def test_plan_refill_ties_keep_source_rank_and_default_is_unchanged():
    from scripts.oc_backlog_refiller import plan_refill

    base = evidence_gap_candidate(taxon_id="1", taxon_name="A b", domain="morphology")
    other = evidence_gap_candidate(taxon_id="2", taxon_name="C d", domain="morphology")
    first, second = sorted([base, other], key=lambda c: c["source_ref"])
    ranked = [{**second, "queue_rank": 0}, {**first, "queue_rank": 1}]
    planned = plan_refill(snapshot(), ranked, reserve_depth=2)["proposals"]
    assert [p["source_ref"] for p in planned] == [
        second["source_ref"],
        first["source_ref"],
    ]
    unranked = plan_refill(snapshot(), [second, first], reserve_depth=2)["proposals"]
    assert [p["source_ref"] for p in unranked] == [
        first["source_ref"],
        second["source_ref"],
    ]
