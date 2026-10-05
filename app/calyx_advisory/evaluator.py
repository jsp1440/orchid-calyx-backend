"""Deterministic Calyx advisory evaluator. Same artifact in, same advisory out."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contract import (
    CONTRACT,
    FINDING_KINDS,
    PROHIBITED_ACTIONS,
    UNCERTAIN_STATES,
    checksum,
    contains_locality_key,
    validate_advisory,
    ContractViolation,
)
from .presentations import AUDIENCES

#: More distinct items than this on one surface without progressive disclosure is
#: a cognitive-load finding.
MAX_UNDISCLOSED_ITEMS = 7


def _finding(kind, severity, competency, targets, rationale, evidence, recommendation, artifact_id):
    return {
        "finding_id": checksum([kind, artifact_id, sorted(targets)])[:12],
        "kind": kind,
        "severity": severity,
        "competency": competency,
        "targets": sorted(targets),
        "rationale": rationale,
        "evidence": evidence,
        "recommendation": recommendation,
        "scientific_effect": "none",
    }


def evaluate(artifact: Mapping[str, Any]) -> dict[str, Any]:
    if contains_locality_key(artifact):
        raise ContractViolation("ARTIFACT_CONTAINS_LOCALITY")
    artifact_id = str(artifact["artifact_id"])
    claims = {c["id"]: c for c in artifact.get("claims") or []}
    surfaces = list(artifact.get("surfaces") or [])
    findings: list[dict[str, Any]] = []

    for surface in surfaces:
        sid = surface["id"]
        for cid in surface.get("claim_ids") or []:
            claim = claims.get(cid)
            if claim is None or claim["evidence_state"] not in UNCERTAIN_STATES:
                continue
            missing = sorted(
                {m["id"] for m in claim.get("mechanisms") or []}
                - set(surface.get("mechanism_ids_shown") or ())
            )
            if missing or not surface.get("uncertainty_shown"):
                findings.append(_finding(
                    "educational_gap", "high", "science-education", [sid, cid],
                    "A surface presents a contested claim without all competing mechanisms "
                    "or its uncertainty, so learners would read an open question as settled.",
                    [f"surface:{sid}", f"claim:{cid}", f"missing_mechanisms:{','.join(missing) or 'none'}",
                     f"uncertainty_shown:{bool(surface.get('uncertainty_shown'))}"],
                    "Restore the omitted qualification and teach it; do not remove it from the claim.",
                    artifact_id,
                ))
        if surface.get("has_media") and not surface.get("alt_text"):
            findings.append(_finding(
                "accessibility_gap", "high", "accessibility", [sid],
                "Media is shown without a text alternative.",
                [f"surface:{sid}", "has_media:true", "alt_text:false"],
                "Provide a text alternative that states the same qualifications.", artifact_id))
        if not surface.get("reading_level"):
            findings.append(_finding(
                "accessibility_gap", "low", "accessibility", [sid],
                "No reading level is declared, so understandability cannot be checked.",
                [f"surface:{sid}", "reading_level:undeclared"],
                "Declare the intended reading level for this audience.", artifact_id))
        if int(surface.get("items_shown") or 0) > MAX_UNDISCLOSED_ITEMS and not surface.get(
            "progressive_disclosure"
        ):
            findings.append(_finding(
                "ux_gap", "medium", "web-interaction-design", [sid],
                f"More than {MAX_UNDISCLOSED_ITEMS} items are shown at once with no progressive "
                "disclosure.",
                [f"surface:{sid}", f"items_shown:{surface.get('items_shown')}"],
                "Introduce progressive disclosure; keep every item reachable.", artifact_id))

    for cid, claim in sorted(claims.items()):
        if claim["evidence_state"] not in UNCERTAIN_STATES:
            continue
        covering = {
            s.get("audience") for s in surfaces if cid in (s.get("claim_ids") or [])
        }
        for audience in AUDIENCES:
            if audience in covering:
                continue
            if audience == "inquiry":
                findings.append(_finding(
                    "teaching_opportunity", "medium", "teaching-modalities", [cid],
                    "A contested claim with competing mechanisms has no inquiry experience, "
                    "although dispute is where investigation teaches most.",
                    [f"claim:{cid}", "missing_audience:inquiry",
                     f"mechanisms:{len(claim.get('mechanisms') or [])}"],
                    "Add a predict-observe-compare investigation that ends in stating the "
                    "uncertainty.", artifact_id))
            else:
                findings.append(_finding(
                    "curriculum_gap", "medium", "curriculum-instructional-design", [cid],
                    f"No {audience} presentation exists for this claim, so the learning "
                    "progression has a missing tier.",
                    [f"claim:{cid}", f"missing_audience:{audience}"],
                    f"Add a {audience} presentation derived from the same scientific core.",
                    artifact_id))

    findings.sort(key=lambda f: (FINDING_KINDS.index(f["kind"]), f["targets"], f["finding_id"]))
    if not findings:
        findings = [{
            "finding_id": checksum(["no_action", artifact_id])[:12],
            "kind": "no_action", "severity": "info", "competency": "science-education",
            "targets": [], "rationale": "No educational, UX, curriculum or accessibility gap found.",
            "evidence": [], "recommendation": "None.", "scientific_effect": "none",
        }]
    advisory = {
        "contract": CONTRACT,
        "artifact_id": artifact_id,
        "artifact_checksum": checksum(artifact),
        "prohibited_actions": list(PROHIBITED_ACTIONS),
        "findings": findings,
    }
    validate_advisory(advisory)
    return advisory
