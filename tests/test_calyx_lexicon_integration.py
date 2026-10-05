from app.lexicon.routes import _definition_map, _entry_payload, lexicon_capabilities


def test_definition_priority_and_famous_shape():
    concept = {
        "concept_id": "11111111-1111-1111-1111-111111111111",
        "concept_uri": "https://id.orchidcontinuum.org/concept/11111111-1111-1111-1111-111111111111",
        "status": "ACTIVE",
        "review_state": "APPROVED",
        "created_at": None,
        "revised_at": None,
    }
    labels = [
        {"label_type": "PREFERRED", "label": "Resupination"},
        {"label_type": "ALTERNATE", "label": "floral resupination"},
    ]
    definitions = [
        {
            "definition_id": "d1",
            "definition_type": "GLOSSARY",
            "text": "Rotation of the developing orchid flower or ovary resulting in a changed final orientation.",
            "review_state": "APPROVED",
            "provenance": {"citation": "test source"},
            "created_at": None,
            "revised_at": None,
        },
        {
            "definition_id": "d2",
            "definition_type": "NORMATIVE_SCIENTIFIC",
            "text": "A developmental reorientation process whose exact mechanism and degree vary among orchid lineages.",
            "review_state": "APPROVED",
            "provenance": {},
            "created_at": None,
            "revised_at": None,
        },
    ]

    assert _definition_map(definitions)["GLOSSARY"].startswith("Rotation")
    entry = _entry_payload(concept, labels, definitions)
    assert entry["slug"] == "resupination"
    assert entry["preferred_term"] == "Resupination"
    assert entry["quick_definition"].startswith("Rotation")
    assert entry["expanded_definition"].startswith("A developmental")
    assert entry["synonyms"] == ["floral resupination"]
    assert "core_definition" in entry["maturity"]
    assert "scientifically_enriched" in entry["maturity"]
    assert "expert_reviewed" in entry["maturity"]
    assert entry["source_system"] == "oc_concepts"


def test_definition_version_exposes_source_provided_citation_and_evidence_identity():
    concept = {
        "concept_id": "11111111-1111-1111-1111-111111111111",
        "status": "ACTIVE",
        "review_state": "APPROVED",
    }
    definitions = [
        {
            "definition_id": "d1",
            "definition_type": "GLOSSARY",
            "text": "A source-grounded definition.",
            "review_state": "APPROVED",
            "provenance": {
                "citation": "Example orchid study",
                "identifiers": [
                    {"scheme": "doi", "value": "10.1234/example"},
                    {"scheme": "pmid", "value": "12345678"},
                    {"scheme": "uri", "value": "https://example.org/private"},
                    {"scheme": "other", "value": "local-id"},
                ],
                "evidence_id": "evidence-1",
                "source_hash": "a" * 64,
                "excerpt_hash": "b" * 64,
                "confidence": 0.72,
                "uncertainty": "Interpretation remains provisional.",
                "storage_uri": "file:///private/source.pdf",
            },
        }
    ]

    entry = _entry_payload(concept, [], definitions)

    assert entry["definition_versions"][0]["sources"] == ["Example orchid study"]
    assert entry["definition_versions"][0]["citation_identity"] == {
        "identifiers": [
            {"scheme": "doi", "value": "10.1234/example"},
            {"scheme": "pmid", "value": "12345678"},
        ],
        "evidence_id": "evidence-1",
        "source_hash": "a" * 64,
        "excerpt_hash": "b" * 64,
        "confidence": 0.72,
        "uncertainty": "Interpretation remains provisional.",
    }


def test_definition_version_does_not_synthesize_missing_citation_identity():
    concept = {
        "concept_id": "11111111-1111-1111-1111-111111111111",
        "status": "ACTIVE",
        "review_state": "APPROVED",
    }
    definitions = [
        {
            "definition_id": "d1",
            "definition_type": "GLOSSARY",
            "text": "A definition with display-only provenance.",
            "review_state": "APPROVED",
            "provenance": {"citation": "Unresolved source"},
        }
    ]

    entry = _entry_payload(concept, [], definitions)

    assert entry["definition_versions"][0]["sources"] == ["Unresolved source"]
    assert entry["definition_versions"][0]["citation_identity"] is None


def test_capabilities_preserve_governance_boundaries():
    result = lexicon_capabilities()
    assert result["source_ui"] == "Famous AI Illustrated Orchid Lexicon"
    assert result["canonical_concept_registry"] == "/api/concepts"
    assert result["vision_lexicon"] == "/api/vision-lexicon"
    assert result["calyx_conversation"] == "/api/calyx/speak/conversations"
    assert result["governance"]["invented_enrichment_prohibited"] is True
    assert result["governance"]["automatic_concept_promotion"] is False
    assert result["governance"]["automatic_publication"] is False
