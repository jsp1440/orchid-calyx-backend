"""Vision Lab junction publisher adapter (oc-junction-profile-v1).

Vision Lab is the Continuum's image-analysis module (see
``app/scientific_adapter_lab/vision_matrix_proof.py`` for the fixture-backed
vision → matrix proof path). This adapter lets Vision Lab emit one junction
signal — ``vision.image_verified`` — carrying the verification outcome of a
licensed orchid image, with scientific context preserved end-to-end:

- taxon identity: ``accepted_name``/``canonical_taxon_id``/``rank``; an
  accepted name without a canonical id is emitted with the mandatory
  ``taxon_identity_state='unresolved'`` marker — ambiguity is never silently
  resolved;
- provenance: source/evidence carried by reference
  (``source.source_record_id``, ``evidence.evidence_refs``), never by copy;
- uncertainty: ``evidence.confidence`` in [0,1], where ``None`` means UNKNOWN
  and is never coerced to 0; ``verification_state`` preserved distinctly;
- conflicting evidence: a ``conflict`` block with ``counterevidence_present``
  stays a separate signal and is never merged, averaged, or ranked away.

The adapter builds the signal and presents it at the junction port
(``JunctionRouter.publish``). It holds no authority: the signal is advisory,
and Vision Lab's manifest grants no work proposal or execution capability.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..router import JunctionRouter
from ..signals import build_signal

MODULE_ID = "vision-lab"
EVENT_TYPE = "vision.image_verified"
PIPELINE_STAGE = "api_producer"  # per the contract's junction_additions entry


class VisionLabPublisher:
    """Emit ``vision.image_verified`` junction signals for Vision Lab."""

    def __init__(self, router: JunctionRouter, *, component_version: str | None = None) -> None:
        self._router = router
        self._component_version = component_version

    def emit_image_verified(
        self,
        *,
        image: dict[str, Any],
        verified: bool,
        taxon: dict[str, Any] | None = None,
        confidence: float | None = None,
        evidence_refs: list[str] | None = None,
        verification_state: str = "unverified",
        conflict: dict[str, Any] | None = None,
        entity_scope: str | None = None,
        correlation_id: str | None = None,
        parent_event_id: str | None = None,
        sequence: int = 1,
        occurred_at: datetime | None = None,
        model_provenance: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build and publish one image-verification signal.

        ``confidence=None`` means UNKNOWN and is preserved as ``null`` — it is
        never coerced to 0. ``conflict`` (e.g. ``status='counterevidence_present'``
        with ``counterevidence_ids``) is carried through unchanged.
        """

        payload: dict[str, Any] = {
            "image_id": image.get("image_id"),
            "content_hash": image.get("content_hash"),
            "license_code": image.get("license_code"),
            "verification": "verified" if verified else "rejected",
        }
        if model_provenance:
            payload["model_provenance"] = model_provenance

        scope = entity_scope
        if scope is None:
            canonical = (taxon or {}).get("canonical_taxon_id")
            scope = f"taxon:{canonical}" if canonical else "domain:vision"

        evidence: dict[str, Any] = {
            "confidence": confidence,  # null means UNKNOWN, never 0
            "verification_state": verification_state,
            "evidence_refs": list(evidence_refs or []),
        }
        source: dict[str, Any] = {
            "source_id": image.get("source_dataset"),
            "source_record_id": image.get("image_id"),
            "dataset": image.get("source_dataset"),
            "dataset_version": image.get("source_collection"),
            "reference": image.get("canonical_uri"),
        }

        event = build_signal(
            source_module=MODULE_ID,
            event_type=EVENT_TYPE,
            pipeline_stage=PIPELINE_STAGE,
            entity_scope=scope,
            consequence_class="observation",
            payload=payload,
            taxon=taxon,
            source=source,
            evidence=evidence,
            conflict=conflict,
            safe_status={
                "status": "ok" if verified else "withheld",
                "reason_code": "IMAGE_VERIFIED" if verified else "IMAGE_REJECTED",
                "blocker": None,
                "error_code": None,
            },
            correlation_id=correlation_id,
            parent_event_id=parent_event_id,
            sequence=sequence,
            occurred_at=occurred_at,
            component_version=self._component_version,
        )
        return self._router.publish(MODULE_ID, event)
