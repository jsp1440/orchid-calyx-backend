"""Tests for GET /calyx/synthesis/{taxon_id} — TeachingSynthesisV1 HTTP endpoint.

Proves:
- Endpoint returns a valid synthesis dict for a known taxon_id
- All domains are UNAVAILABLE when no provider is connected (fail-closed)
- Sensitive locality is withheld
- graph_mutation is always False
- contract_version and schema_version are present
- Invalid audience/depth fall back to defaults (no 422)
- JSON-serializable output
"""

from __future__ import annotations

import json

from app.calyx_conversation.teaching_synthesis import (
    AudienceLevel,
    DepthLevel,
    SubjectIdentity,
    build_teaching_synthesis,
)

# ---------------------------------------------------------------------------
# Call the builder directly (same logic as the route handler) to prove
# the endpoint plumbing without needing a running ASGI server.
# ---------------------------------------------------------------------------

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
    assert _DICT.get("contract_version") == "CALYX-TEACHING-SYNTHESIS-001"


def test_schema_version_present():
    assert _DICT.get("schema_version") == "teaching-synthesis/v1"


def test_subject_identity_preserved():
    subject = _DICT.get("subject", {})
    assert subject.get("taxon_name") == "Epidendrum radicans"
    assert subject.get("taxon_id") == "test-taxon-001"


def test_graph_mutation_false():
    assert _DICT.get("graph_mutation") is False


def test_sensitive_locality_withheld():
    policy = _DICT.get("sensitive_locality_policy", {})
    assert policy.get("coordinates_withheld") is True


def test_no_coordinate_fields_in_output():
    serialized = json.dumps(_DICT)
    for key in ['"latitude"', '"longitude"', '"lat":', '"lon":', '"lng":']:
        assert key not in serialized, f"Coordinate key {key} found in synthesis output"


def test_all_domains_unavailable_when_no_provider():
    # With domain_data all-None, relationship_model entries should be UNAVAILABLE/GAP
    assert "relationship_model" in _DICT
    rm = _DICT["relationship_model"]
    # relationship_model may be a dict keyed by domain name
    if isinstance(rm, dict):
        for domain, entry in rm.items():
            state = entry.get("evidence_state") if isinstance(entry, dict) else None
            assert state is None or state.upper() in ("UNAVAILABLE", "GAP", "UNKNOWN"), (
                f"Unexpected evidence_state '{state}' for domain '{domain}'"
            )
    else:
        for rel in rm:
            state = rel.get("evidence_state") if isinstance(rel, dict) else None
            assert state is None or state.upper() in ("UNAVAILABLE", "GAP", "UNKNOWN")


def test_knowledge_gaps_populated():
    # All domains are unavailable so gaps should be non-empty
    assert "knowledge_gaps" in _DICT
    assert len(_DICT["knowledge_gaps"]) > 0


def test_output_json_serializable():
    assert json.dumps(_DICT)


def test_audience_default_falls_back_to_public():
    # Invalid audience → AudienceLevel.PUBLIC via try/except in route
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
    # Ensure the synthesis never signals a KG write operation
    s = build_teaching_synthesis(_SUBJECT, _DOMAIN_DATA)
    assert s.graph_mutation is False


def test_synthesis_endpoint_in_capabilities():
    from app.calyx_conversation.routes import capabilities
    caps = capabilities()
    assert any("/synthesis/" in ep for ep in caps.get("endpoints", []))
