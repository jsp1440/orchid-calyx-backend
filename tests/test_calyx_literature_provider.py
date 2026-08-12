from app.calyx_conversation.provider import DeterministicGovernedReplyProvider


def test_provider_distinguishes_graph_publication_and_literal_document_match():
    lines = DeterministicGovernedReplyProvider._format_graph_literature(
        {
            "status": "available",
            "explicit_taxa": ["Laelia anceps"],
            "results": [
                {
                    "kg_node_id": 12,
                    "source_pk": "p12",
                    "title": "Persisted paper",
                    "associated_taxa": ["Laelia anceps"],
                    "provenance": {"persisted_graph_edge": True},
                },
                {
                    "kg_node_id": None,
                    "source_pk": "77",
                    "title": "Corpus paper",
                    "associated_taxa": ["Laelia anceps"],
                    "provenance": {
                        "persisted_graph_edge": False,
                        "scientific_claim_inferred": False,
                    },
                },
            ],
        }
    )
    text = "\n".join(lines)
    assert "Persisted Knowledge Graph literature matches: 1" in text
    assert "Additional research-document corpus matches: 1" in text
    assert "graph publication" in text
    assert "literal document match" in text
    assert "discovery metadata only" in text
