from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from .acquisition import SUPPORTED_FORMATS, AcquisitionMetadata, DesignDocumentAcquirer
from .models import DesignDomain, DesignKnowledgeType, DesignReviewDecision, ReviewState
from .reasoning import DesignReasoningService
from .service import DesignIntelligenceService

ARCHIVE_DRIVE_ID = "1z_aiDTAHsGMqPfWU1FCYgIRKKU7AKw5L"
ARCHIVE_SHA256 = "aaf27bf015e544b802296fc047ccc5979d9bd7a8012f96480abb52cdf5634a4c"
ARCHIVE_VERSION = "BUILD-089C-v1"
RIGHTS_STATE = "USER_SUPPLIED_INTERNAL_RESEARCH_ONLY"
REUSE_LICENSE = "NOT_SUPPLIED"
UNKNOWN_AUTHOR = "AUTHOR_NOT_SUPPLIED"


@dataclass(frozen=True)
class ProvenanceBinding:
    revision_id: int
    extraction_run_id: int
    anchor_ids: tuple[int, ...]
    evidence_link_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class CorpusFile:
    path: Path
    relative_path: str
    supported: bool
    reason: str | None = None
    correction: str | None = None


class DesignCorpusPopulationService:
    """Deterministically imports and validates the immutable BUILD-089C archive."""

    RETRIEVAL_TOPICS = (
        "dashboard design", "UX guidance", "accessibility",
        "educational psychology", "scientific visualization", "motion design",
        "branding", "component libraries",
    )

    def __init__(self, corpus_service: DesignIntelligenceService, reasoning_service: DesignReasoningService) -> None:
        self.corpus_service = corpus_service
        self.reasoning_service = reasoning_service
        self.acquirer = DesignDocumentAcquirer()

    @staticmethod
    def inventory(root: Path) -> tuple[CorpusFile, ...]:
        values = []
        for path in sorted((p for p in root.rglob("*") if p.is_file()), key=lambda p: p.as_posix().casefold()):
            relative = path.relative_to(root).as_posix()
            supported = path.suffix.casefold() in SUPPORTED_FORMATS
            values.append(CorpusFile(path, relative, supported, None if supported else "UNSUPPORTED_FORMAT", None if supported else "Convert to Markdown, DOCX, PDF, or UTF-8 plain text."))
        return tuple(values)

    @staticmethod
    def verify_archive(path: Path) -> bool:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != ARCHIVE_SHA256:
            raise ValueError("BUILD_089C_ARCHIVE_HASH_MISMATCH")
        return True

    def populate(self, root: Path, binding_for: Callable[[str], ProvenanceBinding], *, publication_date: date | None = None) -> dict:
        inventory = self.inventory(root)
        imported = []
        created = 0
        for item in inventory:
            if not item.supported:
                continue
            binding = binding_for(item.relative_path)
            document_input = self.acquirer.acquire(
                item.path.name,
                item.path.read_bytes(),
                AcquisitionMetadata(
                    logical_key="build-089c:" + item.relative_path.casefold(),
                    title=item.path.stem.replace("_", " "),
                    authors=(UNKNOWN_AUTHOR,),
                    publisher="NOT_SUPPLIED",
                    source_uri=f"google-drive://{ARCHIVE_DRIVE_ID}#{item.relative_path}",
                    license=RIGHTS_STATE,
                    publication_date=publication_date,
                    revision_id=binding.revision_id,
                    extraction_run_id=binding.extraction_run_id,
                    anchor_ids=binding.anchor_ids,
                    evidence_link_ids=binding.evidence_link_ids,
                    topics=("BUILD-089C", "design-intelligence", "calyx research"),
                ),
            )
            document_input = type(document_input)(
                **{
                    **document_input.__dict__,
                    "license_metadata": {
                        "license": RIGHTS_STATE,
                        "rights_state": RIGHTS_STATE,
                        "reuse_or_redistribution_license": REUSE_LICENSE,
                        "display": "INTERNAL_RESEARCH_ONLY",
                        "publicly_redistributable": False,
                    },
                    "source_metadata": {
                        **document_input.source_metadata,
                        "supplied_by": "Jeffery Parham for Orchid Continuum",
                        "source_type": "user-supplied internal research archive",
                        "archive_drive_id": ARCHIVE_DRIVE_ID,
                        "archive_path": item.relative_path,
                    },
                    "requested_domains": (DesignDomain.INFORMATION_ARCHITECTURE,),
                    "requested_types": (DesignKnowledgeType.GUIDELINE,),
                }
            )
            document = self.corpus_service.repository.latest(document_input.logical_key)
            unchanged = bool(
                document
                and document.provenance.content_hash == document_input.provenance.content_hash
                and document.provenance.source_id == document_input.provenance.source_id
            )
            if not unchanged:
                document = self.corpus_service.import_document(document_input)
                self.corpus_service.review(document.document_id, DesignReviewDecision(ReviewState.APPROVED, "build-089c-curator", "Authoritative user-supplied archive retained for internal retrieval."))
                self.corpus_service.publish(document.document_id, "build-089c-curator", "Approved internal research corpus population.")
                created += 1
            units = tuple(
                unit
                for unit in self.reasoning_service.repository.units
                if unit.document_id == document.document_id
                and unit.document_version == document.version
            )
            if not units:
                units = self.reasoning_service.index_document(document)
            imported.append((item, document, units))

        units = tuple(self.reasoning_service.repository.units)
        relationships = tuple(self.reasoning_service.repository.relationships)
        hashes = Counter(hashlib.sha256(" ".join(u.text.casefold().split()).encode()).hexdigest() for u in units)
        retrieval = {query: self.reasoning_service.search(query, limit=3) for query in self.RETRIEVAL_TOPICS}
        cited = sum(bool(re.search(r"(?:https?://|doi:|\[[0-9]+\]|\([A-Z][A-Za-z-]+,?\s+\d{4}\))", u.text)) for u in units)
        domain_counts = Counter(domain.value for unit in units for domain in unit.domains)
        type_counts = Counter(kind for unit in units for kind in unit.knowledge_types)
        expected_domains = {
            "dashboard design": "DASHBOARD_DESIGN", "UX guidance": "UX",
            "accessibility": "ACCESSIBILITY", "educational psychology": "EDUCATIONAL_PSYCHOLOGY",
            "scientific visualization": "SCIENTIFIC_VISUALIZATION", "motion design": "MOTION_DESIGN",
            "branding": "BRANDING", "component libraries": "COMPONENT_LIBRARIES",
        }
        retrieval_outcomes = {}
        for query in self.RETRIEVAL_TOPICS:
            exact = expected_domains[query] in domain_counts
            query_terms = set(re.findall(r"[a-z0-9]+", query.casefold()))
            lexical = any(
                query_terms.issubset(set(re.findall(r"[a-z0-9]+", unit.text.casefold())))
                for unit in units
            )
            status = (
                "COVERED"
                if exact
                else "PARTIALLY_COVERED"
                if lexical
                else "NOT_PRESENT_IN_SOURCE_CORPUS"
            )
            retrieval_outcomes[query] = {
                "status": status,
                "expected_domain": expected_domains[query],
                "results": retrieval[query]["results"] if status != "NOT_PRESENT_IN_SOURCE_CORPUS" else [],
            }
        findings = [
            {"code": "AUTHORSHIP_NOT_SUPPLIED", "severity": "INFO", "count": len(imported)},
            {"code": "REUSE_LICENSE_NOT_SUPPLIED_EXTERNAL_REDISTRIBUTION_BLOCKED", "severity": "INFO", "count": len(imported)},
            {"code": "MISSING_INLINE_CITATION", "severity": "MEDIUM", "count": len(units) - cited},
            {"code": "UNCLASSIFIED_SEMANTIC_UNIT", "severity": "HIGH", "count": sum(not u.domains and not u.knowledge_types and not u.educational_classifications for u in units)},
        ]
        return {
            "archive": {"drive_id": ARCHIVE_DRIVE_ID, "sha256": ARCHIVE_SHA256, "version": ARCHIVE_VERSION},
            "documents_imported": len(imported), "documents_skipped": sum(not x.supported for x in inventory),
            "documents_created": created,
            "imported": [x.relative_path for x, _, _ in imported],
            "skipped": [asdict(x) | {"path": x.relative_path} for x in inventory if not x.supported],
            "semantic_units": len(units), "embeddings": sum(bool(u.embedding) for u in units),
            "relationships": len(relationships), "classifications": sum(len(u.domains) + len(u.knowledge_types) + len(u.educational_classifications) for u in units),
            "domain_counts": dict(sorted(domain_counts.items())), "knowledge_type_counts": dict(sorted(type_counts.items())),
            "duplicates": sum(count - 1 for count in hashes.values() if count > 1),
            "conflicts": sum(r.relationship_type.value == "CONTRADICTS" for r in relationships),
            "obsolete_mentions": sum(bool(re.search(r"\b(obsolete|deprecated|superseded|retracted)\b", u.text, re.IGNORECASE)) for u in units),
            "provenance_coverage": 1.0 if units and all(u.source_location.content_hash and u.source_location.locator.get("anchor_ids") for u in units) else 0.0,
            "retrieval": retrieval,
            "retrieval_outcomes": retrieval_outcomes,
            "metadata_handling_complete": True,
            "rights": {
                "rights_state": RIGHTS_STATE,
                "reuse_or_redistribution_license": REUSE_LICENSE,
                "publicly_redistributable": False,
            },
            "findings": findings,
        }
