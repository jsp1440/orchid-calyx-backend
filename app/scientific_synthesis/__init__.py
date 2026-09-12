"""Evidence-grounded scientific synthesis contracts and validation."""

from .run_manifest import MANIFEST_VERSION, build_run_evidence_manifest
from .service import ScientificSynthesisService

__all__ = ["MANIFEST_VERSION", "ScientificSynthesisService", "build_run_evidence_manifest"]
