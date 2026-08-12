from app.calyx_conversation.provider import DeterministicGovernedReplyProvider


def test_provider_distinguishes_graph_corpus_and_reviewed_evidence():
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
                    "reviewed_evidence": [],
                    "provenance": {"persisted_graph_edge": True},
                },
                {
                    "kg_node_id": None,
                    "source_pk": "77",
                    "title": "Corpus paper",
                    "associated_taxa": ["Laelia anceps"],
                    "reviewed_evidence": [
                        {
                            "normalized_statement": "Laelia anceps was observed with a documented pollination interaction.",
                            "domain": "ecological_interaction",
                            "polarity": "positive",
                            "review_status": "accepted",
                            "normalization_confidence": 0.92,
                        }
                    ],
                    "provenance": {
                        "persisted_graph_edge": False,
                        "scientific_claim_inferred": False,
                        "publication_eligible_evidence": True,
                    },
                },
            ],
        }
    )
    text = "\n".join(lines)
    assert "Persisted Knowledge Graph literature matches: 1" in text
    assert "Additional research-document corpus matches: 1" in text
    assert "Integrity-verified publication-eligible normalized evidence records" in text
    assert "Publication-eligible normalized evidence" in text
    assert "review=accepted" in text
    assert "normalization-confidence=0.92" in text
    assert "graph publication" in text
    assert "literal document match" in text
    assert "discovery metadata only" in text
