from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATION = ROOT / ".github" / "workflows" / "orchid-autonomous-validation.yml"


def test_exact_head_validation_enforces_swarm_write_set():
    text = VALIDATION.read_text(encoding="utf-8")
    assert "Swarm v3 post-build write-set verification" in text
    assert "oc_swarm_write_set_verifier.py" in text
    assert "[OC-SWARM-V2] Resource-aware worker lease claimed:" in text
    assert "gh pr view" in text
    assert "--json files" in text


def test_legacy_or_manual_prs_are_not_retroactively_blocked():
    text = VALIDATION.read_text(encoding="utf-8")
    assert "treating as legacy/manual work" in text
    assert "write-set verification not applicable" in text


def test_verifier_runs_before_normal_validation_suite():
    text = VALIDATION.read_text(encoding="utf-8")
    assert text.index("Swarm v3 post-build write-set verification") < text.index("Install runtime and validation dependencies")
