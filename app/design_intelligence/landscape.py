"""Review-gated import of the LANDSCAPE-001 design guidance package.

The package carries external design-landscape guidance for the homepage, Atlas and
Calyx. It is design intelligence, never scientific evidence, so this importer:

* verifies the guidance file against the package manifest before reading it;
* requires the caller to supply real acquisition provenance (no placeholders);
* imports the document as a draft. It never records a review decision and never
  publishes. A named curator does that through the existing service;
* indexes semantic units only for a document that is both approved and published,
  because ``DesignReasoningService.search`` does not itself filter on publication.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .acquisition import AcquisitionMetadata, DesignDocumentAcquirer
from .knowledge import SemanticUnit
from .models import (
    DesignDocument,
    DesignDomain,
    DesignKnowledgeType,
    PublicationStatus,
    ReviewState,
)
from .population import REUSE_LICENSE, RIGHTS_STATE, UNKNOWN_AUTHOR, ProvenanceBinding
from .reasoning import DesignReasoningService
from .service import DesignIntelligenceService

PACKAGE_ID = "LANDSCAPE-001"
LOGICAL_KEY = "landscape-001:guidance"
EVIDENCE_CLASS = "non_scientific_design_guidance"


class LandscapeGuidanceImporter:
    def __init__(
        self,
        corpus_service: DesignIntelligenceService,
        reasoning_service: DesignReasoningService,
    ) -> None:
        self.corpus_service = corpus_service
        self.reasoning_service = reasoning_service
        self.acquirer = DesignDocumentAcquirer()

    @staticmethod
    def load_manifest(root: Path) -> dict:
        manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8"))
        if manifest.get("package_id") != PACKAGE_ID:
            raise ValueError("LANDSCAPE_PACKAGE_ID_MISMATCH")
        if manifest.get("evidence_class") != EVIDENCE_CLASS:
            raise ValueError("LANDSCAPE_EVIDENCE_CLASS_MISMATCH")
        if manifest.get("auto_review_or_publish") is not False:
            raise ValueError("LANDSCAPE_AUTO_PUBLICATION_FORBIDDEN")
        payload = (root / manifest["guidance_file"]).read_bytes()
        if hashlib.sha256(payload).hexdigest() != manifest["guidance_sha256"]:
            raise ValueError("LANDSCAPE_GUIDANCE_HASH_MISMATCH")
        return manifest

    def import_pending(self, root: Path, binding: ProvenanceBinding) -> DesignDocument:
        """Import as a draft with pending review. No review, no publication."""
        manifest = self.load_manifest(root)
        name = manifest["guidance_file"]
        document_input = self.acquirer.acquire(
            name,
            (root / name).read_bytes(),
            AcquisitionMetadata(
                logical_key=LOGICAL_KEY,
                title="LANDSCAPE-001 Design Guidance",
                authors=(UNKNOWN_AUTHOR,),
                publisher="NOT_SUPPLIED",
                source_uri=f"brain://{manifest['brain_contract']['path']}#{manifest['brain_contract']['sha256']}",
                license=RIGHTS_STATE,
                publication_date=None,
                revision_id=binding.revision_id,
                extraction_run_id=binding.extraction_run_id,
                anchor_ids=binding.anchor_ids,
                evidence_link_ids=binding.evidence_link_ids,
                topics=(
                    PACKAGE_ID,
                    "design-intelligence",
                    "landscape review",
                    "homepage",
                    "atlas",
                    "calyx docent",
                ),
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
                    "evidence_class": EVIDENCE_CLASS,
                    "package_id": PACKAGE_ID,
                    "guidance_record_ids": list(manifest["guidance_record_ids"]),
                    "source_review_sha256": manifest["source_review_sha256"],
                },
                "requested_domains": (
                    DesignDomain.INFORMATION_ARCHITECTURE,
                    DesignDomain.SCIENTIFIC_VISUALIZATION,
                    DesignDomain.INTERACTION_DESIGN,
                ),
                "requested_types": (DesignKnowledgeType.GUIDELINE,),
            }
        )
        return self.corpus_service.import_document(document_input)

    def index_after_publication(self, document_id: int) -> tuple[SemanticUnit, ...]:
        """Index units only once the document is approved and published."""
        repository = self.corpus_service.repository
        document = repository.document(document_id)
        if document is None:
            raise KeyError(document_id)
        if (
            repository.review_state(document_id) is not ReviewState.APPROVED
            or repository.publication_status(document_id)
            is not PublicationStatus.PUBLISHED
        ):
            raise ValueError("LANDSCAPE_INDEX_REQUIRES_APPROVED_PUBLISHED_DOCUMENT")
        existing = tuple(
            unit
            for unit in self.reasoning_service.repository.units
            if unit.document_id == document.document_id
            and unit.document_version == document.version
        )
        return existing or self.reasoning_service.index_document(document)
