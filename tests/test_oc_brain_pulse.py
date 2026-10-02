from scripts.oc_brain_pulse import SOURCE, build_report, fingerprint


def test_brain_pulse_is_provider_free_and_non_authoritative():
    report = build_report()
    assert report["schema"] == "oc.work-discovery.v1"
    assert report["source"] == SOURCE
    assert report["authority"] == {
        "may_queue_research_or_engineering_work": True,
        "may_call_provider": False,
        "may_modify_governance": False,
        "may_promote_hypothesis": False,
        "may_activate_scientific_conclusion": False,
    }


def test_brain_pulse_emits_deduplicable_governed_candidates():
    report = build_report()
    assert report["candidate_count"] > 0
    assert report["candidate_count"] == len(report["candidates"])
    fingerprints = [candidate["fingerprint"] for candidate in report["candidates"]]
    assert len(fingerprints) == len(set(fingerprints))
    for candidate in report["candidates"]:
        assert "oc-queued" in candidate["labels"]
        assert "oc-discovered" in candidate["labels"]
        assert candidate["source"] == SOURCE
        assert candidate["validation_command"] == ""
        assert candidate["capabilities"] == []


def test_brain_fingerprint_changes_only_when_material_identity_changes():
    base = fingerprint("q", "missing_evidence", "gap")
    assert base == fingerprint("q", "missing_evidence", "gap")
    assert base != fingerprint("q2", "missing_evidence", "gap")
    assert base != fingerprint("q", "missing_source", "gap")
    assert base != fingerprint("q", "missing_evidence", "different")
