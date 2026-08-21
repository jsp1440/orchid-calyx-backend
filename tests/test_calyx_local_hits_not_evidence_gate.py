from __future__ import annotations

from app.calyx_conversation import external_literature


def test_unverified_local_hits_do_not_suppress_targeted_external_literature(monkeypatch):
    """Retrieval volume is not the same thing as usable governed evidence.

    The live Phalaenopsis trial on 2026-08-21 returned hundreds of eligible
    local search hits, but the governed mission ended BLOCKED with zero
    supporting evidence and zero citations. Those local rows were mostly
    unverified literature matches with no canonical parent, so they must not
    suppress the targeted external-literature fallback merely because the
    retrieval list is non-empty.
    """

    calls: list[str] = []

    def _search(query: str, *, limit: int = 8):
        calls.append(query)
        return {
            "provider": "Europe PMC",
            "query": query,
            "query_plan": [query],
            "results": [
                {
                    "title": "Phalaenopsis thermal physiology study",
                    "abstract": "Species-level temperature response evidence.",
                    "doi": "10.1000/phalaenopsis-thermal",
                    "external": True,
                    "review_state": "REVIEW_REQUIRED",
                    "canonical_evidence": False,
                }
            ],
            "result_count": 1,
            "candidate_count": 1,
            "diagnostics": [],
            "external": True,
            "review_required": True,
            "automatic_publication": False,
            "knowledge_graph_mutation": False,
        }

    monkeypatch.setattr(external_literature, "search_europe_pmc", _search)
    monkeypatch.setattr(
        "app.calyx_conversation.literature_ingest.ingest_external_literature_for_research",
        lambda records, *, query: {
            "status": "accepted_for_review",
            "record_count": len(records),
            "query": query,
        },
    )

    local_hits = [
        {
            "title": "Generic plant physiology result",
            "object_type": "LITERATURE_RECORD",
            "verification_state": "UNVERIFIED",
            "review_state": "CLEAR",
            "canonical_parent": {"available": False, "id": None},
            "authorized_excerpt": "Generic physiology text not specific to Phalaenopsis.",
        }
        for _ in range(20)
    ]

    result = external_literature.augment_retrieval_with_external_literature(
        {
            "results": local_hits,
            "total_eligible_results": 467,
            "retrieval_mode": "HYBRID",
            "status": "available",
        },
        (
            "Which morphological, anatomical, physiological and life-history traits "
            "distinguish cool-growing Phalaenopsis species from warm-growing ones?"
        ),
        limit=5,
    )

    assert calls, "non-empty retrieval must not by itself count as sufficient evidence"
    assert result["external_literature"]["status"] == "available"
    assert result["external_literature"]["result_count"] == 1
    assert result["external_literature"]["results"][0]["canonical_evidence"] is False
    assert result["external_literature"]["results"][0]["review_state"] == "REVIEW_REQUIRED"
