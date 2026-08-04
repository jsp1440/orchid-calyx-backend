from scripts.run_bounded_resumable_graph_dry_run import build_evidence, choose_domain


def test_choose_domain_prefers_taxonomy():
    assert choose_domain(["media", "taxonomy", "traits"]) == "taxonomy"


def test_choose_domain_uses_deterministic_fallback():
    assert choose_domain(["zeta", "alpha"]) == "alpha"


def test_build_evidence_fails_closed_on_publication():
    evidence = build_evidence(
        domain="taxonomy",
        session={"run_id": "RUN-1"},
        resume={"status": "paused"},
        report={"status": "paused"},
    )
    assert evidence["bounds"] == {
        "batch_size": 100,
        "max_batches_per_step": 1,
        "domains": 1,
    }
    assert evidence["production_graph_mutation"] is False
    assert evidence["production_publication_authorized"] is False
    assert evidence["publication_endpoint_invoked"] is False
    assert len(evidence["artifact_hash"]) == 64
