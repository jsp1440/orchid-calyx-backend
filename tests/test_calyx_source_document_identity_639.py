from __future__ import annotations

from app.conversation_memory.report import build_conversation_markdown
from app.conversation_memory.service import ConversationMemoryService
from app.evidence_retrieval.engine import RetrievalEngine
from app.evidence_retrieval.models import RetrievalQuery


class FixtureProvider:
    def __init__(self):
        self.metadata = {"provider": "fixture"}

    def embed_batch(self, values):
        return [[1.0, 0.0] for _ in values]


class FixtureRepo:
    def __init__(self):
        self.documents = [
            {
                "index_document_id": "index-source",
                "source_object_type": "CLAIM",
                "revision_id": "revision-source",
                "parent_id": "claim-source",
                "active": True,
                "content_hash": "hash-source",
                "anchors": [],
                "metadata": {
                    "source_document_id": "document-source",
                    "document_title": "Source paper",
                    "display_policy": "FULL_TEXT_ALLOWED",
                    "identifier": "doi:source",
                    "locator": "p. 4",
                },
            }
        ]
        self.lexical = [
            {
                "index_document_id": "index-source",
                "normalized_text": "pollination evidence from the source paper",
                "title": "Source paper",
            }
        ]
        self.vectors = [
            {"index_document_id": "index-source", "vector": [1.0, 0.0], "active": True}
        ]


def test_retrieval_preserves_exact_source_document_identity_in_citation():
    result = RetrievalEngine(FixtureRepo(), FixtureProvider()).search(
        RetrievalQuery(text="pollination", mode="HYBRID", internal_access=True)
    )

    citation = result["results"][0]["citation"]
    assert citation["document_id"] == "document-source"
    assert citation["revision_id"] == "revision-source"
    assert citation["identifier"] == "doi:source"


def test_conversation_source_ref_preserves_document_and_revision_identity():
    source_ref = ConversationMemoryService._source_ref(
        {
            "result_id": "result-source",
            "object_type": "CLAIM",
            "title": "Source paper",
            "citation": {
                "document_id": "document-source",
                "revision_id": "revision-source",
                "identifier": "doi:source",
                "locator": "p. 4",
                "document_title": "Source paper",
            },
        }
    )

    assert source_ref["citation"]["document_id"] == "document-source"
    assert source_ref["citation"]["revision_id"] == "revision-source"


def test_conversation_report_exposes_source_document_identity_without_authority_upgrade():
    report = build_conversation_markdown(
        {
            "conversation_id": "conversation-source",
            "title": "Source continuity",
            "messages": [
                {
                    "role": "CALYX",
                    "content": "A retrieval-grounded answer.",
                    "data_status": "CONVERSATION_CONTEXT",
                    "source_refs": [
                        {
                            "result_id": "result-source",
                            "object_type": "CLAIM",
                            "title": "Source paper",
                            "citation": {
                                "document_id": "document-source",
                                "revision_id": "revision-source",
                                "identifier": "doi:source",
                                "locator": "p. 4",
                                "document_title": "Source paper",
                            },
                        }
                    ],
                }
            ],
        }
    )

    assert "Document ID: `document-source`" in report
    assert "Revision: `revision-source`" in report
    assert "not scientific evidence" in report
    assert "Scientific publication authorized: `false`" in report
    assert "Knowledge Graph mutation authorized: `false`" in report
