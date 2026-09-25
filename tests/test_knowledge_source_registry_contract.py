from __future__ import annotations

import pytest

from app.calyx_orchestrator.knowledge_source_registry import (
    AccessPolicy,
    ConnectorPolicy,
    KnowledgeSource,
    KnowledgeSourceRegistry,
    SourceKind,
    SourceState,
    TrustClass,
    prepare_connector_request,
    stable_idempotency_key,
)


def source(**overrides):
    data = {
        "source_id": "lit:orchid-paper-1",
        "kind": SourceKind.LITERATURE,
        "trust_class": TrustClass.REVIEWED,
        "license": "CC-BY-4.0",
        "scope": "orchid physiology",
        "access_policy": AccessPolicy.PUBLIC,
        "state": SourceState.AVAILABLE,
        "snippets": ({"text": "bounded excerpt", "anchor": "p3", "hash": "sha256:abc"},),
        "metadata": {"token": "must-not-leak", "doi": "10.1/example"},
    }
    data.update(overrides)
    return KnowledgeSource(**data)


def test_registration_is_idempotent_but_policy_changes_need_explicit_lineage():
    registry = KnowledgeSourceRegistry()
    item = source()
    registry.register(item)
    registry.register(item)
    assert len(registry.sources) == 1

    with pytest.raises(ValueError):
        registry.register(source(license="ARR"))


def test_private_internal_sources_never_leak_to_public_view():
    registry = KnowledgeSourceRegistry()
    registry.register(source())
    registry.register(
        source(
            source_id="internal:note-1",
            kind=SourceKind.INTERNAL_NOTE,
            trust_class=TrustClass.INTERNAL,
            access_policy=AccessPolicy.INTERNAL,
            license="internal",
        )
    )

    public = registry.public_view()
    assert [item["source_id"] for item in public] == ["lit:orchid-paper-1"]
    assert "token" not in public[0]["metadata"]


def test_states_remain_explicit_not_fabricated_as_empty_success():
    registry = KnowledgeSourceRegistry()
    registry.register(source(source_id="stale", state=SourceState.STALE))
    registry.register(source(source_id="unavailable", state=SourceState.UNAVAILABLE))
    registry.register(source(source_id="contradictory", state=SourceState.CONTRADICTORY))
    registry.register(source(source_id="limited", state=SourceState.RATE_LIMITED))

    states = {item["source_id"]: item["state"] for item in registry.query(audience=AccessPolicy.PUBLIC)}
    assert states == {
        "contradictory": "contradictory",
        "limited": "rate_limited",
        "stale": "stale",
        "unavailable": "unavailable",
    }


def test_untrusted_content_cannot_grant_write_capability():
    with pytest.raises(ValueError):
        source(
            source_id="malicious",
            trust_class=TrustClass.UNTRUSTED_EXTERNAL,
            allowed_actions=("retrieve", "write:graph"),
        )

    with pytest.raises(ValueError):
        ConnectorPolicy(connector_id="x", allowlisted_actions=("retrieve", "write:graph"))

    with pytest.raises(ValueError):
        ConnectorPolicy(connector_id="x", writes_enabled=True)


def test_connector_request_is_bounded_redacted_and_idempotent():
    item = source(allowed_actions=("retrieve",))
    policy = ConnectorPolicy(connector_id="literature", allowlisted_actions=("retrieve",))
    first = prepare_connector_request(
        source=item,
        policy=policy,
        action="retrieve",
        subject="Phragmipedium kovachii",
        payload={"query": "kovachii", "api_key": "secret", "coordinates": [-1, -1]},
    )
    second_key = stable_idempotency_key(item.source_id, "retrieve", "Phragmipedium kovachii")

    assert first.idempotency_key == second_key
    assert first.redacted_payload == {"query": "kovachii"}


def test_unavailable_and_rate_limited_sources_refuse_retrieval():
    policy = ConnectorPolicy(connector_id="literature")
    for state in (SourceState.UNAVAILABLE, SourceState.RATE_LIMITED, SourceState.BLOCKED):
        with pytest.raises(RuntimeError):
            prepare_connector_request(
                source=source(state=state),
                policy=policy,
                action="retrieve",
                subject="test",
            )


def test_non_allowlisted_action_fails_closed():
    with pytest.raises(PermissionError):
        prepare_connector_request(
            source=source(),
            policy=ConnectorPolicy(connector_id="literature"),
            action="delete",
            subject="test",
        )
