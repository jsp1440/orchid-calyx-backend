from app.calyx_engineering.completion_loop import CompletionState, GovernedAutonomousCompletionLoop


class WorkflowAwareClient:
    def pull_request(self, number: int) -> dict:
        return {
            "number": number,
            "state": "open",
            "draft": True,
            "head": {"ref": "calyx/certification-agent-007", "sha": "abc123"},
        }

    def check_runs_for_head(self, head_sha: str) -> list[dict]:
        assert head_sha == "abc123"
        return [
            {
                "name": "publication-pipeline-operational-readiness",
                "status": "completed",
                "conclusion": "failure",
            }
        ]

    def workflow_runs_for_head(self, head_sha: str) -> list[dict]:
        assert head_sha == "abc123"
        return [
            {
                "name": "BUILD-088E Validation",
                "status": "completed",
                "conclusion": "failure",
            }
        ]


class StubRepairResult:
    status = "repair_committed_waiting_for_ci"
    commits = 1


class StubRepairLoop:
    def repair_once(self, **kwargs):
        assert kwargs["pull_request_number"] == 1043
        assert kwargs["attempt"] == 1
        return StubRepairResult()


def test_required_roster_accepts_workflow_name_and_advances_to_repair():
    client = WorkflowAwareClient()
    loop = GovernedAutonomousCompletionLoop(
        client,
        repair_factory=lambda client: StubRepairLoop(),
    )

    receipt = loop.advance(
        pull_request_number=1043,
        repair_paths=["tests/test_build_088e_publication_operational_readiness.py"],
        objective="Repair the intentional AGENT-007 certification failure.",
        attempt=1,
        repairs_authorized=True,
        required_checks=["BUILD-088E Validation"],
    )

    assert receipt.state == CompletionState.REPAIR_COMMITTED
    assert receipt.failed_workflows == ("BUILD-088E Validation",)
    assert receipt.required_checks_known is True
    assert receipt.commits == 1
