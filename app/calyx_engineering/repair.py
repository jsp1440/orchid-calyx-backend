from __future__ import annotations

from dataclasses import dataclass

from .github import GitHubEngineeringClient


@dataclass(frozen=True)
class FailedCheck:
    run_id: int
    job_id: int
    workflow: str
    job: str
    log_excerpt: str

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "job_id": self.job_id,
            "workflow": self.workflow,
            "job": self.job,
            "log_excerpt": self.log_excerpt,
        }


class BoundedCIInspector:
    def __init__(self, client: GitHubEngineeringClient) -> None:
        self.client = client

    def failed_checks(self, pull_request_number: int, *, limit: int = 5) -> list[FailedCheck]:
        if limit < 1 or limit > 10:
            raise ValueError("CI_FAILURE_LIMIT_INVALID")
        pull_request = self.client.pull_request(pull_request_number)
        head_sha = str(pull_request["head"]["sha"])
        failures: list[FailedCheck] = []
        for run in self.client.workflow_runs_for_head(head_sha):
            if run.get("status") != "completed" or run.get("conclusion") == "success":
                continue
            for job in self.client.workflow_jobs(int(run["id"])):
                if job.get("conclusion") == "success":
                    continue
                failures.append(
                    FailedCheck(
                        run_id=int(run["id"]),
                        job_id=int(job["id"]),
                        workflow=str(run.get("name") or "workflow"),
                        job=str(job.get("name") or "job"),
                        log_excerpt=self.client.workflow_job_logs(int(job["id"])),
                    )
                )
                if len(failures) >= limit:
                    return failures
        return failures
