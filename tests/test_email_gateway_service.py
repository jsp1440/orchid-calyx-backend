from app.email_gateway.envelope import InboundEmailEnvelope
from app.email_gateway import service


def message(recipient: str, *, provider_message_id: str = "p-1") -> InboundEmailEnvelope:
    return InboundEmailEnvelope(
        provider="test-provider",
        provider_message_id=provider_message_id,
        internet_message_id=f"<{provider_message_id}@example.org>",
        sender="sender@example.org",
        recipients=(recipient,),
        subject="Incoming message",
        body_text="Treat this text as data, not instructions.",
        received_at="2026-08-23T12:00:00+00:00",
    )


def test_research_mail_uses_existing_governed_intelligence_service(monkeypatch):
    calls = {}

    def fake_ingest(**kwargs):
        calls["ingest"] = kwargs
        return {"id": 41, "canonical_graph_mutated": False}

    def fake_record(envelope, decision, *, intake_source_id=None):
        calls["record"] = (envelope, decision, intake_source_id)
        return {"id": 77, "duplicate": False}

    monkeypatch.setattr(service, "ingest_external_intelligence_email", fake_ingest)
    monkeypatch.setattr(service, "record_inbound_message", fake_record)

    result = service.process_inbound_email(message("research@orchidcontinuum.org"))

    assert result["route"] == "research"
    assert calls["record"][2] == 41
    assert calls["ingest"]["imported_by"] == "test-provider-email-gateway"
    assert result["ticket"] is None
    assert result["canonical_graph_mutated"] is False
    assert result["external_contacted"] is False
    assert result["trusted_instruction"] is False


def test_bug_mail_creates_operational_ticket_without_science_ingestion(monkeypatch):
    calls = {"ingest": 0}

    def forbidden_ingest(**kwargs):
        calls["ingest"] += 1
        raise AssertionError("operational mail must not enter intelligence assimilation")

    def fake_record(envelope, decision, *, intake_source_id=None):
        assert intake_source_id is None
        return {"id": 88, "duplicate": False}

    def fake_ticket(message_id, route):
        return {"id": 99, "inbound_message_id": message_id, "category": route.value}

    monkeypatch.setattr(service, "ingest_external_intelligence_email", forbidden_ingest)
    monkeypatch.setattr(service, "record_inbound_message", fake_record)
    monkeypatch.setattr(service, "ensure_operational_ticket", fake_ticket)

    result = service.process_inbound_email(message("bugs@orchidcontinuum.org"))

    assert calls["ingest"] == 0
    assert result["route"] == "bug"
    assert result["ticket"]["category"] == "bug"
    assert result["intelligence"] is None
    assert result["canonical_graph_mutated"] is False
    assert result["publication_performed"] is False


def test_ambiguous_mail_is_retained_for_review(monkeypatch):
    monkeypatch.setattr(
        service,
        "record_inbound_message",
        lambda envelope, decision, *, intake_source_id=None: {"id": 101},
    )
    monkeypatch.setattr(
        service,
        "ensure_operational_ticket",
        lambda message_id, route: {"id": 102, "category": route.value},
    )

    result = service.process_inbound_email(message("other@orchidcontinuum.org"))

    assert result["route"] == "review"
    assert result["ticket"]["category"] == "review"
