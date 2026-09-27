"""External transports are fixtures; claim verification/settlement are production."""
from copy import deepcopy

import pytest

from scripts.oc_swarm_acquisition_worker import execute_claim
from scripts.oc_swarm_claim import claim_workers

REPO = "jsp1440/orchid-calyx-backend"


class GitHubTransport:
    def __init__(self):
        self.issue = {"number": 42, "title": "Acquire source", "body": "OC-CAPABILITIES: firecrawl-acquisition\nOC-SWARM-WRITES: literature", "state": "OPEN", "labels": ["oc-queued", "oc-p2"]}
        self.comments = {}

    def __call__(self, args, payload=None):
        if args[:2] == ["issue", "view"]:
            return deepcopy(self.issue)
        if args[:2] == ["issue", "edit"]:
            labels = set(self.issue["labels"])
            for index, arg in enumerate(args):
                if arg == "--remove-label":
                    labels.discard(args[index + 1])
                elif arg == "--add-label":
                    labels.add(args[index + 1])
            self.issue["labels"] = sorted(labels)
            return None
        if args[2] == "GET":
            return deepcopy(self.comments[int(args[3].split("/")[-1])])
        comment = {"id": len(self.comments) + 1, "body": payload["body"], "user": {"login": "github-actions[bot]"}, "issue_url": f"https://api.github.com/repos/{REPO}/issues/42"}
        self.comments[comment["id"]] = comment
        return deepcopy(comment)


def claimed():
    transport = GitHubTransport()
    # Capability syntax is the registered canonical work-packet declaration.
    transport.issue["body"] = "OC-SWARM-CAPABILITY: firecrawl-acquisition\nOC-SWARM-WRITES: literature"
    worker = {"issue_number": 42, "reads": [], "writes": ["literature"], "dependencies": [], "provider_free": False, "acquisition": True}
    result = claim_workers({"workers": [worker]}, {"issues": [deepcopy(transport.issue)]}, repository=REPO, run_id=123, call=transport)
    assert result["provider_matrix"] == {"include": []}
    assert result["acquisition_launch_count"] == 1
    return transport, {"repository": REPO, "issue_number": 42, "run_id": 123, "run_attempt": 1, "comment_id": 1}


def test_dispatch_settles_canonical_claim_and_signals_existing_refill():
    transport, identity = claimed()
    def dispatch(request):
        return {**request, "status": "review_pending", "published": False, "sources": [{"paper_id": "hash"}], "validation": {"status": "passed"}}
    receipt = execute_claim(**identity, dispatch=dispatch, call=transport)
    assert "oc-done" in transport.issue["labels"]
    assert "oc-running" not in transport.issue["labels"]
    assert receipt["replenishment_signal"] == "canonical-controller-refill"


def test_owner_gate_added_during_execution_prevents_settlement():
    transport, identity = claimed()
    def dispatch(request):
        transport.issue["labels"].append("oc-owner-gate")
        return {**request, "status": "review_pending", "published": False, "sources": [{}], "validation": {"status": "passed"}}
    with pytest.raises(ValueError, match="exclusive"):
        execute_claim(**identity, dispatch=dispatch, call=transport)
    assert "oc-done" not in transport.issue["labels"]


def test_unvalidated_response_cannot_complete():
    transport, identity = claimed()
    with pytest.raises(ValueError, match="incomplete"):
        execute_claim(**identity, dispatch=lambda _: {}, call=transport)
    assert "oc-running" in transport.issue["labels"]
