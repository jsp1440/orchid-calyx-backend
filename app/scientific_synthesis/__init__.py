"""Evidence-grounded scientific synthesis contracts and validation."""

from .run_manifest import MANIFEST_VERSION, build_run_evidence_manifest
from .service import ScientificSynthesisService

__all__ = ["ScientificSynthesisService", "build_run_evidence_manifest", "MANIFEST_VERSION"]
