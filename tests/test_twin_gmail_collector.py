from __future__ import annotations

import base64

from app.intake.gmail_collector import DEFAULT_QUERY, GoogleApiGmailGateway, parse_gmail_message


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def sample_message():
    return {
        "id": "g1",
        "threadId": "t1",
        "payload": {
            "headers": [
                {"name": "From", "value": "Twin <twin@twin-mail.com>"},
                {"name": "Subject", "value": "Orchid Continuum Daily Briefing — Thursday, August 13, 2026"},
                {"name": "Message-ID", "value": "<g1@twin-mail.com>"},
                {"name": "Date", "value": "Thu, 13 Aug 2026 00:04:00 -0700"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _encode("Research and Publications\nExample High Priority\nEvidence")},
        },
    }


def test_parse_gmail_message_preserves_sender_subject_and_message_identity():
    parsed = parse_gmail_message(sample_message())
    assert parsed.gmail_id == "g1"
    assert parsed.sender == "twin@twin-mail.com"
    assert parsed.subject.startswith("Orchid Continuum Daily Briefing")
    assert parsed.message_id == "<g1@twin-mail.com>"
    assert parsed.received_at == "2026-08-13T00:04:00-07:00"
    assert "Research and Publications" in parsed.body


def test_default_query_is_narrowly_scoped_to_twin_briefings():
    assert "from:twin@twin-mail.com" in DEFAULT_QUERY
    assert "Orchid Continuum Daily Briefing" in DEFAULT_QUERY


def test_google_gateway_uses_only_message_list_and_get():
    calls = []

    class Request:
        def __init__(self, value):
            self.value = value
        def execute(self):
            return self.value

    class Messages:
        def list(self, **kwargs):
            calls.append(("list", kwargs))
            return Request({"messages": [{"id": "g1"}]})
        def get(self, **kwargs):
            calls.append(("get", kwargs))
            return Request(sample_message())

    class Users:
        def messages(self):
            return Messages()

    class Service:
        def users(self):
            return Users()

    gateway = GoogleApiGmailGateway(Service())
    assert gateway.search(DEFAULT_QUERY, 5) == ["g1"]
    assert gateway.get("g1")["id"] == "g1"
    assert [name for name, _ in calls] == ["list", "get"]
