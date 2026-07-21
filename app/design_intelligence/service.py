from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

from .classifier import DOMAIN_TERMS, classify
from .models import (
    DesignDocument,
    DesignDocumentInput,
    DesignDomain,
    DesignKnowledgeType,
    DesignReviewDecision,
    PublicationStatus,
    utcnow,
)


@dataclass(frozen=True)
class DesignSearchQuery:
    text: str
    domains: tuple[DesignDomain, ...] = ()
    knowledge_types: tuple[DesignKnowledgeType, ...] = ()
    topics: tuple[str, ...] = ()
    limit: int = 10
    offset: int = 0

    def __post_init__(self) -> None:
        normalized = " ".join(self.text.split())
        if not normalized or len(normalized) > 500:
            raise ValueError("INVALID_DESIGN_QUERY")
        if not 1 <= self.limit <= 100 or not 0 <= self.offset <= 10_000:
            raise ValueError("INVALID_DESIGN_RETRIEVAL_LIMIT")
        object.__setattr__(self, "text", normalized)


class DesignIntelligenceService:
    CLASSIFIER_VERSION = "089a-design-rules-1"

    def __init__(self, repository) -> None:
        self.repository = repository

    def import_document(self, value: DesignDocumentInput) -> DesignDocument:
        actual_hash = hashlib.sha256(value.content.encode()).hexdigest()
        if actual_hash != value.provenance.content_hash:
            raise ValueError("DESIGN_CONTENT_PROVENANCE_MISMATCH")
        domains, knowledge_types, confidence, evidence = classify(
            f"{value.title} {value.content} {' '.join(value.topics)}",
            value.requested_domains,
            value.requested_types,
        )
        previous = self.repository.latest(value.logical_key)
        document = DesignDocument(
            document_id=1 + max(
                (item.document_id for item in self.repository.documents), default=0
            ),
            logical_key=value.logical_key,
            version=1 if previous is None else previous.version + 1,
            title=value.title,
            content=value.content,
            document_type=value.document_type,
            authors=value.authors,
            publication_date=value.publication_date,
            license_metadata=dict(value.license_metadata),
            provenance=value.provenance,
            domains=domains,
            knowledge_types=knowledge_types,
            topics=tuple(sorted(set(value.topics))),
            classification_confidence=confidence,
            classification_version=self.CLASSIFIER_VERSION,
            source_metadata={**value.source_metadata, "classification_evidence": evidence},
            created_at=utcnow(),
        )
        return self.repository.append_document(document)

    def review(self, document_id: int, decision: DesignReviewDecision):
        return self.repository.add_review(document_id, decision)

    def publish(self, document_id: int, actor: str, rationale: str):
        return self.repository.publish(
            document_id, PublicationStatus.PUBLISHED, actor, rationale
        )

    def search(self, query: DesignSearchQuery) -> dict:
        terms = self._expanded_terms(query.text)
        candidates = []
        for document in self.repository.published_latest():
            if query.domains and not set(query.domains).intersection(document.domains):
                continue
            if query.knowledge_types and not set(query.knowledge_types).intersection(
                document.knowledge_types
            ):
                continue
            if query.topics and not set(map(str.casefold, query.topics)).intersection(
                map(str.casefold, document.topics)
            ):
                continue
            haystack = " ".join(
                (document.title, document.content, " ".join(document.topics))
            ).casefold()
            matched = tuple(sorted(term for term in terms if term in haystack))
            if not matched:
                continue
            lexical = sum(haystack.count(term) for term in matched) / max(1, len(terms))
            score = min(
                1.0,
                0.55 * lexical + 0.45 * document.classification_confidence,
            )
            candidates.append((score, document, matched))
        candidates.sort(key=lambda item: (-item[0], item[1].logical_key, -item[1].version))
        results = [
            self._result(score, document, matched)
            for score, document, matched in candidates
        ]
        return {
            "query": query.text,
            "total": len(results),
            "results": results[query.offset : query.offset + query.limit],
            "classification_version": self.CLASSIFIER_VERSION,
            "published_only": True,
        }

    @staticmethod
    def _expanded_terms(text: str) -> tuple[str, ...]:
        normalized = text.casefold()
        terms = set(re.findall(r"[a-z0-9-]+", normalized))
        for domain, aliases in DOMAIN_TERMS.items():
            if any(alias in normalized for alias in aliases) or domain.value.casefold().replace("_", " ") in normalized:
                terms.update(aliases)
        if "mayer" in normalized:
            terms.update(("mayer", "multimedia learning"))
        return tuple(sorted(term for term in terms if len(term) > 2))

    def _result(self, score, document, matched) -> dict:
        return {
            "document_id": document.document_id,
            "logical_key": document.logical_key,
            "version": document.version,
            "title": document.title,
            "document_type": document.document_type,
            "domains": [item.value for item in document.domains],
            "knowledge_types": [item.value for item in document.knowledge_types],
            "topics": list(document.topics),
            "confidence": document.classification_confidence,
            "retrieval_score": round(score, 6),
            "matched_terms": list(matched),
            "authors": list(document.authors),
            "publication_date": (
                document.publication_date.isoformat() if document.publication_date else None
            ),
            "license_metadata": dict(document.license_metadata),
            "publication_status": self.repository.publication_status(
                document.document_id
            ).value,
            "review_state": self.repository.review_state(document.document_id).value,
            "provenance": asdict(document.provenance),
            "source_metadata": dict(document.source_metadata),
        }
