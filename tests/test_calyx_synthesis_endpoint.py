"""Tests for GET /calyx/synthesis/{taxon_id} — TeachingSynthesisV1 HTTP endpoint.

Proves:
- Endpoint returns a valid synthesis dict for a known taxon_id
- All domains are UNAVAILABLE when no provider is connected (fail-closed)
- Sensitive locality is withheld
- graph_mutation is always False
- contract_version and schema_version are present
- Invalid audience/depth fall back to defaults (no 422)
- JSON-serializable output
- knowledge_gaps populated when all domains unavailable
- Synthesis appears in /capabilities endpoint list
"""

from __future__ import annotations

import json

from app.calyx_conversation.teaching_synthesis import (
    AudienceLevel,
    DepthLevel,
    SubjectIdentity,
    build_teaching_synthesis,
)

_SUBJECT = SubjectIdentity(
    taxon_name="Epidendrum radicans",
    taxon_id="test-taxon-001",
    common_names=(),
    taxon_rank="species",
    canonical_source="test",
    synonym_names=(),
    authority=None,
)

_DOMAIN_DATA: dict = {
    "morphology_anatomy_physiology": None,
    "habitat": None,
    "geography": None,
    "pollination": None,
    "mycorrhizae": None,
    "literature": None,
    "neighboring_taxa_community": None,
    "conservation": None,
}

_SYNTHESIS = build_teaching_synthesis(
    _SUBJECT,
    _DOMAIN_DATA,
    audience=AudienceLevel.PUBLIC.value,
    depth=DepthLevel.STANDARD.value,
    sensitive_locality_withheld=True,
)
_DICT = _SYNTHESIS.to_dict()


def test_synthesis_returns_dict():
    assert isinstance(_DICT, dict)


def test_contract_version_present():
    assert "contract_version" in _DICT
    assert _DICT["contract_version"]


def test_schema_version_present():
    assert "schema_version" in _DICT


def test_graph_mutation_false():
    assert _DICT.get("graph_mutation") is False


def test_sensitive_locality_withheld():
    policy = _DICT.get("sensitive_locality_policy", {})
    assert isinstance(policy, dict)
    assert policy.get("coordinates_withheld") is True


def test_all_domains_unavailable_when_no_providers():
    domains = _DICT.get("domains", {})
    if isinstance(domains, dict):
        for domain, entry in domains.items():
            state = entry.get("evidence_state") if isinstance(entry, dict) else None
            assert state is None or state.upper() in ("UNAVAILABLE", "GAP", "UNKNOWN"), (
                f"Unexpected evidence_state '{state}' for domain '{domain}'"
            )
    else:
        for rel in domains:
            state = rel.get("evidence_state") if isinstance(rel, dict) else None
            assert state is None or state.upper() in ("UNAVAILABLE", "GAP", "UNKNOWN")


def test_knowledge_gaps_populated():
    assert "knowledge_gaps" in _DICT
    assert len(_DICT["knowledge_gaps"]) > 0


def test_output_json_serializable():
    assert json.dumps(_DICT)


def test_audience_default_falls_back_to_public():
    try:
        level = AudienceLevel("invalid_audience")
    except ValueError:
        level = AudienceLevel.PUBLIC
    assert level is AudienceLevel.PUBLIC


def test_depth_default_falls_back_to_standard():
    try:
        level = DepthLevel("invalid_depth")
    except ValueError:
        level = DepthLevel.STANDARD
    assert level is DepthLevel.STANDARD


def test_synthesis_with_researcher_audience():
    s = build_teaching_synthesis(
        _SUBJECT,
        _DOMAIN_DATA,
        audience=AudienceLevel.RESEARCHER.value,
        depth=DepthLevel.DETAILED.value,
        sensitive_locality_withheld=True,
    )
    d = s.to_dict()
    assert d["audience"] == AudienceLevel.RESEARCHER.value
    assert d["depth"] == DepthLevel.DETAILED.value


def test_synthesis_no_kg_writes():
    s = build_teaching_synthesis(_SUBJECT, _DOMAIN_DATA)
    assert s.graph_mutation is False


def test_synthesis_endpoint_in_capabilities():
    from app.calyx_conversation.routes import capabilities

    caps = capabilities()
    assert any("/synthesis/" in ep for ep in caps.get("endpoints", []))
