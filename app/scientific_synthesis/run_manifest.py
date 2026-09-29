"""RunEvidenceManifest — immutable, fingerprinted record of one research run.

This module implements Brain #103 vertical-slice step 10:
"Save an immutable run/evidence manifest."

A RunEvidenceManifest is a deterministic, sha256-fingerprinted snapshot of
the full evidence-to-decision chain for one research run. It reuses canonical
governance contracts from the Brain's `calyx_brain.reasoning_contracts` layer
and is compatible with the `ScientificSynthesisService` validation layer.

It intentionally carries no model inference, no provider authority, no
canonical publication authority, and no production mutation. Human review is
required before any canonical activation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .service import fingerprint

MANIFEST_VERSION = "oc-run-evidence-manifest-v1"


def _str(v: Any) -> str:
    return "" if v is None else str(v)


def build_run_evidence_manifest(
    *,
    run_id: str,
    research_question: str,
    taxon_id: str,
    taxonomy_snapshot_id: str,
    verification_packets: tuple[dict[str, Any], ...],
    review_records: tuple[dict[str, Any], ...],
    epistemic_memory_entries: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Build an immutable, fingerprinted run evidence manifest.

    Parameters
    ----------
    run_id:
        Unique identifier for this research run (e.g. "run:phal-2026-09").
    research_question:
        The research question this run addressed.
    taxon_id:
        Canonical taxon identifier (e.g. "taxon:phalaenopsis").
    taxonomy_snapshot_id:
        Pinned taxonomy release (e.g. "hassler:2026-09").
    verification_packets:
        One or more verification packets produced by
        `calyx_brain.reasoning_contracts.build_verification_packet`.
        Each must carry `contract_version == "oc-verification-handoff-v1"`,
        `human_review_required == True`, and governance flags.
    review_records:
        Zero or more review decision records (may be empty when review is
        still pending).
    epistemic_memory_entries:
        Zero or more epistemic memory entries.

    Returns
    -------
    dict
        Immutable, fingerprinted manifest with `contract_version`,
        `run_fingerprint`, and all governance flags set.

    Raises
    ------
    ValueError
        If required fields are missing or governance flags are violated.
    """
    run_id = _str(run_id).strip()
    if not run_id:
        raise ValueError("RUN_ID_REQUIRED")

    taxon_id = _str(taxon_id).strip()
    if not taxon_id:
        raise ValueError("TAXON_ID_REQUIRED")

    taxonomy_snapshot_id = _str(taxonomy_snapshot_id).strip()
    if not taxonomy_snapshot_id:
        raise ValueError("TAXONOMY_SNAPSHOT_REQUIRED")

    if not verification_packets:
        raise ValueError("VERIFICATION_PACKET_REQUIRED")

    resolved_evidence_count = 0
    missing_evidence_count = 0
    knowledge_gap_count = 0
    all_contradictions: list[str] = []
    verification_state = "ready_for_review"

    for packet in verification_packets:
        if packet.get("contract_version") != "oc-verification-handoff-v1":
            raise ValueError("UNSUPPORTED_VERIFICATION_PACKET")
        if (
            packet.get("human_review_required") is not True
            or packet.get("automatic_scientific_publication_allowed") is not False
        ):
            raise ValueError("PACKET_GOVERNANCE_INVALID")
        resolved = packet.get("resolved_evidence") or []
        missing = packet.get("missing_evidence") or []
        gaps = packet.get("knowledge_gaps") or []
        contradictions = packet.get("contradictions") or []
        resolved_evidence_count += len(resolved)
        missing_evidence_count += len(missing)
        knowledge_gap_count += len(gaps)
        all_contradictions.extend(contradictions)
        pkt_state = packet.get("verification_state", "ready_for_review")
        if pkt_state == "evidence_incomplete":
            verification_state = "evidence_incomplete"
        elif (
            pkt_state == "validation_required"
            and verification_state != "evidence_incomplete"
        ):
            verification_state = "validation_required"

    review_decision: str | None = None
    epistemic_state: str | None = None
    for record in review_records:
        if record.get("contract_version") == "oc-review-decision-record-v1":
            review_decision = _str(record.get("review_decision")) or None

    for entry in epistemic_memory_entries:
        if entry.get("contract_version") == "oc-reviewed-epistemic-memory-v1":
            epistemic_state = _str(entry.get("epistemic_state")) or None

    manifest_content = {
        "run_id": run_id,
        "research_question": research_question,
        "taxon_id": taxon_id,
        "taxonomy_snapshot_id": taxonomy_snapshot_id,
        "verification_packets": list(verification_packets),
        "review_records": list(review_records),
        "epistemic_memory_entries": list(epistemic_memory_entries),
    }
    run_fp = fingerprint(manifest_content)

    return {
        "contract_version": MANIFEST_VERSION,
        "run_id": run_id,
        "research_question": research_question,
        "taxon_id": taxon_id,
        "taxonomy_snapshot_id": taxonomy_snapshot_id,
        "run_fingerprint": run_fp,
        "created_at_utc": datetime.now(tz=timezone.utc).isoformat(),
        "verification_state": verification_state,
        "resolved_evidence_count": resolved_evidence_count,
        "missing_evidence_count": missing_evidence_count,
        "knowledge_gap_count": knowledge_gap_count,
        "contradictions": sorted(set(all_contradictions)),
        "review_decision": review_decision,
        "epistemic_state": epistemic_state,
        "human_review_required": True,
        "automatic_scientific_publication_allowed": False,
        "canonical_knowledge_mutation_allowed": False,
        "canonical_activation_requires_human_authority": True,
        "immutable": True,
    }
