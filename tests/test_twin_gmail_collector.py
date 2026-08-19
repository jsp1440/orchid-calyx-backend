from __future__ import annotations

import base64

import app.intake.gmail_collector as collector
from app.intake.gmail_collector import DEFAULT_QUERY, GoogleApiGmailGateway, parse_gmail_message


def _encode(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def sample_message(*, gmail_id: str = "g1", sender: str = "Twin <twin@twin-mail.com>", subject: str = "Orchid Continuum Daily Briefing — Thursday, August 13, 2026"):
    return {
        "id": gmail_id,
        "threadId": "t1",
        "payload": {
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "Message-ID", "value": f"<{gmail_id}@twin-mail.com>"},
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


def test_collection_filters_non_twin_mail_and_preserves_no_mutation_contract(monkeypatch):
    messages = {
        "good": sample_message(gmail_id="good"),
        "wrong": sample_message(gmail_id="wrong", sender="Other <other@example.org>"),
    }

    class Gateway:
        def search(self, query, limit):
            return list(messages)[:limit]
        def get(self, message_id):
            return messages[message_id]

    ingested = []

    def fake_ingest(**kwargs):
        ingested.append(kwargs)
        return {"id": 17, "intelligence": {"items_discovered": 1}}

    monkeypatch.setattr(collector, "ingest_external_intelligence_email", fake_ingest)
    result = collector.collect_twin_intelligence(Gateway(), limit=10)

    assert len(ingested) == 1
    assert ingested[0]["sender"] == "twin@twin-mail.com"
    assert result["messages_found"] == 2
    assert result["imported"][0]["source_id"] == 17
    assert result["skipped"] == [{"gmail_id": "wrong", "reason": "SENDER_MISMATCH"}]
    assert result["mailbox_mutated"] is False
    assert result["canonical_graph_mutated"] is False
    assert result["external_contacted"] is False
