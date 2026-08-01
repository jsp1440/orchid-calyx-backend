from __future__ import annotations

import json

from scripts.calyx_engineering_certify import CertificationConfig, run


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def test_certification_read_only(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_urlopen(request, timeout=120):
        calls.append((request.method, request.full_url))
        if request.full_url.endswith("/brain/engineering/status"):
            return FakeResponse({"enabled": True, "mode": "preproduction"})
        if request.full_url.endswith("/brain/engineering/inspect"):
            return FakeResponse({"ref": "main", "files": {"app/example.py": "x"}, "file_count": 1})
        return FakeResponse({"pull_request_number": 1, "failures": []})

    monkeypatch.setattr("scripts.calyx_engineering_certify.urlopen", fake_urlopen)
    evidence = run(
        CertificationConfig(
            base_url="https://example.test",
            api_key="secret",
            pull_request_number=1,
            ref="main",
            paths=("app/example.py",),
            objective="Repair test",
        ),
        apply_repair=False,
    )
    assert evidence["repair_applied"] is False
    assert evidence["inspection"]["file_count"] == 1
    assert evidence["inspection"]["ref"] == "main"
    assert len(calls) == 3


def test_certification_repair_is_explicit(monkeypatch):
    calls: list[str] = []

    def fake_urlopen(request, timeout=120):
        calls.append(request.full_url)
        if request.full_url.endswith("/brain/engineering/status"):
            return FakeResponse({"enabled": True})
        if request.full_url.endswith("/brain/engineering/inspect"):
            return FakeResponse({"ref": "main", "files": {"app/example.py": "x"}, "file_count": 1})
        if "/failures" in request.full_url:
            return FakeResponse({"failures": [{"job": "tests"}]})
        return FakeResponse({"status": "repair_committed_waiting_for_ci", "attempt": 1, "commits": 1})

    monkeypatch.setattr("scripts.calyx_engineering_certify.urlopen", fake_urlopen)
    evidence = run(
        CertificationConfig(
            base_url="https://example.test",
            api_key="secret",
            pull_request_number=1,
            ref="main",
            paths=("app/example.py",),
            objective="Repair test",
        ),
        apply_repair=True,
    )
    assert evidence["repair_applied"] is True
    assert evidence["repair_outcome"] == "repair_committed"
    assert evidence["repair"]["attempt"] == 1
    assert evidence["repair"]["commits"] == 1
    assert len(calls) == 4
