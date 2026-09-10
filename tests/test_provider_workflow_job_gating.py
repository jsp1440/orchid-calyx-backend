from pathlib import Path

WORKFLOWS = Path(".github/workflows")
PROVIDER_MARKERS = (
    "anthropics/claude-code-action",
    "@google/gemini-cli",
    "@openai/codex",
    "api.openai.com",
)


def provider_workflows() -> list[Path]:
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if any(marker in path.read_text(encoding="utf-8") for marker in PROVIDER_MARKERS)
    ]


def test_every_provider_capable_job_is_gated_before_initialization():
    expected = {
        "claude-code-governed.yml",
        "orchid-claude-runtime-canary.yml",
        "orchid-completion-lane.yml",
        "orchid-gemini-runtime-canary.yml",
        "orchid-openai-runtime-canary.yml",
    }
    discovered = {path.name for path in provider_workflows()}
    assert discovered == expected

    for path in provider_workflows():
        text = path.read_text(encoding="utf-8")
        job_header = text[: text.index("    steps:")]
        assert "vars.NO_API_MODE == 'false'" in job_header, path


def test_legacy_scheduler_contains_no_provider_or_independent_planner_path():
    text = (WORKFLOWS / "orchid-continuous-completion.yml").read_text(encoding="utf-8")
    assert not any(marker in text for marker in PROVIDER_MARKERS)
    assert "oc_portfolio_scheduler.py" not in text
    assert "orchid-completion-lane.yml" not in text
    assert "gh workflow run orchid-swarm-controller.yml" in text
