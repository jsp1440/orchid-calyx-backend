"""Changed integration ownership policy only; simulated GitHub, no providers."""
from datetime import timedelta
from pathlib import Path

import pytest
import yaml

from scripts.oc_swarm_claim import claim_workers, route_task
from scripts.oc_swarm_lease_reconcile import GitHubTransport, _latest_claim
from scripts.oc_swarm_settlement import settle_worker, verified_issue
from tests.swarm_wave_github_fake import EPOCH, FakeGitHub, iso


def owned():
    fake = FakeGitHub([{
        "number": 1, "title": "Bounded repository work", "body": "",
        "state": "OPEN", "labels": ["oc-queued", "oc-p4"], "createdAt": iso(EPOCH),
    }])
    routing = route_task(fake.rows[1])
    result = claim_workers(
        plan={"workers": [{"issue_number": 1, "dependencies": [], "reads": [],
                           "writes": ["control-plane"],
                           "lane_executable": routing.lane_executable,
                           "provider_free": routing.provider_free,
                           "acquisition": "firecrawl-acquisition" in
                           routing.blocking_provider_capabilities}]},
        snapshot=fake.snapshot(), repository=fake.repository,
        run_id=71, run_attempt=1, call=fake,
    )
    assert result["healthy"] and result["launch_count"] == 1, result
    comment_id = result["confirmed"][0]["lease_comment_id"]
    return fake, dict(repository=fake.repository, issue_number=1, run_id=71,
                      run_attempt=1, comment_id=comment_id)


@pytest.mark.parametrize("age_minutes,allowed", [(0, True), (15, True), (15.01, False),
                                                (89, False), (90, False), (-1, False)])
def test_admission_reserves_execution_and_settlement_budget(age_minutes, allowed):
    fake, identity = owned()
    created = fake.now()
    now = created + timedelta(minutes=age_minutes)
    if allowed:
        verified_issue(**identity, call=fake, now=now, min_remaining_seconds=4500)
    else:
        with pytest.raises(ValueError):
            verified_issue(**identity, call=fake, now=now, min_remaining_seconds=4500)
    assert len(fake.edits) == 1  # claim only, no denial cleanup
    assert len(fake.comments[1]) == 1


def test_settlement_uses_valid_ownership_not_a_new_75_minute_execution_budget():
    fake, identity = owned()
    result = settle_worker(
        **identity, result={"disposition": "done"}, call=fake,
        now=fake.now() + timedelta(minutes=89),
    )
    assert result["lease_comment_id"] == identity["comment_id"]
    assert "oc-done" in fake.labels(1)


@pytest.mark.parametrize("malformed", [False, True])
def test_superseding_claim_on_later_page_blocks_old_worker_and_all_writes(malformed):
    fake, identity = owned()
    moment = fake.now()
    for _ in range(105):
        fake._ticks = 1
        fake.comment(1, "unrelated authenticated progress")
    original = fake.comments[1][0]["body"]
    fake._ticks = 1
    later = fake.comment(1, original if not malformed else
                         "Dependency/resource lease claimed: `{\"schema\":[]}`")
    assert later["id"] > identity["comment_id"]
    before = (len(fake.edits), len(fake.comments[1]))
    with pytest.raises(ValueError, match="superseded|malformed"):
        verified_issue(**identity, call=fake, now=moment)
    with pytest.raises(ValueError, match="superseded|malformed"):
        settle_worker(**identity, result={"disposition": "done"}, call=fake, now=moment)
    assert (len(fake.edits), len(fake.comments[1])) == before


def test_expired_worker_cannot_settle_even_when_labels_still_say_running():
    fake, identity = owned()
    with pytest.raises(ValueError, match="expired"):
        settle_worker(**identity, result={"disposition": "done"}, call=fake,
                      now=fake.now() + timedelta(minutes=90))
    assert fake.labels(1) == {"oc-running", "oc-p4"}


def test_workflow_bounds_and_current_claim_calls_are_wired_in_real_lanes():
    root = Path(__file__).resolve().parents[1] / ".github/workflows"
    controller = yaml.safe_load((root / "orchid-swarm-controller.yml").read_text())
    completion = yaml.safe_load((root / "orchid-completion-lane.yml").read_text())
    free = controller["jobs"]["provider_free_workers"]
    paid = next(job for job in completion["jobs"].values()
                if job.get("env", {}).get("ISSUE_NUMBER"))
    assert free["timeout-minutes"] == paid["timeout-minutes"] == 70
    for job in (free, paid):
        terminal = next(x for x in job["steps"] if
                        x.get("id") == "settlement" or
                        x.get("name") == "Publish durable result and release lease")
        assert "scripts.oc_swarm_settlement" in terminal["run"]
        assert 'gh issue edit "$ISSUE_NUMBER"' not in terminal["run"]
        assert 'gh issue comment "$ISSUE_NUMBER"' not in terminal["run"]
    providers = [x for x in paid["steps"] if x.get("id") in {"claude", "gemini", "openai"}]
    assert len(providers) == 3
    assert all("--min-remaining-seconds 4500" in x["run"] for x in providers)


def test_recovery_reads_beyond_its_old_ten_page_cutoff_and_fails_closed_if_truncated():
    transport = GitHubTransport("owner/repo")
    pages = []

    def read(args):
        page = int(args[-1].split("page=")[-1])
        pages.append(page)
        return [{"id": page * 100 + n} for n in range(100)] if page <= 11 else []

    transport._run = read
    assert len(transport.comments(1)) == 1100 and pages[-1] == 12
    transport._run = lambda args: [{"id": n} for n in range(100)]
    with pytest.raises(ValueError, match="comment_history_incomplete"):
        transport.comments(1)
    transport._run = lambda args: {"message": "invalid response"}
    with pytest.raises(ValueError, match="comment_history_unconfirmed"):
        transport.comments(1)


def test_recovery_does_not_ignore_a_malformed_authenticated_claim():
    fake, _identity = owned()
    fake.comment(1, "[OC-SWARM-V4] Dependency/resource lease claimed: `[]`.")
    before = len(fake.edits)
    with pytest.raises(ValueError, match="malformed_authenticated_claim"):
        _latest_claim(fake.comments[1], repository=fake.repository, number=1)
    assert len(fake.edits) == before
