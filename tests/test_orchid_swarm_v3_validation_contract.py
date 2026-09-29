from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / ".github" / "workflows" / "orchid-autonomous-validation.yml"


def test_exact_head_validation_enforces_versioned_swarm_write_set():
    text = VALIDATION.read_text(encoding="utf-8")
    assert "Swarm post-build write-set verification" in text
    assert "oc_swarm_write_set_verifier.py" in text
    assert "OC-SWARM-V[0-9]+" in text
    assert "gh pr view" in text
    assert "--json files" in text


def test_legacy_or_manual_prs_are_not_retroactively_blocked():
    text = VALIDATION.read_text(encoding="utf-8")
    assert "treating as legacy/manual work" in text
    assert "write-set verification not applicable" in text


def test_verifier_runs_before_normal_validation_suite():
    text = VALIDATION.read_text(encoding="utf-8")
    assert text.index("Swarm post-build write-set verification") < text.index(
        "Install runtime and validation dependencies"
    )


def _verification_step() -> str:
    import yaml

    doc = yaml.safe_load(VALIDATION.read_text(encoding="utf-8"))
    steps = doc["jobs"]["validate"]["steps"]
    return next(
        s["run"]
        for s in steps
        if s.get("name") == "Swarm post-build write-set verification"
    )


def test_edit_lane_heads_require_the_issue_marker_and_lease():
    run = _verification_step()
    assert 'if [[ "$HEAD_REF" == oc/discovered-* ]]; then' in run
    # Each "not applicable" exit is preceded by a refusal for edit-lane heads.
    for skip in (
        "No integration PR for this head",
        "has no OC-AUTO-ISSUE marker; write-set verification not applicable",
        "treating as legacy/manual work",
    ):
        before = run[: run.index(skip)]
        guard = before.rindex('if [[ "$lane_head" == true ]]; then')
        assert "exit 1" in before[guard:], skip
    assert run.index("lane_head=true") < run.index("gh pr view")
