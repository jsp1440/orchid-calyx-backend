from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml"


def test_v4_collects_closed_issues_for_dependency_resolution():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--state all" in text
    assert "oc_swarm_dependency_graph.py" in (
        ROOT / "scripts" / "oc_swarm_controller.py"
    ).read_text(encoding="utf-8")


def test_v4_has_bounded_self_refill():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "max_waves" in text
    assert 'default: "4"' in text
    assert "Dispatch bounded refill wave" in text
    assert "current >= maximum" in text
    assert "gh workflow run orchid-swarm-controller.yml" in text


def test_v4_refills_on_state_changes_and_periodic_pulse():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "*/5 * * * *"' in text
    assert "issues:" in text
    assert "types: [closed, reopened, labeled, unlabeled]" in text
    assert "pull_request:" in text
    assert "types: [closed]" in text


def test_v4_receipt_comes_from_confirmed_claim_adapter():
    # #1364 moved receipt creation out of the shell. The adapter's executable
    # receipt/identity tests live in test_oc_swarm_claim.py.
    import yaml

    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    plan = document["jobs"]["plan"]
    step = next(s for s in plan["steps"] if s.get("id") == "claim")
    assert "python3 -m scripts.oc_swarm_claim" in step["run"]
    assert "--run-attempt" in step["run"]
    assert plan["outputs"]["matrix"] == "${{ steps.claim.outputs.matrix }}"
    assert plan["outputs"]["launch_count"] == "${{ steps.claim.outputs.launch_count }}"


def test_v4_does_not_merge_or_deploy():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "gh pr merge" not in text
    assert "production deploy: disabled" in text.lower()


def test_v4_reusable_workers_receive_the_completion_lane_permission_ceiling():
    text = WORKFLOW.read_text(encoding="utf-8")
    header, jobs = text.split("\njobs:", maxsplit=1)
    workers = jobs.split("\n  workers:", maxsplit=1)[1].split(
        "\n  refill:", maxsplit=1
    )[0]

    # Planning/refill keep the read-biased workflow ceiling. Only reusable
    # implementation workers receive the mutation authority their callee
    # declares, because a called workflow cannot elevate its caller's token.
    assert "contents: read" in header
    assert "pull-requests: read" in header
    for permission in (
        "contents: write",
        "issues: write",
        "pull-requests: write",
        "actions: write",
        "id-token: write",
    ):
        assert permission in workers
