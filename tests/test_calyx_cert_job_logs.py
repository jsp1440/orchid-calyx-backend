from __future__ import annotations

from email.message import Message
from urllib.error import HTTPError

from app.calyx_engineering.github import GitHubEngineeringClient


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return self.content


class RedirectingOpener:
    def open(self, request, timeout=30):
        headers = Message()
        headers["Location"] = "https://signed.example.test/job-log.txt"
        raise HTTPError(request.full_url, 302, "Found", headers, None)


def test_workflow_job_logs_follows_signed_redirect_without_auth(monkeypatch):
    client = GitHubEngineeringClient("owner/repo", token="token")
    redirected_requests = []

    monkeypatch.setattr(
        "app.calyx_engineering.github.build_opener",
        lambda *_handlers: RedirectingOpener(),
    )

    def fake_urlopen(request, timeout=30):
        redirected_requests.append(request)
        return FakeResponse(b"pytest failed\n")

    monkeypatch.setattr("app.calyx_engineering.github.urlopen", fake_urlopen)

    assert client.workflow_job_logs(123) == "pytest failed\n"
    assert redirected_requests[0].full_url == "https://signed.example.test/job-log.txt"
    assert redirected_requests[0].get_header("Authorization") is None
