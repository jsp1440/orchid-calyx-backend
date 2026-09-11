from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(".github/workflows")
LEGACY = WORKFLOWS / "orchid-continuous-completion.yml"
LANE = WORKFLOWS / "orchid-completion-lane.yml"


@pytest.fixture(scope="module")
def legacy_text() -> str:
    return LEGACY.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def lane_text() -> str:
    return LANE.read_text(encoding="utf-8")


def test_legacy_entry_point_only_redirects_to_swarm(legacy_text):
    document = yaml.safe_load(legacy_text)
    assert set(document[True]) == {"workflow_dispatch"}
    assert set(document["jobs"]) == {"redirect"}
    assert "gh workflow run orchid-swarm-controller.yml" in legacy_text
    assert "orchid-completion-lane.yml" not in legacy_text
    assert "oc_portfolio_scheduler.py" not in legacy_text


def test_legacy_redirect_has_read_only_repository_permissions(legacy_text):
    permissions = yaml.safe_load(legacy_text)["permissions"]
    assert permissions == {"actions": "write", "contents": "read"}
    assert "--ref oc-autonomous-integration" in legacy_text


def test_provider_lane_is_gated_before_job_initialization(lane_text):
    document = yaml.safe_load(lane_text)
    execute = document["jobs"]["execute"]
    assert execute["if"] == "vars.NO_API_MODE == 'false'"
    assert "scripts/swarm_anthropic_direct.py" in lane_text
    assert "anthropics/claude-code-action@v1" not in lane_text
    assert "@google/gemini-cli" in lane_text
    assert "@openai/codex" in lane_text


def test_lane_requires_a_live_scheduler_lease(lane_text):
    lease = lane_text.index("name: Verify scheduler lease")
    provider = lane_text.index("scripts/swarm_anthropic_direct.py")
    assert lease < provider
    assert "oc-running" in lane_text[lease:provider]
    assert "Stale/duplicate completion dispatch suppressed" in lane_text[lease:provider]


def test_lane_targets_integration_and_never_merges_main(lane_text):
    assert "INTEGRATION_BRANCH: oc-autonomous-integration" in lane_text
    assert "--base \"$INTEGRATION_BRANCH\"" in lane_text
    assert "gh pr merge" not in lane_text
    assert "deploy production" in lane_text
    assert "Never merge to `main`" in lane_text


def test_lane_preserves_exact_head_validation_dispatch(lane_text):
    assert "orchid-autonomous-validation.yml" in lane_text


def test_lane_keeps_scientific_safety_contract(lane_text):
    assert "sensitive-locality protections" in lane_text
    assert "Never invent science" in lane_text
    assert "activate taxonomy" in lane_text
    assert "publish science" in lane_text
