from __future__ import annotations

from dataclasses import dataclass

from app.calyx_orchestrator.github_proposal_mutation_adapter import GitHubTransportResponse
from app.calyx_orchestrator.github_repository_inspector import GitHubRepositoryConvergenceInspector


@dataclass
class Transport:
    responses: list[GitHubTransportResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, *, json_body=None, params=None):
        del json_body, params
        self.calls.append((method, path))
        return self.responses.pop(0)


def inspector(transport: Transport) -> GitHubRepositoryConvergenceInspector:
    return GitHubRepositoryConvergenceInspector(
        transport=transport,
        repository_allowlist=("jsp1440/orchid-calyx-backend",),
    )


def test_exact_mission_match_continues_one_existing_pr() -> None:
    transport = Transport(
        [
            GitHubTransportResponse(200, {"object": {"sha": "a" * 40}}),
            GitHubTransportResponse(
                200,
                [
                    {"number": 975, "title": "MISSION-1 — implementation", "body": "work"},
                    {"number": 976, "title": "Unrelated cleanup", "body": "nothing"},
                ],
            ),
            GitHubTransportResponse(200, [{"number": 973, "title": "MISSION-1", "body": "task"}]),
        ]
    )
    snapshot = inspector(transport).inspect(
        repository="jsp1440/orchid-calyx-backend",
        objective="Implement provider neutral GitHub agent dispatch",
        mission_id="MISSION-1",
    )
    assert snapshot.base_sha == "a" * 40
    assert snapshot.continuation_pr_numbers == (975,)
    assert snapshot.convergence_pr_numbers == ()
    assert snapshot.related_issue_numbers == (973,)


def test_two_exact_mission_prs_require_convergence() -> None:
    transport = Transport(
        [
            GitHubTransportResponse(200, {"object": {"sha": "b" * 40}}),
            GitHubTransportResponse(
                200,
                [
                    {"number": 10, "title": "MISSION-X attempt", "body": ""},
                    {"number": 11, "title": "another", "body": "MISSION-X replacement"},
                ],
            ),
            GitHubTransportResponse(200, []),
        ]
    )
    snapshot = inspector(transport).inspect(
        repository="jsp1440/orchid-calyx-backend",
        objective="Implement convergence guard",
        mission_id="MISSION-X",
    )
    assert snapshot.continuation_pr_numbers == ()
    assert snapshot.convergence_pr_numbers == (10, 11)


def test_objective_overlap_is_evidence_not_forced_convergence() -> None:
    transport = Transport(
        [
            GitHubTransportResponse(200, {"object": {"sha": "c" * 40}}),
            GitHubTransportResponse(
                200,
                [
                    {
                        "number": 20,
                        "title": "Provider neutral GitHub dispatch cleanup",
                        "body": "agent dispatch adapter",
                    }
                ],
            ),
            GitHubTransportResponse(200, []),
        ]
    )
    snapshot = inspector(transport).inspect(
        repository="jsp1440/orchid-calyx-backend",
        objective="Implement provider neutral GitHub agent dispatch",
        mission_id="MISSION-Y",
    )
    assert snapshot.overlapping_pr_numbers == (20,)
    assert snapshot.continuation_pr_numbers == ()
    assert snapshot.convergence_pr_numbers == ()
    assert snapshot.implementation_complete is False
